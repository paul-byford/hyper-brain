"""Data structures passed between the ingestion stages.

Plain frozen dataclasses, matching ``brain_app.models``: easy to construct in a
test, easy to reason about in review, and cheap to serialise.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Landing outcomes for a single item.
WRITTEN = "written"  # a new document was created
UPDATED = "updated"  # an existing document changed and was rewritten
SKIPPED = "skipped"  # content unchanged (same checksum), left untouched


@dataclass(frozen=True)
class RawItem:
    """One raw item pulled from a source, before parsing.

    ``identifier`` is a stable id *within* the source (a relative path, a URL, a
    repo-relative path). It is what makes re-ingestion address the same landed
    document, so it must be deterministic across runs.
    """

    identifier: str
    content: bytes
    mime: str
    source_url: str
    title: str | None = None


@dataclass(frozen=True)
class ParsedDoc:
    """Parser output: a clean markdown body plus any metadata it could extract."""

    body: str
    title: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LandResult:
    """What happened to one item when it reached the corpus."""

    doc_id: str
    path: str
    status: str
    checksum: str


@dataclass(frozen=True)
class IngestReport:
    """The outcome of ingesting one source."""

    source_id: str
    domain: str
    results: list[LandResult] = field(default_factory=list)

    def _count(self, status: str) -> int:
        return sum(1 for r in self.results if r.status == status)

    @property
    def written(self) -> int:
        return self._count(WRITTEN)

    @property
    def updated(self) -> int:
        return self._count(UPDATED)

    @property
    def skipped(self) -> int:
        return self._count(SKIPPED)

    def summary(self) -> str:
        return (
            f"{self.source_id} -> {self.domain}: "
            f"{self.written} new, {self.updated} updated, {self.skipped} unchanged"
        )
