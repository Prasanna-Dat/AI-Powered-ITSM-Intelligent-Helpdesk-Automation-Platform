import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Confidence, Empty, INTENT_LABEL, OUTCOME_LABEL, Sources, Steps } from "../components/ui.jsx";

function Row({ k, children }) { return (<><dt>{k}</dt><dd>{children}</dd></>); }

export default function AIAnalysis({ selectedId }) {
  const [list, setList] = useState([]);
  const [cur, setCur] = useState(selectedId);
  const [a, setA] = useState(null);

  useEffect(() => { api.analyses().then((rows) => { setList(rows); if (!cur && rows[0]) setCur(rows[0].analysis_id); }); }, []); // eslint-disable-line
  useEffect(() => { if (selectedId) setCur(selectedId); }, [selectedId]);
  useEffect(() => { if (cur) api.analysis(cur).then(setA); }, [cur]);

  return (
    <section className="page">
      <header className="page-head">
        <h2>AI Analysis</h2>
        <p>How the assistant understood a request, what evidence it used, what it did and where it was recorded.</p>
      </header>
      {list.length === 0 ? <Empty>No analyses yet. Send a message in Self-Service first.</Empty> : (
        <div className="split">
          <ul className="list">
            {list.map((r) => (
              <li key={r.analysis_id}>
                <button className={cur === r.analysis_id ? "on" : ""} onClick={() => setCur(r.analysis_id)}>
                  <span>{r.message.slice(0, 60)}</span>
                  <span className="muted small">{INTENT_LABEL[r.intent]} · {Math.round(r.confidence * 100)}%</span>
                </button>
              </li>))}
          </ul>
          {a && (
            <div className="detail">
              <blockquote>{a.message}</blockquote>
              <dl className="kv">
                <Row k="Intent"><Badge tone="blue">{INTENT_LABEL[a.intent]}</Badge></Row>
                <Row k="Category / sub-category">{a.category} / {a.subcategory}</Row>
                <Row k="Priority">{a.priority}</Row>
                <Row k="Impact / urgency">{a.impact} / {a.urgency}</Row>
                <Row k="Assignment group">{a.assignment_group}</Row>
                <Row k="Summary">{a.summary}</Row>
                <Row k="Suggested resolution">{a.suggested_resolution}</Row>
                <Row k="Confidence"><Confidence value={a.confidence} threshold={a.threshold} /></Row>
                <Row k="Outcome">{OUTCOME_LABEL[a.outcome]}{a.escalated && <> <Badge tone="amber">human escalation</Badge></>}</Row>
                <Row k="ServiceNow reference">{a.servicenow ? `${a.servicenow.number} (${a.servicenow.mode}, ${a.servicenow.state})` : "none"}</Row>
                <Row k="Automation">{a.automation ? `${a.automation.title}: ${a.automation.success ? "success" : "failed"}` : "none"}</Row>
                <Row k="Models">{a.models.llm} · {a.models.embedding} · {a.models.vector_db}</Row>
              </dl>
              <h3>Knowledge sources</h3>
              <Sources sources={a.sources} />
              <h3>Retrieved chunks</h3>
              {a.retrieved_chunks.map((c) => (
                <details key={c.chunk_id}><summary>{c.chunk_id} · {c.title} · {c.section} · score {c.score}</summary><pre>{c.text}</pre></details>))}
              <h3>Decision trace</h3>
              <Steps steps={a.steps} />
              <h3>Answer</h3>
              <pre className="answer-pre">{a.answer}</pre>
            </div>)}
        </div>)}
    </section>
  );
}
