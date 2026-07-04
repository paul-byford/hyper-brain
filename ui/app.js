// Brain Explorer UI wiring. Loads the exported index + policy, then renders the
// identity/isolation panel, the domain browser, the wikilink graph and the
// search/answer panel. All trust lives in the server; this only renders data.
import {
  allowedDomains,
  extractiveAnswer,
  graphData,
  principalsFromPolicy,
  rankChunks,
  reconstructDoc,
} from "./lib.js";

const state = { index: null, policy: null, domains: [], allowed: new Set(), principal: null };

const $ = (sel) => document.querySelector(sel);

function friendly(principal) {
  return principal.replace(/^group:/, "").replace(/@.*$/, "");
}

// Fixed-order categorical assignment: sorted domain -> slot class (never cycled).
function domainClass(domain) {
  const i = state.domains.indexOf(domain);
  return `d${i % 8}`;
}
function domainVar(domain) {
  return `var(--domain-${(state.domains.indexOf(domain) % 8) + 1})`;
}
function dot(domain) {
  const s = document.createElement("span");
  s.className = "dot";
  s.style.background = domainVar(domain);
  return s;
}

async function boot() {
  try {
    const [index, policy] = await Promise.all([
      fetch("data/index.json").then((r) => r.json()),
      fetch("data/policy.json").then((r) => r.json()),
    ]);
    state.index = index;
    state.policy = policy;
    state.domains = [...policy.domains].sort();
    $("#hash").textContent = `index ${index.content_hash.slice(0, 12)} · ${index.documents.length} docs`;
    initPrincipals();
    onIdentityChange();
  } catch (e) {
    document.querySelector("main").innerHTML =
      `<section class="panel"><h2>No data</h2><p class="muted">Run <code class="cmd">./brain ui</code>
       (or <code class="cmd">python scripts/export_ui_data.py</code>) to export the index, then serve this
       folder over http. (${e})</p></section>`;
  }
}

function initPrincipals() {
  const sel = $("#principal");
  sel.innerHTML = "";
  for (const p of principalsFromPolicy(state.policy)) {
    const opt = document.createElement("option");
    opt.value = p;
    opt.textContent = friendly(p);
    sel.appendChild(opt);
  }
  sel.addEventListener("change", () => onIdentityChange());
  // Default to the broadest grant so the full graph shows first.
  const broadest = principalsFromPolicy(state.policy)
    .map((p) => ({ p, n: allowedDomains(state.policy, [p]).size }))
    .sort((a, b) => b.n - a.n)[0];
  if (broadest) sel.value = broadest.p;
}

function onIdentityChange() {
  state.principal = $("#principal").value;
  state.allowed = allowedDomains(state.policy, [state.principal]);
  renderAllowed();
  renderBrowser();
  renderGraph();
  renderResults(); // re-run any active search under the new scope
}

function renderAllowed() {
  const box = $("#allowed-domains");
  box.innerHTML = "";
  if (state.allowed.size === 0) {
    box.innerHTML = '<span class="muted">no permitted domains</span>';
    return;
  }
  for (const d of [...state.allowed].sort()) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.appendChild(dot(d));
    chip.appendChild(document.createTextNode(d));
    box.appendChild(chip);
  }
}

function renderBrowser() {
  const el = $("#browser");
  el.innerHTML = "";
  const docs = state.index.documents.filter((d) => state.allowed.has(d.domain));
  for (const domain of state.domains) {
    if (!state.allowed.has(domain)) continue;
    const group = document.createElement("div");
    group.className = "domain-group";
    const label = document.createElement("div");
    label.className = "label";
    label.appendChild(dot(domain));
    label.appendChild(document.createTextNode(domain));
    group.appendChild(label);
    const ul = document.createElement("ul");
    ul.className = "doc-list";
    for (const d of docs.filter((x) => x.domain === domain).sort((a, b) => a.title.localeCompare(b.title))) {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.appendChild(dot(domain));
      btn.appendChild(document.createTextNode(d.title));
      btn.addEventListener("click", () => openDoc(d.doc_id));
      li.appendChild(btn);
      ul.appendChild(li);
    }
    group.appendChild(ul);
    el.appendChild(group);
  }
  if (!el.children.length) el.innerHTML = '<p class="muted">nothing visible to this identity</p>';
}

// --- Graph (a small force layout rendered to SVG) ----------------------------

function renderGraph() {
  const svg = $("#graph");
  const W = svg.clientWidth || 640;
  const H = 440;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = "";

  const { nodes, links } = graphData(state.index.documents, state.index.adjacency, state.allowed);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  nodes.forEach((n, i) => {
    const a = (i / Math.max(nodes.length, 1)) * Math.PI * 2;
    n.x = W / 2 + Math.cos(a) * Math.min(W, H) * 0.28;
    n.y = H / 2 + Math.sin(a) * H * 0.32;
  });

  // Simple simulation: repulsion between all nodes, springs on links, centre pull.
  for (let iter = 0; iter < 320; iter++) {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        let d2 = dx * dx + dy * dy || 0.01;
        const f = 2600 / d2;
        const d = Math.sqrt(d2);
        dx /= d; dy /= d;
        a.x += dx * f; a.y += dy * f; b.x -= dx * f; b.y -= dy * f;
      }
    }
    for (const l of links) {
      const a = byId.get(l.source), b = byId.get(l.target);
      let dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const f = (d - 90) * 0.02;
      dx /= d; dy /= d;
      a.x += dx * f; a.y += dy * f; b.x -= dx * f; b.y -= dy * f;
    }
    for (const n of nodes) { n.x += (W / 2 - n.x) * 0.008; n.y += (H / 2 - n.y) * 0.008; }
  }
  for (const n of nodes) {
    n.x = Math.max(24, Math.min(W - 24, n.x));
    n.y = Math.max(20, Math.min(H - 20, n.y));
  }

  const NS = "http://www.w3.org/2000/svg";
  for (const l of links) {
    const a = byId.get(l.source), b = byId.get(l.target);
    const line = document.createElementNS(NS, "line");
    line.setAttribute("x1", a.x); line.setAttribute("y1", a.y);
    line.setAttribute("x2", b.x); line.setAttribute("y2", b.y);
    svg.appendChild(line);
  }
  for (const n of nodes) {
    const c = document.createElementNS(NS, "circle");
    c.setAttribute("cx", n.x); c.setAttribute("cy", n.y); c.setAttribute("r", 8);
    c.setAttribute("class", domainClass(n.domain));
    const title = document.createElementNS(NS, "title");
    title.textContent = `${n.title} · ${n.domain}`;
    c.appendChild(title);
    c.addEventListener("click", () => openDoc(n.id));
    svg.appendChild(c);
    const t = document.createElementNS(NS, "text");
    t.setAttribute("x", n.x + 11); t.setAttribute("y", n.y + 3);
    t.textContent = n.title.length > 22 ? n.title.slice(0, 21) + "…" : n.title;
    svg.appendChild(t);
  }
  if (!nodes.length) {
    const t = document.createElementNS(NS, "text");
    t.setAttribute("x", W / 2 - 90); t.setAttribute("y", H / 2);
    t.textContent = "no documents visible to this identity";
    svg.appendChild(t);
  }
  renderLegend();
}

function renderLegend() {
  const el = $("#legend");
  el.innerHTML = "";
  for (const d of state.domains) {
    if (!state.allowed.has(d)) continue;
    const item = document.createElement("span");
    item.className = "chip";
    item.appendChild(dot(d));
    item.appendChild(document.createTextNode(d));
    el.appendChild(item);
  }
}

// --- Document viewer ----------------------------------------------------------

function esc(s) { return s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }
function normalise(s) { return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""); }

function resolveWikilink(domain, raw) {
  const target = normalise(raw.split("|")[0]);
  const hit = state.index.documents.find(
    (d) => d.domain === domain &&
      (normalise(d.title) === target || normalise(d.doc_id.split("/").pop()) === target),
  );
  return hit ? hit.doc_id : null;
}

function renderInline(domain, text) {
  return esc(text).replace(/\[\[([^\]]+)\]\]/g, (_m, raw) => {
    const id = resolveWikilink(domain, raw);
    const label = esc(raw.split("|").pop().trim());
    return id ? `<a class="wikilink" data-doc="${id}">${label}</a>` : label;
  });
}

function openDoc(docId) {
  const doc = state.index.documents.find((d) => d.doc_id === docId);
  const panel = $("#doc");
  if (!doc || !state.allowed.has(doc.domain)) {
    // Same response as truly missing: never confirm cross-domain existence.
    panel.innerHTML = '<h2>Document</h2><p class="muted">Not found in your permitted domains.</p>';
    return;
  }
  const md = reconstructDoc(state.index.chunks, docId, doc.title);
  const blocks = md.split("\n\n").map((b) => {
    if (b.startsWith("## ")) return `<h4>${esc(b.slice(3))}</h4>`;
    if (b.startsWith("# ")) return `<h3>${esc(b.slice(2))}</h3>`;
    return `<p>${renderInline(doc.domain, b)}</p>`;
  });

  const tags = doc.tags.length ? `<div class="chips">${doc.tags.map((t) => `<span class="chip">#${esc(t)}</span>`).join("")}</div>` : "";
  let prov = `<div class="provenance"><span class="dot" style="background:${domainVar(doc.domain)}"></span> ${esc(doc.domain)}`;
  if (doc.source) prov += ` · source: ${esc(doc.source)}`;
  if (doc.fetched_at) prov += ` · fetched ${esc(doc.fetched_at)}`;
  if (doc.source_url) prov += ` · <a class="wikilink" href="${esc(doc.source_url)}" target="_blank" rel="noreferrer">origin</a>`;
  prov += "</div>";

  panel.innerHTML = `<h2>Document</h2><article><h3>${esc(doc.title)}</h3>${tags}${blocks.slice(1).join("")}${prov}</article>`;
  panel.querySelectorAll("a.wikilink[data-doc]").forEach((a) =>
    a.addEventListener("click", () => openDoc(a.getAttribute("data-doc"))),
  );
}

// --- Search / answer ----------------------------------------------------------

function renderResults() {
  const q = $("#query").value.trim();
  const box = $("#results");
  if (!q) { box.innerHTML = ""; return; }
  const hits = rankChunks(state.index.chunks, q, state.allowed, 8);
  const ans = extractiveAnswer(q, hits);

  let html = `<div class="answer"><div>${esc(ans.text)}</div>`;
  if (ans.gaps.length) html += `<div class="gaps">Gaps (not supported by retrieved context): ${ans.gaps.map(esc).join(", ")}</div>`;
  html += "</div>";
  for (const { chunk } of hits) {
    html += `<div class="hit"><div class="meta"><span class="dot" style="background:${domainVar(chunk.domain)}"></span>${esc(chunk.domain)} · ${esc(chunk.heading || "—")}</div>
      <div class="title"><a class="wikilink" data-doc="${chunk.doc_id}">${esc(chunk.title)}</a></div>
      <div class="snippet">${esc(chunk.text.slice(0, 180))}${chunk.text.length > 180 ? "…" : ""}</div></div>`;
  }
  box.innerHTML = html;
  box.querySelectorAll("a.wikilink[data-doc]").forEach((a) =>
    a.addEventListener("click", () => openDoc(a.getAttribute("data-doc"))),
  );
}

$("#search-btn").addEventListener("click", renderResults);
$("#query").addEventListener("keydown", (e) => { if (e.key === "Enter") renderResults(); });

boot();
