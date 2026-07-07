"""Ranking: a literal title match ranks above merely semantically-similar docs.

The hybrid ranker fuses semantic + keyword by RRF, which alone can bury a unique
literal match beneath docs that are decent on both axes. A title boost fixes that:
a query that is (part of) a document's title ranks it first.
"""

from __future__ import annotations

from brain_app.retrieval import search
from brain_app.retrieval.search import title_boost

from .conftest import FINSERV

MODEL_RISK = f"{FINSERV}/model-risk-governance-llms"


def test_title_phrase_match_ranks_first(index, embeddings):
    # "model risk governance" is a phrase in the title "Model risk governance for LLMs".
    results = search(index, "model risk governance", {FINSERV}, embeddings, top_k=5)
    assert results
    assert results[0].doc_id == MODEL_RISK


def test_title_boost_is_tiered():
    assert title_boost(["vs", "code"], "VS Code integration") == 1.0  # phrase in title
    assert title_boost(["code", "vs"], "VS Code") == 0.6  # all words, not contiguous
    partial = title_boost(["fraud", "quantum"], "Real-time fraud detection")
    assert 0.0 < partial < 0.6  # only some query words in the title
    assert title_boost([], "anything") == 0.0  # empty query never boosts everything


def test_title_boost_is_word_boundary_safe():
    # "code" must not match inside "encode".
    assert title_boost(["code"], "Encode the payload") == 0.0
