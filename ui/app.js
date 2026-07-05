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
  extractiveAnswer,
  graphData,
  principalsFromPolicy,
  rankChunks,
  reconstructDoc,
} from "./lib.js";

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
let DOMAIN_ORDER = [], domIdx = new Map(), byId = new Map(), PRINCIPALS = [];
const state = { principal: null, allowed: new Set(), openDoc: null, openDocNode: null, query: "", mode: "explore" };

// A sorted domain -> categorical colour slot (1..6), used for dots and nodes.
const domVar = (domain) => `--domain-${((domIdx.get(domain) || 0) % 6) + 1}`;

// ============================================================================
//  Boot
// ============================================================================
async function boot() {
  try {
    const [idx, pol, cfg] = await Promise.all([
      fetch("data/index.json").then((r) => r.json()),
      fetch("data/policy.json").then((r) => r.json()),
      fetch("data/config.json").then((r) => (r.ok ? r.json() : {})).catch(() => ({})),
    ]);
    index = idx; policy = pol; config = cfg;
  } catch (e) {
    document.querySelector(".app").innerHTML =
      `<div class="panel" style="margin:20px;padding:20px"><h2>No data</h2>
       <p style="color:var(--muted)">Run <code class="cmd">./brain ui</code> (or
       <code class="cmd">python scripts/export_ui_data.py</code>) to export the index, then serve this
       folder over http. (${esc(String(e))})</p></div>`;
    return;
  }

  DOMAIN_ORDER = [...policy.domains].sort();
  domIdx = new Map(DOMAIN_ORDER.map((d, i) => [d, i]));
  byId = new Map(index.documents.map((d) => [d.doc_id, d]));
  PRINCIPALS = principalsFromPolicy(policy).map((id) => ({ id, friendly: friendly(id) }));

  $("#hash").textContent = (index.content_hash || "").slice(0, 12);
  $("#doccount").textContent = index.documents.length;

  buildGraph();
  fillMcp();
  initPrincipals();
  wireStatic();

  resize();
  if (W > 0) { seed(); graphSized = true; }
  onScopeChange();
  renderConnections();
  loop();
  setPage("connect"); // Connections is the default page
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
    lab.appendChild(dot); lab.appendChild(document.createTextNode(dom)); g.appendChild(lab);
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
  const gd = graphData(index.documents, index.adjacency, new Set(policy.domains));
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
function loop() { step(); draw(); requestAnimationFrame(loop); }
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
  if (!d || !state.allowed.has(d.domain)) { state.openDoc = null; renderDoc(); return; }
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
  const box = $("#results"); const q = state.query.trim();
  if (!box) return;
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
  for (const { chunk } of hits) {
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

// ---- Page switching (Connections / Explore) ---------------------------------
let graphSized = false;
function setPage(p) {
  $("#page-explore").hidden = p !== "explore";
  $("#page-connect").hidden = p !== "connect";
  for (const b of $("#pagetabs").querySelectorAll("button")) b.classList.toggle("on", b.dataset.page === p);
  for (const el of document.querySelectorAll(".exp-only")) el.style.display = p === "explore" ? "" : "none";
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

  // search
  const qEl = $("#query");
  qEl.addEventListener("input", () => { state.query = qEl.value; renderResults(); });

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

  window.addEventListener("resize", () => { resize(); alpha = Math.max(alpha, 0.5); if (flowActive) flowResize(); });
}

boot();
