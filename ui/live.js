// Live-mode data access: thin wrappers over the brain's REST facade, each carrying
// the OAuth bearer token. Mirrors the server tools one-to-one. All enforcement is
// server-side; this just fetches and shapes JSON for the renderer.

import { token } from "./auth.js";

async function call(apiUrl, path, { method = "GET", body } = {}) {
  const headers = { authorization: `Bearer ${token()}` };
  if (body !== undefined) headers["content-type"] = "application/json";
  const resp = await fetch(`${apiUrl}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (resp.status === 401) throw Object.assign(new Error("unauthenticated"), { status: 401 });
  if (!resp.ok) {
    let detail = "";
    try { detail = (await resp.json()).error || ""; } catch { /* ignore */ }
    throw Object.assign(new Error(detail || `request failed (${resp.status})`), { status: resp.status });
  }
  return resp.json();
}

export const api = (apiUrl) => ({
  me: () => call(apiUrl, "/api/me"),
  documents: () => call(apiUrl, "/api/documents").then((d) => d.documents),
  search: (query, top_k = 8) => call(apiUrl, "/api/search", { method: "POST", body: { query, top_k } }).then((d) => d.results),
  answer: (query, top_k = 6) => call(apiUrl, "/api/answer", { method: "POST", body: { query, top_k } }),
  document: (doc_id) => call(apiUrl, `/api/document?doc_id=${encodeURIComponent(doc_id)}`),
  upload: (filename, content_base64, domain) =>
    call(apiUrl, "/api/upload", { method: "POST", body: { filename, content_base64, domain } }),
  note: (title, content, source_url) =>
    call(apiUrl, "/api/note", { method: "POST", body: { title, content, source_url } }),
  draft: (payload) => call(apiUrl, "/api/draft", { method: "POST", body: payload }),
  simplify: (text) => call(apiUrl, "/api/simplify", { method: "POST", body: { text } }),
  propose: (payload) => call(apiUrl, "/api/propose", { method: "POST", body: payload }),
  create: (payload) => call(apiUrl, "/api/create", { method: "POST", body: payload }),
  edit: (payload) => call(apiUrl, "/api/edit", { method: "POST", body: payload }),
  remove: (doc_id) => call(apiUrl, "/api/delete", { method: "POST", body: { doc_id } }),
  report: (doc_id, reason) => call(apiUrl, "/api/report", { method: "POST", body: { doc_id, reason } }),
  reports: () => call(apiUrl, "/api/reports").then((d) => d.reports),
  resolveReport: (doc_id, remove) =>
    call(apiUrl, "/api/report/resolve", { method: "POST", body: { doc_id, remove } }),
  shares: () => call(apiUrl, "/api/shares"),
  share: (payload) => call(apiUrl, "/api/share", { method: "POST", body: payload }),
  unshare: (payload) => call(apiUrl, "/api/unshare", { method: "POST", body: payload }),
  proposals: () => call(apiUrl, "/api/proposals").then((d) => d.proposals),
  accept: (name) => call(apiUrl, "/api/accept", { method: "POST", body: { name } }),
  agentRun: (query) => call(apiUrl, "/api/agent/run", { method: "POST", body: { query } }),
  linkSuggestions: () => call(apiUrl, "/api/link/suggestions").then((d) => d.suggestions),
  link: (source, target) => call(apiUrl, "/api/link", { method: "POST", body: { source, target } }),
  linkSuggestFor: (text, domain) =>
    call(apiUrl, "/api/link/suggest-for", { method: "POST", body: { text, domain } }).then((d) => d.suggestions),
});

// Read a File object as base64 (no data: prefix), for /api/upload.
export function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error);
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.readAsDataURL(file);
  });
}
