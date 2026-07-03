"""Pillar 1 (functional): the pipeline lands, stamps provenance, and is idempotent."""

from __future__ import annotations

from brain_app.indexer.build import build_index
from brain_app.indexer.chunk import parse_frontmatter
from brain_app.ingest import ingest_source
from brain_app.ingest.models import SKIPPED, UPDATED, WRITTEN
from brain_app.ingest.sources import SourceConfig

from .conftest import FINSERV

# Fixed clock and run id so landed files are byte-identical across runs.
NOW = "2026-07-03T00:00:00+00:00"
RUN = "ingest-test000000"


def _local_source(raw_dir) -> SourceConfig:
    return SourceConfig(
        id="raw-test",
        type="local",
        domain=FINSERV,
        curate=False,
        options={"path": str(raw_dir), "glob": "*.md"},
    )


def _run(raw_dir, corpus, state):
    return ingest_source(
        _local_source(raw_dir),
        corpus,
        state_dir=state,
        run_id=RUN,
        now=NOW,
    )


def test_lands_with_provenance_frontmatter(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "note.md").write_text("---\ntitle: My Note\n---\n\n# My Note\n\nBody.\n", "utf-8")
    corpus = tmp_path / "corpus"

    report = _run(raw, corpus, tmp_path / "state")
    assert report.written == 1

    landed = corpus / FINSERV / "my-note.md"
    assert landed.is_file()
    meta, body = parse_frontmatter(landed.read_text(encoding="utf-8"))
    assert meta["domain"] == FINSERV
    assert meta["source"] == "raw-test"
    assert meta["source_url"].startswith("file://")
    assert meta["fetched_at"] == NOW
    assert meta["ingest_run"] == RUN
    assert len(meta["checksum"]) == 64
    assert "Body." in body


def test_reingest_is_idempotent_byte_for_byte(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "note.md").write_text("# Note\n\nStable body.\n", "utf-8")
    corpus = tmp_path / "corpus"
    state = tmp_path / "state"

    first = _run(raw, corpus, state)
    landed = corpus / FINSERV / "note.md"
    content_after_first = landed.read_text(encoding="utf-8")

    second = _run(raw, corpus, state)
    assert first.written == 1
    assert second.written == 0 and second.skipped == 1
    # Unchanged source leaves the landed file byte-for-byte identical.
    assert landed.read_text(encoding="utf-8") == content_after_first


def test_incremental_only_touches_changed_items(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "a.md").write_text("# A\n\nFirst.\n", "utf-8")
    (raw / "b.md").write_text("# B\n\nStays.\n", "utf-8")
    corpus = tmp_path / "corpus"
    state = tmp_path / "state"

    _run(raw, corpus, state)
    b_before = (corpus / FINSERV / "b.md").read_text(encoding="utf-8")

    # Change only a.md.
    (raw / "a.md").write_text("# A\n\nSecond, edited.\n", "utf-8")
    report = _run(raw, corpus, state)

    statuses = {r.doc_id.rsplit("/", 1)[-1]: r.status for r in report.results}
    assert statuses["a"] == UPDATED
    assert statuses["b"] == SKIPPED
    assert (corpus / FINSERV / "b.md").read_text(encoding="utf-8") == b_before
    assert "Second, edited." in (corpus / FINSERV / "a.md").read_text(encoding="utf-8")


def test_new_status_on_first_land(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "note.md").write_text("# Note\n\nBody.\n", "utf-8")
    report = _run(raw, tmp_path / "corpus", tmp_path / "state")
    assert [r.status for r in report.results] == [WRITTEN]


def test_landed_document_indexes_cleanly(tmp_path, embeddings):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "topic.md").write_text("# Topic\n\nRetrieval augmented generation.\n", "utf-8")
    corpus = tmp_path / "corpus"
    _run(raw, corpus, tmp_path / "state")

    index = build_index(corpus, embeddings=embeddings, provider_name="fake")
    assert FINSERV in index.domains
    assert any(c.doc_id == f"{FINSERV}/topic" for c in index.chunks)
