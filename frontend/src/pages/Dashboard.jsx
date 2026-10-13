import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Empty, statusTone } from "../components/ui.jsx";

function Stat({ label, value, note }) {
  return (
    <div className="stat">
      <div className="stat-value">{value ?? "–"}</div>
      <div className="stat-label">{label}</div>
      {note && <div className="muted small">{note}</div>}
    </div>
  );
}

export default function Dashboard({ onOpenAnalysis }) {
  const [d, setD] = useState(null);
  const [audit, setAudit] = useState([]);
  const [snView, setSnView] = useState({});
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api.dashboard().then(setD).catch((e) => setError(e.message));
    api.auditLogs(12).then(setAudit).catch(() => {});
  }, []);

  useEffect(() => { load(); const t = setInterval(load, 6000); return () => clearInterval(t); }, [load]);

  const checkSN = async (id) => {
    const r = await api.serviceNowIncident(id);
    setSnView((s) => ({ ...s, [id]: r.state_label }));
  };
  const resolve = async (id) => {
    await api.resolveTicket(id, "Resolved by agent from dashboard");
    load();
    checkSN(id);
  };

  if (error) return <div className="alert">{error}</div>;
  if (!d) return <p className="empty">Loading dashboard…</p>;

  return (
    <section className="page">
      <header className="page-head">
        <h2>ITSM Dashboard</h2>
        <p>Live view of tickets, AI results, software requests and automation. Refreshes every few seconds.</p>
      </header>

      <div className="stats">
        <Stat label="Total tickets" value={d.tickets_total} />
        <Stat label="Open tickets" value={d.tickets_open} />
        <Stat label="AI-resolved tickets" value={d.tickets_ai_resolved} note="self-heal agent" />
        <Stat label="Escalated to humans" value={d.tickets_escalated} />
        <Stat label="Answered by RAG" value={d.answered_by_rag} note={`${d.unanswered_escalation_offered} not in KB`} />
        <Stat label="Software requests" value={d.software_requests} note={`${d.software_completed} completed`} />
        <Stat label="Automation success" value={d.automation_success_rate == null ? "–" : `${d.automation_success_rate}%`}
              note={`${d.automation_success} of ${d.automation_total} actions`} />
      </div>

      <h3>Tickets (ServiceNow incidents)</h3>
      {d.recent_tickets.length === 0 ? <Empty>No tickets yet. Report a problem in Self-Service.</Empty> : (
        <div className="table-wrap"><table>
          <thead><tr><th>Ticket</th><th>ServiceNow</th><th>Summary</th><th>Priority</th><th>Group</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>{d.recent_tickets.map((t) => (
            <tr key={t.ticket_id}>
              <td>{t.ticket_id}</td>
              <td>{t.sn_number}{snView[t.ticket_id] && <div className="muted small">SN state: {snView[t.ticket_id]}</div>}</td>
              <td>{t.summary}</td><td>{t.priority}</td><td>{t.assignment_group}</td>
              <td><Badge tone={statusTone(t.status)}>{t.status.replace("_", " ")}</Badge></td>
              <td className="row-actions">
                <button className="link" onClick={() => onOpenAnalysis(t.analysis_id)}>Analysis</button>
                <button className="link" onClick={() => checkSN(t.ticket_id)}>Get from ServiceNow</button>
                {t.status !== "resolved" && t.status !== "ai_resolved" &&
                  <button className="link" onClick={() => resolve(t.ticket_id)}>Resolve</button>}
              </td>
            </tr>))}
          </tbody></table></div>
      )}

      <h3>Software requests</h3>
      {d.recent_requests.length === 0 ? <Empty>No requests yet.</Empty> : (
        <div className="table-wrap"><table>
          <thead><tr><th>Request ID</th><th>Item</th><th>User</th><th>Status</th><th>Created</th></tr></thead>
          <tbody>{d.recent_requests.map((r) => (
            <tr key={r.request_id}><td>{r.request_id}</td><td>{r.software}</td><td>{r.user_id}</td>
              <td><Badge tone={statusTone(r.status)}>{r.status}</Badge></td><td>{r.created_at}</td></tr>))}
          </tbody></table></div>
      )}

      <h3>Automation status</h3>
      {d.recent_automation.length === 0 ? <Empty>No automated actions yet.</Empty> : (
        <div className="table-wrap"><table>
          <thead><tr><th>Action</th><th>User</th><th>Result</th><th>ServiceNow</th><th>Time</th></tr></thead>
          <tbody>{d.recent_automation.map((a, i) => (
            <tr key={i}><td>{a.title}</td><td>{a.user_id}</td>
              <td><Badge tone={a.success ? "green" : "red"}>{a.success ? "success" : "failed"}</Badge></td>
              <td>{a.sn_number}</td><td>{a.created_at}</td></tr>))}
          </tbody></table></div>
      )}

      <h3>Audit log</h3>
      <div className="table-wrap"><table>
        <thead><tr><th>Time</th><th>Action</th><th>Actor</th><th>Reference</th><th>Status</th></tr></thead>
        <tbody>{audit.map((l, i) => (
          <tr key={i}><td>{l.created_at}</td><td>{l.action}</td><td>{l.actor}</td><td>{l.ref}</td><td>{l.status}</td></tr>))}
        </tbody></table></div>
    </section>
  );
}
