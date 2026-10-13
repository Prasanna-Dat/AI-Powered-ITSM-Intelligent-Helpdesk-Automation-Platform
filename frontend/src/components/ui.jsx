// Small shared building blocks used by several screens.
export const INTENT_LABEL = {
  knowledge_question: "Knowledge question",
  incident: "Incident",
  service_request: "Service request",
  automatable_issue: "Automatable issue",
  unknown: "Unknown",
};

export const OUTCOME_LABEL = {
  answered: "Answered from knowledge base",
  ticket_created: "Incident created",
  auto_resolved: "Resolved automatically",
  escalated: "Escalated to a human",
  request_created: "Request created",
  unanswered: "Not in knowledge base",
};

export function Badge({ tone = "grey", children }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function statusTone(s) {
  return { ai_resolved: "green", resolved: "green", Completed: "green", open: "blue", escalated: "amber",
           Provisioning: "blue", Submitted: "blue" }[s] || "grey";
}

// Horizontal bar with a tick showing the escalation threshold.
export function Confidence({ value, threshold }) {
  const pct = Math.round(value * 100);
  const ok = value >= threshold;
  return (
    <div className="conf" title={`Escalation threshold ${Math.round(threshold * 100)}%`}>
      <div className="conf-track">
        <div className={`conf-fill ${ok ? "ok" : "low"}`} style={{ width: `${pct}%` }} />
        <div className="conf-tick" style={{ left: `${threshold * 100}%` }} />
      </div>
      <span className="conf-num">{pct}%</span>
    </div>
  );
}

export function Sources({ sources }) {
  if (!sources?.length) return <p className="muted">No knowledge-base article was used.</p>;
  return (
    <ul className="sources">
      {sources.map((s) => (
        <li key={s.doc_id}>
          <strong>{s.doc_id}</strong> {s.title} <span className="muted">({s.section}, similarity {s.score})</span>
        </li>
      ))}
    </ul>
  );
}

export function Steps({ steps }) {
  return (
    <ol className="steps">
      {steps.map((s, i) => (
        <li key={i} className={`step step-${s.status}`}>
          <span className="step-name">{s.step}</span>
          <span className="step-detail">{s.detail}</span>
        </li>
      ))}
    </ol>
  );
}

export function Empty({ children }) {
  return <p className="empty">{children}</p>;
}
