// Every call to the FastAPI backend lives here, so the screens stay simple.
const BASE = import.meta.env.VITE_API_URL || ""; // empty = use the Vite dev proxy (/api -> localhost:8000)

async function call(path, options = {}) {
  const res = await fetch(BASE + path, { headers: { "Content-Type": "application/json" }, ...options });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch { /* ignore */ }
    throw new Error(msg);
  }
  return res.json();
}
const post = (path, body) => call(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  health: () => call("/api/health"),
  users: () => call("/api/users"),
  chat: (user_id, message, force_intent) => post("/api/chat", { user_id, message, force_intent }),
  createTicket: (user_id, analysis_id) => post("/api/tickets", { user_id, analysis_id }),
  analyses: () => call("/api/analyses"),
  analysis: (id) => call(`/api/analyses/${id}`),
  dashboard: () => call("/api/dashboard"),
  auditLogs: (limit = 15) => call(`/api/audit-logs?limit=${limit}`),
  serviceNowIncident: (ticketId) => call(`/api/tickets/${ticketId}/servicenow`),
  resolveTicket: (ticketId, note) =>
    call(`/api/tickets/${ticketId}`, { method: "PATCH", body: JSON.stringify({ status: "resolved", note }) }),
  kbArticles: () => call("/api/kb/articles"),
  kbArticle: (id) => call(`/api/kb/articles/${id}`),
  kbSearch: (query) => post("/api/kb/search", { query, k: 3 }),
};
