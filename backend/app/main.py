"""FastAPI application - all REST endpoints. Interactive docs: http://localhost:8000/docs"""
import logging
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import automation, db, orchestrator, servicenow, software
from app.config import settings
from app.context import get_ctx
from app.servicenow import sn

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app):
    db.get_db()
    automation.seed_users()
    software.seed_catalog()
    get_ctx()                      # loads embedding model, builds Qdrant collection, loads LLM
    yield


app = FastAPI(title="AI-Powered ITSM Helpdesk", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
app.include_router(servicenow.router)
app.include_router(software.router)


class ChatIn(BaseModel):
    message: str
    user_id: str = "alice"
    force_intent: Optional[Literal["incident", "service_request"]] = None


class TicketIn(BaseModel):
    user_id: str = "alice"
    analysis_id: Optional[str] = None
    message: Optional[str] = None
    reason: str = "User requested human help"


class TicketPatch(BaseModel):
    status: Literal["in_progress", "resolved"]
    note: str = ""


class SearchIn(BaseModel):
    query: str
    k: int = 3
    category: Optional[str] = None


@app.get("/api/health")
def health():
    ctx = get_ctx()
    return {"status": "ok", "database": db.DB_MODE, "servicenow": sn.mode, "llm": ctx.llm.model_name,
            "llm_backend": ctx.llm.backend, "embedding": ctx.embedder.model_name, "vector_db": ctx.kb.store,
            "kb_articles": len(ctx.kb.docs), "kb_chunks": len(ctx.kb.chunks)}


@app.get("/api/config")
def config():
    ctx = get_ctx()
    return {"confidence_threshold": settings.CONFIDENCE_THRESHOLD, "top_k": settings.TOP_K,
            "min_retrieval_score": ctx.embedder.min_score}


@app.get("/api/users")
def users():
    return db.find_all("users", sort_field="user_id", direction=1)


# ------------------------------------------------------------------ chat / analysis
@app.post("/api/chat")
def chat(body: ChatIn):
    if not body.message.strip():
        raise HTTPException(400, "message is empty")
    return orchestrator.handle_message(body.user_id, body.message.strip(), body.force_intent)


@app.get("/api/analyses")
def analyses(user_id: Optional[str] = None):
    q = {"user_id": user_id} if user_id else {}
    rows = db.col("chat_history").find(q, {"retrieved_chunks": 0, "steps": 0}).sort("created_at", -1).limit(50)
    return [db.strip(r) for r in rows]


@app.get("/api/analyses/{analysis_id}")
def analysis(analysis_id: str):
    r = db.strip(db.col("chat_history").find_one({"analysis_id": analysis_id}))
    if not r:
        raise HTTPException(404, "analysis not found")
    return r


# ------------------------------------------------------------------ tickets (ServiceNow incidents)
@app.post("/api/tickets")
def create_ticket(body: TicketIn):
    if not (body.analysis_id or body.message):
        raise HTTPException(400, "analysis_id or message is required")
    return orchestrator.create_ticket_from_analysis(body.user_id, body.analysis_id, body.message, body.reason)


@app.get("/api/tickets")
def tickets():
    return db.find_all("tickets")


@app.get("/api/tickets/{ticket_id}")
def ticket(ticket_id: str):
    t = db.strip(db.col("tickets").find_one({"ticket_id": ticket_id}))
    if not t:
        raise HTTPException(404, "ticket not found")
    return t


@app.get("/api/tickets/{ticket_id}/servicenow")
def ticket_in_servicenow(ticket_id: str):
    """GET Incident from ServiceNow (live read)."""
    t = ticket(ticket_id)
    return sn.get_incident(t["sn_sys_id"])


@app.patch("/api/tickets/{ticket_id}")
def update_ticket(ticket_id: str, body: TicketPatch):
    """UPDATE Incident in ServiceNow and mirror the status locally."""
    t = ticket(ticket_id)
    fields = {"state": "6" if body.status == "resolved" else "2", "work_notes": body.note or f"Status set to {body.status}"}
    if body.status == "resolved":
        fields.update(close_code="Solved (Permanently)", close_notes=body.note or "Resolved by agent")
    res = sn.update_incident(t["sn_sys_id"], fields)
    db.col("tickets").update_one({"ticket_id": ticket_id}, {"$set": {"status": "resolved" if body.status == "resolved" else "open"}})
    return {"ticket": ticket(ticket_id), "servicenow": res}


# ------------------------------------------------------------------ software
@app.get("/api/software/catalog")
def catalog():
    return db.find_all("software_catalog", sort_field="id", direction=1)


@app.get("/api/software/requests")
def software_requests():
    orchestrator.refresh_service_requests()
    return db.find_all("service_requests")


# ------------------------------------------------------------------ dashboard / audit
@app.get("/api/dashboard")
def dashboard():
    orchestrator.refresh_service_requests()
    t = db.col("tickets")
    ch = db.col("chat_history")
    acts = db.find_all("automation_actions", limit=10)
    total_acts = db.col("automation_actions").count_documents({})
    ok_acts = db.col("automation_actions").count_documents({"success": True})
    by_cat = {}
    for row in t.find({}, {"category": 1}):
        by_cat[row["category"]] = by_cat.get(row["category"], 0) + 1
    reqs = db.find_all("service_requests")
    return {
        "tickets_total": t.count_documents({}),
        "tickets_open": t.count_documents({"status": {"$in": ["open", "escalated"]}}),
        "tickets_ai_resolved": t.count_documents({"status": "ai_resolved"}),
        "tickets_escalated": t.count_documents({"status": "escalated"}),
        "answered_by_rag": ch.count_documents({"outcome": "answered"}),
        "unanswered_escalation_offered": ch.count_documents({"outcome": "unanswered"}),
        "software_requests": sum(1 for r in reqs if r["kind"] == "software"),
        "software_completed": sum(1 for r in reqs if r["kind"] == "software" and r["status"] == "Completed"),
        "automation_total": total_acts, "automation_success": ok_acts,
        "automation_success_rate": round(100 * ok_acts / total_acts) if total_acts else None,
        "tickets_by_category": by_cat, "recent_automation": acts, "recent_tickets": db.find_all("tickets", limit=15),
        "recent_requests": reqs[:15],
    }


@app.get("/api/audit-logs")
def audit_logs(limit: int = 100):
    return db.find_all("audit_logs", limit=limit)


# ------------------------------------------------------------------ knowledge base
@app.get("/api/kb/articles")
def kb_articles():
    return get_ctx().kb.articles()


@app.get("/api/kb/articles/{doc_id}")
def kb_article(doc_id: str):
    a = get_ctx().kb.article(doc_id)
    if not a:
        raise HTTPException(404, "article not found")
    return a


@app.post("/api/kb/search")
def kb_search(body: SearchIn):
    """Full RAG: embed query -> Qdrant search -> LLM grounded answer + sources."""
    ctx = get_ctx()
    hits = ctx.kb.search(body.query, body.k, body.category)
    top = hits[0]["score"] if hits else 0.0
    relevant = top >= ctx.embedder.min_score
    text, by = ctx.llm.answer(body.query, hits) if relevant else (None, ctx.llm.backend)
    return {"query": body.query, "relevant": relevant, "top_score": top,
            "answer": text or "Information is unavailable in the approved knowledge base.",
            "answer_generated_by": by, "sources": ctx.kb.sources(hits) if relevant else [], "chunks": hits}


@app.post("/api/kb/reindex")
def kb_reindex():
    ctx = get_ctx()
    ctx.kb.build()
    return {"articles": len(ctx.kb.docs), "chunks": len(ctx.kb.chunks), "vector_db": ctx.kb.store}


@app.post("/api/admin/reset-mock-directory")
def reset_directory():
    """Puts the fake user directory back to its starting state (alice password expired, bob locked)."""
    automation.seed_users(reset=True)
    return {"status": "reset"}
