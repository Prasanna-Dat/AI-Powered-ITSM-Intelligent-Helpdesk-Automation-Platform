"""Intelligent ticket intake: turns free text into structured ITSM fields.

How it decides (hybrid, explainable):
  1. Intent       - regex rules (automation / how-to question / software request / problem words).
  2. Category     - keyword score (70%) + embedding similarity to example sentences (30%).
  3. Urgency / impact - signal words ('cannot', 'since this morning', 'whole team' ...).
  4. Priority     - impact x urgency matrix (P1 most urgent).
Everything returns a confidence number so the orchestrator can escalate when the AI is unsure.
"""
import re

from app import software

# ---- category table: keyword -> weight ---------------------------------------------------------
CATEGORIES = [
    {"key": "vpn", "category": "Network", "sub": "VPN", "group": "Network Support", "resolution": "VPN troubleshooting",
     "kw": {"vpn": 3, "remote access": 2, "anyconnect": 3, "globalprotect": 3, "gateway": 1},
     "examples": ["cannot connect to vpn", "vpn authentication failed", "remote access not working"]},
    {"key": "wifi", "category": "Network", "sub": "Wi-Fi", "group": "Network Support", "resolution": "Wi-Fi connectivity troubleshooting",
     "kw": {"wifi": 3, "wi-fi": 3, "wireless": 2, "internet": 2, "no internet": 3, "network": 1},
     "examples": ["wifi keeps disconnecting", "laptop cannot find wireless network", "no internet connection"]},
    {"key": "email", "category": "Email", "sub": "Outlook", "group": "Messaging Support", "resolution": "Outlook synchronization troubleshooting",
     "kw": {"outlook": 3, "email": 2, "mailbox": 2, "calendar": 2, "inbox": 2, "sync": 2, "emails": 2},
     "examples": ["outlook is not syncing", "emails not arriving in my inbox", "calendar not updating"]},
    {"key": "password", "category": "Access", "sub": "Password Reset", "group": "Identity & Access Support", "resolution": "Password reset",
     "kw": {"password": 3, "passcode": 2, "credentials": 1, "authentication": 1, "sign in": 1, "login": 1},
     "examples": ["my password has expired", "i forgot my password", "need to reset my password"]},
    {"key": "lock", "category": "Access", "sub": "Account Locked", "group": "Identity & Access Support", "resolution": "Account unlock",
     "kw": {"locked": 3, "lock out": 3, "locked out": 3, "unlock": 3, "account": 1},
     "examples": ["my account is locked", "locked out of my account", "please unlock my account"]},
    {"key": "performance", "category": "Hardware", "sub": "Laptop", "group": "Desktop Support", "resolution": "Laptop performance troubleshooting",
     "kw": {"laptop": 2, "slow": 2, "freez": 3, "performance": 3, "hang": 2, "fan": 1, "memory": 1, "battery": 1, "computer": 1},
     "examples": ["my laptop is very slow", "computer keeps freezing", "laptop performance is bad"]},
    {"key": "software", "category": "Software", "sub": "Installation", "group": "Desktop Support", "resolution": "Software installation guidance",
     "kw": {"install": 3, "software": 2, "installation": 3, "download": 1, "application": 1, "app": 1},
     "examples": ["i need software installed", "install an application on my laptop", "software installation failed"]},
    {"key": "access", "category": "Access", "sub": "Application", "group": "Identity & Access Support", "resolution": "Application access request",
     "kw": {"access": 3, "permission": 3, "sharepoint": 2, "folder": 1, "denied": 2, "role": 1},
     "examples": ["i need access to the finance folder", "access denied to application", "request permission for sharepoint"]},
    {"key": "cache", "category": "Software", "sub": "Application Issue", "group": "Application Support", "resolution": "Application restart and cache clearing",
     "kw": {"cache": 3, "teams": 2, "restart": 2, "browser": 1},
     "examples": ["clear my teams cache", "restart the application", "teams is showing old data"]},
]
FALLBACK = {"key": "general", "category": "General", "sub": "Other", "group": "Service Desk (Human Triage)",
            "resolution": "General triage by Service Desk"}

# ---- automation (self-heal) rules --------------------------------------------------------------
AUTOMATION_RULES = [
    ("password_reset", [r"password.*(expired|expire|reset|forgot|forgotten)", r"(expired|forgot|forgotten).*password"]),
    ("account_unlock", [r"locked out", r"account.*locked", r"unlock (my |the )?account", r"account is lock"]),
    ("vpn_status_check", [r"(check|verify).*vpn", r"vpn status"]),
    ("clear_cache", [r"clear.*cache", r"cache.*(clear|corrupt|full)"]),
    ("restart_application", [r"restart.*(outlook|teams|app|application|service)", r"(outlook|teams|app) (is |has )?(frozen|stuck|hung)"]),
]

HOW_TO = r"^(how (do|can|to|should|would)|what (is|are) the (process|procedure|steps)|where (can|do) i|what steps|can you (explain|tell|show)|explain|tell me|steps to|guide)"
QUESTION = r"^(how|what|where|why|when|which|who|can i|can we|could i|is it|is there|are there|do i|does|should i|show me)\b"
PROBLEM = (r"\b(cannot|can't|cant|can not|unable|won't|wont|isn't|doesn't|failing|failed|fails|error|slow|crash\w*|"
           r"freez\w*|frozen|stuck|broken|down|keeps?|not (working|connecting|syncing|opening|loading|responding|starting|sending|receiving))\b")
INSTALL_VERBS = r"\b(install|installed|installation|download|set ?up|provision|need|want|get me|request|require)\b"
ACCESS_REQ = r"\b(need|request|want|require|grant|give me)\b.*\b(access|permission)\b"

URGENT = r"\b(cannot|can't|cant|can not|unable|keeps failing|failing|failed|down|urgent|asap|since this morning|blocked|critical|outage|crash\w*|won't|not (working|connecting|syncing|opening|loading|responding|starting))\b"
LOW_URG = r"\b(whenever|when you get a chance|not urgent|minor|no rush|sometimes)\b"
ENTERPRISE = r"\b(everyone|all users|company[- ]wide|entire company|whole company|outage|all employees)\b"
DEPARTMENT = r"\b(team|department|colleagues|we all|our team|floor|several users|multiple users|office)\b"

PRIORITY = {(1, 1): 1, (1, 2): 2, (1, 3): 3, (2, 1): 2, (2, 2): 3, (2, 3): 4, (3, 1): 2, (3, 2): 3, (3, 3): 4}
IMPACT_NAME = {1: "Enterprise", 2: "Department", 3: "Individual"}
URGENCY_NAME = {1: "High", 2: "Medium", 3: "Low"}

ISSUE_PHRASES = [(r"authent|credential|login|sign in|password", "authentication failure"),
                 (r"connect|connection|disconnect", "connection failure"),
                 (r"slow", "slow performance"), (r"sync", "synchronization issue"),
                 (r"crash|freez|frozen|hang|stuck", "crash / freeze"), (r"install", "installation failure"),
                 (r"access|permission|denied", "access issue"), (r"expired", "expired credentials")]


def _kw_hits(text, kw):
    total = 0
    for word, weight in kw.items():
        if re.search(r"(?<![a-z0-9])" + re.escape(word), text):
            total += weight
    return min(1.0, total / 3)


def classify(message: str, embedder) -> dict:
    t = message.lower().strip()

    # ---------- category ----------
    q = embedder.encode([t])[0]
    best, best_score = None, 0.0
    for rule in CATEGORIES:
        ex = embedder.encode(rule["examples"])
        sim = max(0.0, float((ex @ q).max()))
        score = 0.7 * _kw_hits(t, rule["kw"]) + 0.3 * min(1.0, sim / embedder.full_score)
        if score > best_score:
            best, best_score = rule, score
    cat = best if best_score >= 0.25 else FALLBACK
    category_conf = round(min(1.0, best_score + 0.15), 2) if cat is not FALLBACK else 0.1
    sw = software.match(t)
    if sw and re.search(INSTALL_VERBS, t):              # a catalogue item was named -> software category
        cat, category_conf = next(r for r in CATEGORIES if r["key"] == "software"), 0.95

    # ---------- intent ----------
    action = None
    for name, patterns in AUTOMATION_RULES:
        if any(re.search(p, t) for p in patterns):
            action = name
            break
    if re.search(HOW_TO, t):
        intent, intent_conf = "knowledge_question", 0.8
    elif action:
        intent, intent_conf = "automatable_issue", 0.95
    elif re.search(INSTALL_VERBS, t) and (sw or "install" in t):
        intent, intent_conf = "service_request", 0.95 if sw else 0.5
    elif re.search(ACCESS_REQ, t):
        intent, intent_conf = "service_request", 0.8
        cat = next(r for r in CATEGORIES if r["key"] == "access")
        category_conf = max(category_conf, 0.8)
    elif re.search(PROBLEM, t):
        intent, intent_conf = "incident", 0.85
    elif re.search(QUESTION, t) or t.endswith("?"):
        intent, intent_conf = "knowledge_question", 0.6
    else:
        intent, intent_conf = "unknown", 0.3

    # ---------- impact / urgency / priority ----------
    impact = 1 if re.search(ENTERPRISE, t) else 2 if re.search(DEPARTMENT, t) else 3
    urgency = 3 if re.search(LOW_URG, t) else 1 if re.search(URGENT, t) else 2
    if intent in ("service_request", "knowledge_question"):
        urgency = max(urgency, 2)
    priority = PRIORITY[(impact, urgency)]
    if intent == "service_request":
        priority = 4

    # ---------- summary ----------
    phrase = next((p for pat, p in ISSUE_PHRASES if re.search(pat, t)), "issue")
    summary = f"{cat['sub']} {phrase}" if cat is not FALLBACK else message[:80]
    if intent == "service_request" and sw:
        summary = f"Software request: {sw['name']}"
    if intent == "automatable_issue":
        summary = f"{cat['sub']} - automated fix requested"

    return {"intent": intent, "intent_conf": intent_conf, "category": cat["category"], "subcategory": cat["sub"],
            "category_conf": category_conf, "assignment_group": cat["group"], "suggested_resolution": cat["resolution"],
            "impact": IMPACT_NAME[impact], "impact_n": impact, "urgency": URGENCY_NAME[urgency], "urgency_n": urgency,
            "priority": f"P{priority}", "priority_n": priority, "summary": summary,
            "automation_action": action, "software": sw}
