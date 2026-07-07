// Logic tests for the Brain Explorer, run under node (no browser). They assert the
// UI's isolation and search behaviour against the real exported data.
//   node ui/test/lib.test.mjs
import assert from "node:assert";
import { readFileSync } from "node:fs";

import {
  allowedDomains,
  extractiveAnswer,
  graphData,
  principalsFromPolicy,
  rankChunks,
  reconstructDoc,
} from "../lib.js";

const here = (p) => new URL(p, import.meta.url);
const index = JSON.parse(readFileSync(here("../data/index.json")));
const policy = JSON.parse(readFileSync(here("../data/policy.json")));

const FINSERV = "finserv-ai-engineering";
const RECRUIT = "enterprise-ai-recruitment";
const COMMONS = "commons";
const FIN = ["group:finserv-eng@example.com"];
const REC = ["group:recruiting@example.com"];
const ADMIN = ["group:brain-admins@example.com"];

// --- identity / isolation ---
// Every caller also sees the commons domain (wildcard grant), never the other team's.
const finDomains = allowedDomains(policy, FIN);
assert.ok(finDomains.has(FINSERV) && finDomains.has(COMMONS) && !finDomains.has(RECRUIT));
const recDomains = allowedDomains(policy, REC);
assert.ok(recDomains.has(RECRUIT) && recDomains.has(COMMONS) && !recDomains.has(FINSERV));
assert.strictEqual(allowedDomains(policy, ADMIN).size, 3); // commons + both teams
assert.strictEqual(principalsFromPolicy(policy).length, 3); // the wildcard is not a principal

// --- search is scoped: never crosses the domain boundary ---
const finAllowed = allowedDomains(policy, FIN);
const inDomain = rankChunks(index.chunks, "real-time fraud detection streaming", finAllowed, 8);
assert.ok(inDomain.length > 0, "expected in-domain hits");
assert.ok(inDomain.every((h) => h.chunk.domain !== RECRUIT), "search must never surface the other team");

const crossQuery = rankChunks(index.chunks, "candidate sourcing interview copilots recruiting", finAllowed, 8);
assert.ok(crossQuery.every((h) => h.chunk.domain !== RECRUIT), "finserv caller must never see recruitment");

// --- graph is filtered to the caller's sub-graph ---
const gFin = graphData(index.documents, index.adjacency, finAllowed);
assert.ok(gFin.nodes.length > 0 && gFin.links.length > 0, "expected a finserv sub-graph");
assert.ok(gFin.nodes.every((n) => n.domain !== RECRUIT), "graph leaked across domain");

const gRec = graphData(index.documents, index.adjacency, allowedDomains(policy, REC));
assert.ok(gRec.nodes.every((n) => n.domain !== FINSERV), "recruiter graph leaked across domain");

const gAdmin = graphData(index.documents, index.adjacency, allowedDomains(policy, ADMIN));
assert.strictEqual(new Set(gAdmin.nodes.map((n) => n.domain)).size, 3, "admin sees every domain");

// --- answer + honest gaps ---
const ans = extractiveAnswer("real-time fraud detection", inDomain);
assert.ok(ans.text.length > 0 && Array.isArray(ans.gaps) && Array.isArray(ans.citations));

// --- document reconstruction ---
const doc = index.documents.find((d) => d.domain === FINSERV);
const text = reconstructDoc(index.chunks, doc.doc_id, doc.title);
assert.ok(text.startsWith(`# ${doc.title}`), "reconstruction starts with the title");

// --- provenance is present on the ingested document (for the viewer) ---
assert.ok(index.documents.some((d) => d.source), "expected at least one document with provenance");

console.log("ui lib tests: all passed");
