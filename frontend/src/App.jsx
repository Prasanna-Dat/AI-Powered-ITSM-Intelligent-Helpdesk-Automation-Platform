import { useEffect, useState } from "react";
import { api } from "./api";
import SelfService from "./pages/SelfService.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import AIAnalysis from "./pages/AIAnalysis.jsx";
import KnowledgeBase from "./pages/KnowledgeBase.jsx";

const TABS = [
  ["self", "Self-Service"],
  ["dashboard", "ITSM Dashboard"],
  ["analysis", "AI Analysis"],
  ["kb", "Knowledge Base"],
];

export default function App() {
  const [tab, setTab] = useState("self");
  const [users, setUsers] = useState([]);
  const [userId, setUserId] = useState("alice");
  const [health, setHealth] = useState(null);
  const [error, setError] = useState("");
  const [analysisId, setAnalysisId] = useState(null);

  useEffect(() => {
    api.users().then(setUsers).catch((e) => setError(e.message));
    api.health().then(setHealth).catch(() => setError("Cannot reach the backend. Is it running on port 8000?"));
  }, []);

  const openAnalysis = (id) => { setAnalysisId(id); setTab("analysis"); };

  return (
    <div className="shell">
      <aside className="rail">
        <h1>IT Helpdesk<br />Assistant</h1>
        <nav>
          {TABS.map(([key, label]) => (
            <button key={key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}>{label}</button>
          ))}
        </nav>
        <label className="who">
          Signed in as
          <select value={userId} onChange={(e) => setUserId(e.target.value)}>
            {users.map((u) => <option key={u.user_id} value={u.user_id}>{u.name} ({u.department})</option>)}
          </select>
        </label>
        {health && (
          <dl className="stack">
            <dt>Database</dt><dd>{health.database}</dd>
            <dt>ITSM</dt><dd>{health.servicenow}</dd>
            <dt>LLM</dt><dd>{health.llm}</dd>
            <dt>Embeddings</dt><dd>{health.embedding}</dd>
            <dt>Vector DB</dt><dd>{health.vector_db}</dd>
          </dl>
        )}
      </aside>
      <main>
        {error && <div className="alert">{error}</div>}
        {tab === "self" && <SelfService userId={userId} onOpenAnalysis={openAnalysis} />}
        {tab === "dashboard" && <Dashboard onOpenAnalysis={openAnalysis} />}
        {tab === "analysis" && <AIAnalysis selectedId={analysisId} />}
        {tab === "kb" && <KnowledgeBase />}
      </main>
    </div>
  );
}
