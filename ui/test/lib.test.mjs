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
const FIN = ["group:finserv-eng@example.com"];
const REC = ["group:recruiting@example.com"];
const ADMIN = ["group:brain-admins@example.com"];

// --- identity / isolation ---
assert.deepStrictEqual([...allowedDomains(policy, FIN)], [FINSERV]);
assert.deepStrictEqual([...allowedDomains(policy, REC)], [RECRUIT]);
assert.strictEqual(allowedDomains(policy, ADMIN).size, 2);
assert.strictEqual(principalsFromPolicy(policy).length, 3);

// --- search is scoped: never crosses the domain boundary ---
const finAllowed = allowedDomains(policy, FIN);
const inDomain = rankChunks(index.chunks, "real-time fraud detection streaming", finAllowed, 8);
assert.ok(inDomain.length > 0, "expected in-domain hits");
assert.ok(inDomain.every((h) => h.chunk.domain === FINSERV), "search returned an in-domain result set");

const crossQuery = rankChunks(index.chunks, "candidate sourcing interview copilots recruiting", finAllowed, 8);
assert.ok(crossQuery.every((h) => h.chunk.domain === FINSERV), "finserv caller must never see recruitment");

// --- graph is filtered to the caller's sub-graph ---
const gFin = graphData(index.documents, index.adjacency, finAllowed);
assert.ok(gFin.nodes.length > 0 && gFin.links.length > 0, "expected a finserv sub-graph");
assert.ok(gFin.nodes.every((n) => n.domain === FINSERV), "graph leaked across domain");

const gRec = graphData(index.documents, index.adjacency, allowedDomains(policy, REC));
assert.ok(gRec.nodes.every((n) => n.domain === RECRUIT), "recruiter graph leaked across domain");

const gAdmin = graphData(index.documents, index.adjacency, allowedDomains(policy, ADMIN));
assert.strictEqual(new Set(gAdmin.nodes.map((n) => n.domain)).size, 2, "admin sees both domains");

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
