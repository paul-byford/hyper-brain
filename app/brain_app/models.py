"""Shared data structures for the brain.

These are deliberately plain dataclasses so the index artefact is easy to
serialise to JSON and to reason about in review.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Document:
    """A single markdown document (one node in the link graph)."""

    doc_id: str
    domain: str
    title: str
    path: str
    tags: list[str] = field(default_factory=list)
    # Raw wikilink targets as written in the document, before resolution.
    raw_links: list[str] = field(default_factory=list)
    # Resolved neighbour doc_ids, within the same domain only.
    links: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Chunk:
    """A retrievable slice of a document."""

    id: str
    doc_id: str
    domain: str
    title: str
    heading: str
    text: str
    order: int


@dataclass(frozen=True)
class SearchResult:
    chunk_id: str
    doc_id: str
    domain: str
    title: str
    heading: str
    text: str
    score: float
    # "hybrid" for a fused semantic/keyword hit, "link" for a link-expansion hit.
    via: str


@dataclass(frozen=True)
class Answer:
    """The output of the `answer` (synthesis) mode."""

    text: str
    citations: list[SearchResult]
    # Honest account of what the brain could not support from the retrieved
    # context. Deliberately kept as a first-class field (adapted from gbrain).
    gaps: list[str]
    used_domains: list[str]
