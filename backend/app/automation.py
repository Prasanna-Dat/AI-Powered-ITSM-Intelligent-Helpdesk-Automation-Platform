"""Self-heal actions. All of them are MOCKS that change the fake 'directory' stored in the users collection.

Safety rules (see orchestrator): an action only runs if (1) it is on this whitelist AND
(2) the knowledge base has an approved article that supports it. Every action is written to the audit log.
"""
from app import db

# action -> (human title, KB article title that must support it)
ACTIONS = {
    "password_reset": ("Password reset", "Password Reset"),
    "account_unlock": ("Account unlock", "Account Unlock"),
    "clear_cache": ("Clear application cache", "Application Restart and Cache Clearing"),
    "restart_application": ("Restart application", "Application Restart and Cache Clearing"),
    "vpn_status_check": ("VPN status check", "VPN Troubleshooting"),
}

SEED_USERS = [
    {"user_id": "alice", "name": "Alice Kumar", "email": "alice.kumar@example.com", "department": "Engineering",
     "password_status": "expired", "account_locked": False},
    {"user_id": "bob", "name": "Bob Raj", "email": "bob.raj@example.com", "department": "Finance",
     "password_status": "active", "account_locked": True},
    {"user_id": "charlie", "name": "Charlie Das", "email": "charlie.das@example.com", "department": "Sales",
     "password_status": "active", "account_locked": False},
]


def seed_users(reset=False):
    c = db.col("users")
    if reset:
        c.delete_many({})
    if c.count_documents({}) == 0:
        c.insert_many([{**u, "created_at": db.utcnow()} for u in SEED_USERS])


def _user(user_id):
    return db.col("users").find_one({"user_id": user_id}) or {}


def diagnose(action, user_id):
    u = _user(user_id)
    if action == "password_reset":
        return f"Directory shows password status = '{u.get('password_status', 'unknown')}'"
    if action == "account_unlock":
        return f"Directory shows account_locked = {u.get('account_locked', 'unknown')}"
    if action == "vpn_status_check":
        return "VPN gateway reachable; checking last session for the user"
    return "Application issue reported; restart/cache clear is non-destructive"


def execute(action, user_id):
    """Runs the mock action and returns (success, detail)."""
    if action == "password_reset":
        db.col("users").update_one({"user_id": user_id}, {"$set": {"password_status": "active", "password_reset_at": db.utcnow()}})
        return True, "Password reset completed; secure reset link sent to the registered email"
    if action == "account_unlock":
        db.col("users").update_one({"user_id": user_id}, {"$set": {"account_locked": False, "unlocked_at": db.utcnow()}})
        return True, "Account unlocked in directory"
    if action == "clear_cache":
        db.col("users").update_one({"user_id": user_id}, {"$set": {"cache_cleared_at": db.utcnow()}})
        return True, "Application cache cleared (mock: 1.2 GB removed)"
    if action == "restart_application":
        db.col("users").update_one({"user_id": user_id}, {"$set": {"app_restarted_at": db.utcnow()}})
        return True, "Application restarted"
    if action == "vpn_status_check":
        return True, "VPN gateway status: online; last session ended 12 minutes ago"
    return False, f"Unknown action {action}"


def validate(action, user_id):
    """Re-checks the system after the action. Returns (ok, detail)."""
    u = _user(user_id)
    if action == "password_reset":
        ok = u.get("password_status") == "active"
        return ok, f"Directory now reports password_status = '{u.get('password_status')}'"
    if action == "account_unlock":
        ok = not u.get("account_locked", True)
        return ok, f"Directory now reports account_locked = {u.get('account_locked')}"
    if action == "clear_cache":
        return "cache_cleared_at" in u, "Cache size verified as 0 MB"
    if action == "restart_application":
        return "app_restarted_at" in u, "Application process verified as running"
    return True, "Status verified"
