# Implementation plan

Companion to `ARCHITECTURE.md` and `docs/LINEAGE.md`. This is the build order:
what gets created, in what sequence, and how each phase is proven before the
next. 

## Target repository layout

```
hyper-brain/
  README.md                     # what it is, the one command, quickstart
  ARCHITECTURE.md               # design rationale
  IMPLEMENTATION-PLAN.md        # this file
  docs/
    LINEAGE.md                  # Karpathy -> gbrain -> ours, with attribution
    diagrams/
  LICENSE                       # Apache-2.0
  CONTRIBUTING.md               # how to change corpus and code
  CODEOWNERS
  .editorconfig
  .gitignore
  .github/
    workflows/ci.yml            # lint, terraform validate, unit tests, adk eval
    pull_request_template.md
  brain                         # POSIX entrypoint (the one command)
  brain.ps1                     # Windows entrypoint (same steps)
  Makefile                      # up / down / index / ingest / test / eval / lint aliases
  config/
    personal.tfvars
    controlled.tfvars
    personal.policy.yaml        # domain -> allowed group/identity ACL
    controlled.policy.yaml
    sources.yaml                # ingestion sources -> adapter type + domain
    profiles.md                 # documents the single switch
  infra/
    bootstrap/                  # idempotent state-bucket creation
    providers.tf variables.tf main.tf outputs.tf
    modules/
      storage/                  # GCS buckets (corpus, index, state)
      registry/                 # Artifact Registry
      run_service/              # Cloud Run services (brain, agent, ui)
      run_job/                  # Cloud Run Jobs (indexer, ingestion)
      iam/                      # invoker groups, service accounts
      vertex/                   # Vertex AI (embeddings, Gemini) enablement
      observability/            # Cloud Trace / Monitoring / Logging enablement
  app/                          # the brain (MCP retrieval service)
    pyproject.toml
    Dockerfile
    brain_app/
      server.py                 # MCP over streamable HTTP (+ gated propose_document)
      auth/                     # OIDC verify + domain ACL resolution
      retrieval/                # semantic + BM25 + link graph, RRF fusion
      embeddings/               # provider interface + Vertex adapter
      indexer/                  # chunk, embed, build artefact
      ingest/                   # source-agnostic pipeline
        pipeline.py             # fetch -> parse -> curate -> stamp -> land
        sources.py              # adapter registry (keyed by type)
        state.py                # per-source cursor for incremental sync
        adapters/               # local, web, git (bank extends here)
        parsers/                # markdown, html, pdf (Document AI), transcript
        curate.py               # optional in-tenancy Gemini raw->wiki step
      config.py                 # loads BRAIN_PROFILE + policy
    tests/
  agent/                        # the ADK demo agent
    agent.py                    # LlmAgent + MCPToolset(StreamableHTTP, bearer)
    Dockerfile                  # deploy to Cloud Run / Agent Engine
    evals/
      golden.evalset.json       # multi-turn retrieval + answer quality
      isolation.test.json       # finserv-eng caller must not see recruitment
      test_agent_eval.py        # pytest AgentEvaluator, runs in CI
  ui/                           # Brain Explorer web app
    (static SPA: graph viz, domain browser, search/answer panel, identity panel)
  corpus/
    domains.yaml                # domain registry
    finserv-ai-engineering/*.md    # domain 1: modern AI engineering for financial services
    enterprise-ai-recruitment/*.md # domain 2: modern AI recruitment for enterprises
  raw/                          # ingestion staging (drop sources here, Karpathy-style)
  scripts/
    preflight.sh                # honest-prerequisites gate
```

## Phase 0: repository signals

Establish the project surface first: `README.md`, `LICENSE`
(Apache-2.0), `CONTRIBUTING.md`, `CODEOWNERS`, `.editorconfig`, `.gitignore`, and
a PR template. The CI workflow encodes the three-pillar testing strategy
(`ARCHITECTURE.md` section 10) from day one, even against a skeleton:

- functional: `terraform fmt -check`, `terraform validate`, lint, `pytest`;
- security: `bandit` (SAST), `pip-audit` (dependencies), `gitleaks` (secrets),
  and `checkov`/`tfsec` plus `conftest` (infra policy-as-code);
- AI evals: the offline `adk eval` step (deterministic metrics, no paid service).

`git init`. Exit criterion: CI green on the skeleton with all three pillars wired.

## Phase 1: retrieval core, offline

Build and test the brain with no cloud, so the interesting logic is proven in
isolation.

- `indexer/`: chunk markdown by heading and size, parse `[[wikilinks]]` into a
  link graph, attach domain and document frontmatter.
- `embeddings/`: provider interface plus a Vertex adapter plus a deterministic
  fake for tests.
- `retrieval/`: cosine top-k, BM25, link-neighbour expansion, reciprocal-rank
  fusion, and the domain filter applied before any signal runs. Both modes:
  `search` (ranked chunks) and `answer` (synthesis, with a fake LLM in tests).
- Build a local index from the starter `corpus/` and query it in unit tests,
  including the isolation test (a finserv-ai-engineering caller never receives an
  enterprise-ai-recruitment chunk). Exit criterion: retrieval, fusion and
  isolation pass offline.

## Phase 2: ingestion pipeline and adapters, offline

Placed here on purpose: batch ingestion is fully offline-testable (local and a
web adapter driven by a fixture, deterministic parse, a fake curate), so it
follows the same "logic before cloud" discipline as Phase 1 and makes "add new
data" real before any serving exists. Implements the batch-ingestion path from
`ARCHITECTURE.md` section 12.

- `ingest/pipeline.py`: the source-agnostic pipeline (`fetch -> parse -> optional
  curate -> stamp frontmatter and provenance -> land`), with idempotent upsert by
  checksum.
- `ingest/sources.py` + `config/sources.yaml`: the adapter registry keyed by
  `type`, and the source config that assigns each source a domain.
- `ingest/adapters/`: the three demo adapters, local files, web/URL, git repo,
  each implementing the one `SourceAdapter` interface the bank extends.
- `ingest/parsers/`: markdown passthrough plus HTML, with a PDF parser stubbed
  behind the Document AI seam (real parse wired with cloud later); a deterministic
  fake for tests.
- `ingest/curate.py`: the optional raw-to-wiki step behind an interface, with a
  deterministic fake offline (real Gemini in a later phase).
- `ingest/state.py`: per-source cursor so re-runs only touch what changed.
- Tests (all three pillars): adapter-contract tests, a parse fixture, idempotent
  and incremental land, provenance stamping, and the security test that an adapter
  cannot land a document outside its configured domain, plus a basic PII scan on
  landed content.
- Exit criterion: `make ingest` turns a dropped source (a file, a fixture web
  page, a small repo) into provenance-stamped markdown in `corpus/`, re-running is
  idempotent, and the ingest-time isolation test passes. All offline.

## Phase 3: serving, identity, and the agent write path

- `server.py`: MCP over streamable HTTP exposing `search`, `answer`,
  `get_document`, `list_domains`.
- `auth/`: verify the Google-signed OIDC token, map identity to allowed domains,
  enforce the filter.
- **Agent-authored ingestion** (`propose_document`, `ARCHITECTURE.md` section 12):
  a write-scoped MCP tool that reuses the Phase 2 pipeline to land a proposal as a
  quarantined change (a branch/PR), never a live write. Write scope is separate
  from read scope, and the proposal is domain-validated.
- `config.py`: read `BRAIN_PROFILE`, load the matching policy.
- `Dockerfile`: minimal Python image; loads the index from GCS on startup;
  emits OpenTelemetry spans.
- Pillar 2 security tests land here: a token scoped to one domain cannot retrieve
  another; unsigned, expired, wrong-audience or wrong-issuer tokens are rejected;
  and a read-only caller cannot invoke `propose_document`.
- Exit criterion: run the container locally, connect a real MCP client, see
  domain-scoped results gated by a token, land a document via `propose_document`
  as a reviewable change, and the isolation, token-rejection and write-scope tests
  pass.

## Phase 4: the ADK agent and evals

- `agent/agent.py`: an ADK `LlmAgent` on a Gemini model (Vertex), tools attached
  via `MCPToolset(StreamableHTTPConnectionParams(url, headers=bearer))`, with
  `tool_filter` limited to the brain's tools.
- `agent/evals/`: `golden.evalset.json` and `isolation.test.json`, plus
  `test_agent_eval.py` using `AgentEvaluator.evaluate` with deterministic metrics
  (`tool_trajectory`, `response_match`) so it runs free in CI. Document the paid
  LLM-judged metrics as a controlled-profile opt-in.
- Exit criterion: `adk web` chats with the agent against the local brain; `adk
  eval` / pytest passes the golden set and the isolation eval.

## Phase 5: infrastructure as Terraform (2 to 3 days)

- `bootstrap/`: create-if-not-exists state bucket.
- `modules/`: storage, registry, run_service (brain, agent, ui), run_job, iam,
  vertex, observability.
- `config/*.tfvars` and `config/*.policy.yaml`: the personal and controlled
  profiles, including the observability and eval-service toggles (off for
  personal, available for controlled).
- Controlled profile (Option B): author the controlled-only resources (VPC-SC
  perimeter, internal ingress, Workforce Identity Federation, control-plane policy
  source) behind the profile switch, and add CI that runs `terraform validate`,
  a stub-var `plan` where feasible, and conftest/checkov assertions (private
  buckets, non-public service, least-privilege, perimeter present). Do not apply
  it in the personal demo.
- Exit criterion: `terraform apply` with `personal.tfvars` stands up brain, agent
  and UI in a real personal project and `terraform destroy` removes them cleanly;
  the controlled profile passes validate, plan-where-feasible and policy checks in
  CI.

## Phase 6: the one command

- `scripts/preflight.sh`: auth, project, billing, API and role checks, each with
  an exact remediation on failure.
- `brain` and `brain.ps1`: preflight, terraform apply, build and push images, run
  the index job, print the brain URL, the agent UI URL, the Explorer URL, and the
  MCP config block.
- Subcommands: `up`, `down`, `index`, `ingest`, `grant`, `connect`, `agent`,
  `ui`, `status`, `eval`.
- Exit criterion: on a clean personal project, `brain up` yields a queryable
  brain plus a running agent and UI, and running it twice is idempotent.

## Phase 7: the UI

- `ui/`: Brain Explorer SPA. Graph visualisation of the `[[wikilink]]` graph
  coloured by domain, domain browser and markdown viewer, a search/answer panel
  showing ranked hits, citations and the gap statement, and a "who am I and what
  can I see" identity panel. It also shows document provenance (source, fetched_at)
  and can trigger an ingestion of a dropped source for a live "add data" demo.
  IAM-gated, holds no secrets, renders only what the brain returns.
- The `adk web` dev UI is wired in phase 4 already; this phase adds the richer
  custom surface.
- Exit criterion: an evaluator can, in a browser, see the graph, run a query,
  read a cited answer, and watch isolation change as identity changes.

## Phase 8: observability, corpus and docs (1 day)

- `modules/observability/`: enable Cloud Trace, Monitoring and Logging; confirm
  agent and brain spans appear; document the trace-viewer walkthrough.
- Two domains under `corpus/`, modern AI engineering for financial services and
  modern AI recruitment for enterprises, each a small set of cutting-edge,
  genuinely useful markdown notes with cross-`[[links]]` within a domain, so
  semantic retrieval, link expansion and the isolation boundary are all
  demonstrable out of the box.
- Finish `README.md` quickstart, `config/profiles.md`, and confirm the "what this
  is and is not" section (`ARCHITECTURE.md` section 14).

## Phase 9: verification pass (half a day)

- Confirm the "facts to verify" list (`ARCHITECTURE.md` section 16) against live
  documentation and adjust model names, product names post-rebrand, pricing and
  flags accordingly.
- End-to-end rehearsal: `brain up`, `brain ingest` a fresh source and watch it
  appear, add a document via the agent's `propose_document`, chat via the agent
  UI, run a query in the Explorer, prove isolation, run `brain eval`, open a
  trace, `brain down`, confirm near-zero residual cost.

## Sequencing rationale

Logic before cloud (phases 1 to 4) so the load-bearing retrieval, ingestion,
isolation and the agent are proven where they are cheap to test. Ingestion sits
at phase 2, right after the retrieval core, because "add new data" is central to
the demo and is fully testable offline; the agent write path (`propose_document`)
then rides on both the pipeline and the serving layer at phase 3. Infrastructure
(phase 5) comes before the wrapper (phase 6) so the one command is a thin, honest
orchestration over already-working pieces. Evals arrive with the agent (phase 4)
so quality is guarded from the moment the agent exists, not bolted on at the end.

## Decisions locked

- **Cloud target: GCP.**
- **Controlled profile: Option B.** The controlled profile is authored now in the
  same Terraform modules as personal, behind the profile switch, and is proven by
  `terraform validate`, `terraform plan` (with stub org vars where feasible) and
  conftest/checkov policy assertions in CI. It is **not** live-applied in the
  personal demo; the personal profile is the one that actually applies and runs.
  Controlled resources that cannot `plan` without an Organization (for example
  VPC-SC access policies) fall back to `validate` plus static policy checks, and
  the docs say so plainly rather than faking a green plan. The paid Vertex Gen AI
  Evaluation and Agent Observability toggles are wired as variables defaulted off;
  only the free tier is exercised live.
- **Ingestion: both paths.** Batch adapter ingestion (phase 2) and the gated
  agent `propose_document` write tool (phase 3), both landing through a review
  gate (PR for controlled, `--auto` for the personal demo), with parse and curate
  in-tenancy. Continuous auto-sync is deferred as an opt-in future, not a default.

## Open decisions

- UI framework for Brain Explorer (a lightweight SPA with a graph library), and
  whether the `adk web` dev UI is sufficient for the first demo while the custom
  Explorer follows.
