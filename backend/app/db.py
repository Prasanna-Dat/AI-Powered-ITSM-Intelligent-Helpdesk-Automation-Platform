"""MongoDB access. Uses MongoDB Atlas when MONGODB_URI is set, otherwise an in-memory fake (mongomock).

Collections used: users, tickets, chat_history, service_requests, software_catalog,
automation_actions, audit_logs, knowledge_docs, knowledge_chunks, counters,
mock_sn_incidents, mock_sn_requests.
"""
import logging
from datetime import datetime, timezone

from pymongo import MongoClient, ReturnDocument

from app.config import settings

log = logging.getLogger("db")
_db = None
DB_MODE = "not-started"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_db():
    global _db, DB_MODE
    if _db is not None:
        return _db
    if settings.MONGODB_URI:
        try:
            client = MongoClient(settings.MONGODB_URI, serverSelectionTimeoutMS=8000)
            client.admin.command("ping")          # fails fast if URI / network / IP allow-list is wrong
            _db = client[settings.MONGODB_DB]
            DB_MODE = "MongoDB Atlas"
            log.info("Connected to MongoDB Atlas")
            return _db
        except Exception as exc:                  # noqa: BLE001
            log.error("!!! Could not connect to MongoDB Atlas (%s). Falling back to in-memory DB.", exc)
    import mongomock
    _db = mongomock.MongoClient()[settings.MONGODB_DB]
    DB_MODE = "in-memory (mongomock)"
    return _db


def col(name: str):
    return get_db()[name]


def strip(doc):
    if doc:
        doc.pop("_id", None)
    return doc


def find_all(name, query=None, sort_field="created_at", direction=-1, limit=200):
    return [strip(d) for d in col(name).find(query or {}).sort(sort_field, direction).limit(limit)]


def next_seq(name: str, start: int) -> int:
    """Atomic counter, used for INC / REQ / ticket numbers."""
    c = col("counters")
    c.update_one({"_id": name}, {"$setOnInsert": {"seq": start}}, upsert=True)
    return c.find_one_and_update({"_id": name}, {"$inc": {"seq": 1}},
                                 return_document=ReturnDocument.AFTER)["seq"]


def audit(action: str, actor: str, details: dict, ref: str = "", status: str = "success"):
    """Append-only audit trail. Every automated action and ServiceNow call is written here."""
    col("audit_logs").insert_one({"action": action, "actor": actor, "status": status,
                                  "ref": ref, "details": details, "created_at": utcnow()})
