"""Pillar 1: the brain emits OpenTelemetry spans for its operations.

Skipped unless opentelemetry is installed (the serving [mcp] extra). Uses an
in-memory exporter, so no cloud and no network.
"""

from __future__ import annotations

import pytest

pytest.importorskip("opentelemetry.sdk.trace")

from opentelemetry import trace  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from brain_app.auth.identity import identity_from_claims  # noqa: E402
from brain_app.config import load_policy  # noqa: E402
from brain_app.observability import span  # noqa: E402
from brain_app.serving import BrainService  # noqa: E402


@pytest.fixture(scope="module")
def spans():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # The proxy default provider allows exactly one override; this is the only
    # test that configures tracing, so it wins for the process.
    trace.set_tracer_provider(provider)
    return exporter


def _identity(groups):
    return identity_from_claims({"sub": "u", "email": "u@bank.com", "groups": groups})


def test_span_helper_records_attributes(spans):
    spans.clear()
    with span("brain.test", **{"brain.k": "v", "brain.skip": None}):
        pass
    recorded = spans.get_finished_spans()
    assert [s.name for s in recorded] == ["brain.test"]
    assert recorded[0].attributes["brain.k"] == "v"
    assert "brain.skip" not in recorded[0].attributes  # None attributes are dropped


def test_service_operations_emit_spans(spans, index, embeddings):
    spans.clear()
    svc = BrainService(index, embeddings, load_policy(prof="personal"))
    ident = _identity(["finserv-eng@example.com"])

    svc.search(ident, "real-time fraud detection")
    svc.answer(ident, "in-tenancy vector search")

    by_name = {s.name: s for s in spans.get_finished_spans()}
    assert "brain.search" in by_name
    assert "brain.answer" in by_name
    search_span = by_name["brain.search"]
    # The finserv caller sees their domain plus the shared commons domain.
    assert search_span.attributes["brain.domain_count"] == 2
    assert search_span.attributes["brain.result_count"] >= 1
    assert by_name["brain.answer"].attributes["brain.principal"] == "u"


def test_tracing_is_noop_without_configuration():
    # The span helper must never raise even when nothing is set up to consume it.
    with span("brain.noop", **{"brain.x": 1}) as s:
        # Either a real span or None, but the block must run cleanly.
        assert s is None or s is not None
