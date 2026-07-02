# hyper-brain

A one-command **company brain**: a searchable, versioned knowledge base that your
AI coding agents can query, with multiple knowledge domains isolated from each
other and a data boundary that stays inside your own cloud tenancy.

One person runs a single command and gets a working brain on Google Cloud;
teammates join cheaply. It is near-zero cost when idle and tears down cleanly. The
same repository serves an effortless personal demo and a project that could be deployed inside a cost- and security-controlled environment, with only configuration changing between the two.

- **Design rationale:** [`ARCHITECTURE.md`](ARCHITECTURE.md)
- **Intellectual lineage** (Karpathy's LLM wiki, Garry Tan's gbrain, and what we
  keep or replace): [`docs/LINEAGE.md`](docs/LINEAGE.md)
- **Build plan and status:** [`IMPLEMENTATION-PLAN.md`](IMPLEMENTATION-PLAN.md)

## How it works, in one picture

```
corpus (markdown + [[wikilinks]], under git)
        |  index job: chunk, embed (Vertex AI, in-tenancy), build artefact
        v
index artefact per domain in Google Cloud Storage
        ^  loaded in memory on cold start
        |
Brain service (Cloud Run, scale-to-zero)  --- MCP over HTTP --->  agents
  retrieval: semantic + keyword + link graph, fused
  auth: Cloud Run IAM at the edge + verified OIDC + per-domain ACL in-app
        ^
        |  consumed by
Google ADK agent (Gemini on Vertex)  +  Brain Explorer web UI
```

Knowledge is plain markdown in this repo, so changing what the brain knows is a
reviewable, revertible pull request. There is no database running when nobody is
querying: the index is a file in your own bucket, loaded into a scale-to-zero
container. Embeddings and answer synthesis use first-party Vertex AI models inside
your own tenancy and region, so sensitive content never goes to a third party.

## The two audiences, one codebase

A single switch, `BRAIN_PROFILE` (`personal` or `controlled`), selects one file of
Terraform variables and one policy file. Nothing else branches. The personal demo
exercises the same identity primitive (OIDC plus IAM), the same serving path, the
same agent and UI, and the same isolation logic that a controlled deployment would
use. See [`config/profiles.md`](config/profiles.md) and `ARCHITECTURE.md` section
3.

## Quickstart (target experience)

Prerequisites: the `gcloud` and
`terraform` CLIs, and a Google Cloud project you can use with billing enabled and
the required APIs allowed. In a controlled environment, project creation, spend
approval and API allow-listing are gated by your organisation; the command detects
these and tells you exactly what to fix rather than pretending it can do them.

```sh
./brain up          # preflight, provision, seed the starter corpus, print how to connect
./brain ingest      # pull configured sources (files, web, git) into the corpus
./brain grant alice@example.com --domains finserv-ai-engineering
./brain connect     # prints the MCP config block for your agent
./brain down        # clean teardown
```

New knowledge is added through adapters (`config/sources.yaml`) or by an agent's
gated `propose_document` tool, and always lands as reviewable, provenance-stamped
markdown (see `ARCHITECTURE.md` section 12).

## Project status

This repository is being built in the phases described in
[`IMPLEMENTATION-PLAN.md`](IMPLEMENTATION-PLAN.md). Progress:

- **Implemented:** the offline retrieval core (chunking, `[[wikilink]]` graph,
  hybrid semantic + keyword + link retrieval with reciprocal-rank fusion, `search`
  and `answer` modes, per-domain isolation), the two starter corpora, and the
  test suite. Runs with no cloud and no cost.
- **In progress:** the adapter-based ingestion pipeline and the agent
  `propose_document` write path, the MCP serving layer and OIDC auth, the Google
  ADK agent and evals, the Terraform, the one-command entrypoint, and the Brain
  Explorer UI.

The `brain up` experience above is the target; today you can build and query the
brain locally (see below).

## Run the core locally

```sh
make install        # create a virtualenv and install the app with dev tools
make test           # run the full test suite (functional + security + eval pillars)
make index          # build a local index artefact from the starter corpus
```

## Testing

Testing is a first-class deliverable, organised as three pillars, all run in CI
(`ARCHITECTURE.md` section 10):

1. **Deterministic functional** tests of the retrieval logic.
2. **Security** tests: domain isolation and token verification, plus static
   analysis, dependency audit, secret scanning and infrastructure policy-as-code.
3. **Non-deterministic AI evals**: agent trajectory and answer quality, including
   an isolation eval, with a free offline tier and a richer paid tier for the
   controlled profile.

## Licence

Apache-2.0. See [`LICENSE`](LICENSE). Retrieval design adapted from the
MIT-licensed [gbrain](https://github.com/garrytan/gbrain); see `docs/LINEAGE.md`
for attribution.
