"""Link-graph construction.

Wikilinks are resolved to document ids, but only within the same domain. A link
that points across domains, or to a missing document, is dropped. This is a
defence-in-depth property: because retrieval expands along this graph, keeping the
graph strictly intra-domain means link expansion can never leak a chunk from a
domain the caller may not see. The primary isolation boundary is still the
server-side domain filter; this just means the graph cannot undermine it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..models import Document


def _normalise(value: str) -> str:
    """Normalise a title or stem for link matching."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def resolve_links(documents: Iterable[Document]) -> list[Document]:
    """Return documents with their ``links`` resolved to same-domain doc_ids."""
    docs = list(documents)

    # Build a per-domain lookup from normalised title and normalised doc_id.
    lookup: dict[str, dict[str, str]] = {}
    for doc in docs:
        domain_map = lookup.setdefault(doc.domain, {})
        # Wikilinks are written as a bare title or file stem, so match on those.
        stem = doc.doc_id.rsplit("/", 1)[-1]
        domain_map[_normalise(doc.title)] = doc.doc_id
        domain_map[_normalise(stem)] = doc.doc_id

    resolved: list[Document] = []
    for doc in docs:
        domain_map = lookup.get(doc.domain, {})
        targets: list[str] = []
        for raw in doc.raw_links:
            target = domain_map.get(_normalise(raw))
            if target and target != doc.doc_id and target not in targets:
                targets.append(target)
        resolved.append(
            Document(
                doc_id=doc.doc_id,
                domain=doc.domain,
                title=doc.title,
                path=doc.path,
                tags=doc.tags,
                raw_links=doc.raw_links,
                links=targets,
                source=doc.source,
                source_url=doc.source_url,
                fetched_at=doc.fetched_at,
            )
        )
    return resolved


def build_adjacency(documents: Iterable[Document]) -> dict[str, list[str]]:
    """Build an undirected adjacency map (doc_id -> sorted neighbour doc_ids).

    Undirected so that link expansion pulls both outbound links and backlinks.
    """
    neighbours: dict[str, set[str]] = {}
    for doc in documents:
        neighbours.setdefault(doc.doc_id, set())
        for target in doc.links:
            neighbours.setdefault(target, set())
            neighbours[doc.doc_id].add(target)
            neighbours[target].add(doc.doc_id)
    return {doc_id: sorted(links) for doc_id, links in neighbours.items()}
