"""Five required scenarios + extras. Run:  cd backend && pytest -v"""


def chat(client, msg, user="alice", **kw):
    r = client.post("/api/chat", json={"message": msg, "user_id": user, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_1_intelligent_ticket_intake_vpn(client):
    a = chat(client, "I cannot connect to VPN since this morning. Authentication keeps failing.")
    assert a["intent"] == "incident"
    assert (a["category"], a["subcategory"]) == ("Network", "VPN")
    assert a["priority"] == "P2"
    assert (a["impact"], a["urgency"]) == ("Individual", "High")
    assert a["assignment_group"] == "Network Support"
    assert a["summary"] == "VPN authentication failure"
    assert a["suggested_resolution"] == "VPN troubleshooting"
    assert a["servicenow"]["number"].startswith("INC")
    assert any(s["title"] == "VPN Troubleshooting" for s in a["sources"])


def test_2_self_heal_password_expired(client):
    client.post("/api/admin/reset-mock-directory")
    a = chat(client, "My password has expired.")
    assert a["outcome"] == "auto_resolved"
    assert a["automation"]["success"] is True
    names = [s["step"] for s in a["steps"]]
    for step in ("Identify", "Diagnose", "Knowledge search", "Determine automation", "Execute", "Validate", "Update ServiceNow"):
        assert step in names
    inc = client.get(f"/api/tickets/{a['ticket_id']}/servicenow").json()
    assert inc["state_label"] == "Resolved"
    logs = client.get("/api/audit-logs").json()
    assert any(l["action"].startswith("automation.password_reset") for l in logs)


def test_3_rag_outlook_sync(client):
    a = chat(client, "How do I troubleshoot Outlook synchronization?")
    assert a["intent"] == "knowledge_question" and a["outcome"] == "answered"
    assert a["answer"] and a["sources"][0]["title"] == "Outlook Synchronization Issues"
    assert a["confidence"] >= a["threshold"]


def test_4_software_provisioning_vscode(client):
    a = chat(client, "I need Visual Studio Code.")
    sr = a["service_request"]
    assert sr["software"] == "Visual Studio Code" and sr["status"] == "Provisioning"
    assert sr["request_id"].startswith("REQ") and "created successfully" in sr["message"]


def test_5_unknown_question_no_hallucination(client):
    a = chat(client, "What is the capital of France?")
    assert a["outcome"] == "unanswered" and a["sources"] == []
    assert "won't guess" in a["answer"] and a["can_create_ticket"] is True
    t = client.post("/api/tickets", json={"user_id": "alice", "analysis_id": a["analysis_id"]}).json()
    assert t["status"] == "escalated" and t["sn_number"].startswith("INC")


def test_6_account_unlock(client):
    a = chat(client, "My account is locked", user="bob")
    assert a["outcome"] == "auto_resolved" and a["automation"]["action"] == "account_unlock"


def test_7_software_not_in_catalogue(client):
    a = chat(client, "I need Photoshop installed")
    assert a["outcome"] == "unanswered" and a["service_request"] is None


def test_8_update_incident_and_dashboard(client):
    a = chat(client, "My laptop is very slow")
    r = client.patch(f"/api/tickets/{a['ticket_id']}", json={"status": "resolved", "note": "Cleaned startup items"})
    assert r.json()["servicenow"]["state"] == "Resolved"
    d = client.get("/api/dashboard").json()
    assert d["tickets_total"] >= 3 and d["tickets_ai_resolved"] >= 2 and d["software_requests"] >= 1
