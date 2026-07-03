"""Hybrid retrieval: semantic + keyword, fused, with link expansion.

Adapted from gbrain's hybrid approach (see docs/LINEAGE.md), re-seated on the
in-memory object-store index rather than a running Postgres. The domain filter is
applied first, before any signal runs, so a caller never ranks against or sees a
chunk from a domain they may not read. That ordering is the isolation guarantee.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from ..embeddings.base import EmbeddingProvider
from ..models import SearchResult
from .bm25 import BM25, tokenize
from .index import BrainIndex

# Reciprocal-rank-fusion constant. 60 is the common default.
_RRF_K = 60


def _ranks(scores: list[float]) -> list[int]:
    """Map each position to its 0-based rank (0 = highest score)."""
    order = sorted(range(len(scores)), key=lambda p: scores[p], reverse=True)
    ranks = [0] * len(scores)
    for rank, position in enumerate(order):
        ranks[position] = rank
    return ranks


def search(
    index: BrainIndex,
    query: str,
    allowed_domains: Iterable[str],
    embeddings: EmbeddingProvider,
    *,
    top_k: int = 5,
    expand_links: bool = True,
) -> list[SearchResult]:
    allowed = set(allowed_domains)
    candidates = [i for i, chunk in enumerate(index.chunks) if chunk.domain in allowed]
    if not candidates:
        return []

    # Semantic signal (cosine == dot, both sides normalised).
    query_vec = np.asarray(embeddings.embed([query])[0], dtype=np.float32)
    norm = float(np.linalg.norm(query_vec)) or 1.0
    query_vec = query_vec / norm
    semantic = (index.embeddings[candidates] @ query_vec).tolist()

    # Keyword signal.
    keyword = BM25([tokenize(index.chunks[i].text) for i in candidates]).scores(query)

    # Fuse by reciprocal rank.
    semantic_ranks = _ranks(semantic)
    keyword_ranks = _ranks(keyword)
    fused = [
        1.0 / (_RRF_K + semantic_ranks[p]) + 1.0 / (_RRF_K + keyword_ranks[p])
        for p in range(len(candidates))
    ]
    order = sorted(range(len(candidates)), key=lambda p: fused[p], reverse=True)

    results: list[SearchResult] = []
    seen_chunks: set[str] = set()
    hit_docs: set[str] = set()
    for p in order[:top_k]:
        chunk = index.chunks[candidates[p]]
        results.append(_result(chunk, round(fused[p], 6), "hybrid"))
        seen_chunks.add(chunk.id)
        hit_docs.add(chunk.doc_id)

    if expand_links:
        results.extend(
            _link_expansion(index, candidates, semantic, allowed, hit_docs, seen_chunks, top_k)
        )
    return results


def _link_expansion(
    index: BrainIndex,
    candidates: list[int],
    semantic: list[float],
    allowed: set[str],
    hit_docs: set[str],
    seen_chunks: set[str],
    top_k: int,
) -> list[SearchResult]:
    """Pull the best chunk of each same-domain neighbour of a primary hit."""
    positions_by_doc: dict[str, list[int]] = {}
    for p, i in enumerate(candidates):
        positions_by_doc.setdefault(index.chunks[i].doc_id, []).append(p)

    neighbour_docs: list[str] = []
    for doc_id in hit_docs:
        for neighbour in index.adjacency.get(doc_id, []):
            document = index.documents.get(neighbour)
            if (
                neighbour not in hit_docs
                and neighbour not in neighbour_docs
                and document is not None
                and document.domain in allowed
            ):
                neighbour_docs.append(neighbour)

    scored: list[tuple[int, float]] = []
    for neighbour in neighbour_docs:
        positions = positions_by_doc.get(neighbour, [])
        if not positions:
            continue
        best = max(positions, key=lambda p: semantic[p])
        scored.append((best, semantic[best]))
    scored.sort(key=lambda t: t[1], reverse=True)

    out: list[SearchResult] = []
    for best, score in scored[:top_k]:
        chunk = index.chunks[candidates[best]]
        if chunk.id in seen_chunks:
            continue
        out.append(_result(chunk, round(float(score), 6), "link"))
        seen_chunks.add(chunk.id)
    return out


def _result(chunk, score: float, via: str) -> SearchResult:
    return SearchResult(
        chunk_id=chunk.id,
        doc_id=chunk.doc_id,
        domain=chunk.domain,
        title=chunk.title,
        heading=chunk.heading,
        text=chunk.text,
        score=score,
        via=via,
    )
