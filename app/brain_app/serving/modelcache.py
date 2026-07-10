"""Serving-time caches that cut Gemini/Vertex calls, and so cut 429s at the source.

The brain runs on Vertex's dynamic shared quota, so the way to avoid a 429 without a
quota increase is to make fewer model calls. Two calls repeat in normal use: the query
embedding (the same question, asked again) and the synthesised answer (the same
question over an unchanged corpus). Caching both means a repeated question serves from
memory with no model call, which matters most under exactly the concurrent-burst load
that triggers a 429 on a warm instance.

Both caches are in-process LRU maps: they clear on a scale-to-zero cold start (so they
never serve across a redeploy) and are not shared between instances, which is the right
trade-off for a cache (correctness never depends on a hit). The answer cache keys on the
retrieved context, so a reindex that changes what a query retrieves is naturally a miss.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from collections.abc import Sequence

from ..embeddings.base import EmbeddingProvider
from ..models import Answer, SearchResult
from ..observability import span
from ..retrieval.answer import Synthesiser


class _LruTtl:
    """A small thread-safe LRU cache with an optional TTL. Values are opaque."""

    def __init__(self, max_size: int, ttl: float = 0.0) -> None:
        self.max_size = max_size
        self.ttl = ttl
        self._data: OrderedDict[str, tuple[float, object]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str):
        now = time.monotonic()
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            ts, value = item
            if self.ttl and now - ts > self.ttl:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return value

    def put(self, key: str, value: object) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_size:
                self._data.popitem(last=False)


def _hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


class CachingEmbeddings:
    """Wraps an :class:`EmbeddingProvider`, caching per-text vectors so a repeated text
    (typically a re-asked query) skips the Vertex embedding call. Only the misses in a
    batch are sent to the wrapped provider, and the result order is preserved."""

    def __init__(self, inner: EmbeddingProvider, max_size: int = 2048) -> None:
        self._inner = inner
        self.dim = inner.dim
        self._cache = _LruTtl(max_size)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        texts = list(texts)
        out: list[list[float] | None] = [None] * len(texts)
        misses: list[int] = []
        for i, text in enumerate(texts):
            hit = self._cache.get(_hash("emb", text))
            if hit is None:
                misses.append(i)
            else:
                out[i] = hit  # type: ignore[assignment]
        if misses:
            fresh = self._inner.embed([texts[i] for i in misses])
            for i, vec in zip(misses, fresh, strict=True):
                out[i] = vec
                self._cache.put(_hash("emb", texts[i]), vec)
        return [v for v in out]  # type: ignore[return-value]


class CachingSynthesiser:
    """Wraps a :class:`Synthesiser`, caching the composed :class:`Answer` by the query
    and the exact retrieved context. A repeated question over an unchanged corpus serves
    the cached answer with no Gemini call; a reindex that changes the retrieved chunks
    changes the key, so the cache never serves a stale answer."""

    def __init__(self, inner: Synthesiser, max_size: int = 512, ttl: float = 3600.0) -> None:
        self._inner = inner
        self._cache = _LruTtl(max_size, ttl)

    @staticmethod
    def _key(query: str, results: list[SearchResult]) -> str:
        context = "\n".join(f"{r.doc_id}|{r.heading}|{r.text}" for r in results)
        return _hash("ans", query.strip(), context)

    def synthesise(self, query: str, results: list[SearchResult]) -> Answer:
        key = self._key(query, results)
        cached = self._cache.get(key)
        if cached is not None:
            with span("brain.answer_cache_hit"):
                return cached  # type: ignore[return-value]
        answer = self._inner.synthesise(query, results)
        self._cache.put(key, answer)
        return answer
