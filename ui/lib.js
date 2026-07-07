// Pure Brain Explorer logic: no DOM, so it runs in the browser and under node for
// tests. It mirrors the server's behaviour (the same domain filter, the same
// search/answer shape) but over the exported index; the UI enforces nothing, it
// only renders what a caller in a given identity would be allowed to see.

export const WILDCARD = "*";

const STOP = new Set([
  "the", "and", "for", "with", "that", "this", "how", "what", "are", "our", "you",
  "your", "can", "does", "into", "from", "not", "but", "his", "her", "she", "him",
]);

const TOKEN = /[a-z0-9]+/g;

export function tokenize(text) {
  return (String(text).toLowerCase().match(TOKEN) || []);
}

// The domains a set of principals may retrieve from (mirrors config.Policy).
export function allowedDomains(policy, principals) {
  const declared = new Set(policy.domains);
  const pset = new Set(principals);
  const allowed = new Set();
  for (const grant of policy.grants) {
    if (grant.principal === WILDCARD || pset.has(grant.principal)) {
      for (const d of grant.domains) if (declared.has(d)) allowed.add(d);
    }
  }
  return allowed;
}

// Keyword ranking, scoped to the allowed domains (the isolation boundary).
export function rankChunks(chunks, query, allowed, topK = 8) {
  const qTerms = new Set(tokenize(query));
  if (qTerms.size === 0) return [];
  const scored = [];
  for (const c of chunks) {
    if (!allowed.has(c.domain)) continue;
    const toks = tokenize(`${c.text} ${c.heading} ${c.title}`);
    if (toks.length === 0) continue;
    let hits = 0;
    for (const t of toks) if (qTerms.has(t)) hits++;
    if (hits === 0) continue;
    scored.push({ chunk: c, score: hits / Math.sqrt(toks.length) });
  }
  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, topK);
}

function firstSentence(text) {
  const m = String(text).match(/[^.!?]*[.!?]/);
  return (m ? m[0] : String(text)).trim();
}

// Query terms not supported by any retrieved chunk: the honest gap statement.
export function missingTerms(query, hits) {
  const present = new Set();
  for (const h of hits) for (const t of tokenize(h.chunk.text)) present.add(t);
  const gaps = [];
  for (const t of tokenize(query)) {
    if (t.length > 2 && !STOP.has(t) && !present.has(t)) gaps.push(t);
  }
  return [...new Set(gaps)];
}

export function extractiveAnswer(query, hits) {
  if (hits.length === 0) {
    return { text: "No results in your permitted domains.", gaps: [], citations: [] };
  }
  const top = hits.slice(0, 3);
  return {
    text: top.map((h) => firstSentence(h.chunk.text)).join(" "),
    gaps: missingTerms(query, hits),
    citations: top.map((h) => h.chunk),
  };
}

// Rebuild a document's text from its chunks (the server does the same).
export function reconstructDoc(chunks, docId, title) {
  const parts = [`# ${title}`];
  let lastHeading = null;
  const own = chunks.filter((c) => c.doc_id === docId).sort((a, b) => a.order - b.order);
  for (const c of own) {
    if (c.heading && c.heading !== lastHeading) {
      parts.push(`## ${c.heading}`);
      lastHeading = c.heading;
    }
    parts.push(c.text);
  }
  return parts.join("\n\n");
}

// The intra-domain wikilink graph, filtered to the caller's visible domains, so a
// caller only ever sees the sub-graph they may read.
export function graphData(documents, adjacency, allowed) {
  const nodes = documents
    .filter((d) => allowed.has(d.domain))
    .map((d) => ({ id: d.doc_id, domain: d.domain, title: d.title }));
  const ids = new Set(nodes.map((n) => n.id));
  const links = [];
  const seen = new Set();
  for (const [src, neighbours] of Object.entries(adjacency || {})) {
    if (!ids.has(src)) continue;
    for (const dst of neighbours) {
      if (!ids.has(dst)) continue;
      const key = src < dst ? `${src}|${dst}` : `${dst}|${src}`;
      if (seen.has(key)) continue;
      seen.add(key);
      links.push({ source: src, target: dst });
    }
  }
  return { nodes, links };
}

// Distinct principals a demo user can act as, derived from the policy grants. The
// wildcard is the commons grant, not a person, so it is never a selectable identity.
export function principalsFromPolicy(policy) {
  const seen = [];
  for (const g of policy.grants) {
    if (g.principal !== WILDCARD && !seen.includes(g.principal)) seen.push(g.principal);
  }
  return seen;
}

// Classify a declared domain for display: "commons" if any wildcard grant reaches
// it (shared with everyone), otherwise "team". Personal and shared domains are not
// declared in the policy; the UI tags those from the caller's own context.
export function domainKind(policy, domain) {
  for (const g of policy.grants) {
    if (g.principal === WILDCARD && g.domains.includes(domain)) return "commons";
  }
  return "team";
}
