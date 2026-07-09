"""Autolinker: suggest connections between a caller's notes by embedding similarity.

Links in this brain are wikilinks resolved within a single domain (see
``indexer/graph.py``), so the autolinker only ever proposes links *among the
caller's own personal notes*. It scores candidate pairs by the cosine similarity of
their document embeddings (the mean of a document's chunk vectors, which the index
already holds), excludes pairs that are already linked, and returns the strongest
remaining pairs. The service turns an accepted suggestion into a real ``[[wikilink]]``
so it flows through the normal index build; nothing here writes.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from ..retrieval import BrainIndex


def _doc_vectors(index: BrainIndex, doc_ids: set[str]) -> dict[str, np.ndarray]:
    """A unit vector per document: the L2-normalised mean of its chunk embeddings."""
    rows: dict[str, list[np.ndarray]] = {}
    for i, chunk in enumerate(index.chunks):
        if chunk.doc_id in doc_ids:
            rows.setdefault(chunk.doc_id, []).append(index.embeddings[i])
    vectors: dict[str, np.ndarray] = {}
    for doc_id, chunk_vecs in rows.items():
        mean = np.mean(np.stack(chunk_vecs), axis=0)
        norm = float(np.linalg.norm(mean))
        vectors[doc_id] = mean / norm if norm else mean
    return vectors


def _existing_pairs(adjacency: dict[str, list[str]]) -> set[frozenset[str]]:
    pairs: set[frozenset[str]] = set()
    for src, neighbours in adjacency.items():
        for dst in neighbours:
            pairs.add(frozenset((src, dst)))
    return pairs


def suggest_links(
    index: BrainIndex,
    doc_ids: Iterable[str],
    adjacency: dict[str, list[str]],
    *,
    top_k: int = 8,
    threshold: float = 0.5,
) -> list[tuple[float, str, str]]:
    """Return ``(score, doc_a, doc_b)`` for the strongest not-yet-linked note pairs.

    Only pairs with cosine similarity at or above ``threshold`` are returned, best
    first, capped at ``top_k``. ``doc_ids`` must already be scoped to one domain.
    """
    ids = list(dict.fromkeys(doc_ids))  # de-dup, order-preserving
    vectors = _doc_vectors(index, set(ids))
    ids = [d for d in ids if d in vectors]
    linked = _existing_pairs(adjacency)

    scored: list[tuple[float, str, str]] = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            if frozenset((a, b)) in linked:
                continue
            score = float(np.dot(vectors[a], vectors[b]))
            if score >= threshold:
                scored.append((score, a, b))
    scored.sort(key=lambda t: t[0], reverse=True)
    return scored[:top_k]
