from __future__ import annotations

from brain_app.indexer.build import load_corpus
from brain_app.indexer.graph import build_adjacency, resolve_links
from brain_app.models import Document

from .conftest import CORPUS, FINSERV


def test_wikilinks_resolve_within_corpus():
    documents, _chunks, adjacency, _hash = load_corpus(CORPUS)
    # Both domains have an index.md; namespacing keeps them distinct.
    finserv_overview = documents[f"{FINSERV}/index"]
    # Its links should resolve to real doc_ids in the same domain.
    assert f"{FINSERV}/model-risk-governance-llms" in finserv_overview.links
    assert adjacency[f"{FINSERV}/model-risk-governance-llms"]  # has neighbours


def test_adjacency_never_crosses_domains():
    documents, _chunks, adjacency, _hash = load_corpus(CORPUS)
    for doc_id, neighbours in adjacency.items():
        domain = documents[doc_id].domain
        for neighbour in neighbours:
            assert documents[neighbour].domain == domain


def test_cross_domain_links_are_dropped():
    docs = [
        Document(doc_id="a", domain="d1", title="Alpha", path="a.md", raw_links=["Beta"]),
        Document(doc_id="b", domain="d2", title="Beta", path="b.md", raw_links=["Alpha"]),
    ]
    resolved = resolve_links(docs)
    by_id = {d.doc_id: d for d in resolved}
    assert by_id["a"].links == []  # Beta is in another domain
    assert by_id["b"].links == []
    assert build_adjacency(resolved) == {"a": [], "b": []}
