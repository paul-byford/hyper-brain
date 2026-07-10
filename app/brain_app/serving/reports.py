"""Community moderation: a report is a flag raised against a live document.

Commons is writable by everyone (a wildcard write grant), so the counterweight is a
lightweight report/remove loop. Any reader can flag a document; a moderator of that
domain (its owner, or an explicit write-grant holder) sees the flag in their queue and
either dismisses it or removes the content. Reports are stored out of band from the
corpus, so flagging never touches the live document or the index.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import asdict, dataclass
from typing import Protocol, runtime_checkable

import yaml

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class Report:
    doc_id: str
    domain: str
    reporter: str
    reason: str
    created_at: str


@runtime_checkable
class ReportsStore(Protocol):
    def add(self, report: Report) -> None: ...
    def open_reports(self) -> list[Report]: ...
    def resolve(self, doc_id: str) -> None: ...


class MemoryReportsStore:
    """In-process store; the default and the test double."""

    def __init__(self) -> None:
        self._reports: list[Report] = []

    def add(self, report: Report) -> None:
        self._reports.append(report)

    def open_reports(self) -> list[Report]:
        return list(self._reports)

    def resolve(self, doc_id: str) -> None:
        self._reports = [r for r in self._reports if r.doc_id != doc_id]


class GcsReportsStore:
    """A single ``moderation/reports.yaml`` object holding the open report list.

    Reads are cached for ``ttl`` seconds; a write invalidates the cache. Resolving a
    document drops every report against it (dismiss and remove converge on the same
    "clear the flags" outcome). Reports are rare, so a single object is fine.
    """

    def __init__(self, bucket: str, prefix: str = "moderation", ttl: float = 15.0) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.ttl = ttl
        self._cache: list[Report] | None = None
        self._at = 0.0

    def _blob(self):
        from google.cloud import storage

        return storage.Client().bucket(self.bucket).blob(f"{self.prefix}/reports.yaml")

    def _load(self) -> list[Report]:
        blob = self._blob()
        if not blob.exists():
            return []
        raw = yaml.safe_load(blob.download_as_text()) or []
        return [Report(**r) for r in raw]

    def _save(self, reports: list[Report]) -> None:
        self._blob().upload_from_string(yaml.safe_dump([asdict(r) for r in reports]))
        self._cache = None

    def add(self, report: Report) -> None:
        self._save([*self._load(), report])

    def open_reports(self) -> list[Report]:
        now = time.monotonic()
        if self._cache is not None and now - self._at <= self.ttl:
            return list(self._cache)
        self._cache = self._load()
        self._at = now
        return list(self._cache)

    def resolve(self, doc_id: str) -> None:
        self._save([r for r in self._load() if r.doc_id != doc_id])


def get_reports_store(name: str | None = None) -> ReportsStore:
    """Return the configured reports store.

    ``BRAIN_REPORTS_STORE``: ``memory`` (default, in-process) or ``gcs`` (a single
    object under ``moderation/`` in ``BRAIN_REPORTS_BUCKET``, defaulting to the index
    bucket ``BRAIN_INDEX_BUCKET``).
    """
    name = name or os.environ.get("BRAIN_REPORTS_STORE", "memory")
    if name == "memory":
        return MemoryReportsStore()
    if name == "gcs":
        bucket = os.environ.get("BRAIN_REPORTS_BUCKET") or os.environ.get("BRAIN_INDEX_BUCKET")
        if not bucket:
            raise ValueError("BRAIN_REPORTS_STORE=gcs requires BRAIN_REPORTS_BUCKET")
        return GcsReportsStore(bucket)
    raise ValueError(f"unknown reports store {name!r}")
