"""The `answer` (synthesis) mode.

This is gbrain's "think" idea: not just ranked pages, but a composed answer with
citations and an honest statement of what the brain could not support. The
synthesiser is behind an interface. Offline we use a deterministic extractive
synthesiser (no model, no cost); in production this is a Gemini model on Vertex,
in-tenancy, wired in a later phase. The honest gap statement is kept in both.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Protocol

from ..embeddings.base import EmbeddingProvider
from ..models import Answer, SearchResult
from .index import BrainIndex
from .search import search

_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "in",
    "for",
    "on",
    "with",
    "is",
    "are",
    "how",
    "what",
    "why",
    "do",
    "does",
    "can",
    "i",
    "we",
    "you",
    "it",
    "this",
    "that",
    "at",
    "by",
    "be",
    "as",
    "from",
    "about",
}


class Synthesiser(Protocol):
    def synthesise(self, query: str, results: list[SearchResult]) -> Answer: ...


def _first_sentences(text: str, count: int = 2) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(sentences[:count]).strip()


def _missing_terms(query: str, results: Iterable[SearchResult]) -> list[str]:
    """Query terms not present in any retrieved chunk, as an honest gap list."""
    present = set()
    for result in results:
        present.update(_TOKEN.findall(result.text.lower()))
    gaps: list[str] = []
    for term in _TOKEN.findall(query.lower()):
        if term in _STOPWORDS or len(term) < 3:
            continue
        if term not in present and term not in gaps:
            gaps.append(term)
    return gaps


class ExtractiveSynthesiser:
    """Deterministic, model-free synthesis for offline use and tests."""

    def synthesise(self, query: str, results: list[SearchResult]) -> Answer:
        if not results:
            return Answer(
                text="I don't have anything on that in the domains you can access.",
                citations=[],
                gaps=[query.strip()] if query.strip() else [],
                used_domains=[],
            )
        parts = [f"{_first_sentences(r.text)} [{r.title}]" for r in results[:3]]
        return Answer(
            text=" ".join(parts),
            citations=results,
            gaps=_missing_terms(query, results),
            used_domains=sorted({r.domain for r in results}),
        )


def answer(
    index: BrainIndex,
    query: str,
    allowed_domains: Iterable[str],
    embeddings: EmbeddingProvider,
    synthesiser: Synthesiser | None = None,
    *,
    top_k: int = 5,
) -> Answer:
    results = search(index, query, allowed_domains, embeddings, top_k=top_k)
    return (synthesiser or ExtractiveSynthesiser()).synthesise(query, results)
