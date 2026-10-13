"""ServiceNow integration.

* REAL mode  - used when SERVICENOW_INSTANCE / USER / PASSWORD are set. Calls the ServiceNow Table REST API.
* MOCK mode  - otherwise. A small ServiceNow look-alike stored in MongoDB, also exposed as REST under
               /mock-servicenow/api/now/table/... so the same payloads can be tried with curl / Swagger.

The rest of the app only talks to ServiceNowClient, so switching mock -> real needs no code change.
"""
import uuid

import httpx
from fastapi import APIRouter, HTTPException

from app import db
from app.config import settings

# our category -> ServiceNow default 'category' choice value
SN_CATEGORY = {"Network": "network", "Email": "software", "Access": "inquiry",
               "Hardware": "hardware", "Software": "software", "General": "inquiry"}
STATE_NAMES = {"1": "New", "2": "In Progress", "6": "Resolved", "7": "Closed"}


# ----------------------------------------------------------------------------- mock store
def _mock_create_incident(p: dict) -> dict:
    num = f"INC{db.next_seq('incident', 10000):07d}"
    rec = {**p, "sys_id": uuid.uuid4().hex, "number": num, "state": "1", "opened_at": db.utcnow(),
           "work_notes": ""}
    db.col("mock_sn_incidents").insert_one(dict(rec))
    return rec


def _mock_create_request(p: dict) -> dict:
    num = f"REQ{db.next_seq('request', 1244):06d}"
    rec = {**p, "sys_id": uuid.uuid4().hex, "number": num, "request_state": "requested",
           "opened_at": db.utcnow()}
    db.col("mock_sn_requests").insert_one(dict(rec))
    return rec


def _mock_get(collection, key):
    rec = db.col(collection).find_one({"$or": [{"sys_id": key}, {"number": key}]})
    if not rec:
        raise HTTPException(404, f"{key} not found")
    return db.strip(rec)


def _mock_update(collection, key, fields):
    rec = _mock_get(collection, key)
    if "work_notes" in fields and rec.get("work_notes"):
        fields = {**fields, "work_notes": rec["work_notes"] + "\n" + fields["work_notes"]}
    db.col(collection).update_one({"sys_id": rec["sys_id"]}, {"$set": fields})
    return _mock_get(collection, rec["sys_id"])


# ----------------------------------------------------------------------------- client
class ServiceNowClient:
    @property
    def mode(self):
        return "ServiceNow REST API" if settings.servicenow_real else "Mock ServiceNow"

    # -- low level ---------------------------------------------------------------
    def _call(self, method, table, sys_id="", json=None, params=None):
        url = f"{settings.servicenow_base}/api/now/table/{table}" + (f"/{sys_id}" if sys_id else "")
        r = httpx.request(method, url, json=json, params=params, timeout=30,
                          auth=(settings.SERVICENOW_USER, settings.SERVICENOW_PASSWORD),
                          headers={"Accept": "application/json", "Content-Type": "application/json"})
        r.raise_for_status()
        return r.json()["result"]

    def _group_id(self, name):
        """ServiceNow wants the sys_id of the assignment group, so we look it up by name."""
        try:
            res = self._call("GET", "sys_user_group", params={"sysparm_query": f"name={name}", "sysparm_limit": 1})
            return res[0]["sys_id"] if res else None
        except Exception:                                   # noqa: BLE001
            return None

    # -- incidents ---------------------------------------------------------------
    def create_incident(self, p: dict) -> dict:
        if not settings.servicenow_real:
            res = _mock_create_incident(p)
        else:
            body = {k: v for k, v in p.items() if k != "assignment_group"}
            gid = self._group_id(p.get("assignment_group", ""))
            if gid:
                body["assignment_group"] = gid
            res = self._call("POST", "incident", json=body)
        db.audit("servicenow.create_incident", "ai-agent", {"number": res["number"], "mode": self.mode}, res["number"])
        return {"sys_id": res["sys_id"], "number": res["number"], "mode": self.mode,
                "state": STATE_NAMES.get(str(res.get("state", "1")), "New")}

    def get_incident(self, key: str) -> dict:
        res = _mock_get("mock_sn_incidents", key) if not settings.servicenow_real else \
            self._call("GET", "incident", key)
        return {**res, "state_label": STATE_NAMES.get(str(res.get("state")), str(res.get("state"))), "mode": self.mode}

    def update_incident(self, sys_id: str, fields: dict) -> dict:
        res = _mock_update("mock_sn_incidents", sys_id, fields) if not settings.servicenow_real else \
            self._call("PATCH", "incident", sys_id, json=fields)
        db.audit("servicenow.update_incident", "ai-agent", {"sys_id": sys_id, "fields": list(fields)}, res.get("number", ""))
        return {"number": res.get("number"), "state": STATE_NAMES.get(str(res.get("state")), str(res.get("state"))),
                "mode": self.mode}

    # -- service requests --------------------------------------------------------
    def create_service_request(self, p: dict) -> dict:
        if not settings.servicenow_real:
            res = _mock_create_request(p)
        else:
            body = {k: v for k, v in p.items() if k != "assignment_group"}
            res = self._call("POST", "sc_request", json=body)
        db.audit("servicenow.create_request", "ai-agent", {"number": res["number"], "mode": self.mode}, res["number"])
        return {"sys_id": res["sys_id"], "number": res["number"], "mode": self.mode}

    def update_service_request(self, sys_id: str, fields: dict):
        res = _mock_update("mock_sn_requests", sys_id, fields) if not settings.servicenow_real else \
            self._call("PATCH", "sc_request", sys_id, json=fields)
        db.audit("servicenow.update_request", "ai-agent", {"sys_id": sys_id, "fields": list(fields)}, res.get("number", ""))
        return res


sn = ServiceNowClient()

# ----------------------------------------------------------------------------- mock REST endpoints
router = APIRouter(prefix="/mock-servicenow/api/now/table", tags=["Mock ServiceNow (REST look-alike)"])


@router.post("/incident")
def r_create_incident(body: dict):
    return {"result": _mock_create_incident(db.strip(dict(body)))}


@router.get("/incident/{key}")
def r_get_incident(key: str):
    return {"result": _mock_get("mock_sn_incidents", key)}


@router.patch("/incident/{key}")
def r_update_incident(key: str, body: dict):
    return {"result": _mock_update("mock_sn_incidents", key, body)}


@router.post("/sc_request")
def r_create_request(body: dict):
    return {"result": _mock_create_request(db.strip(dict(body)))}


@router.get("/sc_request/{key}")
def r_get_request(key: str):
    return {"result": _mock_get("mock_sn_requests", key)}
