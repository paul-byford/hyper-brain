# Lineage and analysis: Karpathy's LLM wiki, gbrain, and what we take

This document is the analysis for: what the prior art set out
to solve, how each step improved on the one before and why, and exactly what we
keep, adapt, or discard for our own design and the reasons. It is the honest
record of our debt to prior work.

Sources are listed at the end.

---

## 1. Karpathy's "LLM wiki" (the second brain)

**What it set out to solve.** Personal knowledge is scattered across Notion,
Google Docs, bookmarks, screenshots and notes, in formats an LLM cannot reason
over coherently. Karpathy's insight was that if you keep everything as plain
markdown in a folder and point a capable coding agent at it, the agent can read
what is relevant and answer grounded in your own material rather than the general
internet.

**The shape.** A three-layer folder:

- `raw/`: source material dropped in as-is (papers converted to markdown, cloned
  repos, clipped web articles, meeting notes, screenshots).
- `wiki/`: the LLM's output. It reads the raw material, writes encyclopedia-style
  articles for each concept it identifies, creates backlinks between related
  articles, and maintains an `index` file summarising the whole wiki.
- The agent (Claude Code or similar) does the indexing and updating; you ask it
  questions and it reads the files to answer.

**Why it is good.** It is just a folder of markdown, so you inherit git version
history, portability, no vendor lock-in, no proprietary database, and beautiful
graph visualisation in Obsidian. The LLM, not a rigid pipeline, does the
structuring, so the knowledge organises itself into linked articles.

**Its limits (the openings the next step exploits).**

- **Retrieval is "agent greps files".** There is no embedding index. Relevance
  depends on the agent reading and searching the tree, which degrades as the
  corpus grows past what fits comfortably in context or in a few tool calls.
- **Single user, no access control.** A folder on your machine has no notion of
  "this caller may see these topics and not those". There is no isolation
  boundary to enforce.
- **It stores what you put in.** The wiki reflects the raw material; it does not
  actively reconcile contradictions, score salience, or maintain its own evolving
  model of the domain.
- **No first-class synthesis product.** You get an agent that can answer, but
  "return the answer with citations and an honest account of what is missing" is
  not a built-in capability, it is whatever the agent improvises.

Karpathy's pattern is the right *foundation*: markdown, git, links, LLM-authored
structure. Its ceiling is retrieval quality at scale and the absence of
multi-user boundaries.

---

## 2. gbrain (Garry Tan)

gbrain, open-sourced April 2026, takes Karpathy's foundation and productises the
two things the foundation lacks: **retrieval quality** and **multi-user
structure**, plus a synthesis layer. Its own framing: "Search gives you raw
pages. GBrain gives you the answer," and "Karpathy's system stored what you put
in; GBrain builds its own understanding of what you put in."

**How it improves on the wiki, and why each matters.**

1. **Hybrid retrieval instead of grep.** gbrain keeps the git-backed markdown but
   syncs it into a database (PGLite locally, Postgres plus pgvector for shared
   deployments) and retrieves with three fused signals:
   - vector search (HNSW over pgvector, pluggable embedding providers),
   - keyword BM25,
   - a typed knowledge graph with zero-LLM-cost auto-linking on every write,
   combined by reciprocal-rank fusion and a reranker. Their published benchmark
   claims the graph signal alone adds +31.4 points of P@5. *Why it matters:* this
   is the direct fix for the wiki's weakest point. Semantic plus keyword plus
   graph beats "the agent searches the folder", and it holds up as the corpus
   grows.

2. **Synthesis, not just retrieval (search vs think).** `gbrain search` returns
   ranked pages; `gbrain think` reads them and writes a synthesised answer with
   citations and an explicit gap analysis of what the brain does not know. *Why
   it matters:* it turns retrieval into an answer, and the honest "here is what I
   could not find" is exactly what an agent needs to decide whether to act.

3. **It builds its own understanding.** Schema packs (canonical types like
   person, company, deal) and a typed entity graph mean gbrain structures
   incoming material into an evolving model, and a "dream cycle" runs autonomous
   enrichment (dedup, contradiction finding, salience scoring) on a schedule.
   *Why it matters:* this is the "stores what you put in" versus "builds
   understanding" distinction; the brain gets better between writes, not only at
   write time.

4. **Company brain: multi-user with scoped access.** gbrain adds a federated,
   OAuth-scoped institutional memory for teams of 10 to 50, with access tiers and
   a claim of zero data leaks across them, exposed over MCP (stdio for local
   clients, HTTP with OAuth 2.1, scopes and rate limiting for remote). *Why it
   matters:* this is the multi-user boundary the single-user wiki never had, and
   it is the part closest to our own brief.

**gbrain's cost, from our brief's point of view.** gbrain is powerful but its
operational substrate is heavy for our two audiences: it wants a running Postgres
with pgvector for anything shared, it ships its own OAuth 2.1 server with dynamic
client registration, it leans on external managed hosting recipes (Railway,
Supabase, Fly, ngrok) and multiple third-party embedding and rerank providers,
and it runs background job queues (BullMQ "minions") and a 24/7 dream cycle. Each
of those is either an always-on cost, a third-party processor outside the
tenancy, or a piece of hand-rolled-adjacent auth. Every one collides with at
least one of our constraints: near-zero idle cost, no external SaaS database, the
sensitive-data boundary, and no bespoke security.

So gbrain is the right teacher for *retrieval and multi-user structure*, and the
wrong template for *operations* in a cost- and security-controlled setting. That
split is what shapes what we take.

---

## 3. What we keep, adapt, and discard, and why

Our design sits downstream of both. High grade data
boundary, near-zero idle cost, no external SaaS, no hand-rolled security,
one-command provisioning decide where we follow gbrain and where we part from
it.

### Keep from Karpathy's wiki

- **Markdown as the single source of truth, under git.** Knowledge is a
  reviewable, versioned asset. This is non-negotiable and both predecessors agree.
- **The wiki link graph.** `[[wikilinks]]` between documents are first-class and
  drive both retrieval (neighbour expansion) and the UI (graph visualisation).
- **LLM-assisted authoring.** The corpus can be grown by an agent writing
  markdown, then reviewed as a pull request.

### Adapt from gbrain (with attribution, see below)

- **Hybrid retrieval.** We adopt gbrain's vector plus BM25 plus link-graph blend
  with reciprocal-rank fusion. We implement it over an in-memory index loaded
  from object storage rather than a running Postgres, which is the key operational
  change (see discard).
- **The search versus think split.** We expose both: `search_brain` returns
  ranked, cited chunks; `answer` (think) returns a synthesised answer with
  citations and an explicit gap statement. This is the most valuable idea we take,
  and it maps naturally onto our ADK agent (which performs the synthesis using an
  in-tenancy Gemini model on Vertex).
- **Frontmatter metadata and a contract-first engine interface.** A `BrainEngine`
  style interface (index, search, answer, get_document, list_domains) keeps the
  retrieval core swappable, exactly as gbrain's contract-first engine does.
- **Company-brain multi-tenancy with scoped access.** We keep the goal of one
  brain, several domains, per-caller isolation. We change *how* it is enforced
  (see discard).

### Discard or replace, and why

- **Running Postgres plus pgvector, replaced by an object-store index with
  in-memory brute-force search.** gbrain's database is an always-on cost and, for
  the shared case, an external managed dependency. At small-team corpus sizes a
  file of vectors in the user's own bucket, scanned in memory by a scale-to-zero
  container, gives the same retrieval with near-zero idle cost and no external
  database. When the corpus outgrows brute force we add an ANN index in the same
  artefact; this does not bring back a running server.
- **gbrain's OAuth 2.1 server with dynamic client registration, replaced by
  platform IAM plus OIDC.** The brief forbids hand-rolled security and prefers
  primitives a reviewer already trusts. We use Cloud Run IAM at the edge and
  verified Google-signed OIDC tokens in the app, with domain ACLs. We write no
  auth server.
- **Third-party embedding and rerank providers, replaced by first-party
  in-tenancy Vertex AI.** gbrain's pluggability sends content to whichever
  provider you configure; several are third parties outside the tenancy. Our data
  boundary requires the embedding (and synthesis) model to be first-party and
  in-region. We keep the *provider interface* gbrain-style so a self-hosted model
  can drop in, but the default is Vertex.
- **Dream cycle, minions and BullMQ, deferred.** Autonomous enrichment is
  valuable but needs an always-on queue and scheduled LLM spend, which fights
  near-zero idle cost. We note it as an optional future Cloud Run Job, not part of
  the core.
- **Bun and TypeScript runtime, replaced by Python.** This is a stack choice, not
  a criticism; Python gives us the mature Vertex AI and Google ADK SDKs that our
  agent and UI story depends on.

### Ingestion: how new knowledge enters (the clearest inheritance from both)

Getting data *in* is where the two predecessors differ most sharply, and our
answer takes the best of each.

- **Keep from Karpathy: the raw-to-wiki transform.** His pattern is a `raw/`
  drop where source material lands, and an LLM that rewrites it into clean,
  linked markdown articles. We keep this exactly: a staging area, an optional
  in-tenancy Gemini curation step, and provenance-stamped markdown as the output.
  It is the most engaging "add data" moment and it preserves git as the record.
- **Adapt from gbrain: multi-source, contract-first ingestion.** gbrain pulls
  from many sources (email, calendar, tweets), routes them by per-source config,
  and auto-links on write. We adapt this into a source-agnostic pipeline with a
  `SourceAdapter` contract and a registry keyed by `type`, so the bank extends to
  Confluence, Jira or SharePoint by writing one adapter, not touching the core.
- **Discard from gbrain: un-reviewed continuous mutation.** gbrain's headline is
  that it "runs while you sleep" and rewrites its own pages. That is the wrong
  default for a bank: knowledge that mutates outside review cannot be audited. We
  replace it with a **review gate**, every addition, whether batch or from an
  agent's `propose_document` tool, lands as a reviewable, revertible change (a PR
  in the controlled profile). Continuous auto-sync remains available as an
  explicit opt-in, never the default.
- **Our addition: agent-authored knowledge, safely.** Neither predecessor exposes
  a gated write tool over MCP. We do (`propose_document`), so an agent can
  contribute what it learns in conversation, but as a quarantined proposal, with
  write scope separate from read scope and the domain validated at land time.

### Attribution

gbrain is MIT licensed. Where we adapt its retrieval approach (the hybrid fusion
and the search versus think split) we credit it in the code and docs. We adapt
patterns rather than lift its TypeScript wholesale, because our runtime (Python,
object-store index, Vertex, ADK) is deliberately different; a direct port would
carry the operational substrate we set out to replace.

---

## 4. The one-line summary of the lineage

Karpathy proved markdown plus git plus an LLM is a knowledge base. gbrain proved
that base needs real hybrid retrieval and a synthesis layer to be useful at scale
and across a team. We take both lessons and re-seat them on a scale-to-zero,
in-tenancy, IAM-secured substrate so the same artefact is a free personal demo
and a defensible bank-shaped design; we feed it through an adapter-based,
review-gated ingestion pipeline so new knowledge enters in interesting ways
without escaping review; and we put a Google ADK agent and a graph UI in front of
it so the demo is something you can watch work.

---

## Sources

- gbrain repository, Garry Tan: <https://github.com/garrytan/gbrain>
- "Karpathy's Instructions for Building an AI-Driven Second Brain", Techstrong.ai:
  <https://techstrong.ai/features/karpathys-instructions-for-building-an-ai-driven-second-brain/>
- "What Is Andrej Karpathy's LLM Wiki?", MindStudio:
  <https://www.mindstudio.ai/blog/andrej-karpathy-llm-wiki-knowledge-base-claude-code>
- "Garry Tan Open-Sources GBrain", Proudfrog:
  <https://proudfrog.com/en/news/2026-04-16-garry-tan-open-sources-gbrain-personal-knowledge>
- GBrain review, Vectorize: <https://vectorize.io/articles/gbrain-review>
- Google Agent Development Kit: <https://adk.dev/>
- ADK MCP tools (MCPToolset, Streamable HTTP): <https://adk.dev/tools-custom/mcp-tools/>
