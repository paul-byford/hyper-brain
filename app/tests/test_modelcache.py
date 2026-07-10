"""Serving-time caches: a repeated query serves from memory with no model call.

These pin the 429-mitigation behaviour: the embedding cache and the answer cache each
avoid a repeat model call on a cache hit, only send batch misses to the wrapped
provider, and treat a changed retrieval context as a genuine miss (no stale answers).
"""

from __future__ import annotations

from brain_app.models import Answer, SearchResult
from brain_app.serving.modelcache import CachingEmbeddings, CachingSynthesiser


class _CountingEmbeddings:
    dim = 3

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[float(len(t)), 0.0, 0.0] for t in texts]


class _CountingSynth:
    def __init__(self) -> None:
        self.calls = 0

    def synthesise(self, query, results):
        self.calls += 1
        return Answer(text=f"answer {self.calls}", citations=results, gaps=[], used_domains=[])


def _result(doc_id="commons/x", text="body"):
    return SearchResult(
        chunk_id=f"{doc_id}#0",
        doc_id=doc_id,
        domain="commons",
        title="X",
        heading="",
        text=text,
        score=1.0,
        via="dense",
    )


def test_embedding_cache_skips_repeat_calls():
    inner = _CountingEmbeddings()
    cache = CachingEmbeddings(inner)
    first = cache.embed(["hello"])
    second = cache.embed(["hello"])
    assert first == second
    assert inner.calls == [["hello"]]  # the second call was served from cache


def test_embedding_cache_only_embeds_batch_misses_in_order():
    inner = _CountingEmbeddings()
    cache = CachingEmbeddings(inner)
    cache.embed(["a"])  # warm "a"
    inner.calls.clear()
    out = cache.embed(["a", "bb", "ccc"])
    # Only the two misses were sent to the provider, and the full result is in order.
    assert inner.calls == [["bb", "ccc"]]
    assert out == [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0], [3.0, 0.0, 0.0]]


def test_embedding_cache_passes_through_dim():
    assert CachingEmbeddings(_CountingEmbeddings()).dim == 3


def test_answer_cache_hits_on_same_query_and_context():
    inner = _CountingSynth()
    cache = CachingSynthesiser(inner)
    results = [_result()]
    a1 = cache.synthesise("q", results)
    a2 = cache.synthesise("q", results)
    assert a1.text == a2.text == "answer 1"
    assert inner.calls == 1  # only one real synthesis


def test_answer_cache_misses_when_context_changes():
    inner = _CountingSynth()
    cache = CachingSynthesiser(inner)
    cache.synthesise("q", [_result(text="old body")])
    cache.synthesise("q", [_result(text="new body after reindex")])
    assert inner.calls == 2  # changed retrieval context is a genuine miss


def test_answer_cache_misses_on_different_query():
    inner = _CountingSynth()
    cache = CachingSynthesiser(inner)
    results = [_result()]
    cache.synthesise("first question", results)
    cache.synthesise("second question", results)
    assert inner.calls == 2
