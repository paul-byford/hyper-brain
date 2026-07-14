# Architecture: a one-command company brain

This document is the design rationale for hyper-brain.For the intellectual lineage (Karpathy's LLM wiki, Garry Tan's gbrain, and what we keep, adapt or discard from each), see `docs/LINEAGE.md`.

---

## 1. Summary in one paragraph

The brain is a **stateless, scale-to-zero container** (Google Cloud Run) that
serves an **MCP endpoint**. Knowledge is plain markdown held **in the repository
under git**. A build step chunks it, computes embeddings with a **first-party
in-tenancy model** (Vertex AI), and writes a per-domain **index artefact to
object storage** (GCS). Retrieval is a **hybrid of semantic, keyword and
link-graph signals** and comes in two modes borrowed from gbrain: `search`
(ranked, cited chunks) and `answer` (a synthesised reply with citations and an
honest gap statement). There is no database running when nobody is querying, so
idle cost is a few pennies of storage. Callers are identified by **OIDC and
authorised by IAM plus an in-app domain ACL**. In front of the brain we ship a
**Google ADK agent** (Gemini on Vertex) that consumes the MCP endpoint, and a
**graph-based web UI** so the demo can be watched working. The single command is a
thin, idempotent wrapper over **Terraform** plus a build and seed step. The same
artefact serves a personal demo and a bank evaluation because the only things
that change between them are a **profile of configuration** (identity source,
project context, policy source), never the code.

---

## 2. Components

```
   sources (files, web, git, Confluence, ...)   agents (via MCP propose_document)
                         |  SourceAdapter.fetch                     |
                         v                                          v
        parse + optional in-tenancy curate (Gemini)        review gate (branch / PR)
                         \__________________  ____________________/
                                            v
        corpus (markdown + [[wikilinks]] + provenance, under git)
                         |  brain index  (Cloud Run Job)
                         v
        index artefact per domain in GCS  (vectors + chunk text + link graph)
                         ^  loads on cold start
                         |
   +---------------------+----------------------+
   |         Brain service (Cloud Run)          |   MCP over streamable HTTP
   |  retrieval: vector + BM25 + link, fused    |   tools: search / answer /
   |  auth: edge IAM + in-app OIDC + domain ACL |          get_document / list_domains
   +---------------------+----------------------+
             ^                          ^
             | MCPToolset (bearer)      | MCP (bearer)
   +---------+---------+      +---------+-----------------+
   |  ADK agent        |      |  Any MCP client           |
   |  (Gemini/Vertex)  |      |  (Claude Code, Cursor)    |
   +---------+---------+      +---------------------------+
             ^
             | HTTP (IAM-gated)
   +---------+-------------------+
   |  Brain Explorer web UI      |  graph viz, domain browser,
   |  + ADK dev UI (adk web)     |  search/answer with citations
   +-----------------------------+
```

Three deployable units, all serverless and scale-to-zero: the **brain** (MCP
retrieval service), the **agent** (ADK, optional but the centre of the demo), and
the **UI** (static app plus the ADK dev UI). The corpus and index are data, not
services.

---

## 3. The two audiences, from one codebase

An effortless personal demo **and** a production project an enterprise has a pathway to adopt.

The mechanism is a single explicit switch: **`BRAIN_PROFILE`**, with two values,
`personal` and `controlled`. It selects one file of Terraform variables and one
policy file. Nothing else branches. Everything that is genuinely the same stays
in shared modules and shared application code, including the agent and the UI.

| Concern                  | `personal`                                             | `controlled`                                                                                    | Same primitive?                 |
| ------------------------ | ------------------------------------------------------ | ----------------------------------------------------------------------------------------------- | ------------------------------- |
| Cloud project            | your own personal GCP project                          | the bank's pre-provisioned project                                                              | yes, a GCP project              |
| Who can invoke           | a Google Group you own                                 | the bank's federated group via Workforce Identity Federation                                    | yes, IAM `run.invoker`          |
| Caller identity          | personal Google account OIDC token                     | bank IdP identity federated to Google OIDC                                                      | yes, a Google-signed OIDC token |
| Domain policy            | `config/personal.policy.yaml` in the repo              | policy sourced from the bank's control (same schema)                                            | yes, the same ACL schema        |
| Ingestion                | demo adapters (files, web, git), fast `--auto` landing | same adapters plus the bank's own connectors, PR-gated review                                   | yes, same adapter contract      |
| Embeddings and synthesis | Vertex AI in your region                               | Vertex AI in the bank's region, optionally behind VPC-SC                                        | yes, same API                   |
| Agent and UI             | same ADK agent, same web UI                            | same ADK agent, same web UI                                                                     | yes, identical code             |
| Evals and observability  | free offline ADK evals in CI, basic Cloud Trace        | same evals plus paid Vertex Gen AI Evaluation, simulation, online monitors, Agent Observability | yes, same eval files and OTel   |
| Network posture          | public Cloud Run URL, IAM-gated                        | internal ingress plus VPC-SC perimeter                                                          | same service, stricter config   |

The point that matters: the personal demo is not a stand-in. It exercises
the **same identity primitive** (OIDC plus IAM), the **same serving path**, the
**same agent and UI**, and the **same isolation logic**. Moving to the bank
changes configuration and surrounding policy context, not the architecture.

Where the switch lives, concretely: `config/<profile>.tfvars` (infra),
`config/<profile>.policy.yaml` (domain ACL, identical schema), and one
environment variable read by the entrypoint. No conditional logic in the
application beyond "load the policy you were given".

---

## 4. Where the data boundary sits (and the biggest risk)

Assume the knowledge is sensitive. Content is at rest in two places, both inside
the user's own cloud tenancy: the **corpus** (markdown in git, plus a copy in a
private GCS bucket used to build the index) and the **index artefact** (chunk
text plus embedding vectors plus link graph, in a private GCS bucket).

Content is **in transit** in ways that matter, and all of them stay first-party
and in-tenancy:

1. **Embeddings.** The indexer sends chunk text to the **Vertex AI embedding
   model** to be turned into vectors.
2. **Synthesis.** The `answer` mode and the ADK agent send retrieved chunks to a
   **Gemini model on Vertex AI** to compose a cited answer.
3. **Ingestion parse and curate.** When new source material is ingested (section
   12), parsing of rich formats (for example PDFs via **Vertex AI Document AI**)
   and the optional LLM curation of raw text into clean markdown (via **Gemini on
   Vertex**) also run in-tenancy. Ingestion never sends sensitive source content
   to a third-party parser or SaaS.

**Decision: the embedding, synthesis, parse and curate models are all the cloud
provider's own first-party models, called from inside the same tenancy and
region.** Content
goes to Google-managed endpoints, not a third party, stays within the same cloud
boundary and region as everything else, is governed by the same IAM, and under
Google Cloud's enterprise data terms is not used to train models. For the
controlled profile both calls sit inside a **VPC Service Controls perimeter**
together with GCS, so content cannot egress the perimeter.

Why not the alternatives: a third-party API (OpenAI, and gbrain's other pluggable
providers) sends sensitive content to a processor outside the tenancy and fails
the data boundary; a self-hosted model in a local binary or GPU container keeps
data closest to home but violates "no heavy local binaries" and breaks
scale-to-zero economics. The self-hosted model is kept as a documented drop-in
for the strictest case, not the default.

The approach rests on an enterprise reviewer accepting "sensitive content transits to first-party
managed Vertex models within our own tenancy, region and VPC-SC perimeter". If that is unacceptable, the embedding and synthesis calls must move to self-hosted models, which reintroduces heavy compute and undercuts the idle-cost and no-binaries story. The design contains the risk by putting both models behind **narrow interfaces** (`app/embeddings/` and the agent's model config) so a
self-hosted adapter drops in without touching retrieval, serving, isolation or
infra topology.

---

## 5. The stack, and why

Primary target: **Google Cloud Platform.** Justification per requirement:

- **Cheap when idle, easy teardown:** Cloud Run scales to zero and bills per
  request; idle cost is only GCS and Artifact Registry storage (pennies).
  Teardown is `terraform destroy`. No database runs 24/7.
- **No external SaaS database:** there is no vector database. For a small-team
  corpus (thousands to low tens of thousands of chunks) a brute-force cosine scan
  over an in-memory array is fast and needs no running datastore. The index is a
  file in the user's own bucket. Reaching for a managed vector DB (as gbrain does
  with Postgres plus pgvector) would add idle cost and an external dependency for
  no benefit at this scale.
- **Data boundary:** first-party Vertex AI embeddings and Gemini synthesis,
  in-tenancy, in-region (section 4).
- **Free identity, same primitive controlled:** Google OIDC plus Cloud Run IAM
  `run.invoker`; Workforce Identity Federation for the bank (section 7).
- **No hand-rolled security:** authentication is Google-signed OIDC verified
  against Google's public keys; coarse authorisation is platform IAM. We write no
  crypto and no session logic, and no OAuth server (which gbrain does ship).
- **Declarative infrastructure:** all infrastructure is Terraform, not shell
  `gcloud` calls.
- **Agent and UI:** Google ADK is first-party, deploys to Cloud Run or Vertex AI
  Agent Engine with one command, runs Gemini in-tenancy, connects to our MCP
  endpoint via `MCPToolset`, and ships a dev web UI, so the demo agent and its UI
  are on the same platform as the brain (sections 8 and 9).

**Portability** is a virtue not a requirement. The shape (serverless container,
object-store index, first-party embeddings and synthesis, OIDC/IAM, an
MCP-consuming agent) maps onto Azure (Container Apps, Blob, Azure OpenAI, Entra
ID) and AWS (App Runner or Lambda, S3, Bedrock, IAM/Cognito). We keep the
vendor-specific seams (embeddings, model, identity verification) behind small
interfaces so a port is an adapter plus a tfvars file, not a rewrite. We do not
abstract further; GCP is built properly and directly.

Application language: **Python**, for the mature Vertex AI, MCP and Google ADK
SDKs.

---

## 6. Retrieval (adapted from gbrain)

We keep the gbrain philosophy of **hybrid retrieval** and its **search versus
think** split, and re-seat both on our object-store index instead of a running
Postgres. See `docs/LINEAGE.md` for the full comparison and attribution (gbrain
is MIT licensed).

- **Chunking:** markdown split by heading and size, preserving document, section
  and domain metadata from frontmatter.
- **Three signals, fused:**
  - **Semantic:** cosine similarity between the query embedding and chunk
    embeddings, brute force in memory (fast at this scale).
  - **Keyword:** a lightweight BM25 pass for exact-term queries embeddings miss.
  - **Link graph:** `[[wikilinks]]` between docs form a graph; after the top
    hits we pull graph neighbours so the agent gets linked context, not isolated
    chunks. This is the signal gbrain found most valuable and it is what makes a
    brain more than a vector search.
  The three are combined by **reciprocal-rank fusion**, as gbrain does.
- **Two modes:**
  - `search` returns ranked, cited chunks (fast, no LLM cost).
  - `answer` (gbrain's "think") sends the retrieved chunks to Gemini on Vertex
    and returns a synthesised answer with citations and an **explicit statement
    of what the brain does not know**. The honest gap statement is deliberately
    kept; it is what lets an agent decide whether to act.

The domain filter (section 7) is applied **before** any signal runs, so a caller
never sees, ranks against, or synthesises from a domain they may not read.

When the corpus outgrows brute force (roughly beyond low tens of thousands of
chunks) the swap is an approximate-nearest-neighbour index in the same artefact,
or Vertex AI Vector Search. That is a `retrieval/` change, not an architecture
change. It is convenient, not load-bearing.

---

## 7. Identity, authorisation and domain isolation

Two layers, both platform-native, no bespoke auth:

1. **Edge (coarse):** Cloud Run's built-in IAM check. Only identities granted
   `roles/run.invoker` reach the container. Personal: a Google Group. Controlled:
   a group federated from the bank IdP via Workforce Identity Federation. Adding a
   teammate is a group membership change.
2. **In-app (fine, per domain):** the container verifies the caller's
   Google-signed OIDC ID token (audience equals the service URL) against Google's
   public keys, extracts the identity, and looks up which **domains** that
   identity may retrieve from in the loaded policy. Retrieval is filtered to those
   domains before anything is returned.

**Why the server is the trustworthy place to enforce domain isolation.** The
agent (the client) is untrusted and can ask for anything. The Cloud Run service
is the only component that both holds the full index and can verify the token
signature. Enforcing in the client, or by handing out per-domain URLs without a
server check, would be bypassable and would count as hand-rolled security.
Defence in depth: index artefacts are partitioned per domain under separate GCS
prefixes with separate IAM, so the boundary is enforced at storage as well as at
query time, but the **verified-identity server-side filter is the primary
boundary**.

Note the boundary holds even with the agent in the loop: the ADK agent forwards
the caller's identity to the brain and the brain enforces the ACL, so the agent
cannot retrieve across domains on a caller's behalf.

**Team model.** One person runs `brain up` and becomes the provisioner. Others
join cheaply: the provisioner runs `brain grant <email> --domains a,b`, which
adds the person to the invoker group and the domain ACL; the person runs
`brain connect`, which prints the MCP config block (or points their ADK agent at
the endpoint). No per-user infrastructure.

**Four kinds of domain, one mechanism.** A domain is the unit of access; who a
grant names is the only thing that varies:

- **Commons** - a grant to the wildcard `*` in the base policy, so every signed-in
  caller can read it (onboarding, handbook). The brain is never anonymous, so `*`
  means "any authenticated caller."
- **Personal** - `personal:{subject}`, derived from the caller's stable subject,
  never named in the policy. Every caller reads and writes their own; `add_note`
  lands notes here ungated (you own it). Because it is never a declared domain,
  `domains_for` (which intersects with the declared set) means a `*` grant can
  **never** reach anyone's personal domain: the load-bearing invariant of the
  personal space.
- **Team / org** - an email or `group:` grant in the base policy (`tfvars`),
  admin-owned and slow-changing.
- **Shared** - dynamic, user-authored grants in a **sharing overlay**, merged over
  the base policy at request time. A user shares a domain or a single document they
  own with a person or group (`share`), revokes it (`unshare`), and what they never
  share stays private for good. The overlay lives as per-owner
  `shares/{owner}.yaml` objects in a dedicated shares bucket the brain fully owns
  (so the index bucket it serves stays read-only). Two rules the base policy does
  not need: a share principal is never `*` (opening content to everyone is an admin
  act in the base policy), and a user can only share content they own or may write,
  never re-share what was merely shared to them. Doc-level shares admit exactly one
  document without dragging in its domain neighbours; link expansion stays scoped to
  the caller's own domains.

A brand-new Google user with no team grant is therefore never a dead end: they land
on commons (content to start using) plus their own empty personal space (a place to
write), and see anything shared with them alongside their own domains.

### Content safety at the shared boundary (Model Armor)

The domain ACL decides *who may see what*; it does not inspect the *content* itself. So a
second, complementary guard sits on the two places where content becomes shared or
guest-visible: **Google Model Armor**, called **in-region** (europe-west2 — the endpoint region
is derived from the template name). Content bound for a shared space (a write, proposal, edit or
Studio draft) and every agent answer on the guest read path passes through it. Detected PII and
secrets (Sensitive Data Protection) are **redacted in place** from the exact code-point ranges
Model Armor returns — **redact then allow**, so a leaked password or card never lands in the
corpus or reaches a guest, while the useful content still saves. Prompt-injection / jailbreak
and responsible-AI hits are surfaced as **flags** rather than blocks: the agents' tool-only
guardrails already bound what an injected instruction could do, so flagging keeps the run honest
without refusing a legitimate question that merely *mentions* an attack.

It is **env-gated** on `BRAIN_MODEL_ARMOR_TEMPLATE`, a pure pass-through no-op when unset, so a
deployment that does not want it (and the offline tests) never call out. Terraform enables the
API, provisions the template (SDP + prompt-injection + responsible-AI; the malicious-URI filter
is omitted because europe-west2 does not support it) and grants the brain `roles/modelarmor.user`.
The guard is **best-effort**: any Model Armor error returns the text unchanged, because content
safety must never hard-fail a write or an answer on an availability blip.

---

## 8. The agent (Google ADK)

The goal is a brain an agent can query. We ship a first-party demo agent
built with **Google ADK** so the repository proves the whole path, not just the
endpoint, and so the demo is compelling on its own without the evaluator wiring
up their own agent.

- **What it is:** an ADK `LlmAgent` running a **Gemini model on Vertex AI**
  (in-tenancy, consistent with the data boundary), whose tools are the brain's
  MCP tools, attached with `MCPToolset` over **streamable HTTP** with the caller's
  OIDC token as a bearer header. `tool_filter` restricts it to the brain's tools.
- **Why ADK:** it is Google-first-party (same trust surface as the rest of the
  stack), it speaks MCP natively as a client, it runs the model in-tenancy on
  Vertex, it deploys to **Cloud Run or Vertex AI Agent Engine** with one command
  (so the agent inherits the same scale-to-zero and IAM story as the brain), and
  it ships a **dev web UI** we reuse for the demo (section 9).
- **A multi-agent team (live):** the agent is a **coordinator** that delegates over
  ADK agent transfer to three sub-agents. Two are brain-facing, each with its own MCP
  toolset filtered to its role: a **researcher** (read tools: search/answer/get_document/
  list_domains) and a **curator** (search/get_document/**propose_document**). The third
  is an **analyst** that carries **no brain tools** and instead *writes* Python that runs
  in Gemini's **server-side code sandbox** (ADK `BuiltInCodeExecutor`): the code executes
  on Google's side, in a Google-managed environment with no network or data access, **not
  in our process** — so quantitative questions are *computed* and checkable rather than
  guessed. The analyst itself is a normal Gemini agent (not a sandbox); being tool-less is
  what keeps it from reading the corpus. For a heavier, stateful sandbox, setting
  `enable_code_interpreter` provisions the managed **Vertex AI Code Interpreter** extension
  and points the analyst at it (`VertexAiCodeExecutor`); that extension is **us-central1-only**,
  so it trades in-region execution for the managed sandbox (see infra/modules/code_interpreter).
  A question routes to the researcher, "draft/add a document" to
  the curator (whose proposal lands in the **human review queue** (section 12), never
  live), and anything needing arithmetic to the analyst. The brain enforces the ACL
  behind every tool, so the whole team is scoped to what the caller may see and write.
- **Memory + sessions (signed-in, optional):** when an Agent Engine instance is
  configured (`enable_memory`, provisioned in-region in europe-west2), the live run gains
  Agent Engine **Sessions** (conversation continuity — follow-up questions keep context)
  and a per-user **Memory Bank** (durable, cross-session memory). Recalled memories are
  injected into the run **server-side, never as a tool**, so a prompt injection can't reach
  them; Memory Bank extracts durable ones after. Every read and write is scoped to the
  **verified caller's subject** (never a client parameter), so a user's memory never crosses
  to anyone else — a hermetic isolation eval enforces it, and **guests get none**.
- **Deterministic offline tier:** the same agent runs as a single researcher backed
  by a `FakeBrainModel` and in-process tools, so the golden and isolation evals
  (`tool_trajectory` + `response_match`) are hermetic and free in CI.
- **Two ways to consume the brain, one codebase:** power users point their own
  MCP client (Claude Code, Cursor) at the endpoint; the demo and less technical
  evaluators use the shipped ADK agent and its UI. Both hit the same MCP tools
  under the same auth.

**AI-platform layer (governance).** Two enterprise concerns are made explicit and
auditable, in-tenancy: a **model inventory** (`config/models.yaml` - what models run,
their version, purpose, owner and approval) and a **versioned prompt registry**
(`brain_app/prompts.py` - each agent prompt named, semver'd and content-hashed).
`brain platform` prints both. **Traces** go to Cloud Trace by default (in-tenancy,
scale-to-zero); the same OpenTelemetry spans can optionally be exported to a
self-hosted **Langfuse** (`BRAIN_OTEL=langfuse` + the standard `OTEL_EXPORTER_OTLP_*`
env) for LLM-native tracing, prompt and eval linkage - kept a toggle so the default
path stays Google-native and scale-to-zero.

The agent is **convenient, not load-bearing**: the brain stands alone as an MCP
service, and the ADK agent is the demo-facing consumer. But it is the piece that
makes the demo rich, and it keeps the entire stack on first-party Google
primitives a bank reviewer can reason about.

---

## 9. The UI

A brain you can only reach through a terminal does not work well for all user types. Two UI surfaces,
both scale-to-zero and behind the same IAM:

1. **ADK dev UI (`adk web`).** ADK's built-in chat interface, pointed at the demo
   agent. Near-zero effort, and it shows tool calls and traces live, so an
   evaluator watches the agent call `search`/`answer` on the brain and reason over
   citations. This is the fastest path to a watchable demo.
2. **Brain Explorer (custom web app).** A single-page app (served
   from GCS or Cloud Run, IAM-gated) that makes the knowledge tangible:
   - a **graph visualisation** of the `[[wikilink]]` graph (the Obsidian-style
     view Karpathy's pattern is loved for), coloured by domain, where isolation is
     visible (a caller only sees the sub-graph they may read),
   - a **domain browser** and document viewer rendering the markdown,
   - a **search / answer panel** showing ranked hits, citations, and the honest
     gap statement side by side, so the difference between raw retrieval and
     synthesis is on screen,
   - a small **"who am I and what can I see" panel** that reads the verified
     identity and lists the caller's permitted domains, making the isolation
     boundary a demo feature rather than an invisible check.

The UI holds no secrets and enforces nothing; it renders what the IAM-gated,
ACL-enforcing brain returns. That keeps the trust boundary in the server
(section 7) and lets the UI be a thin, pretty client. Design intent for the
Explorer is captured in the frontend work in the plan.

---

## 10. Testing strategy: deterministic, security and AI evals

Testing is a first-class deliverable here. The principle is **three pillars, all
CI-gated, running free and offline wherever possible**, because a system with a
sensitive data boundary and a domain-isolation guarantee has to prove those
properties continuously, not assert them once in prose. The three pillars answer
three different questions: is the logic correct, is the boundary secure, and is
the probabilistic agent still good enough.

**Pillar 1: deterministic functional tests.** Ordinary unit and integration
tests, run in CI with no cloud (embedding and LLM calls replaced by deterministic
fakes), covering: chunking and `[[wikilink]]` graph construction; the three
retrieval signals and their reciprocal-rank fusion; ranking stability;
`get_document` and `list_domains`; the MCP tool contracts (shapes and errors);
indexer idempotency (content-hash upsert produces no duplicates); and profile and
policy loading. These are fast, hermetic, and gate every pull request.

**Pillar 2: security tests.** The properties we treat as first-order get
their own tests, so a regression fails the build rather than shipping:

- **Authorisation and isolation.** Integration tests hit the running brain with
  tokens scoped to different domains and assert that a caller only ever receives
  chunks from permitted domains, that the filter is applied before retrieval, and
  that cross-domain requests return nothing. This tests the boundary at the
  trustworthy layer (the server, section 7), not just at the agent.
- **Token verification.** Tests that unsigned, expired, wrong-audience or
  wrong-issuer OIDC tokens are rejected, so the platform-native auth is exercised,
  not assumed.
- **Infrastructure policy-as-code.** Static checks over the Terraform (for example
  Checkov or tfsec, plus OPA/conftest for our own rules) assert that buckets are
  private, the brain service is not public and requires an invoker, service
  accounts are least-privilege, and (controlled profile) that the VPC-SC perimeter
  and internal ingress are set. These run in CI and need no cloud.
  - **OAuth exception.** Enabling remote MCP connectors (`enable_oauth`, personal
    profile) is a deliberate, audited relaxation: the OAuth Authorization Server and
    the brain become `allUsers`-reachable so hosted clients (Claude/ChatGPT) can
    discover and call them, with the Google-brokered OAuth bearer as the in-app gate
    instead of edge IAM. The conftest rule permits public ingress *only* on those two
    services and still fails any other public invoker. The controlled profile stays
    perimeter-internal and never opens. See [`docs/oauth.md`](docs/oauth.md).
- **Supply chain and static analysis.** Dependency audit (`pip-audit`), Python
  SAST (`bandit`), and secret scanning (`gitleaks`) as standard maintained-project
  hygiene.
- **Adversarial retrieval (the AI-specific security case).** Because corpus
  content is fed to an LLM, we test that a poisoned document (for example one that
  instructs the agent to reveal another domain or to ignore its scope) cannot
  cause cross-domain exfiltration or scope escape. This straddles pillars 2 and 3
  and is expressed as an eval so it runs continuously.

**Pillar 3: non-deterministic AI evals.** Agents are probabilistic, so "does it
still work" cannot be a pass/fail assertion; it needs trajectory and
answer-quality evaluation. Verified real-world context: at Google Cloud Next '26
(22 April 2026) Vertex AI was rebranded to the **Gemini Enterprise Agent
Platform**, whose Govern and Optimize layers add **Agent Simulation**
(stress-test against synthetic interactions before deploy), **Agent Evaluation**
(auto-raters and online monitors scoring task success and safety on live
traffic), and **Agent Observability** (a Unified Trace Viewer over reasoning
paths). ADK plugs into all of it. We run the evals in two tiers matched to the two
audiences.

**Evaluation, two tiers matched to the two audiences.**

- **Free and offline (personal, and CI for everyone).** ADK's built-in eval
  framework runs deterministic metrics with no paid service: `tool_trajectory`
  match and `response_match` (ROUGE) over `.test.json` (single-session) and
  `.evalset.json` (multi-turn) files. We ship a golden eval set over the starter
  corpus and run it in CI via the pytest `AgentEvaluator`, so a corpus or agent
  change that breaks retrieval fails the build. One eval is deliberately an
  **isolation test**: a caller scoped to `finserv-ai-engineering` must not
  retrieve an `enterprise-ai-recruitment` chunk, so the domain boundary is
  asserted by the eval suite, not just
  asserted in prose.
- **Rich and paid (controlled).** The controlled profile can enable the **Vertex
  Gen AI Evaluation Service** for LLM-judged and rubric metrics
  (`final_response_match_v2`, `hallucinations_v1`, `safety_v1`, rubric-based
  quality), plus Agent Simulation before deploy and Agent Evaluation online
  monitors on live traffic. These cost money and run on demand, not at idle, which
  is why they are off by default.

**Observability.** ADK emits OpenTelemetry aligned with the GenAI semantic
conventions, so turning on tracing is configuration, not code: the Terraform
enables Cloud Trace, Cloud Monitoring and Cloud Logging, and both the agent and
the brain service export spans (retrieval calls, tool calls, model calls, token
counts, latency). In the demo the evaluator can open the trace viewer and watch a
single question fan out into `search`/`answer` calls against the brain and a
Gemini synthesis step. The personal profile gets basic Cloud Trace (generous free
tier at demo volume); the controlled profile gets the full Agent Observability
dashboards and the Unified Trace Viewer.

**Data boundary note.** LLM-judged evaluation and simulation run on Vertex within
the tenancy, consistent with section 4; no evaluation content leaves to a third
party. Traces and logs stay in the user's own Cloud Observability, not an external
APM.

---

## 11. Knowledge as a reviewable, versioned asset

The corpus is markdown under `corpus/<domain>/` in git. Changing what the brain
knows is a pull request: inspectable in review, revertible with `git revert`,
attributable with `git blame`. Re-indexing is a job, not a mutation of live
state, so a bad change is rolled back by reverting the markdown and re-running
`brain index`. There is no hidden mutable knowledge store to drift out of sync
with the repository. (We deliberately defer gbrain's autonomous "dream cycle"
enrichment for this reason: it fights near-zero idle cost and it makes the brain
mutate outside review. It is noted as an optional future Cloud Run Job.)

### The corpus is an Open Knowledge Format bundle

That "markdown + frontmatter + `[[wikilinks]]` under git" shape is not ad-hoc: it is
Google's **Open Knowledge Format** (OKF), the open, vendor-neutral standard for
portable, agent-readable knowledge (`docs/LINEAGE.md` section 4). The mapping is
near-exact, so we adopt OKF as the corpus format rather than inventing our own:

- A **bundle** is a directory tree of markdown concepts; each `corpus/<domain>/` is a
  bundle, and the whole corpus is one. A reserved `index.md` lists a directory.
- A **concept** is one markdown file with YAML frontmatter. OKF requires exactly one
  field, `type`, which `_stamp` writes (`Note`, `Reference`, `Web article`,
  `Transcript`, ...); `title`, `tags`, and our provenance (`source`, `source_url`,
  `fetched_at`, `checksum`, `ingest_run`) ride along as OKF producer extensions.
- The **concept id** is the path minus `.md`, which is exactly our `domain/slug`
  `doc_id`. Links are a directed graph, authored as `[[wikilinks]]`.

Two consequences follow. First, **interop is built in**: any space exports as a clean
OKF bundle (`brain_app.okf.bundle_zip` renders OKF-native `resource` / `timestamp`
fields and rewrites `[[wikilinks]]` to standard markdown links), consumable by another
OKF tool or Google's Knowledge Catalog; and an externally-authored OKF bundle imports
through the same web / git / file adapters, since it is just markdown in a tree.
Second, **conformance is enforced**: `brain_app.okf.validate_bundle` checks every
non-reserved concept has parseable frontmatter with a non-empty `type`, and the seed
corpus is validated in CI. OKF governs the format at rest; the domain ACL (section 7),
hybrid retrieval (section 6) and the review gate (section 12) govern how it is served
and grown.

---

## 12. Ingestion: adapters and the corpus lifecycle

A brain is only as useful as it is easy to feed. Hand-writing markdown is the
floor; the demo has to show new data arriving in interesting ways, and a bank has
to be able to point the brain at its own sources without us rewriting the core.
The design is a **contract-first ingestion pipeline**: the core is
source-agnostic, and every source is a small, swappable adapter the bank can
extend.

### The pipeline

```
SourceAdapter.fetch -> Parser (bytes+mime -> markdown) -> [optional] Curate (Gemini)
   -> stamp frontmatter + provenance -> land (idempotent upsert) -> review gate -> index
```

- **`SourceAdapter`** (`fetch() -> Iterable[RawItem]`): pulls raw items and their
  provenance from one source. Adding a source is implementing this one interface
  and adding a config entry. Adapters are registered in a registry keyed by a
  `type`, configured in `config/sources.yaml` (this echoes gbrain's per-source
  routing). We ship three demo adapters: **local files** (a `raw/` drop, the
  Karpathy pattern), **web/URL**, and **git repo**. The bank extends with
  Confluence, Jira, SharePoint, GCS and so on.
- **`Parser`** (`bytes + mime -> markdown + metadata`): pluggable by content type
  (markdown passthrough, HTML, PDF via in-tenancy Vertex AI Document AI,
  transcripts). This is the second extension seam.
- **Curate (optional).** A Gemini pass, in-tenancy, that rewrites messy source
  text into a clean, well-structured article with frontmatter and suggested
  `[[wikilinks]]`. This is Karpathy's raw-to-wiki idea: drop a PDF, get a curated
  page. It is optional because it costs model calls and because its output must be
  reviewed.
- **Provenance.** Every ingested document is stamped with `source`, `source_url`,
  `fetched_at`, `checksum` and `ingest_run` in its frontmatter, so a reader (and
  the UI) can see where a fact came from, and so re-ingestion is idempotent.
- **Land, idempotently.** Documents are upserted by checksum, and each source
  keeps a cursor so re-runs only touch what changed. Re-ingesting converges rather
  than duplicating, the same discipline as `brain index`.

### Two ways in, both gated

1. **Batch ingestion (option B).** `brain ingest` runs the pipeline for the
   configured sources, in-cloud as a Cloud Run Job so source content and models
   stay in-tenancy. This is the workhorse.
2. **Agent-authored (option C).** The MCP server exposes a gated
   **`propose_document`** write tool, so an agent (Claude Code, or the ADK agent)
   can contribute knowledge discovered in conversation. 

Both paths land through a **review gate**, and this is the load-bearing decision.
An addition becomes a branch and a pull request (the `controlled` default), so new
knowledge is inspectable, attributable and revertible before it is retrievable,
and so ingestion can never silently place content in the wrong domain and breach
isolation. The `personal` profile offers a fast `--auto` path that commits
directly for instant gratification in the demo. We deliberately reject gbrain's
default of un-reviewed continuous mutation; a bank cannot audit knowledge that
rewrites itself behind the reviewer's back.

### Isolation and authorisation at ingest

Domain is assigned at ingest, by adapter configuration, and validated: an adapter
cannot write outside its configured domain, and the same folder-equals-domain
check the indexer enforces applies to landed documents. The `propose_document`
tool is write-scoped separately from read access, and a proposal is a
quarantined change (a PR), never a live write, so the retrieval isolation boundary
in section 7 is never in the ingestion path's hands.

### Where this sits on the load-bearing scale

Load-bearing: in-tenancy parse and curate (the data boundary, section 4) and the
review gate (preserves the reviewable-asset property and the isolation boundary).
Convenient and swappable: the specific adapters, the parser implementations, and
whether curation runs at all. The single biggest new risk is **curation
fidelity**, an LLM rewriting a source can introduce errors, which is exactly why
provenance and the review gate are not optional.

---

## 13. The one command, honestly bounded

`brain up` runs, in order:

1. **Preflight** (the honest-prerequisites gate). Checks: gcloud authenticated, a
   project selected, billing enabled, required APIs enabled, and the caller
   holding the provisioning role. On any failure it prints the **exact** command
   to fix it and exits non-zero. It never silently assumes access.
2. **Terraform apply** (state in a GCS backend bucket created by an idempotent
   bootstrap). Provisions Cloud Run (brain, agent, UI), buckets, IAM, Artifact
   Registry, and the Vertex AI API enablement.
3. **Build and push** the container images to Artifact Registry.
4. **Index** the starter corpus via a Cloud Run Job (so corpus and embeddings
   stay in-cloud even during seeding), writing artefacts to GCS.
5. **Print** the service URLs (brain, agent UI, Explorer) and the ready-to-paste
   MCP config block.

Adding knowledge afterwards is a separate command, `brain ingest` (section 12),
run whenever new source material should enter the brain; it is not part of
`brain up` because seeding and ongoing ingestion are different lifecycles.

**What the command cannot do, and should not pretend to.** In a controlled
environment, project creation, billing/spend approval and service allow-listing
are genuinely gated by the organisation. The command **detects** these as
prerequisites and fails loudly with the remediation; it does not attempt them.
That is the honest line between "one command to a working brain" and "one command
that provisions a company".

**Idempotency and recovery.** Terraform is declarative, so re-running converges
rather than duplicating. The state bucket bootstrap is create-if-not-exists. The
index step upserts by content hash. A run that dies partway is fixed by running
`brain up` again.

Local prerequisites are kept minimal and named honestly: `gcloud` and `terraform`
(or Docker to run them in a container). These are the unavoidable dependencies.

---

## 14. What this is, and what it is not

**What the personal demo proves:**

- The one-command experience end to end, on a free-tier personal account.
- The real identity primitive (OIDC plus IAM), not a mock.
- Server-side multi-domain isolation against a verified identity, visible in the
  UI.
- Hybrid retrieval and the search-versus-answer split, with in-tenancy embeddings
  and synthesis and no external SaaS.
- A working ADK agent and a graph UI over the brain.
- Adding new knowledge through adapters (files, web, git) and through an agent's
  gated `propose_document` tool, all landing as reviewable, provenance-stamped
  markdown.
- A golden ADK eval suite in CI (including an isolation eval) and agent traces in
  Cloud Trace, at no cost, proving the governance surface is real.
- Near-zero idle cost and a clean `terraform destroy`.

**What would still change for a genuine controlled deployment:**

- Identity source becomes the bank IdP via Workforce Identity Federation; groups
  become the bank's groups. Configuration, not code.
- Networking hardens: internal ingress, a VPC-SC perimeter around Vertex AI and
  GCS, private egress. Terraform variables, not new architecture.
- The policy file is sourced from the bank's control plane instead of the repo.
- Ingestion points at the bank's own sources: they write adapters for Confluence,
  Jira, SharePoint and the like against the same contract, and the fast `--auto`
  landing is replaced by the PR-gated review flow.
- Project, billing and API allow-listing are handled by the organisation as
  prerequisites, outside the command.

**Honest limits:**

- The data boundary depends on accepting first-party managed Vertex calls for
  embeddings and synthesis (section 4). The strictest environments may require
  self-hosted models; the interfaces exist for that, but it changes the cost
  profile.
- Brute-force retrieval is deliberately simple and will need an ANN index as the
  corpus grows.
- Cold starts add latency on the first query after idle; acceptable for an
  agent-assist tool, not for a low-latency interactive UI.
- The ADK agent is a demo consumer, not a hardened multi-user application; it
  inherits the brain's isolation but is not itself the security boundary.
- LLM curation during ingestion can misread or reshape a source; the review gate
  and provenance are the mitigation, but curation output must be read, not trusted
  blindly.

---

## 15. Load-bearing versus convenient

**Load-bearing** (change these and the design changes):

- Scale-to-zero serverless plus object-store index (idle cost, no external DB).
- First-party in-tenancy embeddings and synthesis (the data boundary).
- OIDC plus IAM identity (auth, and the two-audience switch).
- Server-side domain filtering against a verified identity (isolation).
- The ingestion review gate and in-tenancy parse/curate (keeps knowledge a
  reviewable asset and keeps ingestion inside the data boundary).
- Terraform (idempotency, recovery, and the real-repository signal).

**Convenient** (swappable without touching the architecture):

- The ADK agent (the brain stands alone as an MCP service; the agent is the demo
  consumer). MCP itself could be plain REST.
- The UI surfaces (nice for the demo, enforce nothing).
- Evaluation and observability (the free ADK eval tier and Cloud Trace add a lot
  of credibility for near-zero effort; the paid Vertex evaluation and Agent
  Observability tiers are controlled-profile options, not core).
- The specific ingestion adapters and parsers, and whether curation runs (the
  pipeline contract and review gate are load-bearing; the adapters are not).
- GCS specifically (any object store).
- The exact retrieval blend and brute-force search.
- Python as the implementation language.

---

## 16. Facts to verify before writing provisioning code

Reasoned from current knowledge and to be confirmed against live documentation
before infra is written, because each would change a detail if it has moved:

- Current Vertex AI embedding model name and dimensions, and the enterprise data
  terms excluding inputs from training.
- Current Gemini model id available on Vertex for the ADK agent and `answer`
  synthesis, and its in-region availability.
- Cloud Run always-free-tier limits and current per-request pricing, and that
  `min-instances = 0` incurs no idle compute charge.
- Google ADK's current `MCPToolset` / `StreamableHTTPConnectionParams` API and
  header-based auth, and one-command deploy targets (Cloud Run and Vertex AI Agent
  Engine).
- Workforce Identity Federation availability and any per-identity pricing for the
  controlled federation claim.
- The Gemini Enterprise Agent Platform (formerly Vertex AI) product and API names
  post the April 2026 rebrand, and which ADK eval metrics are free/offline versus
  which require the paid Vertex Gen AI Evaluation Service, plus Cloud Trace free
  tier limits at demo volume.
- That Cloud Run forwards a verifiable ID token the app can use for in-app
  per-domain authz (as opposed to only the edge IAM allow/deny).
- Vertex AI Document AI availability and in-region support for parsing rich
  formats during ingestion, and the current MCP convention for server-exposed
  write tools (for the gated `propose_document` path).
