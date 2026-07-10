// Hyper Brain UI. Loads the exported index + policy (+ optional config), then
// renders two pages: Explore (identity/scope, domain browser, canvas knowledge
// graph, search/answer, reading modes) and Connections (sources -> brain ->
// surfaces flow, the onboarding pipeline, surfaces + MCP connector, architecture).
//
// The UI holds no secrets and enforces nothing (ARCHITECTURE.md section 9): it
// renders what a caller in a given identity would be allowed to see. All trust
// lives in the server. Pure logic (the domain ACL, scoped search, answer, graph)
// comes from lib.js, so it mirrors the server's behaviour.
import {
  allowedDomains,
  domainKind,
  extractiveAnswer,
  graphData,
  principalsFromPolicy,
  rankChunks,
  reconstructDoc,
} from "./lib.js";
import { beginLogin, completeLoginIfRedirected, signOut, token } from "./auth.js";
import { api, fileToBase64 } from "./live.js";

// Live mode is on when the deployed config carries the brain REST base + OAuth issuer.
// Until a visitor signs in they see the public landing page; after, real per-user data.
let LIVE = false, API = null, ME = null;
// Notes/uploads land in the corpus and are searchable only after the next index
// build, so a just-created note is not in /api/documents yet. We show it optimistically
// here (marked pending) so the user sees it immediately.
let PENDING_NOTES = [];

const $ = (sel) => document.querySelector(sel);
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const norm = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const short = (id) => id.split("/").pop();
const friendly = (p) => p.replace(/^group:/, "").replace(/@.*$/, "");
function withAlpha(hex, a) {
  hex = hex.trim();
  if (hex.startsWith("#")) {
    const n = hex.length === 4
      ? [hex[1] + hex[1], hex[2] + hex[2], hex[3] + hex[3]]
      : [hex.slice(1, 3), hex.slice(3, 5), hex.slice(5, 7)];
    const [r, g, b] = n.map((x) => parseInt(x, 16));
    return `rgba(${r},${g},${b},${a})`;
  }
  return hex;
}

// ---- State + data (populated after fetch) -----------------------------------
let index = null, policy = null, config = {};
let AGENTS = null, AGENTSEL = null; // agent/model/prompt manifest + selected agent id
let DOMAIN_ORDER = [], domIdx = new Map(), byId = new Map(), PRINCIPALS = [];
const state = { principal: null, allowed: new Set(), openDoc: null, openDocNode: null, query: "", mode: "explore" };

// A sorted domain -> categorical colour slot (1..6), used for dots and nodes.
const domVar = (domain) => `--domain-${((domIdx.get(domain) || 0) % 6) + 1}`;

// ============================================================================
//  Boot
// ============================================================================
// ---- Boot overlay: a single loading gate so cold starts never show a half-page ----
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function setBootMessage(m) { const el = $("#bootmsg"); if (el) el.textContent = m; }
function showBoot(m) { const b = $("#booting"); if (!b) return; b.classList.remove("error"); b.hidden = false; setBootMessage(m || "Loading…"); }
function hideBoot() { const b = $("#booting"); if (b) b.hidden = true; }
function revealApp() { const el = $("#approot"); if (el) el.hidden = false; }
function bootError(msg, onRetry, label) {
  const b = $("#booting"); if (!b) return;
  b.hidden = false; b.classList.add("error");
  $("#booterrmsg").textContent = msg;
  const btn = $("#bootretry"); btn.textContent = label || "Try again";
  btn.onclick = () => { b.classList.remove("error"); if (onRetry) onRetry(); };
}

// Retry only transient failures (network blip or a warming service's 5xx/429); real
// errors (401/403/404) surface immediately. Backs off up to ~20s, then gives up.
async function withRetry(fn) {
  const MAX = 6;
  for (let i = 0; ; i++) {
    try { return await fn(); }
    catch (e) {
      const s = e && e.status;
      const transient = s == null || s === 0 || s === 429 || (s >= 500 && s < 600);
      if (!transient || i >= MAX) throw e;
      setBootMessage("Still waking the brain service. Hang tight…");
      await sleep(Math.min(800 * 2 ** i, 5000));
    }
  }
}

async function boot() {
  config = await fetch("data/config.json").then((r) => (r.ok ? r.json() : {})).catch(() => ({}));
  AGENTS = await fetch("data/agents.json").then((r) => (r.ok ? r.json() : null)).catch(() => null);
  LIVE = !!(config.api_url && config.auth_url);

  if (LIVE) {
    API = api(config.api_url);
    try {
      await completeLoginIfRedirected(config.auth_url);
    } catch (e) {
      $("#landinghint").textContent = String(e.message || e);
    }
    if (!token()) { hideBoot(); showLanding(); return; }
    await loadLive();
    return;
  }
  await bootDemo();
}

// Fetch the essential per-user data (with cold-start retries) before revealing the
// app, so the user never sees empty boxes. 401 anywhere means the session is gone.
async function loadLive() {
  showBoot("Waking the brain service. This can take a few seconds if it has been idle…");
  let me, docs;
  try {
    me = await withRetry(() => API.me());
    setBootMessage("Loading your workspace…");
    docs = await withRetry(() => API.documents());
  } catch (e) {
    if (e && e.status === 401) { signOut(); hideBoot(); showLanding(); return; }
    bootError("We can't reach the brain service right now. It may still be waking up, or the connection dropped.", loadLive);
    return;
  }
  try {
    revealApp();
    await bootLive(me, docs);
    hideBoot();
  } catch (e) {
    if (e && e.status === 401) { signOut(); hideBoot(); showLanding(); return; }
    bootError("Something went wrong loading your workspace.", loadLive);
  }
}

// The session expired while the app was open (a poll came back 401): tell the user
// plainly rather than leaving stale content on screen with no sign they are signed out.
function sessionExpired() {
  if (livePollTimer) { clearInterval(livePollTimer); livePollTimer = null; }
  signOut();
  bootError("Your session has expired. Please sign in again.", () => beginLogin(config.auth_url), "Sign in again");
}

function showLanding() {
  hideBoot();
  $("#landing").hidden = false;
  $("#approot").hidden = true;
  $("#signin").addEventListener("click", () => beginLogin(config.auth_url));
}

// Local / offline demo: the static exported index with the "Acting as" simulator.
async function bootDemo() {
  try {
    const [idx, pol] = await Promise.all([
      fetch("data/index.json").then((r) => r.json()),
      fetch("data/policy.json").then((r) => r.json()),
    ]);
    index = idx; policy = pol;
  } catch {
    bootError("No exported data found. Run ./brain ui (or python scripts/export_ui_data.py) to export the index, then reload.", bootDemo);
    return;
  }

  revealApp();
  DOMAIN_ORDER = [...policy.domains].sort();
  domIdx = new Map(DOMAIN_ORDER.map((d, i) => [d, i]));
  byId = new Map(index.documents.map((d) => [d.doc_id, d]));
  PRINCIPALS = principalsFromPolicy(policy).map((id) => ({ id, friendly: friendly(id) }));

  $("#hash").textContent = (index.content_hash || "").slice(0, 12);
  $("#doccount").textContent = index.documents.length;

  buildGraph();
  fillMcp();
  initPrincipals();
  initPersonal();
  wireStatic();

  resize();
  if (W > 0) { seed(); graphSized = true; }
  onScopeChange();
  renderConnections();
  loop();
  setPage("connect"); // Connections is the default page
  hideBoot();
}

// Signed-in live mode: render from the per-user data loadLive() already fetched
// (with cold-start retries), so this runs only once the data is in hand.
async function bootLive(me, docs) {
  ME = me;
  // Shape the REST payload like the static index so the renderers are reused.
  const adjacency = {};
  for (const d of docs) adjacency[d.doc_id] = d.links || [];
  index = { documents: docs, adjacency, chunks: [], content_hash: "" };
  policy = { domains: [], grants: [] };
  byId = new Map(docs.map((d) => [d.doc_id, d]));

  const domains = [...new Set(docs.map((d) => d.domain))].sort();
  DOMAIN_ORDER = domains;
  domIdx = new Map(DOMAIN_ORDER.map((d, i) => [d, i]));
  state.allowed = new Set(domains);
  state.principal = ME.you.email || ME.you.subject;

  $("#hash").textContent = "live";
  $("#doccount").textContent = docs.length;

  // Live chrome: show who is signed in, hide the "Acting as" simulator, offer review.
  $("#userchip").hidden = false;
  $("#username").textContent = friendly(state.principal);
  $("#signout").addEventListener("click", () => { broadcast("signout"); signOut(); window.location.reload(); });
  const idpill = document.querySelector("#page-explore .idpill");
  if (idpill) idpill.style.display = "none";
  const canReview = (ME.writable || []).length > 0;
  $("#reviewtab").hidden = !canReview;
  $("#agentlive").hidden = false; // signed in: the Agents page can run the real team

  buildGraph();
  fillMcp();
  // Note: initPersonal() (the demo simulator + its handlers) is deliberately NOT
  // called in live mode; wireLive() owns the live personal actions instead.
  $("#sharespace").hidden = true; // demo share flow needs simulated principals
  wireStatic();
  wireLive();

  resize();
  if (W > 0) { seed(); graphSized = true; }
  renderScope(); renderBrowser(); renderLegend(); relightGraph();
  renderPersonal();
  renderConnections();
  loop();
  initLiveChannel(); // cross-tab pending-note updates (same browser)
  startLivePoll(); // keep this tab current (picks up content added anywhere)
  ensureIdxTicker(); // live "indexing…" status while added content is pending
  setPage("connect"); // Open on the Overview tab.
}

// ---- Live-mode search (REST-backed) -----------------------------------------
// Retrieval is fast, so it runs as you type (debounced, latest-wins). The grounded
// answer is a Gemini call, so it runs only on Enter, not on every keystroke.
let liveSearchTimer = null;
let liveSearchSeq = 0;

function scheduleLiveSearch() {
  clearTimeout(liveSearchTimer);
  const q = state.query.trim();
  if (!q) { liveSearchSeq++; $("#results").innerHTML = ""; return; }
  liveSearchTimer = setTimeout(() => runLiveSearch(q, false), 250);
}

function submitLiveSearch() {
  clearTimeout(liveSearchTimer);
  const q = state.query.trim();
  if (!q) { liveSearchSeq++; $("#results").innerHTML = ""; return; }
  runLiveSearch(q, true); // Enter: also compose a grounded answer
}

// Collapse chunk-level hits to one entry per document (best-ranked chunk wins).
function dedupeByDoc(results) {
  const seen = new Set(); const out = [];
  for (const r of results) { if (seen.has(r.doc_id)) continue; seen.add(r.doc_id); out.push(r); }
  return out;
}

async function runLiveSearch(q, withAnswer) {
  const seq = ++liveSearchSeq; // any newer query invalidates this one
  const box = $("#results");
  box.innerHTML = '<p class="empty">searching…</p>';
  let results;
  try { results = await API.search(q); }
  catch (e) { if (seq === liveSearchSeq) box.innerHTML = `<p class="empty">${esc(e.message || String(e))}</p>`; return; }
  if (seq !== liveSearchSeq) return; // superseded while awaiting
  const docs = dedupeByDoc(results);
  renderLiveResults(box, docs, null, withAnswer);
  if (withAnswer && docs.length) {
    let ans = null;
    try { ans = await API.answer(q); } catch { /* keep the hits, drop the answer */ }
    if (seq !== liveSearchSeq) return;
    renderLiveResults(box, docs, ans, true);
  }
}

function renderLiveResults(box, docs, ans, withAnswer) {
  if (!docs.length) {
    box.innerHTML = `<div class="answer"><div class="lbl"><span class="spark"></span><span class="eyebrow">Answer</span></div><p>${esc((ans && ans.text) || "No results in the domains you can see.")}</p></div>`;
    return;
  }
  let html = "";
  if (ans) {
    html += `<div class="answer"><div class="lbl"><span class="spark"></span><span class="eyebrow">Grounded answer · ${esc(docs[0].domain)}</span></div>`;
    html += `<p>${esc(ans.text)}</p>`;
    html += `<div class="cites">${(ans.citations || []).map((c) => `<span class="cite" data-doc="${c.doc_id}">↳ ${esc(short(c.doc_id))}</span>`).join("")}</div>`;
    if ((ans.gaps || []).length) html += `<div class="gaps">gaps · not supported by retrieved context: ${ans.gaps.map(esc).join(", ")}</div>`;
    html += `</div>`;
  } else if (withAnswer) {
    html += `<div class="answer"><div class="lbl"><span class="spark"></span><span class="eyebrow">Grounded answer</span></div><p class="empty">composing…</p></div>`;
  } else {
    html += `<div class="answerhint mono">Press Enter for a grounded, cited answer.</div>`;
  }
  html += `<div class="hits">`;
  for (const r of docs) {
    const snip = esc(stripWiki(r.text).slice(0, 130));
    html += `<div class="hit" data-doc="${r.doc_id}"><div class="meta"><span class="dot" style="background:var(${domVar(r.domain)})"></span>${esc(r.domain)} · ${esc(r.heading || "-")}</div>
      <div class="htitle">${esc(r.title)}</div><div class="snip">${snip}…</div></div>`;
  }
  html += `</div>`;
  box.innerHTML = html;
  box.querySelectorAll("[data-doc]").forEach((a) => a.addEventListener("click", () => openDocument(a.dataset.doc)));
}

async function renderDocLive(d) {
  const el = $("#doc");
  el.innerHTML = '<p class="placeholder">loading…</p>';
  try {
    const doc = await API.document(d.doc_id);
    const blocks = String(doc.text || "").split("\n\n").map((b) => {
      if (b.startsWith("## ")) return `<h4>${esc(b.slice(3))}</h4>`;
      if (b.startsWith("# ")) return `<h3>${esc(b.slice(2))}</h3>`;
      return `<p>${esc(stripWiki(b))}</p>`;
    });
    const tags = (doc.tags && doc.tags.length)
      ? `<div class="chips" style="margin:2px 0 10px">${doc.tags.map((t) => `<span class="chip tag">#${esc(t)}</span>`).join("")}</div>` : "";
    let prov = `<div class="provenance"><span class="dot" style="background:var(${domVar(doc.domain)})"></span>${esc(doc.domain)}`;
    if (doc.source) prov += ` · source: ${esc(doc.source)}`;
    if (doc.fetched_at) prov += ` · fetched ${esc(doc.fetched_at)}`;
    prov += "</div>";
    el.innerHTML = `<article><h3>${esc(doc.title)}</h3>${tags}${blocks.slice(1).join("")}${prov}</article>`;
  } catch (e) {
    el.innerHTML = `<p class="placeholder">${esc(e.message || String(e))}</p>`;
  }
}

function renderPersonalLive() {
  const owner = $("#personalowner");
  const pd = ME.personal && ME.personal.domain;
  if (owner) owner.textContent = `${friendly(state.principal)} · ${pd || "no personal space"}`;
  const list = $("#personallist");
  if (list) {
    list.innerHTML = "";
    const notes = index.documents.filter((d) => d.domain === pd);
    const indexedTitles = new Set(notes.map((n) => n.title));
    // Just-created notes/uploads not yet in the index, shown as pending.
    const pending = PENDING_NOTES.filter((p) => !indexedTitles.has(p.title));
    if (!notes.length && !pending.length) list.innerHTML = '<li class="empty" style="padding:6px 2px">No notes yet. Add one or upload a file. Only you will see it.</li>';
    for (const p of pending) {
      const li = document.createElement("li"); li.className = "pnote";
      // A (non-interactive) button, matching the real notes below, so it aligns.
      li.innerHTML = `<div class="pnote-row"><button type="button" class="pnote-title" disabled><span class="dot personal-dot"></span><span class="t">${esc(p.title)}</span></button><span class="kindbadge kind-personal">${esc(p.status || "pending index")}</span></div>`;
      list.appendChild(li);
    }
    for (const n of notes) {
      const li = document.createElement("li"); li.className = "pnote";
      const row = document.createElement("div"); row.className = "pnote-row";
      const b = document.createElement("button"); b.className = "pnote-title";
      b.innerHTML = `<span class="dot personal-dot"></span><span class="t">${esc(n.title)}</span>`;
      b.addEventListener("click", () => openDocument(n.doc_id));
      row.appendChild(b); li.appendChild(row); list.appendChild(li);
    }
  }
  // Shared-with-you, from the server's view of the caller.
  const box = $("#sharedwithyou");
  const swy = (ME.shared_with_you || {});
  const domains = swy.domains || [], docs = swy.documents || [];
  if (box) {
    if (!domains.length && !docs.length) { box.innerHTML = ""; }
    else {
      let html = '<div class="sharedhead">Shared with you</div><ul class="doclist">';
      for (const d of domains) html += `<li class="pnote shared"><div class="pnote-row"><span class="pnote-title"><span class="dot shared-dot"></span><span class="t">${esc(d.domain)}</span></span><span class="kindbadge kind-shared">shared</span></div></li>`;
      for (const id of docs) html += `<li class="pnote shared"><div class="pnote-row"><button class="pnote-title" data-doc="${esc(id)}"><span class="dot shared-dot"></span><span class="t">${esc(short(id))}</span></button></div></li>`;
      html += "</ul>";
      box.innerHTML = html;
      box.querySelectorAll("[data-doc]").forEach((a) => a.addEventListener("click", () => openDocument(a.dataset.doc)));
    }
  }
  renderLinksBox();
}

// ---- Autolinker: connect your own notes -------------------------------------
function personalNotes() {
  const pd = ME && ME.personal && ME.personal.domain;
  return pd ? index.documents.filter((d) => d.domain === pd) : [];
}
function renderLinksBox() {
  const box = $("#linksbox"); if (!box) return;
  const notes = personalNotes();
  if (notes.length < 2) { box.hidden = true; return; } // nothing to connect yet
  box.hidden = false;
  const opts = notes.map((n) => `<option value="${esc(n.doc_id)}">${esc(n.title)}</option>`).join("");
  const src = $("#linksrc"), dst = $("#linkdst");
  if (src && dst) {
    const keepSrc = src.value, keepDst = dst.value;
    src.innerHTML = opts; dst.innerHTML = opts;
    if ([...src.options].some((o) => o.value === keepSrc)) src.value = keepSrc;
    if ([...dst.options].some((o) => o.value === keepDst)) dst.value = keepDst;
    else if (dst.options.length > 1) dst.selectedIndex = 1; // default to a different note
  }
}
async function loadLinkSuggestions() {
  const wrap = $("#linksuggestions"); if (!wrap) return;
  wrap.innerHTML = '<p class="addnote" style="margin:6px 0">Looking for related notes…</p>';
  let suggestions;
  try { suggestions = await API.linkSuggestions(); }
  catch (e) { wrap.innerHTML = `<p class="addnote" style="margin:6px 0">${esc(e.message || String(e))}</p>`; return; }
  if (!suggestions.length) {
    wrap.innerHTML = '<p class="addnote" style="margin:6px 0">No new suggestions. Your related notes may already be linked.</p>';
    return;
  }
  wrap.innerHTML = suggestions.map((s) => `
    <div class="linkrow" data-src="${esc(s.source)}" data-dst="${esc(s.target)}">
      <div class="linkpair"><span class="lp">${esc(s.source_title)}</span><span class="linkarrow">↔</span><span class="lp">${esc(s.target_title)}</span></div>
      <div class="linkmeta mono">${Math.round(s.score * 100)}% · ${esc(s.reason)}</div>
      <div class="linkacts"><button class="gobtn tiny linkadd">Add</button><button class="ghostbtn tiny linkskip">Dismiss</button></div>
    </div>`).join("");
  wrap.querySelectorAll(".linkrow").forEach((row) => {
    row.querySelector(".linkadd").addEventListener("click", () => doLink(row.dataset.src, row.dataset.dst, row));
    row.querySelector(".linkskip").addEventListener("click", () => row.remove());
  });
}
async function doLink(source, target, row) {
  const status = $("#linkstatus");
  try {
    const r = await API.link(source, target);
    const msg = r.status === "exists"
      ? "Those notes are already linked."
      : "Linked. It appears in the graph once the index rebuilds.";
    if (status) status.innerHTML = `<p class="addnote" style="margin:6px 0">${msg}</p>`;
    if (row) row.remove();
    startLivePoll(); // pick up the reindexed edge
  } catch (e) {
    if (status) status.innerHTML = `<p class="addnote" style="margin:6px 0">${esc(e.message || String(e))}</p>`;
  }
}

async function renderReview() {
  const box = $("#reviewlist"); if (!box) return;
  box.innerHTML = '<p class="empty">loading…</p>';
  try {
    const proposals = await API.proposals();
    if (!proposals.length) { box.innerHTML = '<p class="empty">Nothing awaiting your review.</p>'; return; }
    box.innerHTML = "";
    for (const p of proposals) {
      const card = document.createElement("div"); card.className = "reviewcard";
      card.innerHTML = `<div class="rc-main"><span class="kindbadge kind-team">${esc(p.domain)}</span>
        <span class="rc-name mono">${esc(short(p.dest))}</span></div>`;
      const btn = document.createElement("button"); btn.className = "gobtn"; btn.textContent = "Accept";
      btn.addEventListener("click", async () => {
        btn.disabled = true; btn.textContent = "Accepting…";
        try {
          await API.accept(p.name);
          card.innerHTML = `<div class="rc-main"><span class="kindbadge kind-team">${esc(p.domain)}</span> <span class="rc-name mono">accepted · reindexing</span></div>`;
        } catch (e) {
          btn.disabled = false; btn.textContent = "Accept";
          card.querySelector(".rc-main").insertAdjacentHTML("beforeend", `<span class="rc-err">${esc(e.message || String(e))}</span>`);
        }
      });
      card.appendChild(btn); box.appendChild(card);
    }
  } catch (e) {
    box.innerHTML = `<p class="empty">${esc(e.message || String(e))}</p>`;
  }
}

// Same-origin tabs share a channel, so a note added in one tab shows immediately as
// pending in the others (before it is indexed and visible to the server). Scoped to
// the signed-in subject so two different users' tabs never cross.
let liveChannel = null;
function initLiveChannel() {
  if (!("BroadcastChannel" in window)) return;
  liveChannel = new BroadcastChannel("hyper-brain-live");
  liveChannel.addEventListener("message", (e) => {
    const m = e.data || {};
    if (m.sub !== (ME.you && ME.you.subject)) return; // ignore other users' tabs
    if (m.type === "signout") { signOut(); window.location.reload(); return; }
    if (m.type === "pending" && m.title) {
      const pd = ME.personal && ME.personal.domain;
      const known = PENDING_NOTES.some((p) => p.title === m.title) ||
        index.documents.some((d) => d.domain === pd && d.title === m.title);
      if (known) return;
      PENDING_NOTES.unshift({ title: m.title });
      renderPersonal();
      startLivePoll(); // this tab now polls too, so it resolves when indexed
    }
  });
}
function broadcast(type, extra) {
  if (liveChannel) liveChannel.postMessage({ type, sub: ME.you && ME.you.subject, ...extra });
}
function broadcastPending(title) { broadcast("pending", { title }); }

// Wire the live-only actions (add note, upload, share space) to the REST facade.
function wireLive() {
  $("#addnote").addEventListener("click", () => { $("#notemodal").hidden = false; $("#notetitle").focus(); });
  $("#suggestlinks").addEventListener("click", loadLinkSuggestions);
  $("#linkbtn").addEventListener("click", () => {
    const s = $("#linksrc").value, t = $("#linkdst").value;
    if (s && t && s !== t) doLink(s, t);
    else if ($("#linkstatus")) $("#linkstatus").innerHTML = '<p class="addnote" style="margin:6px 0">Pick two different notes.</p>';
  });

  // Studio: source picker, file chooser, generate draft, preview, create/propose.
  $("#studioseg").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setStudioSrc(b.dataset.src); });
  $("#studiofilebtn").addEventListener("click", () => $("#studiofile").click());
  $("#studiofile").addEventListener("change", (e) => {
    studioFile = (e.target.files && e.target.files[0]) || null;
    $("#studiofilename").textContent = studioFile ? studioFile.name : "";
  });
  $("#studiourl").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); generateDraft(); } });
  $("#studiogen").addEventListener("click", generateDraft);
  $("#draftcontent").addEventListener("input", () => { renderDraftPreview(); updateSplitVisibility(); });
  $("#drafttarget").addEventListener("change", () => { updateCreateLabel(); loadDraftLinks(); });
  $("#draftcreate").addEventListener("click", draftCreateClicked);
  $("#draftdiscard").addEventListener("click", draftDiscardClicked);
  $("#draftsimplify").addEventListener("click", simplifyDraft);
  $("#draftsplit").addEventListener("click", enterSplitMode);
  $("#studioagain").addEventListener("click", resetStudio);
  $("#notedo").addEventListener("click", async () => {
    const title = $("#notetitle").value.trim(), content = $("#notebody").value.trim();
    if (!title && !content) return;
    const noteTitle = title || "Untitled note";
    $("#notemodal").hidden = true; $("#notetitle").value = ""; $("#notebody").value = "";
    // Optimistic: show the note at once with a "saving" badge, so a slow save still
    // gives instant feedback instead of a blank wait until the request returns. It
    // flips to "pending index" on success, or rolls back and restores the draft on
    // failure so the user can retry without retyping.
    const entry = { title: noteTitle, status: "saving" };
    PENDING_NOTES.unshift(entry);
    renderPersonal(); renderIndexStatus();
    flashUpload(`Saving “${noteTitle}”…`);
    try {
      await API.note(noteTitle, content);
      entry.status = "pending index";
      broadcastPending(noteTitle);
      renderPersonal(); renderIndexStatus();
      flashUpload("Note saved. Indexing now, searchable in a few minutes.");
      startLivePoll();
    } catch (e) {
      PENDING_NOTES = PENDING_NOTES.filter((p) => p !== entry); // roll back the optimistic add
      renderPersonal(); renderIndexStatus();
      $("#notetitle").value = title; $("#notebody").value = content; $("#notemodal").hidden = false;
      flashUpload(`Could not save the note: ${e.message || e}`);
    }
  });
  document.querySelectorAll("[data-close-note]").forEach((el) => el.addEventListener("click", () => { $("#notemodal").hidden = true; }));

  // Agents page: run the real ADK team live.
  $("#agentrun").addEventListener("click", runLiveAgent);
  $("#agentquery").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); runLiveAgent(); } });

  $("#uploadbtn").addEventListener("click", () => $("#fileinput").click());
  $("#fileinput").addEventListener("change", async (e) => {
    const file = e.target.files && e.target.files[0]; if (!file) return;
    // Show the item immediately with an "uploading" badge (like a note), then flip to
    // "pending index" on success, or remove it and surface the error on failure.
    const entry = { title: file.name, status: "uploading" };
    PENDING_NOTES.unshift(entry);
    renderPersonal();
    flashUpload(`Uploading ${file.name}…`);
    try {
      const b64 = await fileToBase64(file);
      await API.upload(file.name, b64);
      $("#fileinput").value = "";
      entry.status = "pending index";
      broadcastPending(file.name);
      await reloadLiveDocs(`Uploaded ${file.name}. indexing now, searchable in a few minutes.`);
    } catch (err) {
      PENDING_NOTES = PENDING_NOTES.filter((p) => p !== entry);
      renderPersonal();
      flashUpload(String(err.message || err));
    }
  });
}

function flashUpload(msg) {
  const el = $("#uploadstatus"); if (el) el.innerHTML = `<p class="addnote" style="margin:8px 0 0">${esc(msg)}</p>`;
}

async function reloadLiveDocs(msg) {
  const docs = await API.documents();
  applyLiveDocs(docs);
  if (msg) flashUpload(msg);
  startLivePoll(); // keep refreshing until the pending note is indexed
}

// Replace the in-memory index with a fresh document set and re-render everything.
// Pending notes that have now been indexed are dropped (they are real docs again),
// and any newly-indexed document is added to the knowledge graph in place.
function applyLiveDocs(docs) {
  const adjacency = {};
  for (const d of docs) adjacency[d.doc_id] = d.links || [];
  index = { documents: docs, adjacency, chunks: [], content_hash: "" };
  byId = new Map(docs.map((d) => [d.doc_id, d]));
  const domains = [...new Set(docs.map((d) => d.domain))].sort();
  DOMAIN_ORDER = domains;
  domIdx = new Map(domains.map((d, i) => [d, i]));
  state.allowed = new Set(domains);
  const pd = ME.personal && ME.personal.domain;
  const indexedTitles = new Set(docs.filter((d) => d.domain === pd).map((d) => d.title));
  PENDING_NOTES = PENDING_NOTES.filter((p) => !indexedTitles.has(p.title));
  idxExtraPending = 0; // the document set grew, so pending non-personal adds are indexed
  $("#doccount").textContent = docs.length;
  syncLiveGraph();
  renderScope(); renderBrowser(); renderLegend(); renderPersonal();
  renderIndexStatus();
}

// ---- Background-indexing status ---------------------------------------------
// Adding a note or file triggers a background re-index (a Cloud Run job that
// rebuilds the index). The job does not report granular progress, so we show what
// we can know honestly: how many just-added items are still pending, how long it has
// been, and a clear "done" once the poll sees them indexed.
let idxStartedAt = 0, idxDoneUntil = 0, idxTicker = null;
// Adds to commons/team domains are not in PENDING_NOTES (that is personal-only), so
// count them here too, cleared when the poll sees the document set grow (indexed).
let idxExtraPending = 0;
function _mmss(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
function renderIndexStatus() {
  const el = $("#idxstatus"), txt = $("#idxtext");
  if (!el || !txt) return;
  const n = PENDING_NOTES.length + idxExtraPending;
  if (n > 0) {
    if (!idxStartedAt) idxStartedAt = Date.now();
    idxDoneUntil = 0;
    const elapsed = Date.now() - idxStartedAt;
    let s = `Indexing ${n} item${n === 1 ? "" : "s"}… ${_mmss(elapsed)}`;
    if (elapsed > 180000) s += " · longer than usual";
    el.hidden = false; el.className = "idxstatus working";
    txt.textContent = s;
    return;
  }
  if (idxStartedAt) { idxDoneUntil = Date.now() + 6000; idxStartedAt = 0; } // just finished
  if (idxDoneUntil && Date.now() < idxDoneUntil) {
    el.hidden = false; el.className = "idxstatus done";
    txt.textContent = "✓ Indexed · up to date";
    return;
  }
  el.hidden = true;
}
function ensureIdxTicker() {
  if (idxTicker || !LIVE) return;
  idxTicker = setInterval(renderIndexStatus, 1000); // keeps the elapsed time live
}

// Add any new document as a graph node without disturbing the existing layout, then
// rebuild the edges from the current links. Nudges the simulation so it settles.
function syncLiveGraph() {
  let added = false;
  for (const d of index.documents) {
    if (nodeById.has(d.doc_id)) continue;
    const degree = (index.adjacency[d.doc_id] || []).length;
    const cx = W > 0 ? clusterX(d.domain) : (W || 600) * 0.5;
    const n = {
      id: d.doc_id, domain: d.domain, title: d.title,
      x: cx + (Math.random() - 0.5) * 90, y: (H > 0 ? H : 600) * 0.5 + (Math.random() - 0.5) * 90,
      vx: 0, vy: 0, r: degree >= 4 ? 11 : 8, vis: 1, target: 1, pinned: false,
    };
    nodes.push(n); nodeById.set(n.id, n); added = true;
  }
  const gd = graphData(index.documents, index.adjacency, new Set(DOMAIN_ORDER));
  EDGES = gd.links.map((l) => ({ a: l.source, b: l.target }));
  adj = new Map(nodes.map((n) => [n.id, new Set()]));
  for (const e of EDGES) { if (adj.has(e.a) && adj.has(e.b)) { adj.get(e.a).add(e.b); adj.get(e.b).add(e.a); } }
  if (added) alpha = Math.max(alpha, 0.6);
  relightGraph();
}

// Keep the view current: poll for the indexed document set so a pending note (on the
// tab that added it) flips to a real, searchable document once the rebuild finishes,
// and so any *other* open tab picks up new content on its own. Polls only while the
// tab is visible, and only re-renders when the document set actually changed.
let livePollTimer = null;
function startLivePoll() {
  if (livePollTimer || !LIVE) return;
  livePollTimer = setInterval(async () => {
    if (document.hidden) return;
    let docs;
    try { docs = await API.documents(); }
    catch (e) { if (e && e.status === 401) sessionExpired(); return; }
    if (docs.length === index.documents.length) return; // steady: nothing new
    const hadPending = PENDING_NOTES.length;
    applyLiveDocs(docs);
    if (hadPending && PENDING_NOTES.length < hadPending) {
      flashUpload("Indexed. Your note is searchable now.");
    }
  }, 20000);
}

// ---- Principal + scope ------------------------------------------------------
function initPrincipals() {
  const sel = $("#principal");
  sel.innerHTML = "";
  for (const p of PRINCIPALS) {
    const o = document.createElement("option");
    o.value = p.id; o.textContent = p.friendly; sel.appendChild(o);
  }
  sel.addEventListener("change", () => { state.principal = sel.value; onScopeChange(); });
  // Default to the broadest grant so the full graph shows when Explore opens.
  const broadest = PRINCIPALS
    .map((p) => ({ id: p.id, n: allowedDomains(policy, [p.id]).size }))
    .sort((a, b) => b.n - a.n)[0];
  state.principal = broadest ? broadest.id : (PRINCIPALS[0] && PRINCIPALS[0].id);
  if (state.principal) sel.value = state.principal;
}
function onScopeChange() {
  state.allowed = allowedDomains(policy, [state.principal]);
  // If the open doc is no longer visible, close it (never confirm cross-domain).
  if (state.openDoc && !state.allowed.has(byId.get(state.openDoc).domain)) {
    state.openDoc = null; renderDoc();
  }
  renderScope(); renderBrowser(); renderLegend(); relightGraph(); renderResults();
  renderPersonal();
}
function renderScope() {
  const vis = index.documents.filter((d) => state.allowed.has(d.domain)).length;
  $("#visN").textContent = vis;
  $("#totN").textContent = index.documents.length;
  const box = $("#scopechips"); box.innerHTML = "";
  for (const dom of DOMAIN_ORDER) {
    const ok = state.allowed.has(dom);
    const c = document.createElement("span");
    c.className = "chip" + (ok ? "" : " blocked");
    const dot = document.createElement("span");
    dot.className = "dot"; dot.style.background = `var(${domVar(dom)})`;
    c.appendChild(dot); c.appendChild(document.createTextNode(dom));
    box.appendChild(c);
  }
}

// Classify a domain for its badge. Live mode reads the caller's real spaces from
// /api/me; demo mode derives commons/team from the exported policy.
function kindOf(dom) {
  if (LIVE && ME) {
    if (ME.personal && dom === ME.personal.domain) return "personal";
    if ((ME.commons || []).some((c) => c.domain === dom)) return "commons";
    const shared = (ME.shared_with_you && ME.shared_with_you.domains) || [];
    if (shared.some((s) => s.domain === dom)) return "shared";
    return "team";
  }
  return domainKind(policy, dom);
}

// ---- Domain browser ---------------------------------------------------------
function renderBrowser() {
  const el = $("#browser"); el.innerHTML = "";
  let any = false;
  for (const dom of DOMAIN_ORDER) {
    if (!state.allowed.has(dom)) continue;
    any = true;
    const g = document.createElement("div"); g.className = "domgroup";
    const lab = document.createElement("div"); lab.className = "glabel";
    const dot = document.createElement("span"); dot.className = "dot"; dot.style.background = `var(${domVar(dom)})`;
    lab.appendChild(dot); lab.appendChild(document.createTextNode(dom));
    const kind = kindOf(dom);
    const badge = document.createElement("span");
    badge.className = "kindbadge kind-" + kind;
    badge.textContent = kind;
    lab.appendChild(badge);
    g.appendChild(lab);
    const ul = document.createElement("ul"); ul.className = "doclist";
    const docs = index.documents.filter((d) => d.domain === dom).sort((a, b) => a.title.localeCompare(b.title));
    for (const d of docs) {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.dataset.doc = d.doc_id;
      if (d.doc_id === state.openDoc) b.className = "active";
      const dt = document.createElement("span"); dt.className = "dot"; dt.style.background = `var(${domVar(dom)})`;
      const t = document.createElement("span"); t.className = "t"; t.textContent = d.title;
      b.appendChild(dt); b.appendChild(t);
      b.addEventListener("click", () => openDocument(d.doc_id));
      li.appendChild(b); ul.appendChild(li);
    }
    g.appendChild(ul); el.appendChild(g);
  }
  if (!any) el.innerHTML = '<p class="empty">nothing visible to this identity</p>';
}
function renderLegend() {
  const el = $("#legend"); el.innerHTML = "";
  for (const dom of DOMAIN_ORDER) {
    if (!state.allowed.has(dom)) continue;
    const c = document.createElement("span"); c.className = "chip";
    const dot = document.createElement("span"); dot.className = "dot"; dot.style.background = `var(${domVar(dom)})`;
    c.appendChild(dot); c.appendChild(document.createTextNode(dom)); el.appendChild(c);
  }
}

// ============================================================================
//  Personal space + sharing (client-side demo of add_note / share / unshare).
//  Kept separate from the index/graph so it never affects isolation rendering:
//  it demonstrates the model the deployed brain enforces server-side.
// ============================================================================
const PERSONAL = {};        // principal -> [{ id, title, body }]
let SHARES = [];            // { by, to, scope: "space"|"doc", docId, docTitle, write }
let shareCtx = null;        // the pending share target while the modal is open

const personalDomainId = (p) => `personal:${p}`;

function seedPersonal() {
  // A couple of private notes per identity, so the space is never empty in the demo.
  const seeds = {
    default: [
      { title: "My priorities this week", body: "Ship the sharing overlay. Draft the model-risk memo. Prep Friday review." },
      { title: "Scratch: ideas to file later", body: "A private jot only I can see, until I choose to share it." },
    ],
  };
  for (const p of PRINCIPALS) {
    PERSONAL[p.id] = (seeds[p.id] || seeds.default).map((n, i) => ({
      id: `${personalDomainId(p.id)}/note-${i + 1}`, title: n.title, body: n.body,
    }));
  }
}

function myNotes() { return PERSONAL[state.principal] || []; }
function noteById(id) { for (const list of Object.values(PERSONAL)) { const n = list.find((x) => x.id === id); if (n) return n; } return null; }
function sharesForMe() { return SHARES.filter((s) => s.to === state.principal); }

function renderPersonal() {
  if (LIVE) { renderPersonalLive(); return; }
  const owner = $("#personalowner");
  if (owner) owner.textContent = `Acting as ${friendly(state.principal)} · ${personalDomainId(state.principal)}`;
  const list = $("#personallist");
  if (list) {
    list.innerHTML = "";
    const notes = myNotes();
    if (!notes.length) list.innerHTML = '<li class="empty" style="padding:6px 2px">No notes yet. Add one, and only you will see it.</li>';
    for (const n of notes) {
      const li = document.createElement("li"); li.className = "pnote";
      const row = document.createElement("div"); row.className = "pnote-row";
      const b = document.createElement("button"); b.className = "pnote-title";
      const dt = document.createElement("span"); dt.className = "dot personal-dot";
      const t = document.createElement("span"); t.className = "t"; t.textContent = n.title;
      b.appendChild(dt); b.appendChild(t);
      b.addEventListener("click", () => { li.classList.toggle("open"); });
      const sh = document.createElement("button"); sh.className = "ghostbtn tiny";
      const sharedCount = SHARES.filter((s) => s.scope === "doc" && s.docId === n.id).length;
      sh.textContent = sharedCount ? `Shared · ${sharedCount}` : "Share";
      sh.addEventListener("click", (e) => { e.stopPropagation(); openShare({ scope: "doc", docId: n.id, title: n.title }); });
      row.appendChild(b); row.appendChild(sh);
      const body = document.createElement("div"); body.className = "pnote-body"; body.textContent = n.body;
      li.appendChild(row); li.appendChild(body); list.appendChild(li);
    }
  }
  renderSharedWithYou();
}

function renderSharedWithYou() {
  const box = $("#sharedwithyou"); if (!box) return;
  const mine = sharesForMe();
  if (!mine.length) { box.innerHTML = ""; return; }
  let html = '<div class="sharedhead">Shared with you</div><ul class="doclist">';
  for (const s of mine) {
    if (s.scope === "space") {
      const notes = PERSONAL[s.by] || [];
      html += `<li class="pnote shared"><div class="pnote-row"><span class="pnote-title"><span class="dot shared-dot"></span><span class="t">${esc(friendly(s.by))}'s personal space</span></span><span class="kindbadge kind-shared">${s.write ? "read+write" : "read"}</span></div>`;
      html += `<div class="pnote-body">${notes.map((n) => `<b>${esc(n.title)}</b><br>${esc(n.body)}`).join("<br><br>") || "(empty)"}</div></li>`;
    } else {
      const n = noteById(s.docId);
      html += `<li class="pnote shared"><div class="pnote-row"><span class="pnote-title"><span class="dot shared-dot"></span><span class="t">${esc(s.docTitle)}</span></span><span class="kindbadge kind-shared">from ${esc(friendly(s.by))}</span></div>`;
      html += `<div class="pnote-body">${n ? esc(n.body) : "(unavailable)"}</div></li>`;
    }
  }
  html += "</ul>";
  box.innerHTML = html;
}

function openShare(ctx) {
  shareCtx = ctx;
  $("#sharetitle").textContent = ctx.scope === "space" ? "Share your personal space" : "Share a note";
  $("#sharelead").textContent = ctx.scope === "space"
    ? "Everyone you pick can read every note in your personal space, until you revoke it."
    : `Share "${ctx.title}". They see just this note, alongside their own domains.`;
  const sel = $("#sharewith"); sel.innerHTML = "";
  for (const p of PRINCIPALS) {
    if (p.id === state.principal) continue;
    const o = document.createElement("option"); o.value = p.id; o.textContent = friendly(p.id); sel.appendChild(o);
  }
  $("#sharewrite").checked = false;
  renderShareList();
  $("#sharemodal").hidden = false;
}
function closeShare() { $("#sharemodal").hidden = true; shareCtx = null; }

function currentCtxShares() {
  return SHARES.filter((s) => s.by === state.principal &&
    (shareCtx.scope === "space" ? s.scope === "space" : s.scope === "doc" && s.docId === shareCtx.docId));
}
function renderShareList() {
  const wrap = $("#sharelistwrap"); if (!wrap) return;
  const existing = currentCtxShares();
  if (!existing.length) { wrap.innerHTML = '<p class="addnote" style="margin:12px 0 0">Not shared with anyone yet.</p>'; return; }
  let html = '<div class="sharedhead" style="margin-top:14px">Currently shared with</div><ul class="sharelist">';
  for (const s of existing) {
    html += `<li><span class="dot shared-dot"></span>${esc(friendly(s.to))}${s.write ? " · write" : ""}<button class="ghostbtn tiny" data-revoke="${esc(s.to)}">Revoke</button></li>`;
  }
  html += "</ul>";
  wrap.innerHTML = html;
  wrap.querySelectorAll("[data-revoke]").forEach((btn) => btn.addEventListener("click", () => {
    const to = btn.dataset.revoke;
    SHARES = SHARES.filter((s) => !(s.by === state.principal && s.to === to &&
      (shareCtx.scope === "space" ? s.scope === "space" : s.scope === "doc" && s.docId === shareCtx.docId)));
    renderShareList(); renderPersonal();
  }));
}
function doShare() {
  const to = $("#sharewith").value;
  if (!to || !shareCtx) return;
  const write = $("#sharewrite").checked;
  // Replace any existing grant to the same principal for this target (idempotent).
  SHARES = SHARES.filter((s) => !(s.by === state.principal && s.to === to &&
    (shareCtx.scope === "space" ? s.scope === "space" : s.scope === "doc" && s.docId === shareCtx.docId)));
  SHARES.push({
    by: state.principal, to, scope: shareCtx.scope,
    docId: shareCtx.docId || null, docTitle: shareCtx.title || null, write,
  });
  renderShareList(); renderPersonal();
}

function addNote() {
  const title = $("#notetitle").value.trim(), body = $("#notebody").value.trim();
  if (!title && !body) return;
  const list = PERSONAL[state.principal] || (PERSONAL[state.principal] = []);
  list.unshift({ id: `${personalDomainId(state.principal)}/note-${Date.now()}`, title: title || "Untitled note", body });
  $("#notetitle").value = ""; $("#notebody").value = "";
  $("#notemodal").hidden = true;
  renderPersonal();
}

function initPersonal() {
  seedPersonal();
  $("#sharespace").addEventListener("click", () => openShare({ scope: "space" }));
  $("#addnote").addEventListener("click", () => { $("#notemodal").hidden = false; $("#notetitle").focus(); });
  $("#sharedo").addEventListener("click", doShare);
  $("#notedo").addEventListener("click", addNote);
  document.querySelectorAll("[data-close-share]").forEach((el) => el.addEventListener("click", closeShare));
  document.querySelectorAll("[data-close-note]").forEach((el) => el.addEventListener("click", () => { $("#notemodal").hidden = true; }));
}

// ============================================================================
//  Canvas knowledge graph
// ============================================================================
const canvas = $("#graph"), ctx = canvas.getContext("2d");
const tip = $("#tooltip");
let W = 0, H = 0, dpr = 1;
let nodes = [], nodeById = new Map(), EDGES = [], adj = new Map();
let alpha = 1, hover = null, drag = null;

function buildGraph() {
  nodes = index.documents.map((d) => {
    const degree = (index.adjacency[d.doc_id] || []).length;
    return { id: d.doc_id, domain: d.domain, title: d.title, x: 0, y: 0, vx: 0, vy: 0,
      r: degree >= 4 ? 11 : 8, vis: 1, target: 1, pinned: false };
  });
  nodeById = new Map(nodes.map((n) => [n.id, n]));
  // Full link set (all domains); relightGraph fades the ones a caller can't read.
  const gd = graphData(index.documents, index.adjacency, new Set(DOMAIN_ORDER));
  EDGES = gd.links.map((l) => ({ a: l.source, b: l.target }));
  adj = new Map(nodes.map((n) => [n.id, new Set()]));
  for (const e of EDGES) { adj.get(e.a).add(e.b); adj.get(e.b).add(e.a); }
}
function clusterX(domain) {
  const i = domIdx.get(domain) || 0, n = DOMAIN_ORDER.length;
  return n <= 1 ? W * 0.5 : W * (0.25 + 0.5 * i / (n - 1));
}
function resize() {
  const rect = canvas.getBoundingClientRect();
  dpr = Math.min(window.devicePixelRatio || 1, 2);
  W = rect.width; H = rect.height;
  canvas.width = W * dpr; canvas.height = H * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
function seed() {
  nodes.forEach((n, i) => {
    const a = (i / Math.max(nodes.length, 1)) * Math.PI * 2;
    n.x = clusterX(n.domain) + Math.cos(a) * 70;
    n.y = H / 2 + Math.sin(a) * 90;
  });
}
function relightGraph() {
  for (const n of nodes) n.target = state.allowed.has(n.domain) ? 1 : 0;
  alpha = Math.max(alpha, 0.9); // reheat so the layout re-settles
}
function step() {
  for (const n of nodes) n.vis += (n.target - n.vis) * 0.08;
  const active = nodes.filter((n) => n.vis > 0.05);
  for (let i = 0; i < active.length; i++) {
    for (let j = i + 1; j < active.length; j++) {
      const a = active[i], b = active[j];
      let dx = a.x - b.x, dy = a.y - b.y;
      const d2 = dx * dx + dy * dy || 0.01, d = Math.sqrt(d2);
      const f = (2200 / d2) * alpha;
      dx /= d; dy /= d;
      a.vx += dx * f; a.vy += dy * f; b.vx -= dx * f; b.vy -= dy * f;
    }
  }
  for (const e of EDGES) {
    const a = nodeById.get(e.a), b = nodeById.get(e.b);
    if (a.vis < 0.05 || b.vis < 0.05) continue;
    let dx = b.x - a.x, dy = b.y - a.y;
    const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
    const f = (d - 96) * 0.015 * alpha;
    dx /= d; dy /= d;
    a.vx += dx * f; a.vy += dy * f; b.vx -= dx * f; b.vy -= dy * f;
  }
  for (const n of active) {
    n.vx += (clusterX(n.domain) - n.x) * 0.01 * alpha;
    n.vy += (H / 2 - n.y) * 0.012 * alpha;
  }
  for (const n of active) {
    if (n === drag) { n.vx = 0; n.vy = 0; continue; }
    n.vx *= 0.86; n.vy *= 0.86;
    n.x += n.vx; n.y += n.vy;
    n.x = Math.max(n.r + 6, Math.min(W - n.r - 6, n.x));
    n.y = Math.max(n.r + 6, Math.min(H - n.r - 6, n.y));
  }
  alpha *= 0.992; if (alpha < 0.05) alpha = 0.05;
}
function draw() {
  ctx.clearRect(0, 0, W, H);
  // In read mode the open document is the focus, so the minimap traces its
  // context (current node + neighbours) even without a hover.
  const focus = hover || (state.mode === "read" ? state.openDocNode : null);
  const hi = focus ? adj.get(focus.id) : null;
  for (const e of EDGES) {
    const a = nodeById.get(e.a), b = nodeById.get(e.b);
    const v = Math.min(a.vis, b.vis); if (v < 0.05) continue;
    const on = focus && (e.a === focus.id || e.b === focus.id);
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2 - 14;
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.quadraticCurveTo(mx, my, b.x, b.y);
    ctx.strokeStyle = withAlpha(cssVar("--pulse"), (on ? 0.85 : focus ? 0.08 : 0.28) * v);
    ctx.lineWidth = on ? 1.8 : 1; ctx.stroke();
  }
  for (const n of nodes) {
    if (n.vis < 0.05) continue;
    const dimmed = focus && n !== focus && !(hi && hi.has(n.id));
    const col = cssVar(domVar(n.domain));
    const a = (dimmed ? 0.22 : 1) * n.vis;
    const g = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, n.r * 3.4);
    g.addColorStop(0, withAlpha(col, 0.5 * a)); g.addColorStop(1, withAlpha(col, 0));
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(n.x, n.y, n.r * 3.4, 0, 7); ctx.fill();
    ctx.beginPath(); ctx.arc(n.x, n.y, n.r * n.vis, 0, 7);
    ctx.fillStyle = withAlpha(col, a); ctx.fill();
    ctx.lineWidth = 1.5; ctx.strokeStyle = withAlpha(cssVar("--ground"), a); ctx.stroke();
    if (n === state.openDocNode) { ctx.lineWidth = 2; ctx.strokeStyle = withAlpha(cssVar("--signal"), a); ctx.stroke(); }
    if ((n.r >= 11 || focus === n || (hi && hi.has(n.id)) || n === state.openDocNode) && n.vis > 0.4) {
      ctx.font = "600 11px " + cssVar("--sans").replace(/"/g, "");
      ctx.fillStyle = withAlpha(cssVar("--ink"), (dimmed ? 0.3 : 0.92) * n.vis);
      ctx.textBaseline = "middle";
      const t = n.title.length > 26 ? n.title.slice(0, 25) + "…" : n.title;
      ctx.fillText(t, n.x + n.r + 6, n.y);
    }
  }
}
function loop() {
  // While the layout is still settling (and not being dragged), advance the physics
  // a few ticks per rendered frame. This fast-forwards the opening animation to a
  // readable layout ~3x sooner while keeping the render itself a smooth 60fps and the
  // final layout identical. Dragging and the settled state stay at one tick.
  const ticks = !drag && alpha > 0.15 ? 3 : 1;
  for (let i = 0; i < ticks; i++) step();
  draw();
  requestAnimationFrame(loop);
}
function nodeAt(x, y) {
  let best = null, bd = 16 * 16;
  for (const n of nodes) {
    if (n.vis < 0.4) continue;
    const dx = x - n.x, dy = y - n.y, d = dx * dx + dy * dy;
    if (d < bd) { bd = d; best = n; }
  }
  return best;
}
function pos(ev) { const r = canvas.getBoundingClientRect(); return { x: ev.clientX - r.left, y: ev.clientY - r.top }; }

// ---- Document viewer --------------------------------------------------------
function resolveLink(domain, raw) {
  const target = norm(raw.split("|")[0]);
  const hit = index.documents.find(
    (d) => d.domain === domain && (norm(d.title) === target || norm(short(d.doc_id)) === target),
  );
  return hit ? hit.doc_id : null;
}
function renderInline(domain, text) {
  return esc(text).replace(/\[\[([^\]]+)\]\]/g, (_m, raw) => {
    const id = resolveLink(domain, raw);
    const label = esc(raw.split("|").pop().trim());
    return id ? `<a class="wikilink" data-doc="${id}">${label}</a>` : label;
  });
}
const stripWiki = (s) => s.replace(/\[\[([^\]]+)\]\]/g, (_m, r) => r.split("|").pop());
function openDocument(id) {
  const d = byId.get(id);
  // In live mode the server already scoped byId to what the caller may see (including
  // docs shared to them, whose domain is not in state.allowed), so trust byId there.
  if (!d || (!LIVE && !state.allowed.has(d.domain))) { state.openDoc = null; renderDoc(); return; }
  state.openDoc = id; state.openDocNode = nodeById.get(id);
  renderDoc(); renderBrowser();
  if (state.mode === "explore") setMode("read");
  else alpha = Math.max(alpha, 0.3);
}
function renderDoc() {
  const el = $("#doc"), head = $("#dochead"), close = $("#docclose");
  if (!state.openDoc) {
    state.openDocNode = null; close.hidden = true; head.textContent = "Document";
    el.innerHTML = '<p class="placeholder">Select a document from the browser, a graph node, or a search hit.</p>';
    return;
  }
  close.hidden = false;
  const d = byId.get(state.openDoc);
  head.textContent = "Document · " + d.domain;
  if (LIVE) { renderDocLive(d); return; }
  const md = reconstructDoc(index.chunks, d.doc_id, d.title);
  const blocks = md.split("\n\n").map((b) => {
    if (b.startsWith("## ")) return `<h4>${esc(b.slice(3))}</h4>`;
    if (b.startsWith("# ")) return `<h3>${esc(b.slice(2))}</h3>`;
    return `<p>${renderInline(d.domain, b)}</p>`;
  });
  const tags = (d.tags && d.tags.length)
    ? `<div class="chips" style="margin:2px 0 10px">${d.tags.map((t) => `<span class="chip tag">#${esc(t)}</span>`).join("")}</div>` : "";
  let prov = `<div class="provenance"><span class="dot" style="background:var(${domVar(d.domain)})"></span>${esc(d.domain)}`;
  if (d.source) prov += ` · source: ${esc(d.source)}`;
  if (d.fetched_at) prov += ` · fetched ${esc(d.fetched_at)}`;
  if (d.source_url) prov += ` · <a class="wikilink" href="${esc(d.source_url)}" target="_blank" rel="noreferrer">origin</a>`;
  prov += "</div>";
  el.innerHTML = `<article><h3>${esc(d.title)}</h3>${tags}${blocks.slice(1).join("")}${prov}</article>`;
  el.querySelectorAll("a.wikilink[data-doc]").forEach((a) =>
    a.addEventListener("click", () => openDocument(a.dataset.doc)));
}

// ---- Search / answer (scoped to allowed domains via lib.js) -----------------
function renderResults() {
  const box = $("#results");
  if (!box) return;
  if (LIVE) { scheduleLiveSearch(); return; }
  const q = state.query.trim();
  if (!q) { box.innerHTML = ""; return; }
  const hits = rankChunks(index.chunks, q, state.allowed, 8);
  const ans = extractiveAnswer(q, hits);
  if (!hits.length) {
    box.innerHTML = `<div class="answer"><div class="lbl"><span class="spark"></span><span class="eyebrow">Answer</span></div><p>${esc(ans.text)}</p></div>`;
    return;
  }
  const dom = hits[0].chunk.domain;
  let html = `<div class="answer"><div class="lbl"><span class="spark"></span><span class="eyebrow">Grounded answer · ${esc(dom)}</span></div>`;
  html += `<p>${renderInline(dom, ans.text)}</p>`;
  html += `<div class="cites">${ans.citations.map((c) => `<span class="cite" data-doc="${c.doc_id}">↳ ${esc(short(c.doc_id))}</span>`).join("")}</div>`;
  if (ans.gaps.length) html += `<div class="gaps">gaps · not supported by retrieved context: ${ans.gaps.map(esc).join(", ")}</div>`;
  html += `</div><div class="hits">`;
  const seenDocs = new Set();
  for (const { chunk } of hits) {
    if (seenDocs.has(chunk.doc_id)) continue; // one entry per document
    seenDocs.add(chunk.doc_id);
    const snip = esc(stripWiki(chunk.text).slice(0, 130));
    html += `<div class="hit" data-doc="${chunk.doc_id}"><div class="meta"><span class="dot" style="background:var(${domVar(chunk.domain)})"></span>${esc(chunk.domain)} · ${esc(chunk.heading || "-")}</div>
      <div class="htitle">${esc(chunk.title)}</div><div class="snip">${snip}…</div></div>`;
  }
  html += `</div>`;
  box.innerHTML = html;
  box.querySelectorAll("[data-doc]").forEach((a) => a.addEventListener("click", () => openDocument(a.dataset.doc)));
}

// ---- View modes (Explore / Split / Read) ------------------------------------
function setMode(m) {
  state.mode = m;
  $("#grid").setAttribute("data-mode", m);
  for (const b of $("#modeseg").querySelectorAll("button")) b.classList.toggle("on", b.dataset.mode === m);
  requestAnimationFrame(() => { resize(); alpha = Math.max(alpha, 0.5); });
}

// ============================================================================
//  Connections page
// ============================================================================
const SOURCES = [
  { glyph: "▤", name: "Files & docs", detail: "PDFs, slides and markdown, uploaded or from Drive and SharePoint.", status: "Live" },
  { glyph: "◍", name: "Web & wikis", detail: "Pages by URL, plus Confluence and Notion spaces.", status: "Live" },
  { glyph: "◈", name: "Code", detail: "Git repos: READMEs, ADRs and docs, onboarded on every sync.", status: "Live" },
  { glyph: "◗", name: "Conversations", detail: "Slack, Teams and email threads worth remembering.", status: "Connector" },
  { glyph: "◎", name: "Voice & meetings", detail: "Transcripts from Zoom, Meet, Gong or Otter: the tacit knowledge only ever said out loud.", status: "Connector" },
  { glyph: "✦", name: "Agents", detail: "Research agents draft notes and propose them through the same gated review as people.", status: "Connector" },
];
const SURFACES = [
  { glyph: "◧", name: "Coding assistants", detail: "MCP inside IDEs like Claude Code and Cursor: grounded answers where engineers work.", status: "Live" },
  { glyph: "◆", name: "Grounded assistant", detail: "A chat assistant, built on Google ADK, that answers from Hyper Brain with citations, on the web, in Slack or in Teams.", status: "Live" },
  { glyph: "∿", name: "Voice assistant", detail: "Ask by voice and hear a grounded answer read back, with the citations kept as a transcript. Voice sits on both sides: it comes in as meeting transcripts and goes out as answers.", status: "Connector" },
  { glyph: "◉", name: "Hyper Brain UI", detail: "This app: browse, search, read and propose.", status: "Live" },
  { glyph: "⬡", name: "Embedded / API", detail: "Point any internal app at the MCP endpoint, and build your own surface.", status: "Connector", action: "mcp" },
];
const STAGES = [
  { k: "Fetch", d: "A connector pulls the raw item from its source, in-tenancy, so nothing leaves your cloud." },
  { k: "Parse", d: "Markdown and PDFs (via Document AI) become clean text with headings and structure preserved." },
  { k: "Curate", d: "Gemini normalises, titles and tags the content, turning a raw file into a governed note." },
  { k: "Land", d: "Written as provenance-stamped markdown, deduped by checksum, and assigned to a domain." },
  { k: "Index", d: "Chunked, embedded with in-tenancy Vertex, and woven into the wikilink knowledge graph." },
];
const ARCH = [
  { k: "Scale to zero", d: "Runs on Cloud Run: nothing runs, and nothing is billed, until something asks." },
  { k: "In-tenancy boundary", d: "Corpus, embeddings and synthesis never leave your own cloud tenancy." },
  { k: "Vertex, in-region", d: "Embeddings and Gemini answers are generated inside your region." },
  { k: "Least-privilege IAM", d: "Every service runs as its own minimal, single-purpose service account." },
  { k: "Provenance & gated writes", d: "Every note carries its source; new content is reviewed before it merges." },
  { k: "Observability", d: "Every request is traced end to end in Cloud Trace." },
];

function connCard(c) {
  const live = c.status === "Live";
  const badge = `<span class="st ${live ? "live" : ""}">${c.status}</span>`;
  const foot = c.action
    ? `<div class="cardfoot">${badge}<span class="actionhint">Connector info →</span></div>`
    : badge;
  const open = c.action
    ? `<div class="conncard action" data-action="${c.action}" role="button" tabindex="0">`
    : `<div class="conncard">`;
  return `${open}<div class="top"><div class="cg">${c.glyph}</div><div class="nm">${c.name}</div></div>`
    + `<div class="dt">${c.detail}</div>${foot}</div>`;
}
function renderConnections() {
  $("#sourcecards").innerHTML = SOURCES.map(connCard).join("");
  $("#surfacecards").innerHTML = SURFACES.map(connCard).join("");
  $("#archgrid").innerHTML = ARCH.map((a) => `<div class="archcard"><div class="k">${a.k}</div><div class="d">${a.d}</div></div>`).join("");
  const pipe = $("#pipeline");
  pipe.innerHTML = STAGES.map((s, i) => `<div class="stage-step" data-i="${i}"><div class="n">0${i + 1}</div><div class="k">${s.k}</div></div>`).join("");
  pipe.querySelectorAll(".stage-step").forEach((el) => el.addEventListener("click", () => showStage(+el.dataset.i)));
  showStage(0);
  $("#runpipe").addEventListener("click", runPipeline);

  const sc = $("#surfacecards");
  sc.addEventListener("click", (e) => { if (e.target.closest('.conncard.action[data-action="mcp"]')) openMcp(); });
  sc.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && e.target.closest('.conncard.action[data-action="mcp"]')) { e.preventDefault(); openMcp(); }
  });

  // The Explore page "Add data" panel mirrors the same source categories.
  const ms = $("#minisources");
  if (ms) ms.innerHTML = SOURCES.map((s) =>
    `<li><span class="mg">${s.glyph}</span><span class="mn">${s.name}</span><span class="ms ${s.status === "Live" ? "live" : ""}">${s.status}</span></li>`).join("");
  const tc = $("#toconnect");
  if (tc) tc.addEventListener("click", () => setPage("connect"));
}
function showStage(i) {
  document.querySelectorAll("#pipeline .stage-step").forEach((n, j) => n.classList.toggle("active", j === i));
  $("#pipedetail").textContent = STAGES[i].d;
}
let runTimer = null;
function runPipeline() {
  const steps = [...document.querySelectorAll("#pipeline .stage-step")];
  if (!steps.length) return;
  clearInterval(runTimer);
  steps.forEach((s) => s.classList.remove("lit"));
  let i = 0;
  runTimer = setInterval(() => {
    steps.forEach((s, j) => s.classList.toggle("lit", j === i));
    if (i < STAGES.length) { showStage(i); i++; }
    else {
      clearInterval(runTimer);
      steps.forEach((s) => s.classList.remove("lit"));
      $("#pipedetail").textContent = "Indexed. The document is now searchable and appears in the graph, within the index TTL, no redeploy.";
    }
  }, 720);
}

// ---- MCP connector modal ----------------------------------------------------
function fillMcp() {
  const url = (config && config.mcp_url) || "https://<your-brain>.run.app/mcp";
  const u = $("#mcpurl"); if (u) u.textContent = url;
  const conf = $("#mcpconf");
  if (conf) {
    conf.textContent = JSON.stringify(
      { mcpServers: { "hyper-brain": { type: "http", url, headers: { Authorization: "Bearer ${HYPER_BRAIN_TOKEN}" } } } },
      null, 2,
    );
  }
}
const mcpmodal = $("#mcpmodal");
function openMcp() { mcpmodal.hidden = false; }
function closeMcp() { mcpmodal.hidden = true; }

// ---- Connections flow diagram (canvas) --------------------------------------
const flow = $("#flow"), fx = flow.getContext("2d");
let fW = 0, fH = 0, fdpr = 1, flowActive = false, flowRunning = false, fparts = [];
const SRC_L = ["Files", "Web", "Voice", "Code", "Agents"];
const SURF_L = ["IDEs", "Assistant", "This UI", "Your apps", "+ surfaces"];
const FN = 5;
const fam = () => cssVar("--sans").replace(/"/g, "");
const monofam = () => cssVar("--mono").replace(/"/g, "");
// A little knowledge graph drawn inside the central box: the brain *is* an
// interconnected wiki. Positions are normalised (0..1) within the box's inner area.
const BRAIN_NODES = [
  { x: 0.50, y: 0.46, r: 3.4 },
  { x: 0.22, y: 0.20, r: 2.2 },
  { x: 0.78, y: 0.24, r: 2.4 },
  { x: 0.14, y: 0.62, r: 2.2 },
  { x: 0.86, y: 0.58, r: 2.2 },
  { x: 0.38, y: 0.82, r: 2.2 },
  { x: 0.66, y: 0.84, r: 2.4 },
  { x: 0.50, y: 0.13, r: 2.0 },
];
const BRAIN_EDGES = [[0, 1], [0, 2], [0, 3], [0, 4], [0, 5], [0, 6], [1, 7], [2, 7], [1, 3], [2, 4], [5, 6], [3, 5], [4, 6]];
function flowResize() {
  const r = flow.getBoundingClientRect();
  if (!r.width) return;
  fdpr = Math.min(window.devicePixelRatio || 1, 2);
  fW = r.width; fH = r.height;
  flow.width = fW * fdpr; flow.height = fH * fdpr;
  fx.setTransform(fdpr, 0, 0, fdpr, 0, 0);
}
function flowInit() {
  fparts = [];
  for (let e = 0; e < 2 * FN; e++) for (let k = 0; k < 2; k++)
    fparts.push({ e, t: (k / 2) + Math.random() * 0.4, s: 0.004 + Math.random() * 0.004 });
}
function flowGeom() {
  const leftX = fW * 0.19, rightX = fW * 0.81, midX = fW * 0.5;
  const bw = Math.min(158, fW * 0.2), bh = Math.min(fH * 0.62, 196), cy = fH / 2;
  const yOf = (i) => fH * 0.14 + i * (fH * 0.72 / (FN - 1));
  return { leftX, rightX, midX, bw, bh, cy, yOf };
}
function flowEdge(e, g) {
  if (e < FN) return { x1: g.leftX, y1: g.yOf(e), x2: g.midX - g.bw / 2, y2: g.cy };
  return { x1: g.midX + g.bw / 2, y1: g.cy, x2: g.rightX, y2: g.yOf(e - FN) };
}
function flowStep() { for (const p of fparts) { p.t += p.s; if (p.t > 1) p.t -= 1; } }
function flowDraw() {
  fx.clearRect(0, 0, fW, fH);
  const g = flowGeom();
  const gold = cssVar("--signal"), pulse = cssVar("--pulse"), ink = cssVar("--ink"), muted = cssVar("--muted");
  for (let e = 0; e < 2 * FN; e++) {
    const { x1, y1, x2, y2 } = flowEdge(e, g), mx = (x1 + x2) / 2;
    fx.beginPath(); fx.moveTo(x1, y1); fx.bezierCurveTo(mx, y1, mx, y2, x2, y2);
    fx.strokeStyle = withAlpha(pulse, 0.95); fx.lineWidth = 1; fx.stroke();
  }
  const boxL = g.midX - g.bw / 2, boxT = g.cy - g.bh / 2;
  fx.fillStyle = cssVar("--panel-2"); fx.strokeStyle = withAlpha(gold, 0.85); fx.lineWidth = 1.5;
  fx.fillRect(boxL, boxT, g.bw, g.bh);
  fx.strokeRect(boxL, boxT, g.bw, g.bh);
  fx.textAlign = "center"; fx.textBaseline = "middle";
  // Title along the top.
  fx.fillStyle = ink; fx.font = "700 12px " + fam();
  fx.fillText("HYPER BRAIN", g.midX, boxT + 17);
  // Inner knowledge graph in the middle band: the interconnected wiki.
  const padX = 15, topH = 34, botH = 30;
  const gx0 = boxL + padX, gy0 = boxT + topH, gw = g.bw - 2 * padX, gh = g.bh - topH - botH;
  const px = (n) => gx0 + n.x * gw, py = (n) => gy0 + n.y * gh;
  const t = performance.now() / 1000;
  for (const [a, b] of BRAIN_EDGES) {
    const A = BRAIN_NODES[a], B = BRAIN_NODES[b];
    fx.beginPath(); fx.moveTo(px(A), py(A)); fx.lineTo(px(B), py(B));
    fx.strokeStyle = withAlpha(gold, 0.26); fx.lineWidth = 1; fx.stroke();
  }
  for (let i = 0; i < BRAIN_NODES.length; i++) {
    const n = BRAIN_NODES[i], x = px(n), y = py(n);
    const pulse = 0.55 + 0.45 * Math.sin(t * 1.6 + i * 0.8); // gentle activation wave
    const glow = fx.createRadialGradient(x, y, 0, x, y, n.r * 3);
    glow.addColorStop(0, withAlpha(gold, 0.5 * pulse)); glow.addColorStop(1, withAlpha(gold, 0));
    fx.fillStyle = glow; fx.beginPath(); fx.arc(x, y, n.r * 3, 0, 7); fx.fill();
    fx.fillStyle = withAlpha(gold, 0.9); fx.beginPath(); fx.arc(x, y, n.r, 0, 7); fx.fill();
  }
  // Process caption along the bottom.
  fx.fillStyle = muted; fx.font = "9px " + monofam();
  fx.fillText("INGEST · CURATE", g.midX, boxT + g.bh - 20);
  fx.fillText("INDEX · SERVE", g.midX, boxT + g.bh - 9);
  for (const p of fparts) {
    const { x1, y1, x2, y2 } = flowEdge(p.e, g), mx = (x1 + x2) / 2, t = p.t, u = 1 - t;
    const x = u * u * u * x1 + 3 * u * u * t * mx + 3 * u * t * t * mx + t * t * t * x2;
    const y = u * u * u * y1 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t * t * t * y2;
    fx.beginPath(); fx.arc(x, y, 2.4, 0, 7); fx.fillStyle = withAlpha(gold, 0.95); fx.fill();
  }
  fx.font = "600 11px " + fam();
  for (let i = 0; i < FN; i++) {
    flowNode(g.leftX, g.yOf(i), gold);
    fx.textAlign = "right"; fx.fillStyle = ink; fx.fillText(SRC_L[i], g.leftX - 12, g.yOf(i));
    flowNode(g.rightX, g.yOf(i), gold);
    fx.textAlign = "left"; fx.fillStyle = ink; fx.fillText(SURF_L[i], g.rightX + 12, g.yOf(i));
  }
}
function flowNode(x, y, col) {
  fx.fillStyle = cssVar("--panel"); fx.strokeStyle = withAlpha(col, 0.9); fx.lineWidth = 1.5;
  fx.fillRect(x - 5, y - 5, 10, 10); fx.strokeRect(x - 5, y - 5, 10, 10);
}
function flowLoop() {
  if (!flowActive) { flowRunning = false; return; }
  flowStep(); flowDraw(); requestAnimationFrame(flowLoop);
}

// ---- Agents page: animated, interactive multi-agent flow (ADK showcase) -----
const agentCanvas = $("#agentcanvas"), ax = agentCanvas.getContext("2d");
let aW = 0, aH = 0, adpr = 1, agentsActive = false, agentsRunning = false;
let aScenario = "ask", aStep = 0, aT = 0;
// Live mode: real events arrive over SSE and queue up; each animates as it fires, so
// you watch the actual run unfold. Demo mode loops the scripted scenarios.
let aMode = "demo";
let aQueue = [], aCur = null, aStreamDone = false, aLiveAnswer = "", aAnswerShown = false;
let aStepNo = 0; // count of live steps shown so far (for numbering the caption)
let aFiring = false; // submitted, awaiting the first real event: pulse the You box

// Positions are normalised (0..1). Left: you. The coordinator is a hub that fans out
// to its two specialists (researcher up, curator down), so a delegation edge never
// crosses the other specialist. Then the governed brain (MCP), then the resources.
const A_NODES = {
  you:     { x: 0.115, y: 0.50, label: "You", sub: "the caller", kind: "out" },
  coord:   { x: 0.30,  y: 0.50, label: "Coordinator", sub: "routes the request", kind: "agent" },
  research:{ x: 0.45,  y: 0.24, label: "Researcher", sub: "read tools", kind: "agent" },
  curate:  { x: 0.45,  y: 0.76, label: "Curator", sub: "write tools", kind: "agent" },
  brain:   { x: 0.645, y: 0.50, label: "Brain · MCP", sub: "enforces the domain ACL", kind: "brain" },
  gemini:  { x: 0.87,  y: 0.22, label: "Gemini · Vertex", sub: "in-tenancy synthesis", kind: "res" },
  corpus:  { x: 0.87,  y: 0.50, label: "Corpus + index", sub: "hybrid retrieval", kind: "res" },
  review:  { x: 0.87,  y: 0.80, label: "Review queue", sub: "human approval", kind: "res" },
};

const A_SCENARIOS = {
  ask: {
    steps: [
      { a: "you", b: "coord", cap: "You ask: “how do we detect fraud in real time?”" },
      { a: "coord", b: "research", cap: "Coordinator delegates → transfer_to_agent(researcher)" },
      { a: "research", b: "brain", cap: "Researcher calls search over authenticated MCP" },
      { a: "brain", b: "corpus", cap: "Brain retrieves your domain-scoped chunks (semantic + keyword)" },
      { a: "brain", b: "gemini", cap: "Gemini composes a grounded, cited answer, inside your tenancy" },
      { a: "brain", b: "research", cap: "The cited answer returns to the researcher" },
      { a: "research", b: "you", cap: "Researcher answers you, with citations and honest gaps" },
    ],
  },
  propose: {
    steps: [
      { a: "you", b: "coord", cap: "You ask: “draft a note on feature flags for finserv”" },
      { a: "coord", b: "curate", cap: "Coordinator delegates → transfer_to_agent(curator)" },
      { a: "curate", b: "brain", cap: "Curator grounds the draft: search + get_document" },
      { a: "brain", b: "corpus", cap: "Brain retrieves the relevant material" },
      { a: "curate", b: "brain", cap: "Curator calls propose_document" },
      { a: "brain", b: "review", cap: "Proposal is staged for human review, never written live" },
      { a: "curate", b: "you", cap: "Curator: “proposed into finserv, awaiting review”" },
    ],
  },
};

// The union of every scenario edge, drawn faintly as the always-visible agent map.
const A_ALL_EDGES = (() => {
  const seen = new Set(), out = [];
  for (const name of Object.keys(A_SCENARIOS))
    for (const s of A_SCENARIOS[name].steps) {
      const k = s.a + ">" + s.b;
      if (!seen.has(k)) { seen.add(k); out.push([s.a, s.b]); }
    }
  return out;
})();

function aColor(kind) {
  return { out: cssVar("--faint"), agent: cssVar("--signal"),
    brain: cssVar("--domain-2"), res: cssVar("--domain-3") }[kind] || cssVar("--muted");
}
function agentsResize() {
  const r = agentCanvas.getBoundingClientRect(); if (!r.width) return;
  adpr = Math.min(window.devicePixelRatio || 1, 2);
  aW = r.width; aH = r.height;
  agentCanvas.width = aW * adpr; agentCanvas.height = aH * adpr;
  ax.setTransform(adpr, 0, 0, adpr, 0, 0);
}
const aPos = (n) => ({ x: n.x * aW, y: n.y * aH });
function agentsStepTick() {
  if (aMode === "live") {
    if (!aCur) {
      if (aQueue.length) { aCur = aQueue.shift(); aFiring = false; aStepNo++; aT = 0; }
      else if (aStreamDone && !aAnswerShown) { aFiring = false; showLiveAnswer(); } // failed before any event
      return;
    }
    aT += 0.02; // brisk, so queued real events don't lag far behind the run
    if (aT < 1) return;
    if (aQueue.length) { aCur = aQueue.shift(); aStepNo++; aT = 0; }
    else { aT = 1; if (aStreamDone && !aAnswerShown) showLiveAnswer(); } // hold, awaiting the next event
    return;
  }
  aT += 0.012; // demo: loop the scripted scenario
  if (aT >= 1) { aT = 0; aStep = (aStep + 1) % A_SCENARIOS[aScenario].steps.length; }
}
const aBoxW = () => Math.max(120, Math.min(170, aW * 0.17));
const A_BOXH = 44;
// Where the ray leaving box centre c in unit direction (dx,dy) meets the box edge.
function boxExit(c, dx, dy) {
  const hw = aBoxW() / 2, hh = A_BOXH / 2;
  const tx = dx !== 0 ? hw / Math.abs(dx) : Infinity;
  const ty = dy !== 0 ? hh / Math.abs(dy) : Infinity;
  const t = Math.min(tx, ty);
  return { x: c.x + dx * t, y: c.y + dy * t };
}
// The connecting segment, trimmed to both boxes' borders so lines never cross text.
function aSeg(a, b) {
  const pa = aPos(A_NODES[a]), pb = aPos(A_NODES[b]);
  let dx = pb.x - pa.x, dy = pb.y - pa.y; const d = Math.hypot(dx, dy) || 1; dx /= d; dy /= d;
  return { p1: boxExit(pa, dx, dy), p2: boxExit(pb, -dx, -dy) };
}
function aEdge(a, b, active) {
  const { p1, p2 } = aSeg(a, b);
  ax.beginPath(); ax.moveTo(p1.x, p1.y); ax.lineTo(p2.x, p2.y);
  ax.strokeStyle = active ? withAlpha(cssVar("--signal"), 0.9) : withAlpha(cssVar("--pulse"), 0.85);
  ax.lineWidth = active ? 2 : 1; ax.stroke();
}
function aParticle(a, b, t) {
  const { p1, p2 } = aSeg(a, b);
  for (let k = 0; k < 6; k++) {
    const tt = t - k * 0.045; if (tt < 0 || tt > 1) continue;
    const x = p1.x + (p2.x - p1.x) * tt, y = p1.y + (p2.y - p1.y) * tt, s = 7 - k;
    ax.fillStyle = withAlpha(cssVar("--signal"), 0.95 - k * 0.15);
    ax.fillRect(x - s / 2, y - s / 2, s, s);
  }
}
function aNode(id, active) {
  const n = A_NODES[id], p = aPos(n), col = aColor(n.kind);
  const w = aBoxW(), h = A_BOXH, x0 = p.x - w / 2, y0 = p.y - h / 2;
  // Opaque base first so an edge never shows through, then a tint if active.
  ax.fillStyle = cssVar("--panel"); ax.fillRect(x0, y0, w, h);
  if (active) { ax.fillStyle = withAlpha(col, 0.14); ax.fillRect(x0, y0, w, h); }
  ax.strokeStyle = active ? col : cssVar("--hair");
  ax.lineWidth = active ? 2 : 1;
  ax.strokeRect(x0, y0, w, h);
  ax.fillStyle = col; ax.fillRect(x0 + 10, p.y - 7, 7, 7);
  ax.textAlign = "left"; ax.textBaseline = "alphabetic";
  ax.fillStyle = cssVar("--ink"); ax.font = "700 12.5px " + fam();
  ax.fillText(n.label, x0 + 25, p.y - 2);
  ax.fillStyle = cssVar("--muted"); ax.font = "10px " + fam();
  ax.fillText(n.sub, x0 + 25, p.y + 12);
}
// The mode badge and the diagram's live ring: unmistakable live-vs-simulated cue.
let aModeLabel = "";
function setAgentModeUI() {
  let label, cls;
  if (aMode === "live") { label = aStreamDone ? "Live run · done" : "Live run"; cls = aStreamDone ? "live done" : "live running"; }
  else { label = "Simulated flow"; cls = "demo"; }
  if (label === aModeLabel) return;
  aModeLabel = label;
  const pill = $("#agentmode"); if (pill) { pill.textContent = label; pill.className = "agentmode " + cls; }
  const wrap = $("#agentwrap"); if (wrap) wrap.classList.toggle("live", aMode === "live");
}
// A pulsing gold ring on a node, e.g. the You box "firing up" the instant you submit,
// before the first real event arrives (there is a short lag while the run starts).
function aPulseNode(id) {
  const p = aPos(A_NODES[id]), w = aBoxW(), h = A_BOXH;
  const pulse = 0.5 + 0.5 * Math.sin(performance.now() / 210);
  ax.strokeStyle = withAlpha(cssVar("--signal"), 0.35 + 0.55 * pulse);
  ax.lineWidth = 1.5 + 1.8 * pulse;
  ax.strokeRect(p.x - w / 2, p.y - h / 2, w, h);
}
function agentsDraw() {
  ax.clearRect(0, 0, aW, aH);
  for (const [a, b] of A_ALL_EDGES) aEdge(a, b, false); // faint always-visible map
  const cur = aMode === "live" ? aCur : A_SCENARIOS[aScenario].steps[aStep];
  const firing = aMode === "live" && aFiring && !cur;
  if (cur) { aEdge(cur.a, cur.b, true); aParticle(cur.a, cur.b, aT); }
  for (const id of Object.keys(A_NODES)) {
    aNode(id, (!!cur && (id === cur.a || id === cur.b)) || (firing && id === "you"));
  }
  if (firing) aPulseNode("you"); // animate immediately on submit
  setAgentModeUI();
  const cap = $("#agentcap");
  if (!cap) return;
  if (aMode === "live") {
    if (cur) cap.textContent = `${aStepNo} · ${cur.cap}`;
    else if (firing) cap.textContent = "Firing up the agent team…";
    else if (aStreamDone) cap.textContent = aLiveAnswer || "Run ended.";
    else cap.textContent = "waiting for the first event…";
  } else {
    const steps = A_SCENARIOS[aScenario].steps;
    cap.textContent = `step ${aStep + 1}/${steps.length} · ${cur.cap}`;
  }
}
function agentsLoop() {
  if (!agentsActive) { agentsRunning = false; return; }
  agentsStepTick(); agentsDraw(); requestAnimationFrame(agentsLoop);
}
function showLiveAnswer() {
  aAnswerShown = true;
  const body = $("#agentanswerbody"); if (body) body.textContent = aLiveAnswer;
  const el = $("#agentanswer"); if (el) el.hidden = false;
}
function resetLiveAgent() {
  aMode = "demo"; aQueue = []; aCur = null; aStreamDone = false; aLiveAnswer = ""; aAnswerShown = false;
  aStepNo = 0; aFiring = false;
  const el = $("#agentanswer"); if (el) el.hidden = true;
  const body = $("#agentanswerbody"); if (body) body.textContent = "";
}
function setScenario(name) {
  if (!A_SCENARIOS[name]) return;
  resetLiveAgent();
  aScenario = name; aStep = 0; aT = 0;
  for (const b of $("#agentseg").querySelectorAll("button")) b.classList.toggle("on", b.dataset.scenario === name);
  agentsResize(); agentsDraw();
}
// One SSE frame from the live run: a step to animate, the final answer, or an error.
function handleAgentEvent(msg) {
  if (msg.step && msg.step.edge) aQueue.push({ a: msg.step.edge[0], b: msg.step.edge[1], cap: msg.step.caption || "" });
  if (msg.error) { aStreamDone = true; aLiveAnswer = "Error: " + msg.error; }
  if (msg.done) { aStreamDone = true; aLiveAnswer = msg.answer || "(no answer returned)"; }
}
// Phase 3: stream the real ADK run over SSE and light each edge as its event fires.
async function runLiveAgent() {
  const q = $("#agentquery").value.trim(); if (!q || !LIVE) return;
  resetLiveAgent();
  aMode = "live"; aStep = 0; aT = 0; aFiring = true; aStepNo = 0; // pulse the You box at once
  $("#agentrun").disabled = true;
  const cap = $("#agentcap"); if (cap) cap.textContent = "Firing up the agent team…";
  try {
    const resp = await fetch(`${config.api_url}/api/agent/stream`, {
      method: "POST",
      headers: { authorization: `Bearer ${token()}`, "content-type": "application/json" },
      body: JSON.stringify({ query: q }),
    });
    if (!resp.ok || !resp.body) throw new Error(`agent stream failed (${resp.status})`);
    const reader = resp.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, i); buf = buf.slice(i + 2);
        const line = frame.split("\n").find((l) => l.startsWith("data:"));
        if (line) { try { handleAgentEvent(JSON.parse(line.slice(5).trim())); } catch { /* skip */ } }
      }
    }
    aStreamDone = true;
  } catch (e) {
    aStreamDone = true; aFiring = false; aLiveAnswer = "Run failed: " + String(e.message || e);
  } finally {
    $("#agentrun").disabled = false;
  }
}

// ---- Agent registry: model inventory + versioned prompts -------------------
const aFind = (id) => (AGENTS ? AGENTS.agents.find((a) => a.id === id) : null);
function renderAgentReg() {
  const cards = $("#agentregcards");
  if (!AGENTS || !cards) return;
  cards.innerHTML = AGENTS.agents.map((a) => {
    const p = a.prompt;
    return `<button class="agentcard" data-agent="${a.id}">
      <div class="agentcardtop"><span class="agentcardname">${esc(a.name)}</span>
        <span class="agentcardmodel mono">${esc(a.model)}</span></div>
      <div class="agentcardrole">${esc(a.role)}</div>
      <div class="agentcardver mono">${esc(p.name)} · v${esc(p.version)} · <span class="sha">${esc(p.sha)}</span></div>
    </button>`;
  }).join("");
  cards.querySelectorAll(".agentcard").forEach((b) =>
    b.addEventListener("click", () => selectAgent(b.dataset.agent)));
  renderAgentModels();
  renderAgentEvals();
  selectAgent(AGENTSEL && aFind(AGENTSEL) ? AGENTSEL : AGENTS.agents[0].id);
}
function renderAgentEvals() {
  const el = $("#agentevals"), ev = AGENTS && AGENTS.evals;
  if (!el || !ev) return;
  const metrics = (ev.metrics || []).map((m) => `<div class="evalmetric">
    <span class="evalmetricname mono">${esc(m.metric)}</span>
    <span class="evalthresh mono">≥ ${esc(String(m.threshold))}</span>
    <span class="evalabout">${esc(m.about)}</span></div>`).join("");
  const suites = (ev.suites || []).map((s) => `<div class="evalsuite${s.boundary ? " boundary" : ""}">
    <div class="evalsuitetop">
      <span class="evalsuitename">${esc(s.name)}</span>
      ${s.boundary ? '<span class="evalbadge mono">privacy gate</span>' : ""}
      <span class="evalcases mono">${esc(String(s.cases))} case${s.cases === 1 ? "" : "s"}</span>
    </div>
    <div class="evalsuiteabout">${esc(s.about)}</div>
    <div class="evalsamples">${s.samples.map((q) => `<span class="evalq mono">${esc(q)}</span>`).join("")}</div>
    <div class="evalasserts"><span class="evalassertk mono">asserts</span> ${esc(s.asserts)}</div>
  </div>`).join("");
  el.innerHTML = `
    <div class="agentevalshead">
      <span class="eyebrow">AI platform · agent evals</span>
      <h4>The agent team is graded by evals on every change</h4>
      <p>${esc(ev.tier)} Two gates every pull request must clear:</p>
    </div>
    <div class="evalcriteria">${metrics}</div>
    <div class="evalsuites">${suites}</div>
    <div class="evalpaid mono">Opt-in paid tier (LLM-judged, controlled profile, not run in the free tier): ${(ev.paid_tier || []).map(esc).join(" · ")}</div>`;
}
function renderAgentModels() {
  const el = $("#agentmodels");
  if (!el || !AGENTS) return;
  const rows = (AGENTS.models || []).map((m) => `<tr>
    <td class="mono">${esc(m.id || "")}</td>
    <td>${esc(m.modality || "")}</td>
    <td class="mono">${esc(m.region || "")}</td>
    <td><span class="mstatus ${m.status === "approved" ? "ok" : "opt"}">${esc(m.status || "")}</span></td>
    <td class="mpurpose">${esc(m.purpose || "")}</td></tr>`).join("");
  el.innerHTML = `<div class="agentmodelshead mono">Model inventory · config/models.yaml</div>
    <div class="agentmodelscroll"><table class="agentmodeltable">
      <thead><tr><th>Model</th><th>Modality</th><th>Region</th><th>Status</th><th>Purpose</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
}
function selectAgent(id) {
  const a = aFind(id);
  if (!a) return;
  AGENTSEL = id;
  for (const b of document.querySelectorAll(".agentcard")) b.classList.toggle("on", b.dataset.agent === id);
  const md = a.model_detail || {}, p = a.prompt;
  const meta = [
    ["prompt", `${p.name} · v${p.version} · sha ${p.sha}`],
    ["model", `${a.model}${md.provider ? " · " + md.provider : ""}${md.region ? " · " + md.region : ""}`],
    ["status", md.status || "registered"],
    ["tools", a.tools.join(", ")],
  ].map(([k, v]) => `<div class="ametarow"><span class="ametak">${esc(k)}</span><span class="ametav mono">${esc(v)}</span></div>`).join("");
  $("#agentregdetail").innerHTML = `
    <div class="agentdetailhead"><h5>${esc(a.name)}</h5>
      <span class="agentdetailrole">${esc(a.role)}</span></div>
    <div class="agentdetailmeta">${meta}</div>
    <div class="agentdetaillabel mono">Active prompt · content-hashed ${esc(p.sha)}</div>
    <pre class="agentprompt">${esc(p.text)}</pre>`;
}
// Clicking an agent box in the diagram opens that agent's registry entry.
const A_CLICKABLE = ["coord", "research", "curate"];
function agentAt(clientX, clientY) {
  const r = agentCanvas.getBoundingClientRect();
  const cx = clientX - r.left, cy = clientY - r.top, w = aBoxW(), h = A_BOXH;
  return A_CLICKABLE.find((id) => {
    const p = aPos(A_NODES[id]);
    return Math.abs(cx - p.x) <= w / 2 && Math.abs(cy - p.y) <= h / 2;
  }) || null;
}

// ---- Page switching (Connections / Explore) ---------------------------------
let graphSized = false;
// ---- Studio: bring in content (URL / file / text) and curate it into a draft ----
let studioSrc = "url", studioFile = null, studioDraft = null;
let splitItems = null; // when set, the draft panel is in split review/edit mode
function renderStudio() {
  if (!LIVE) { studioMsg("Sign in to bring in and curate content."); return; }
}
function studioMsg(msg, spin) {
  const el = $("#studiostatus");
  if (!el) return;
  el.innerHTML = msg
    ? `<p class="studiostat">${spin ? '<span class="idxspin"></span>' : ""}<span>${esc(msg)}</span></p>`
    : "";
}
// Cycle status lines while a generate is in flight, so a ~30s Gemini pass looks alive.
let studioProgTimer = null;
function startStudioProgress(steps) {
  let i = 0;
  studioMsg(steps[0], true);
  studioProgTimer = setInterval(() => { i = (i + 1) % steps.length; studioMsg(steps[i], true); }, 3500);
}
function stopStudioProgress() { if (studioProgTimer) { clearInterval(studioProgTimer); studioProgTimer = null; } }
function setStudioSrc(src) {
  if (!src) return;
  studioSrc = src;
  for (const b of $("#studioseg").querySelectorAll("button")) b.classList.toggle("on", b.dataset.src === src);
  $("#sf-url").hidden = src !== "url";
  $("#sf-file").hidden = src !== "file";
  $("#sf-text").hidden = src !== "text";
}
async function generateDraft() {
  if (!LIVE) return;
  const curate = $("#studiocurate").checked;
  const payload = { curate };
  if (studioSrc === "url") {
    const url = $("#studiourl").value.trim();
    if (!url) return studioMsg("Enter a URL to fetch.");
    payload.kind = "url"; payload.url = url;
  } else if (studioSrc === "text") {
    const text = $("#studiotext").value.trim();
    if (!text) return studioMsg("Paste some text to curate.");
    payload.kind = "text"; payload.text = text;
  } else {
    if (!studioFile) return studioMsg("Choose a file first.");
    payload.kind = "file"; payload.filename = studioFile.name;
    payload.content_base64 = await fileToBase64(studioFile);
  }
  const btn = $("#studiogen"); btn.disabled = true;
  resetDraftPanel(); // start fresh: clear any prior draft, split, or success state
  const ai = curate ? "Curating with Gemini Vertex (this can take ~30s)…" : "Preparing the draft…";
  const steps = studioSrc === "url"
    ? ["Fetching the page…", "Extracting the main content…", ai, "Polishing the draft…"]
    : studioSrc === "file"
      ? ["Parsing the file…", ai, "Polishing the draft…"]
      : [ai, "Structuring the draft…"];
  startStudioProgress(steps);
  try {
    studioDraft = await API.draft(payload);
    stopStudioProgress();
    openDraft(studioDraft);
    studioMsg("");
  } catch (e) {
    stopStudioProgress();
    studioMsg(e.message || String(e));
  } finally { btn.disabled = false; }
}
// Clear the draft panel to a neutral state, so starting a new draft (or discarding)
// never leaves stale split/success/in-progress UI from a previous piece of content.
function resetDraftPanel() {
  splitItems = null;
  $("#splitview").hidden = true;
  $("#draftsingle").hidden = false;
  $("#draftdiscard").textContent = "Discard";
  const ds = $("#draftsuccess"); if (ds) { ds.classList.remove("show"); ds.hidden = true; }
  $("#draftbody").style.opacity = "1";
  $("#draftcreate").disabled = false;
  $("#studiodraft").hidden = true;
}
function openDraft(draft) {
  resetDraftPanel();
  $("#drafttitle").value = draft.title || "";
  $("#draftcontent").value = draft.content || "";
  $("#drafttags").value = (draft.tags || []).join(", ");
  const src = $("#draftsource");
  if (draft.source_url) {
    src.hidden = false;
    src.innerHTML = `Source: <a href="${esc(draft.source_url)}" target="_blank" rel="noopener">${esc(draft.source_url)}</a>`;
  } else src.hidden = true;
  $("#draftcurated").hidden = !draft.curated;
  renderDraftTargets();
  renderDraftPreview();
  updateSplitVisibility();
  $("#draftresult").innerHTML = "";
  const ds = $("#draftsuccess"); ds.hidden = true; ds.classList.remove("show");
  $("#draftbody").style.opacity = "1";
  $("#studiodraft").hidden = false;
  loadDraftLinks();
}
function renderDraftTargets() {
  const sel = $("#drafttarget"), pd = ME.personal && ME.personal.domain;
  // Personal + any team domain the caller holds a write grant on. All are direct
  // writes now (a write grant is trust); the agent's proposals still go to review.
  let html = `<option value="${esc(pd)}">Personal space</option>`;
  for (const d of (ME.writable || [])) html += `<option value="${esc(d)}">${esc(d)}</option>`;
  sel.innerHTML = html;
  updateCreateLabel();
}
function updateCreateLabel() {
  $("#draftcreate").textContent = "Create";
}
function renderDraftPreview() {
  const el = $("#draftpreview");
  if (el) el.innerHTML = mdToHtml($("#draftcontent").value);
}
// Suggested links for the draft: existing docs similar to it, click to add a [[wikilink]].
async function loadDraftLinks() {
  const wrap = $("#draftlinks"); if (!wrap || !studioDraft) return;
  wrap.innerHTML = '<div class="draftlinkshint">Finding related content to link…</div>';
  let suggestions;
  try { suggestions = await API.linkSuggestFor($("#draftcontent").value, $("#drafttarget").value); }
  catch { wrap.innerHTML = ""; return; }
  if (!suggestions || !suggestions.length) {
    wrap.innerHTML = '<div class="draftlinkshint">No related content to link yet.</div>';
    return;
  }
  wrap.innerHTML =
    '<div class="draftlinkshead mono">Suggested links · click to add</div><div class="draftlinkrow">' +
    suggestions.map((s) => `<button class="draftlink" data-title="${esc(s.title)}"><span class="dl-add">+</span> ${esc(s.title)} <span class="dl-score mono">${Math.round(s.score * 100)}%</span></button>`).join("") +
    "</div>";
  wrap.querySelectorAll(".draftlink").forEach((b) => b.addEventListener("click", () => insertWikilink(b.dataset.title, b)));
}
function insertWikilink(title, btn) {
  const ta = $("#draftcontent"), wl = `[[${title}]]`;
  if (!ta.value.includes(wl)) {
    const v = ta.value.replace(/\s+$/, "");
    ta.value = v + (v.includes("## Related") ? `\n- ${wl}\n` : `\n\n## Related\n\n- ${wl}\n`);
    renderDraftPreview();
  }
  if (btn) { btn.disabled = true; btn.classList.add("added"); const a = btn.querySelector(".dl-add"); if (a) a.textContent = "✓"; }
}
async function createDraft() {
  if (!LIVE || !studioDraft) return;
  const title = $("#drafttitle").value.trim() || "Untitled";
  const content = $("#draftcontent").value;
  const target = $("#drafttarget").value, pd = ME.personal && ME.personal.domain;
  const src = studioDraft.source_url || undefined;
  const tags = draftTags();
  const btn = $("#draftcreate"); btn.disabled = true;
  try {
    await API.create({ domain: target, title, content, source_url: src, tags });
    if (target === pd) {
      PENDING_NOTES.unshift({ title, status: "saving" });
      renderPersonal(); renderIndexStatus();
    } else {
      idxExtraPending += 1; renderIndexStatus(); // commons/team add: reflect it in the pill
    }
    startLivePoll();
    const where = target === pd ? "your personal space" : target;
    studioSuccess(title, `Added to ${where}. Indexing now, searchable in a few minutes.`);
  } catch (e) {
    $("#draftresult").innerHTML = `<p class="addnote" style="margin:8px 0 0">${esc(e.message || String(e))}</p>`;
    btn.disabled = false;
  }
}
// Gracefully retire the editor: fade it back, reveal a success panel in the freed
// space that invites the user to add more while their content indexes.
function studioSuccess(title, msg) {
  studioDraft = null;
  const body = $("#draftbody");
  body.style.transition = "opacity .3s"; body.style.opacity = "0.12";
  $("#ds-title").textContent = `Added “${title}”`;
  $("#ds-msg").textContent = msg;
  const ds = $("#draftsuccess"); ds.hidden = false;
  requestAnimationFrame(() => ds.classList.add("show"));
}
function resetStudio() {
  const ds = $("#draftsuccess"); if (ds) { ds.classList.remove("show"); ds.hidden = true; }
  $("#draftbody").style.opacity = "1";
  $("#studiodraft").hidden = true;
  $("#draftcreate").disabled = false;
  splitItems = null; $("#splitview").hidden = true; $("#draftsingle").hidden = false; $("#draftdiscard").textContent = "Discard";
  $("#studiourl").value = ""; $("#studiotext").value = ""; studioFile = null; $("#studiofilename").textContent = "";
  $("#draftresult").innerHTML = ""; studioMsg("");
  if (studioSrc === "url") $("#studiourl").focus();
}
function discardDraft() {
  studioDraft = null; $("#studiodraft").hidden = true; $("#draftresult").innerHTML = "";
  const ds = $("#draftsuccess"); if (ds) { ds.classList.remove("show"); ds.hidden = true; }
  $("#draftbody").style.opacity = "1"; $("#draftcreate").disabled = false;
}
function draftTags() {
  return $("#drafttags").value.split(",").map((t) => t.trim()).filter(Boolean);
}
// Parse the draft's markdown into a preamble (before the first '##') plus '##' sections.
const _META_HEADINGS = new Set(["summary", "key terms", "related", "sections", "references"]);
function draftSections() {
  const parts = $("#draftcontent").value.split(/^(##\s+.*)$/m);
  const preamble = (parts[0] || "").trim();
  const sections = [];
  for (let i = 1; i < parts.length; i += 2) {
    sections.push({ heading: parts[i].replace(/^##\s+/, "").trim(), body: (parts[i + 1] || "").trim() });
  }
  return { preamble, sections };
}
function updateSplitVisibility() {
  const content = draftSections().sections.filter((s) => !_META_HEADINGS.has(s.heading.toLowerCase()));
  $("#draftsplit").hidden = content.length < 2;
}
// "Explain simply": rewrite the draft in plain language (on-demand model call).
async function simplifyDraft() {
  if (!LIVE) return;
  const btn = $("#draftsimplify"), label = btn.textContent;
  btn.disabled = true; btn.textContent = "Simplifying…";
  try {
    const r = await API.simplify($("#draftcontent").value);
    if (r.simplified) {
      $("#draftcontent").value = r.content; renderDraftPreview(); updateSplitVisibility();
      $("#draftresult").innerHTML = '<p class="addnote" style="margin:8px 0 0">Rewritten in plainer language.</p>';
    } else {
      $("#draftresult").innerHTML = '<p class="addnote" style="margin:8px 0 0">Could not simplify right now (the model was busy). Try again shortly.</p>';
    }
  } catch (e) {
    $("#draftresult").innerHTML = `<p class="addnote" style="margin:8px 0 0">${esc(e.message || String(e))}</p>`;
  } finally { btn.disabled = false; btn.textContent = label; }
}
// Split builds the notes as editable items (index + one per substantive section) but
// does NOT create them: the user reviews/edits each, then "Create all" writes them.
function buildSplitItems() {
  const { preamble, sections } = draftSections();
  const content = sections.filter((s) => !_META_HEADINGS.has(s.heading.toLowerCase()));
  const meta = sections.filter((s) => _META_HEADINGS.has(s.heading.toLowerCase()));
  const base = $("#drafttitle").value.trim() || "Untitled";
  let indexBody = preamble.replace(/^#\s+.*$/m, "").trim();
  for (const m of meta) indexBody += `\n\n## ${m.heading}\n\n${m.body}`;
  const items = [{ kind: "index", title: base, body: indexBody.trim() }];
  for (const s of content) items.push({ kind: "section", title: `${base}: ${s.heading}`, body: s.body });
  return items;
}
// Assemble one item into full markdown, deriving the cross-links from current titles so
// renaming a note keeps the index<->section links correct.
function assembleSplitItem(item) {
  if (item.kind === "index") {
    const links = splitItems.filter((x) => x.kind === "section").map((x) => `- [[${x.title}]]`).join("\n");
    return `# ${item.title}\n\n${item.body}\n\n## Sections\n\n${links}\n`;
  }
  const indexTitle = (splitItems.find((x) => x.kind === "index") || {}).title || "Index";
  return `# ${item.title}\n\n${item.body}\n\n## Related\n\n- [[${indexTitle}]]\n`;
}
function enterSplitMode() {
  const items = buildSplitItems();
  if (items.filter((x) => x.kind === "section").length < 2) return;
  splitItems = items;
  renderSplitItems();
  $("#draftsingle").hidden = true;
  $("#splitview").hidden = false;
  $("#draftcreate").textContent = `Create ${items.length} notes`;
  $("#draftdiscard").textContent = "Back to single draft";
}
function exitSplitMode() {
  splitItems = null;
  $("#splitview").hidden = true;
  $("#draftsingle").hidden = false;
  $("#draftdiscard").textContent = "Discard";
  updateCreateLabel();
}
function renderSplitItems() {
  const wrap = $("#splititems");
  $("#splitcount").textContent = splitItems.length;
  wrap.innerHTML = splitItems.map((item, i) => `
    <details class="splititem" ${i === 0 ? "open" : ""}>
      <summary><span class="splitkind ${item.kind}">${item.kind}</span><span class="splitname">${esc(item.title)}</span></summary>
      <div class="splitedit">
        <input class="spl-title mono" data-i="${i}" value="${esc(item.title)}" aria-label="Note title" />
        <div class="splitcols">
          <textarea class="spl-body mono" data-i="${i}" rows="8" spellcheck="false">${esc(item.body)}</textarea>
          <div class="draftpreview spl-preview" data-i="${i}"></div>
        </div>
      </div>
    </details>`).join("");
  wrap.querySelectorAll(".spl-title").forEach((el) => el.addEventListener("input", () => {
    splitItems[+el.dataset.i].title = el.value;
    const name = el.closest(".splititem").querySelector(".splitname"); if (name) name.textContent = el.value;
    refreshSplitPreviews(); // titles drive the cross-links, so refresh all previews
  }));
  wrap.querySelectorAll(".spl-body").forEach((el) => el.addEventListener("input", () => {
    splitItems[+el.dataset.i].body = el.value; refreshSplitPreview(+el.dataset.i);
  }));
  refreshSplitPreviews();
}
function refreshSplitPreview(i) {
  const el = $(`#splititems .spl-preview[data-i="${i}"]`);
  if (el) el.innerHTML = mdToHtml(assembleSplitItem(splitItems[i]));
}
function refreshSplitPreviews() { splitItems.forEach((_, i) => refreshSplitPreview(i)); }
async function createSplitAll() {
  if (!LIVE || !splitItems) return;
  const target = $("#drafttarget").value, pd = ME.personal && ME.personal.domain;
  const src = studioDraft ? studioDraft.source_url || undefined : undefined;
  const tags = draftTags();
  const btn = $("#draftcreate"); btn.disabled = true;
  try {
    for (const item of splitItems) {
      await API.create({ domain: target, title: item.title, content: assembleSplitItem(item), source_url: src, tags });
    }
    const all = splitItems.map((x) => x.title), n = splitItems.length;
    if (target === pd) {
      for (const t of all) PENDING_NOTES.unshift({ title: t, status: "saving" });
      renderPersonal(); renderIndexStatus();
    } else { idxExtraPending += n; renderIndexStatus(); }
    startLivePoll();
    splitItems = null; $("#splitview").hidden = true; $("#draftsingle").hidden = false;
    studioSuccess(all[0], `Created ${n} linked notes (an index plus ${n - 1} sections). Indexing now.`);
  } catch (e) {
    $("#draftresult").innerHTML = `<p class="addnote" style="margin:8px 0 0">${esc(e.message || String(e))}</p>`;
    btn.disabled = false;
  }
}
// The Create / Discard buttons are shared, so route them by mode.
function draftCreateClicked() { if (splitItems) createSplitAll(); else createDraft(); }
function draftDiscardClicked() { if (splitItems) exitSplitMode(); else discardDraft(); }
// Minimal, safe markdown -> HTML for the live draft preview (headings, lists, inline).
function mdToHtml(md) {
  const e = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const inline = (s) => e(s)
    .replace(/\[\[([^\]]+)\]\]/g, '<span class="wl">[[$1]]</span>')
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  const lines = (md || "").split("\n");
  let html = "", inList = false, para = [];
  const flushPara = () => { if (para.length) { html += "<p>" + inline(para.join(" ")) + "</p>"; para = []; } };
  const flushList = () => { if (inList) { html += "</ul>"; inList = false; } };
  for (const raw of lines) {
    const line = raw.replace(/\s+$/, "");
    const h = /^(#{1,6})\s+(.*)$/.exec(line), li = /^[-*]\s+(.*)$/.exec(line);
    if (h) { flushPara(); flushList(); const n = h[1].length; html += `<h${n}>${inline(h[2])}</h${n}>`; }
    else if (li) { flushPara(); if (!inList) { html += "<ul>"; inList = true; } html += `<li>${inline(li[1])}</li>`; }
    else if (!line.trim()) { flushPara(); flushList(); }
    else para.push(line);
  }
  flushPara(); flushList();
  return html;
}

function setPage(p) {
  $("#page-explore").hidden = p !== "explore";
  $("#page-connect").hidden = p !== "connect";
  $("#page-arch").hidden = p !== "arch";
  $("#page-agents").hidden = p !== "agents";
  const studio = $("#page-studio"); if (studio) studio.hidden = p !== "studio";
  if (p === "studio") renderStudio();
  const rev = $("#page-review"); if (rev) rev.hidden = p !== "review";
  if (p === "review") renderReview();
  for (const b of $("#pagetabs").querySelectorAll("button")) b.classList.toggle("on", b.dataset.page === p);
  for (const el of document.querySelectorAll(".exp-only")) el.style.display = p === "explore" ? "" : "none";
  // Agents animation: run only while its page is visible.
  agentsActive = p === "agents";
  if (agentsActive) {
    requestAnimationFrame(() => {
      agentsResize();
      if (!agentsRunning) { agentsRunning = true; agentsLoop(); }
    });
  }
  if (p === "connect") {
    flowActive = true;
    requestAnimationFrame(() => {
      flowResize(); if (!fparts.length) flowInit();
      if (!flowRunning) { flowRunning = true; flowLoop(); }
    });
  } else {
    flowActive = false;
    // The graph may have booted while its page was hidden (0 size): size + seed now.
    requestAnimationFrame(() => {
      resize();
      if (!graphSized && W > 0) { seed(); graphSized = true; }
      alpha = Math.max(alpha, 0.7);
    });
  }
}

// ---- Static event wiring (attached once, after data is ready) ---------------
function wireStatic() {
  // graph interaction
  canvas.addEventListener("mousemove", (ev) => {
    const p = pos(ev);
    if (drag) { drag.x = p.x; drag.y = p.y; alpha = Math.max(alpha, 0.4); return; }
    const n = nodeAt(p.x, p.y);
    hover = n;
    canvas.style.cursor = n ? "pointer" : "grab";
    if (n) {
      tip.classList.add("on");
      tip.querySelector(".tt").textContent = n.title;
      tip.querySelector(".td").textContent = short(n.id) + " · " + n.domain;
      tip.style.left = Math.min(p.x + 14, W - 240) + "px";
      tip.style.top = Math.max(p.y - 10, 4) + "px";
    } else tip.classList.remove("on");
  });
  canvas.addEventListener("mousedown", (ev) => {
    const p = pos(ev); const n = nodeAt(p.x, p.y);
    if (n) { drag = n; n.pinned = true; canvas.classList.add("grabbing"); }
  });
  window.addEventListener("mouseup", () => {
    if (drag) { drag.pinned = false; drag = null; canvas.classList.remove("grabbing"); }
  });
  canvas.addEventListener("click", (ev) => { const p = pos(ev); const n = nodeAt(p.x, p.y); if (n) openDocument(n.id); });
  canvas.addEventListener("mouseleave", () => { hover = null; tip.classList.remove("on"); });

  // search: type to filter (debounced in live mode); Enter for a grounded answer.
  const qEl = $("#query");
  qEl.addEventListener("input", () => { state.query = qEl.value; renderResults(); });
  qEl.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    state.query = qEl.value;
    if (LIVE) submitLiveSearch(); else renderResults();
  });

  // theme
  $("#theme").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme");
    const isDark = cur ? cur === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.setAttribute("data-theme", isDark ? "light" : "dark");
    renderScope(); renderBrowser(); renderLegend();
  });

  // modes
  $("#modeseg").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setMode(b.dataset.mode); });
  $("#docclose").addEventListener("click", () => { state.openDoc = null; renderDoc(); renderBrowser(); setMode("explore"); });

  // pages
  $("#pagetabs").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setPage(b.dataset.page); });

  // agents page: scenario switch + replay
  $("#agentseg").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setScenario(b.dataset.scenario); });
  $("#agentreplay").addEventListener("click", () => { aStep = 0; aT = 0; });

  // agents page: model/prompt registry, and click an agent box to open its entry
  renderAgentReg();
  agentCanvas.addEventListener("click", (e) => {
    const id = agentAt(e.clientX, e.clientY);
    if (!id) return;
    selectAgent(id);
    $("#agentreg").scrollIntoView({ behavior: "smooth", block: "nearest" });
  });
  agentCanvas.addEventListener("mousemove", (e) => {
    agentCanvas.style.cursor = agentAt(e.clientX, e.clientY) ? "pointer" : "default";
  });

  // modal
  mcpmodal.addEventListener("click", (e) => {
    if (e.target.matches("[data-close]") || e.target.classList.contains("modal-backdrop")) closeMcp();
  });
  document.querySelectorAll(".copybtn").forEach((b) => b.addEventListener("click", () => {
    const el = document.querySelector(b.dataset.copy); if (!el) return;
    const text = el.textContent;
    const done = () => { const o = b.textContent; b.textContent = "Copied ✓"; setTimeout(() => { b.textContent = o; }, 1400); };
    const fallback = () => {
      const ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); } catch (_) { /* best effort */ }
      ta.remove(); done();
    };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, fallback);
    else fallback();
  }));

  // global keys
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); $("#query").focus(); }
    else if (e.key === "Escape" && !mcpmodal.hidden) closeMcp();
    else if (e.key === "Escape" && state.mode === "read") setMode("explore");
  });

  window.addEventListener("resize", () => { resize(); alpha = Math.max(alpha, 0.5); if (flowActive) flowResize(); if (agentsActive) agentsResize(); });
}

boot();
