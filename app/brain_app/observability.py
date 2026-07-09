"""Optional OpenTelemetry tracing for the brain (ARCHITECTURE.md section 10).

ADK traces the agent side itself; this instruments the brain's own operations so a
single question fans out into visible spans (`brain.search`, `brain.answer`, ...)
in the Cloud Trace viewer, next to the agent's model and tool spans.

Tracing is optional and lazy on two levels, so the offline core stays
dependency-free:

- if ``opentelemetry`` is not installed at all, the instrumentation degrades to a
  no-op context manager;
- if it is installed but no exporter is configured (``BRAIN_OTEL=none``, the
  default), spans are cheap no-ops via the default tracer.

Turning tracing on is configuration, not code: set ``BRAIN_OTEL`` and the
observability APIs (enabled by the Terraform observability module).
"""

from __future__ import annotations

import os
from contextlib import contextmanager

SERVICE_NAME = "hyper-brain"


def configure(exporter: str | None = None) -> bool:
    """Set up a tracer provider from ``BRAIN_OTEL`` (``none`` | ``console`` | ``gcp``).

    Returns True if tracing was turned on. Safe to call once at server startup;
    a missing opentelemetry install or an unknown exporter is a quiet no-op.
    """
    exporter = (exporter or os.environ.get("BRAIN_OTEL", "none")).lower()
    if exporter == "none":
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
    except ImportError:
        return False

    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
    if exporter == "console":
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    elif exporter == "gcp":
        # In-tenancy: spans go to the caller's own Cloud Trace (section 10). Use the
        # SIMPLE processor, not batch: Cloud Run throttles CPU to ~zero once a
        # request returns, freezing a batch processor's background flush thread, so
        # buffered spans never export. Simple exports synchronously on span end,
        # while the request still holds CPU, and preserves scale-to-zero.
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

        provider.add_span_processor(SimpleSpanProcessor(CloudTraceSpanExporter()))
    elif exporter in ("otlp", "langfuse"):
        # Optional: export the same spans to any OpenTelemetry OTLP endpoint, e.g. a
        # self-hosted (in-tenancy) or cloud Langfuse for LLM-native tracing, prompt
        # and eval linkage. The endpoint/auth come from the standard OTEL_EXPORTER_OTLP_*
        # env vars, so pointing at Langfuse is configuration, not code. Lazy import so
        # this stays a no-op unless the [otlp] extra is installed.
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        except ImportError:
            return False
        provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter()))
    else:
        return False

    trace.set_tracer_provider(provider)
    return True


@contextmanager
def span(name: str, **attributes):
    """Start a span, or a no-op if opentelemetry is unavailable.

    ``None``-valued attributes are dropped so callers can pass optional context
    without guarding each one.
    """
    try:
        from opentelemetry import trace
    except ImportError:
        yield None
        return

    tracer = trace.get_tracer(SERVICE_NAME)
    with tracer.start_as_current_span(name) as current:
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(key, value)
        yield current
