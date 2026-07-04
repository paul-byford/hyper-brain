"""Pillar 1 (functional): the optional curate seam.

Offline the curator is a deterministic passthrough; a custom curator is invoked
only when a source opts in with ``curate: true``; and the Gemini curator rewrites
via an injected model call (the real one is a lazy in-tenancy Vertex call).
"""

from __future__ import annotations

from brain_app.ingest import ingest_source
from brain_app.ingest.curate import GeminiCurator, PassthroughCurator, get_curator
from brain_app.ingest.models import ParsedDoc
from brain_app.ingest.sources import SourceConfig

from .conftest import FINSERV

NOW = "2026-07-03T00:00:00+00:00"
RUN = "ingest-test000000"


class _ShoutCurator:
    def curate(self, doc: ParsedDoc) -> ParsedDoc:
        return ParsedDoc(body=doc.body.upper(), title=doc.title, tags=doc.tags)


def test_passthrough_is_a_noop():
    doc = ParsedDoc(body="untouched", title="t", tags=["x"])
    assert get_curator("off").curate(doc) == doc
    assert isinstance(get_curator(), PassthroughCurator)


def test_get_curator_returns_gemini():
    assert isinstance(get_curator("gemini"), GeminiCurator)


def test_gemini_curator_rewrites_via_injected_model():
    # The real model call is injectable, so the transform is testable with no cloud.
    curator = GeminiCurator(generate=lambda prompt: "# Clean\n\nRewritten with [[link]].")
    out = curator.curate(ParsedDoc(body="messy raw text", title="t", tags=["x"]))
    assert "# Clean" in out.body
    assert out.title == "t" and out.tags == ["x"]


def test_custom_curator_runs_only_when_source_opts_in(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "note.md").write_text("# Note\n\nlowercase body.\n", "utf-8")
    corpus = tmp_path / "corpus"

    source = SourceConfig(
        id="raw-test",
        type="local",
        domain=FINSERV,
        curate=True,
        options={"path": str(raw), "glob": "*.md"},
    )
    ingest_source(
        source, corpus, state_dir=tmp_path / "s", curator=_ShoutCurator(), run_id=RUN, now=NOW
    )
    landed = (corpus / FINSERV / "note.md").read_text(encoding="utf-8")
    assert "LOWERCASE BODY." in landed
