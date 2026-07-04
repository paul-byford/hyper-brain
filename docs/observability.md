# Observability

Turning on tracing is configuration, not code (ARCHITECTURE.md section 10). Both
the agent and the brain export OpenTelemetry spans to the caller's **own** Cloud
Trace, in-tenancy; nothing goes to a third-party APM.

## What emits spans

- **The agent** is traced by ADK, aligned with the GenAI semantic conventions:
  model calls, tool calls, token counts and latency.
- **The brain** emits its own spans for each operation, so a single question fans
  out visibly into the work it caused:

  | Span | Attributes |
  |------|------------|
  | `brain.search` | `brain.domain_count`, `brain.top_k`, `brain.principal`, `brain.result_count` |
  | `brain.answer` | `brain.domain_count`, `brain.principal`, `brain.citation_count`, `brain.gap_count` |
  | `brain.get_document` | `brain.doc_id`, `brain.principal` |
  | `brain.propose_document` | `brain.domain`, `brain.principal` |

  Span attributes deliberately carry *shape* (how many domains, how many results),
  not raw query text, so traces are useful without becoming a second copy of
  sensitive content.

## Turning it on

- **Locally:** set `BRAIN_OTEL=console` to print spans, or `BRAIN_OTEL=gcp` to
  export to Cloud Trace (needs the `[mcp]` extra and credentials). Default is
  `none` (spans are cheap no-ops).
- **In the cloud:** set `enable_observability = true` in the tfvars. The Terraform
  [observability module](../infra/modules/observability/) enables the Cloud Trace,
  Monitoring and Logging APIs, and the brain and agent services are deployed with
  `BRAIN_OTEL=gcp`. Personal keeps this off (basic Cloud Trace has a generous free
  tier at demo volume); controlled turns it on for the full dashboards.

## The trace-viewer walkthrough

1. Deploy with observability on: `enable_observability = true`, then `./brain up`.
2. Ask the agent a question (via `adk web` or the deployed agent UI), for example
   *"how do we detect fraud in real time?"*.
3. Open **Cloud Trace** in the Google Cloud console
   (`https://console.cloud.google.com/traces/list?project=<your-project>`).
4. Pick the most recent trace. You will see one question fan out: the agent's
   model span, a tool span for the `search`/`answer` call, and beneath it the
   brain's `brain.search` / `brain.answer` span with its domain and result counts,
   plus latency for each hop.
5. Switch identity (a finserv-scoped caller) and repeat: the `brain.domain_count`
   attribute on the span reflects the reduced scope, so the isolation boundary is
   visible in the traces too.

Traces and logs stay in the user's own Cloud Observability; the personal profile
gets basic Cloud Trace, the controlled profile the full Agent Observability
dashboards and Unified Trace Viewer.
