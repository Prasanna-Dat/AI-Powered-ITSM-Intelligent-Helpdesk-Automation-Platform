"""The brain of the platform. One function - handle_message() - runs the whole journey:

   Employee request -> AI understanding -> knowledge retrieval -> decision -> automation -> ServiceNow -> resolution

Four workflows: knowledge question (RAG) | incident | automatable issue (self-heal) | service request (software/access).
Every run records a step-by-step trace that the 'AI Analysis' screen displays.
"""
import uuid

from app import automation, db, software
from app.classifier import classify
from app.config import settings
from app.context import get_ctx
from app.servicenow import SN_CATEGORY, sn

HUMAN_GROUP = "Service Desk (Human Triage)"


def _clip(x):
    return max(0.0, min(1.0, x))


def _step(steps, name, status, detail):
    steps.append({"step": name, "status": status, "detail": detail, "at": db.utcnow()})


def _incident_payload(a, user, extra_note=""):
    srcs = ", ".join(s["title"] for s in a["sources"]) or "none"
    desc = (f"{a['message']}\n\n--- AI analysis ---\nIntent: {a['intent']}\nCategory: {a['category']} / {a['subcategory']}\n"
            f"Confidence: {a['confidence']}\nSuggested resolution: {a['suggested_resolution']}\n"
            f"Knowledge sources: {srcs}\nReported by: {user.get('name')} <{user.get('email')}>\n{extra_note}").strip()
    return {"short_description": a["summary"], "description": desc,
            "category": SN_CATEGORY.get(a["category"], "inquiry"), "subcategory": a["subcategory"].lower(),
            "impact": str(a["impact_n"]), "urgency": str(a["urgency_n"]), "priority": str(a["priority_n"]),
            "assignment_group": a["assignment_group"], "contact_type": "self-service"}


def _save_ticket(a, sn_ref, status, user_id):
    tid = f"TKT{db.next_seq('ticket', 1000):05d}"
    ticket = {"ticket_id": tid, "user_id": user_id, "summary": a["summary"], "message": a["message"],
              "intent": a["intent"], "category": a["category"], "subcategory": a["subcategory"],
              "priority": a["priority"], "assignment_group": a["assignment_group"], "confidence": a["confidence"],
              "status": status, "sn_number": sn_ref["number"], "sn_sys_id": sn_ref["sys_id"],
              "analysis_id": a["analysis_id"], "created_at": db.utcnow()}
    db.col("tickets").insert_one(dict(ticket))
    return ticket


def _sn_summary(ref, state=None):
    return {"number": ref["number"], "sys_id": ref["sys_id"], "mode": ref["mode"], "state": state or ref.get("state", "New")}


# ===================================================================================== main entry
def handle_message(user_id: str, message: str, force_intent: str | None = None) -> dict:
    ctx = get_ctx()
    user = db.strip(db.col("users").find_one({"user_id": user_id})) or {"user_id": user_id, "name": user_id, "email": ""}
    steps = []

    # 1. understand ------------------------------------------------------------------------------
    c = classify(message, ctx.embedder)
    if force_intent in ("incident", "service_request") and c["intent"] != force_intent:
        c["intent"], c["intent_conf"] = force_intent, 0.9
    _step(steps, "Intent detection", "done", f"{c['intent']} | {c['category']} / {c['subcategory']} | {c['priority']}")

    # 2. retrieve --------------------------------------------------------------------------------
    hits = ctx.kb.search(message)
    top = hits[0]["score"] if hits else 0.0
    relevant = top >= ctx.embedder.min_score
    retr_conf = _clip(top / ctx.embedder.full_score) if relevant else 0.0
    if c["intent"] == "unknown" and relevant:
        c["intent"], c["intent_conf"] = "knowledge_question", 0.5
    sources = ctx.kb.sources(hits) if relevant else []
    _step(steps, "Knowledge search (vector DB)", "done" if relevant else "no-match",
          f"top score {top} (min {ctx.embedder.min_score}) via {ctx.kb.store}")

    sw = c["software"]
    third = 1.0 if (c["intent"] == "service_request" and sw) else retr_conf
    confidence = round(0.4 * c["intent_conf"] + 0.3 * c["category_conf"] + 0.3 * third, 2)

    a = {"analysis_id": "AN-" + uuid.uuid4().hex[:8].upper(), "user_id": user_id, "message": message,
         "intent": c["intent"], "category": c["category"], "subcategory": c["subcategory"],
         "priority": c["priority"], "priority_n": c["priority_n"], "impact": c["impact"], "impact_n": c["impact_n"],
         "urgency": c["urgency"], "urgency_n": c["urgency_n"], "assignment_group": c["assignment_group"],
         "summary": c["summary"], "suggested_resolution": c["suggested_resolution"], "confidence": confidence,
         "threshold": settings.CONFIDENCE_THRESHOLD, "sources": sources, "retrieved_chunks": hits,
         "answer": "", "answer_generated_by": None, "outcome": "", "escalated": False, "can_create_ticket": False,
         "automation": None, "servicenow": None, "ticket_id": None, "service_request": None,
         "models": {"llm": ctx.llm.model_name, "embedding": ctx.embedder.model_name, "vector_db": ctx.kb.store},
         "created_at": db.utcnow()}

    # 3. route -----------------------------------------------------------------------------------
    if c["intent"] == "automatable_issue":
        _self_heal(a, c, user, hits, steps, ctx)
    elif c["intent"] == "service_request":
        _service_request(a, c, user, steps)
    elif c["intent"] == "incident":
        _incident(a, user, hits, relevant, steps, ctx)
    else:
        _knowledge(a, hits, relevant, steps, ctx)

    a["steps"] = steps
    db.col("chat_history").insert_one(dict(a))
    db.audit("chat.handled", user_id, {"analysis_id": a["analysis_id"], "intent": a["intent"], "outcome": a["outcome"],
                                       "confidence": a["confidence"]}, a["analysis_id"])
    return a


# ===================================================================================== workflows
def _grounded_answer(a, message, hits, relevant, steps, ctx):
    if not relevant:
        return None
    text, by = ctx.llm.answer(message, hits[:settings.TOP_K])
    a["answer_generated_by"] = by
    _step(steps, "Grounded answer (LLM)", "done" if text else "refused",
          f"generated by {by}" if text else "LLM judged the approved KB insufficient")
    return text


def _knowledge(a, hits, relevant, steps, ctx):
    low = a["confidence"] < settings.CONFIDENCE_THRESHOLD
    text = None if low else _grounded_answer(a, a["message"], hits, relevant, steps, ctx)
    if text:
        a["answer"], a["outcome"], a["can_create_ticket"] = text, "answered", True   # 'still need help?' option
        _step(steps, "Decision", "done", "Answered from approved knowledge base")
    else:
        a.update(answer=("I could not find this in the approved IT knowledge base, so I won't guess. "
                         "I can create a ticket so a human agent can help you."),
                 outcome="unanswered", escalated=True, can_create_ticket=True, sources=[])
        _step(steps, "Decision", "escalate", f"confidence {a['confidence']} < threshold {settings.CONFIDENCE_THRESHOLD} "
              "or KB insufficient -> offer human escalation (no hallucination)")


def _incident(a, user, hits, relevant, steps, ctx):
    low = a["confidence"] < settings.CONFIDENCE_THRESHOLD
    if low:
        a["assignment_group"], a["escalated"] = HUMAN_GROUP, True
        _step(steps, "Decision", "escalate", f"confidence {a['confidence']} < {settings.CONFIDENCE_THRESHOLD}: route to human triage")
    text = _grounded_answer(a, a["message"], hits, relevant, steps, ctx)
    ref = sn.create_incident(_incident_payload(a, user, "Low AI confidence - human triage requested." if low else ""))
    a["servicenow"] = _sn_summary(ref)
    t = _save_ticket(a, ref, "escalated" if low else "open", a["user_id"])
    a["ticket_id"] = t["ticket_id"]
    _step(steps, "ServiceNow", "done", f"Incident {ref['number']} created ({ref['mode']})")
    head = f"I've logged incident {ref['number']} ({a['priority']}) for {a['assignment_group']}."
    if text and not low:
        a["answer"] = f"{head} While you wait, the approved knowledge base suggests:\n\n{text}"
    else:
        a["answer"], a["sources"] = f"{head} I don't have an approved article to suggest, so a human agent will pick it up.", []
    a["outcome"] = "escalated" if low else "ticket_created"


def _self_heal(a, c, user, hits, steps, ctx):
    action = c["automation_action"]
    title, kb_title = automation.ACTIONS[action]
    uid = a["user_id"]
    log = []

    def rec(step, status, detail):
        _step(steps, step, status, detail)
        log.append({"step": step, "status": status, "detail": detail})
        db.audit(f"automation.{action}.{step.lower().replace(' ', '_')}", "ai-agent", {"detail": detail}, a["analysis_id"],
                 "success" if status in ("done", "ok") else status)

    rec("Identify", "done", f"Automatable issue: {title}")
    rec("Diagnose", "done", automation.diagnose(action, uid))
    supported = any(h["title"] == kb_title and h["score"] >= ctx.embedder.min_score for h in hits)
    rec("Knowledge search", "done" if supported else "no-match",
        f"Approved article '{kb_title}' {'found' if supported else 'NOT found'} in top results")
    if not supported or a["confidence"] < settings.CONFIDENCE_THRESHOLD:
        rec("Determine automation", "blocked", "Not safe to automate (no approved KB support or low confidence) -> incident")
        a["intent"] = "incident"
        _incident(a, user, hits, bool(hits), steps, ctx)
        return
    rec("Determine automation", "done", f"'{action}' is whitelisted and supported by KB -> safe to run")
    ok, detail = automation.execute(action, uid)
    rec("Execute", "done" if ok else "failed", detail)
    v_ok, v_detail = automation.validate(action, uid)
    rec("Validate", "done" if v_ok else "failed", v_detail)

    ref = sn.create_incident(_incident_payload(a, user, "Created by AI self-heal agent."))
    if ok and v_ok:
        sn.update_incident(ref["sys_id"], {"state": "6", "close_code": "Solved (Permanently)",
                                           "close_notes": f"Resolved automatically: {detail}. Validation: {v_detail}",
                                           "work_notes": "AI agent executed: " + title})
        status, a["outcome"], state = "ai_resolved", "auto_resolved", "Resolved"
        a["answer"] = f"Done. {detail}. Verified: {v_detail}. ServiceNow incident {ref['number']} was updated to Resolved."
    else:
        sn.update_incident(ref["sys_id"], {"state": "2", "work_notes": "Automation failed; needs a human agent."})
        status, a["outcome"], state, a["escalated"] = "escalated", "escalated", "In Progress", True
        a["answer"] = f"The automatic fix did not pass validation. I escalated this to a human agent: {ref['number']}."
    rec("Update ServiceNow", "done", f"{ref['number']} -> {state}")
    a["servicenow"] = _sn_summary(ref, state)
    a["ticket_id"] = _save_ticket(a, ref, status, uid)["ticket_id"]
    a["sources"] = [s for s in a["sources"] if s["title"] == kb_title] or a["sources"]
    a["automation"] = {"action": action, "title": title, "success": bool(ok and v_ok), "log": log}
    db.col("automation_actions").insert_one({"action": action, "title": title, "user_id": uid, "success": bool(ok and v_ok),
                                             "ticket_id": a["ticket_id"], "sn_number": ref["number"], "created_at": db.utcnow()})


def _service_request(a, c, user, steps):
    sw = c["software"]
    uid = a["user_id"]
    if sw:
        _step(steps, "Software catalogue", "done", f"Matched {sw['name']} ({sw['id']})")
        ref = sn.create_service_request({"short_description": f"Software install: {sw['name']}",
                                         "description": f"{a['message']}\nRequested by {user.get('name')} <{user.get('email')}>\nAI confidence {a['confidence']}",
                                         "assignment_group": "Desktop Support"})
        _step(steps, "ServiceNow", "done", f"Request {ref['number']} created ({ref['mode']})")
        job = software.provision(ref["number"], sw["name"], uid)
        _step(steps, "Mock provisioning API", "done", f"Job {job['job_id']} started")
        rec = {"request_id": ref["number"], "sn_sys_id": ref["sys_id"], "kind": "software", "software": sw["name"],
               "software_id": sw["id"], "user_id": uid, "status": "Provisioning", "job_id": job["job_id"],
               "created_at": db.utcnow()}
        db.col("service_requests").insert_one(dict(rec))
        a["service_request"] = {"request_id": ref["number"], "software": sw["name"], "status": "Provisioning",
                                "message": "ServiceNow Request created successfully"}
        a["servicenow"] = _sn_summary(ref, "Requested")
        a["answer"] = f"Your request for {sw['name']} is in. ServiceNow request {ref['number']} was created and the install is now provisioning."
        a["outcome"] = "request_created"
        return
    if c["category"] == "Access":
        ref = sn.create_service_request({"short_description": f"Application access request: {a['message'][:80]}",
                                         "description": f"{a['message']}\nRequested by {user.get('name')}", "assignment_group": a["assignment_group"]})
        db.col("service_requests").insert_one({"request_id": ref["number"], "sn_sys_id": ref["sys_id"], "kind": "access",
                                               "software": "Application access", "user_id": uid, "status": "Submitted",
                                               "created_at": db.utcnow()})
        a["service_request"] = {"request_id": ref["number"], "software": "Application access", "status": "Submitted",
                                "message": "ServiceNow Request created successfully"}
        a["servicenow"] = _sn_summary(ref, "Requested")
        a["answer"], a["outcome"] = f"Access request {ref['number']} was submitted for approval.", "request_created"
        _step(steps, "ServiceNow", "done", f"Request {ref['number']} created")
        return
    a.update(answer="That software is not in the Software Catalogue, so I can't provision it automatically. I can create a ticket for approval.",
             outcome="unanswered", can_create_ticket=True, escalated=True, sources=[])
    _step(steps, "Software catalogue", "no-match", "Not in catalogue -> offer human ticket")


# ===================================================================================== user-triggered escalation
def create_ticket_from_analysis(user_id, analysis_id=None, message=None, reason="User requested human help"):
    ctx = get_ctx()
    user = db.strip(db.col("users").find_one({"user_id": user_id})) or {"user_id": user_id, "name": user_id, "email": ""}
    hist = db.col("chat_history").find_one({"analysis_id": analysis_id}) if analysis_id else None
    if hist:
        a = db.strip(hist)
    else:
        c = classify(message or "", ctx.embedder)
        a = {**c, "analysis_id": None, "message": message, "confidence": 0.0, "sources": [], "category": c["category"],
             "subcategory": c["subcategory"], "suggested_resolution": c["suggested_resolution"], "intent": "incident"}
    if a.get("ticket_id") and a.get("outcome") in ("ticket_created", "escalated", "auto_resolved"):
        return db.strip(db.col("tickets").find_one({"ticket_id": a["ticket_id"]}))
    if a["category"] == "General":
        a["assignment_group"] = HUMAN_GROUP
    a["summary"] = a.get("summary") or (a["message"] or "")[:80]
    ref = sn.create_incident(_incident_payload(a, user, f"Escalated: {reason}"))
    t = _save_ticket({**a, "analysis_id": a.get("analysis_id")}, ref, "escalated", user_id)
    if hist:
        db.col("chat_history").update_one({"analysis_id": analysis_id}, {"$set": {
            "ticket_id": t["ticket_id"], "servicenow": _sn_summary(ref), "escalated": True, "outcome": "escalated",
            "answer": hist.get("answer", "") + f"\n\nTicket {ref['number']} created for a human agent."}})
    db.audit("ticket.escalated", user_id, {"reason": reason, "sn": ref["number"]}, t["ticket_id"])
    return t


def refresh_service_requests():
    """Advance mock provisioning status (Provisioning -> Completed) and sync ServiceNow."""
    for r in db.col("service_requests").find({"status": "Provisioning"}):
        if software.job_status(r["job_id"]) == "completed":
            db.col("service_requests").update_one({"request_id": r["request_id"]}, {"$set": {"status": "Completed", "completed_at": db.utcnow()}})
            try:
                sn.update_service_request(r["sn_sys_id"], {"request_state": "closed_complete"})
            except Exception:                                    # noqa: BLE001
                pass
