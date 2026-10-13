"""Software catalogue, matching, and the MOCK provisioning API (no real installation happens)."""
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter

from app import db
from app.config import settings

CATALOG = [
    {"id": "SW001", "name": "Visual Studio Code", "aliases": ["visual studio code", "vs code", "vscode"], "version": "1.95", "category": "Developer Tools"},
    {"id": "SW002", "name": "Python", "aliases": ["python"], "version": "3.12", "category": "Developer Tools"},
    {"id": "SW003", "name": "Git", "aliases": ["git"], "version": "2.47", "category": "Developer Tools"},
    {"id": "SW004", "name": "Google Chrome", "aliases": ["google chrome", "chrome"], "version": "130", "category": "Browsers"},
    {"id": "SW005", "name": "Zoom", "aliases": ["zoom"], "version": "6.2", "category": "Collaboration"},
    {"id": "SW006", "name": "Slack", "aliases": ["slack"], "version": "4.40", "category": "Collaboration"},
    {"id": "SW007", "name": "Docker Desktop", "aliases": ["docker desktop", "docker"], "version": "4.35", "category": "Developer Tools"},
    {"id": "SW008", "name": "Postman", "aliases": ["postman"], "version": "11", "category": "Developer Tools"},
    {"id": "SW009", "name": "7-Zip", "aliases": ["7-zip", "7zip"], "version": "24.09", "category": "Utilities"},
    {"id": "SW010", "name": "Notepad++", "aliases": ["notepad++", "notepad plus"], "version": "8.7", "category": "Utilities"},
]


def seed_catalog():
    c = db.col("software_catalog")
    if c.count_documents({}) == 0:
        c.insert_many([dict(i) for i in CATALOG])


def match(text: str):
    """Longest alias found in the text wins ('visual studio code' beats 'code')."""
    t = text.lower()
    best, best_len = None, 0
    for item in db.find_all("software_catalog", sort_field="id", direction=1):
        for alias in item["aliases"]:
            if re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", t) and len(alias) > best_len:
                best, best_len = item, len(alias)
    return best


# ---------------------------------------------------------------------------- mock provisioning API
def provision(request_id: str, software: str, user_id: str) -> dict:
    """Pretend to push an install to the user's laptop. Status becomes 'completed' after a delay."""
    job = {"job_id": "JOB-" + uuid.uuid4().hex[:8].upper(), "request_id": request_id, "software": software,
           "user_id": user_id, "status": "provisioning", "started_at": db.utcnow()}
    db.col("provisioning_jobs").insert_one(dict(job))
    db.audit("provisioning.start", "ai-agent", {"software": software, "user": user_id, "job": job["job_id"]}, request_id)
    return job


def job_status(job_id: str) -> str:
    j = db.col("provisioning_jobs").find_one({"job_id": job_id})
    if not j:
        return "unknown"
    started = datetime.fromisoformat(j["started_at"])
    if (datetime.now(timezone.utc) - started).total_seconds() >= settings.PROVISIONING_SECONDS:
        return "completed"
    return "provisioning"


router = APIRouter(prefix="/mock-provisioning", tags=["Mock Provisioning API"])


@router.post("/install")
def api_install(body: dict):
    return provision(body.get("request_id", "REQ-MANUAL"), body.get("software", "unknown"), body.get("user_id", "unknown"))


@router.get("/jobs/{job_id}")
def api_job(job_id: str):
    return {"job_id": job_id, "status": job_status(job_id)}
