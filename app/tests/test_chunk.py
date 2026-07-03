from __future__ import annotations

from brain_app.indexer.chunk import (
    build_chunks,
    extract_wikilinks,
    load_document,
    parse_frontmatter,
)

from .conftest import CORPUS, FINSERV


def test_parse_frontmatter_splits_meta_and_body():
    meta, body = parse_frontmatter("---\ntitle: X\ndomain: d\n---\nhello world")
    assert meta == {"title": "X", "domain": "d"}
    assert body.strip() == "hello world"


def test_parse_frontmatter_absent():
    meta, body = parse_frontmatter("no frontmatter here")
    assert meta == {}
    assert body == "no frontmatter here"


def test_extract_wikilinks_dedupes_and_handles_alias():
    assert extract_wikilinks("see [[A]] and [[B|alias]] then [[A]]") == ["A", "B"]


def test_load_document_and_chunk_from_corpus():
    path = CORPUS / FINSERV / "model-risk-governance-llms.md"
    document, body = load_document(path, domain_hint=FINSERV)
    assert document.domain == FINSERV
    assert document.title == "Model risk governance for LLMs"
    assert document.raw_links  # it links to other docs

    assert document.doc_id == f"{FINSERV}/model-risk-governance-llms"

    chunks = build_chunks(document, body)
    assert chunks
    assert all(c.doc_id == f"{FINSERV}/model-risk-governance-llms" for c in chunks)
    assert [c.order for c in chunks] == list(range(len(chunks)))
    assert all(c.id == f"{c.doc_id}#{c.order}" for c in chunks)
