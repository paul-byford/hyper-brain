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
| `◇` **Agent Studio** | Collaborative, visual (no-code) workspace to discover models, engineer prompts, and assemble agents for fast prototyping. | Add an admin-only "Agent Studio" tab beside Content Studio where you compose a new specialist sub-agent visually — name, system prompt, and an allow-list of our MCP tools — preview it against a sample question, then register it into the live team shown on the Agents page. |
| `✓` **Agent Development Kit (ADK)** | Code-first framework for granular control of agent logic, tools, and multi-agent orchestration. | We already run an ADK coordinator delegating to researcher + curator. Deepen it: add a third specialist (a "reviewer" that pre-checks proposals against domain policy) and expose ADK `transfer_to_agent` hops as first-class steps in the live run. |
| `◇` **Agent Garden** | Library of prebuilt agent samples that accelerate common patterns. | Ship a "recipes" gallery of prebuilt brain agents (onboarding buddy, release-notes writer, meeting-notes curator) seeded from ADK samples, each one-click addable to a workspace and pre-wired to the right domains. |
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
| `◇` **Sessions** | Maintain interaction history within a single conversation for ongoing context. | Our live agent run is one-shot per query. Add Sessions so a follow-up ("and how does that compare to last quarter?") keeps context in the Agents page runner, with the session id shown in the trace. |
| `◇` **Memory Bank** | Extracts, stores, and retrieves personalized user info across sessions. | Give each signed-in user a Memory Bank so the brain remembers their recurring interests, preferred domains, and terminology, and personalizes answers — stored per-identity and clamped by the same domain ACL, so personalization never crosses a boundary. |

## Security and governance

| Feature | Purpose | How Hyper Brain could demonstrate it |
| --- | --- | --- |
| `◇` **Agent Identity (SPIFFE)** | A unique, IAM-native, auditable ID per agent — a granular alternative to shared service accounts. | Give the researcher and curator each their **own** SPIFFE agent identity instead of one shared SA, so Cloud Audit Logs attribute every corpus read or proposal to a specific agent. Fits our existing "least-privilege service account per workload" story. |
| `~` **Agent Identity Auth Manager** | Handles OAuth and refresh-token complexity for secure tool calls on a user's behalf. | We already run an OAuth 2.1 AS for callers. Use Auth Manager for the other direction: let the curator call a user's own connector (their Drive, a wiki) on their behalf with managed refresh, so Studio can draft from sources only that user can see. |
| `~` **Agent Registry** | Central, queryable store of agent metadata: versions, frameworks, capabilities, MCP tool names, annotations. | The Agents page already renders a registry-like view; back it with the real Agent Registry so agent versions, prompt hashes, and MCP tool names are queryable and audited, not just drawn. |
| `◇` **Semantic Governance Policies** | Configure natural-constraint policies over agent behavior and tool usage. | Encode our review rules as semantic policies enforced at the platform: "the curator may never write to a team domain without human review", "the researcher may not call web tools when serving the finserv domain." |
| `~` **IAM Policies (per-agent)** | Assign fine-grained permissions directly to an agent for specific resources. | Bind IAM so the researcher agent is read-only on the corpus bucket and the curator can write only to the staging/proposals prefix — mirroring our domain ACL down at the IAM layer, provable in an eval. |
| `◇` **Model Armor** | Inspects tool calls and responses to enforce content policies. | Run Model Armor over Studio drafts and agent answers to catch PII/secret leakage **before** content lands in the commons or is shown to a guest — a natural guard given our open commons and guest read path. |

## Connectivity and integration

| Feature | Purpose | How Hyper Brain could demonstrate it |
| --- | --- | --- |
| `✓` **MCP (Model Context Protocol)** | Standard protocol for secure agent-to-tool connectivity. | Our brain already serves its tools over MCP. Register that MCP server in the platform so **external** Gemini Enterprise agents (Claude, ChatGPT, an org's own agents) can discover and call our governed brain by URL. |
| `◇` **Skill Registry** | Central repository for creating and managing the tools/skills agents can call. | Publish our brain tools (`search`, `answer`, `get_document`, `propose_document`) as versioned Skills in the Skill Registry, so any agent across the org reuses one governed, audited toolset instead of re-implementing retrieval. |

## Quality and performance

| Feature | Purpose | How Hyper Brain could demonstrate it |
| --- | --- | --- |
| `◇` **GenAI Evaluation Service (Auto SxS)** | Online, side-by-side quality evaluation of agent output. | Add an Auto SxS eval that pits two prompt/model versions of the researcher against real queries and reports which grounds its answers better — the "which prompt ships" gate for our versioned prompts. |
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
