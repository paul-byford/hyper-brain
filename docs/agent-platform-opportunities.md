# Google Gemini Enterprise Agent Platform — feature map for Hyper Brain

A survey of the features on Google's
[Gemini Enterprise Agent Platform](https://docs.cloud.google.com/gemini-enterprise-agent-platform/agents),
with, for each: its **purpose**, and a **concrete upgrade** that would let Hyper Brain
demonstrate it. Hyper Brain already sits squarely on this platform's building blocks
(Google ADK agents, MCP tools, Vertex AI, per-workload identity, offline evals), so much
of this is about deepening and surfacing what we do, not starting from scratch.

**Status legend** — `✓` already exercised · `~` partial today · `◇` new opportunity.

## Core development tools

| Feature | Purpose | How Hyper Brain could demonstrate it |
| --- | --- | --- |
| `✓` **Agent Studio** | Collaborative, visual (no-code) workspace to discover models, engineer prompts, and assemble agents for fast prototyping. | **Done.** An admin-only **Agent Studio** panel in the Studio tab: a moderator composes a custom specialist — name, a description (the coordinator's routing cue), a system prompt, and an allow-list of the brain's tools (read + `propose_document`) — previews it live against a sample question, then registers it. It joins the live team (its routing line is appended to the coordinator; it runs as a **leaf** sub-agent) and appears as a node on the Agents map. A custom agent is **behaviour, not access**: its tools bind to *whoever runs it*, domain-scoped exactly like the researcher, so it can never exceed the caller's permissions, and its answers still pass the Model Armor guard. Definitions persist in a shared GCS registry (in-memory off-cloud); a hermetic test pins the admin gate and validation. |
| `✓` **Agent Development Kit (ADK)** | Code-first framework for granular control of agent logic, tools, and multi-agent orchestration. | We already run an ADK coordinator delegating to researcher + curator. Deepen it: add a third specialist (a "reviewer" that pre-checks proposals against domain policy) and expose ADK `transfer_to_agent` hops as first-class steps in the live run. |
| `✓` **Agent Garden** | Library of prebuilt agent samples that accelerate common patterns. | **Done.** A curated **recipe gallery** in the Studio tab: prebuilt specialists (*onboarding buddy*, *release-notes writer*, *meeting-notes curator*, *policy checker*), each a ready-made spec (name, system prompt, tool allow-list). "Use this recipe" drops it into the Agent Studio composer, where a moderator reviews/tweaks and registers it — at which point it joins the live team **and** the Agent Registry. Builds directly on Agent Studio, so a recipe is a starting point, never an unreviewed drop-in. |
| `~` **Managed Agents API** | Config-driven, REST-first way to run autonomous agents in a managed sandbox with mounted skills and artifacts. | Describe our agent team as a declarative manifest (YAML) instead of code, mount a domain's OKF bundle as the agent's "artifacts", and expose it through the Managed Agents API so a team is defined by config + corpus, not a redeploy. |

## Models and intelligence

| Feature | Purpose | How Hyper Brain could demonstrate it |
| --- | --- | --- |
| `~` **Model Garden** | Catalog of 200+ foundation models (Google, partner, open) for discovery and experimentation. | Our Agents page already carries a model inventory; turn it into a Model-Garden-style picker so an admin can swap the answer or curation model **per domain** (e.g. a cheaper model for the commons, a stronger one for finserv), each choice content-hashed and eval-gated. |

## Deployment and runtime

| Feature | Purpose | How Hyper Brain could demonstrate it |
| --- | --- | --- |
| `~` **Agent Runtime** | Fully managed environment to host, deploy, and scale ADK (or other) agents. | Today `brain-agent` runs on raw scale-to-zero Cloud Run. Deploy the ADK agent to Agent Runtime (Agent Engine) instead and show the same team scaling under load without us managing the container — a clean "managed vs self-hosted" toggle in the arch page. |
| `◇` **Agent Gateway** | Managed networking that governs all agent traffic, enforces access-control policy, and enables Model Armor inspection. | Front our MCP endpoint with Agent Gateway so every tool call passes one governed ingress with policy + Model Armor, replacing the bespoke CORS/allow-list we hand-wire on the brain service today. |

## Sessions and memory

| Feature | Purpose | How Hyper Brain could demonstrate it |
| --- | --- | --- |
| `✓` **Sessions** | Maintain interaction history within a single conversation for ongoing context. | **Done.** The live agent run uses Agent Engine **Sessions** (in-region, europe-west2): the coordinator returns a session id, follow-up questions continue the same conversation, and a "New conversation" button starts fresh. Guests get ephemeral in-memory sessions. |
| `✓` **Memory Bank** | Extracts, stores, and retrieves personalized user info across sessions. | **Done.** Signed-in users get an Agent Engine **Memory Bank** (in-region): the server recalls memories relevant to the question and injects them into the run (server-side, never a tool), and Memory Bank extracts durable ones after. Every read/write is scoped to the **verified subject** (never a client parameter), so a user's memories never reach anyone else — a hermetic isolation eval enforces it; **guests get none**; a "what the brain remembers about you" panel surfaces it. |

## Security and governance

| Feature | Purpose | How Hyper Brain could demonstrate it |
| --- | --- | --- |
| `◇` **Agent Identity (SPIFFE)** | A unique, IAM-native, auditable ID per agent — a granular alternative to shared service accounts. | Give the researcher and curator each their **own** SPIFFE agent identity instead of one shared SA, so Cloud Audit Logs attribute every corpus read or proposal to a specific agent. Fits our existing "least-privilege service account per workload" story. |
| `~` **Agent Identity Auth Manager** | Handles OAuth and refresh-token complexity for secure tool calls on a user's behalf. | We already run an OAuth 2.1 AS for callers. Use Auth Manager for the other direction: let the curator call a user's own connector (their Drive, a wiki) on their behalf with managed refresh, so Studio can draft from sources only that user can see. |
| `✓` **Agent Registry** | Central, queryable store of agent metadata: versions, frameworks, capabilities, MCP tool names, annotations. | **Done.** The team is registered in the **official GCP Agent Registry** (`agentregistry.googleapis.com`, in-region europe-west2). Each agent — the built-in coordinator/researcher/curator/analyst **and** every Agent Studio custom specialist — is a `Service` with an **A2A Agent Card** (version = its prompt version, skills = its MCP tools, framework/model/prompt content-hash in the description). Registered with `brain registry sync` (idempotent create/patch); read back from the platform's `agents.list` by `/api/registry` + `brain registry list`, and surfaced on the Agents page as a live "catalogued in GCP Agent Registry" strip beside our own model/prompt manifest. Gated by `enable_agent_registry` (Terraform enables the API + grants the brain SA `roles/agentregistry.viewer`; registration itself is an operator action). |
| `◇` **Semantic Governance Policies** | Configure natural-constraint policies over agent behavior and tool usage. | Encode our review rules as semantic policies enforced at the platform: "the curator may never write to a team domain without human review", "the researcher may not call web tools when serving the finserv domain." |
| `~` **IAM Policies (per-agent)** | Assign fine-grained permissions directly to an agent for specific resources. | Bind IAM so the researcher agent is read-only on the corpus bucket and the curator can write only to the staging/proposals prefix — mirroring our domain ACL down at the IAM layer, provable in an eval. |
| `✓` **Model Armor** | Inspects tool calls and responses to enforce content policies. | **Done.** Content bound for a shared space (writes, proposals, edits, Studio drafts) and agent answers on the guest read path pass through **Model Armor** (in-region, europe-west2): detected PII/secrets are **redacted in place** from the exact code-point ranges it returns — **redact-then-allow**, so a leaked password or card never lands in the corpus while the useful content still saves — and prompt-injection / responsible-AI hits are surfaced as flags (the agents' tool-only guardrails already bound an injected instruction). Env-gated on `BRAIN_MODEL_ARMOR_TEMPLATE`; Terraform enables the API, provisions the template (SDP + prompt-injection + RAI; malicious-URI is unsupported in europe-west2) and grants the brain `roles/modelarmor.user`. A pure pass-through no-op when off. |

## Connectivity and integration

| Feature | Purpose | How Hyper Brain could demonstrate it |
| --- | --- | --- |
| `✓` **MCP (Model Context Protocol)** | Standard protocol for secure agent-to-tool connectivity. | Our brain already serves its tools over MCP. Register that MCP server in the platform so **external** Gemini Enterprise agents (Claude, ChatGPT, an org's own agents) can discover and call our governed brain by URL. |
| `✓` **Skill Registry** | Central repository for creating and managing the tools/skills agents can call. | **Done.** The Skill Registry is the same official Agent Registry: **skills are surfaced to agents over MCP**, so a toolset is published by registering its **MCP server**. We register the brain's MCP server as a `Service` with an `mcpServerSpec` (`type = TOOL_SPEC`, content = the MCP `tools/list` for `search` / `answer` / `get_document` / `list_domains` / `propose_document`, JSON-RPC interface). The platform then catalogs each tool as a queryable **Skill** (an `McpServer` with a `tools` array). `brain registry sync` publishes it; `brain registry list`, `/api/registry`, and the Agents-page strip surface it — one governed, audited toolset any org agent can discover and reuse instead of re-implementing retrieval. |

## Quality and performance

| Feature | Purpose | How Hyper Brain could demonstrate it |
| --- | --- | --- |
| `✓` **GenAI Evaluation Service (Auto SxS)** | Online, side-by-side quality evaluation of agent output. | **Done.** A trace-centric eval workbench following the platform's evaluate procedure. On the Agents page a live run's **trace** (tool calls with args, transfers, and tool responses) is captured and shown, and an **adaptive-rubric** assessment grades the answer — criteria generated per query, each critiqued with a ✓/✗ verdict + reason (in-region, ~2 Gemini calls, mirroring `RubricGenerationConfig`/`RubricBasedMetric`). The **managed** service is exercised by `brain sxs`: a pairwise **"which prompt/model ships"** gate (managed groundedness + QA-quality autoraters) over the golden queries, printing win rates and a ship/keep verdict. The Vertex GenAI Evaluation Service is **us-central1-only**, so the managed metrics run cross-region while the UI rubrics stay in-region. |
| `◇` **Example Store** | Store and retrieve examples used for evaluation and optimization. | Keep golden Q&A pairs and exemplar good/bad drafts in the Example Store; feed them as few-shot to the curator and reuse the same set as eval fixtures, so examples have one home. |
| `✓` **Offline Evaluations** | Test agent behavior against datasets with no production impact. | We already run offline evals (answer correctness + the domain-isolation boundary) as Pillar 3 in CI. Move them onto the platform's Offline Evaluations for dashboards and history, keeping the isolation-boundary assertion as a hard gate. |
| `◇` **Online Monitors** | Continuously evaluate agent quality in production. | Add an Online Monitor that samples live answers for citation-groundedness and raises an alert (and a banner on the arch page) if groundedness regresses after a prompt or model change. |

## Observability and analysis

| Feature | Purpose | How Hyper Brain could demonstrate it |
| --- | --- | --- |
| `~` **Cloud Observability Suite (OpenTelemetry)** | Collects traces, logs, and metrics across the platform, gateway, and security layers. | Extend our tracing (see [`docs/observability.md`](observability.md)) to emit OTel from the agent and MCP server so spans flow into one suite spanning gateway → brain → Vertex. |
| `~` **Cloud Trace** | Captures execution paths showing an agent's reasoning progression. | Surface a per-answer Cloud Trace deep-link in the Agents live runner so you can inspect the coordinator → researcher → brain → Gemini path for any real question. |
| `~` **Topology** | Visualizes agent dependencies and interactions. | Our Agents map is hand-drawn; back it with the platform Topology so it reflects the **real** agent/tool/resource edges and updates itself as the team changes. |
| `◇` **Security Command Center integration** | Threat detection and unified security visibility for agent workloads. | Wire SCC to flag anomalous agent behavior (a spike in cross-domain tool calls, an unusual egress) and show a posture indicator on the architecture/admin page. |

## Sandbox capabilities

| Feature | Purpose | How Hyper Brain could demonstrate it |
| --- | --- | --- |
| `✓` **Code Execution** | Agents run Python inside an isolated sandbox. | **Done.** An **analyst** sub-agent runs Python in a server-side Google sandbox to compute quantitative answers rather than guess them; the Agents page shows the code + output and a dashed "sandbox" node. Default is Gemini's **in-region** built-in sandbox (`BuiltInCodeExecutor`); setting `enable_code_interpreter` swaps in the managed **Vertex AI Code Interpreter** (`VertexAiCodeExecutor`, provisioned by Terraform) — a heavier, stateful sandbox, at the cost of running **us-central1-only** (cross-region). Verified live end-to-end with the built-in sandbox. |
| `◇` **Computer Use** | Agents interact with UIs and applications programmatically. | A governed, opt-in "computer use" ingest agent that logs into a permitted internal web app behind a form to fetch content Studio cannot reach by plain URL, then runs it through the normal curate → review pipeline. |
| `◇` **Custom Containers (BYOC)** | Bring custom containerized environments for specialized workloads. | Package our ingest pipeline (Document AI parse → curate → land) as a BYOC image mounted into the agent runtime, so the curator can run our exact, provenance-stamping pipeline inside the sandbox. |

## Administrative interfaces

| Feature | Purpose | How Hyper Brain could demonstrate it |
| --- | --- | --- |
| `◇` **Agent Platform Console** | Central hub for governance, security, and monitoring across the agent lifecycle. | Link our arch/admin page to the Agent Platform Console, or mirror a lightweight "governance" tab that shows each agent's version, active policies, and latest eval status at a glance. |
| `~` **Gemini Enterprise Admin** | Manages licenses, instances, data connectors, and user permissions. | Map our domain-grant admin flow onto Gemini Enterprise Admin's connectors + permissions, so granting a team a domain also provisions its data connector — one action, not two. |
| `~` **Google Workspace Admin Console** | Governs Gemini Enterprise service availability and permissions for Workspace. | Gate brain availability by Workspace org unit / group, so an admin enables Hyper Brain for specific teams via existing Workspace groups — we already accept group-based domain grants, so this is the provisioning half. |

---

_Source: Google, [Gemini Enterprise Agent Platform — Agents](https://docs.cloud.google.com/gemini-enterprise-agent-platform/agents)
(feature names as published; MCP is labelled Model Context Protocol here, its standard meaning).
This is a snapshot for planning; verify current availability and names before building._
