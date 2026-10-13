import { useRef, useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Confidence, INTENT_LABEL, OUTCOME_LABEL, Sources, Steps } from "../components/ui.jsx";

// One AI reply, with everything the employee needs: answer, evidence, ticket / request references and next actions.
function Reply({ m, userId, onOpenAnalysis, onTicket }) {
  const [busy, setBusy] = useState(false);
  const sr = m.service_request;
  const createTicket = async () => {
    setBusy(true);
    try { onTicket(m.analysis_id, await api.createTicket(userId, m.analysis_id)); } finally { setBusy(false); }
  };
  return (
    <div className="msg bot">
      <p className="answer">{m.answer}</p>

      {sr && (
        <dl className="result">
          <dt>Request ID</dt><dd>{sr.request_id}</dd>
          <dt>Software</dt><dd>{sr.software}</dd>
          <dt>Status</dt><dd><Badge tone="blue">{sr.status}</Badge></dd>
          <dd className="wide ok-text">{sr.message}</dd>
        </dl>
      )}

      {m.automation && (
        <details open>
          <summary>Automated actions ({m.automation.title})</summary>
          <Steps steps={m.automation.log} />
        </details>
      )}

      {m.sources?.length > 0 && (<><h4>Sources used</h4><Sources sources={m.sources} /></>)}

      <div className="meta">
        <Badge tone="blue">{INTENT_LABEL[m.intent]}</Badge>
        <Badge>{m.category} / {m.subcategory}</Badge>
        <Badge tone={m.priority === "P1" || m.priority === "P2" ? "amber" : "grey"}>{m.priority}</Badge>
        {m.servicenow && <Badge tone="green">{m.servicenow.number}</Badge>}
        <span className="muted">{OUTCOME_LABEL[m.outcome]}</span>
      </div>
      <Confidence value={m.confidence} threshold={m.threshold} />

      <div className="actions">
        {m.can_create_ticket && !m.servicenow && (
          <button className="btn" disabled={busy} onClick={createTicket}>
            {m.outcome === "answered" ? "Still need help? Create a ticket" : "Create a ticket"}
          </button>
        )}
        <button className="btn ghost" onClick={() => onOpenAnalysis(m.analysis_id)}>View AI analysis</button>
      </div>
    </div>
  );
}

export default function SelfService({ userId, onOpenAnalysis }) {
  const [mode, setMode] = useState("ask");            // ask = chatbot, submit = request form
  const [msgs, setMsgs] = useState([]);
  const [text, setText] = useState("");
  const [kind, setKind] = useState("auto");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const end = useRef(null);

  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  const send = async (e) => {
    e.preventDefault();
    const q = text.trim();
    if (!q || busy) return;
    setMsgs((x) => [...x, { role: "user", text: q }]);
    setText(""); setBusy(true); setError("");
    try {
      const force = mode === "submit" && kind !== "auto" ? kind : undefined;
      const res = await api.chat(userId, q, force);
      setMsgs((x) => [...x, { role: "bot", ...res }]);
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };

  const onTicket = (analysisId, ticket) =>
    setMsgs((x) => x.map((m) => m.analysis_id === analysisId
      ? { ...m, servicenow: { number: ticket.sn_number }, answer: `${m.answer}\n\nTicket ${ticket.sn_number} created for a human agent.` }
      : m));

  return (
    <section className="page">
      <header className="page-head">
        <h2>Employee Self-Service</h2>
        <p>Ask a question, report a problem or request software. The assistant decides what to do and shows its evidence.</p>
      </header>

      <div className="tabs">
        <button className={mode === "ask" ? "on" : ""} onClick={() => setMode("ask")}>Ask the assistant</button>
        <button className={mode === "submit" ? "on" : ""} onClick={() => setMode("submit")}>Submit a request</button>
      </div>

      <div className="chat">
        {msgs.length === 0 && <p className="empty">No messages yet. Type your question or problem below.</p>}
        {msgs.map((m, i) => m.role === "user"
          ? <div key={i} className="msg me">{m.text}</div>
          : <Reply key={i} m={m} userId={userId} onOpenAnalysis={onOpenAnalysis} onTicket={onTicket} />)}
        {busy && <div className="msg bot muted">Working on it…</div>}
        <div ref={end} />
      </div>
      {error && <div className="alert">{error}</div>}

      <form className="composer" onSubmit={send}>
        {mode === "submit" && (
          <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Request type">
            <option value="auto">Let the assistant decide</option>
            <option value="incident">Report an issue (incident)</option>
            <option value="service_request">Request something (service request)</option>
          </select>
        )}
        {mode === "ask"
          ? <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Describe your question or problem" />
          : <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="Describe what you need in detail" />}
        <button className="btn primary" disabled={busy || !text.trim()}>{mode === "ask" ? "Send" : "Submit request"}</button>
      </form>
    </section>
  );
}
