"""Pillar 1: ingested documents carry provenance through to the index (for the UI)."""

from __future__ import annotations

from brain_app.indexer.build import build_index
from brain_app.indexer.chunk import load_document
from brain_app.retrieval.index import BrainIndex


def test_load_document_reads_provenance_frontmatter(tmp_path):
    path = tmp_path / "note.md"
    path.write_text(
        "---\ntitle: N\ndomain: d\nsource: raw-finserv\n"
        "source_url: file:///x\nfetched_at: '2026-07-03T00:00:00+00:00'\n---\n\n# N\n\nBody.\n",
        encoding="utf-8",
    )
    document, _ = load_document(path, domain_hint="d")
    assert document.source == "raw-finserv"
    assert document.source_url == "file:///x"
    assert document.fetched_at == "2026-07-03T00:00:00+00:00"


def test_hand_written_doc_has_no_provenance(tmp_path):
    path = tmp_path / "note.md"
    path.write_text("---\ntitle: N\ndomain: d\n---\n\n# N\n\nBody.\n", encoding="utf-8")
    document, _ = load_document(path, domain_hint="d")
    assert document.source is None
    assert document.fetched_at is None


def test_provenance_survives_index_roundtrip(tmp_path, embeddings):
    corpus = tmp_path / "corpus" / "d"
    corpus.mkdir(parents=True)
    (corpus / "ingested.md").write_text(
        "---\ntitle: Ingested\ndomain: d\nsource: raw-finserv\n"
        "fetched_at: '2026-07-03T00:00:00+00:00'\n---\n\n# Ingested\n\nBody.\n",
        encoding="utf-8",
    )
    index = build_index(tmp_path / "corpus", embeddings=embeddings, provider_name="fake")

    out = tmp_path / "index.json"
    index.save(out)
    loaded = BrainIndex.load(out)
    doc = loaded.documents["d/ingested"]
    assert doc.source == "raw-finserv"
    assert doc.fetched_at == "2026-07-03T00:00:00+00:00"
