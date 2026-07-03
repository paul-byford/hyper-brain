"""Contract-first ingestion pipeline (ARCHITECTURE.md section 12).

The core is source-agnostic: every source is a small, swappable ``SourceAdapter``
and every content type a swappable ``Parser``, both behind narrow interfaces the
bank extends without touching the retrieval core. The whole pipeline is offline
testable, so "add new data" is proven before any serving or cloud exists: real
parse and (later) curate stay in-tenancy, deterministic fakes keep tests free.

The flow, per source:

    adapter.fetch -> parser -> [optional] curate -> stamp provenance -> land

Landing is an idempotent upsert by checksum: re-running converges rather than
duplicating, and a source's domain is assigned by config and validated, so an
adapter can never place content outside its configured domain.
"""

from __future__ import annotations

from .models import IngestReport, LandResult, ParsedDoc, RawItem
from .pipeline import ingest_all, ingest_source
from .sources import SourceConfig, load_sources

__all__ = [
    "IngestReport",
    "LandResult",
    "ParsedDoc",
    "RawItem",
    "SourceConfig",
    "ingest_all",
    "ingest_source",
    "load_sources",
]
