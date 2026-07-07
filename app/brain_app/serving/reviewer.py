"""Server-side review of staged proposals (the in-browser review queue backs onto this).

``propose_document`` stages a document under ``proposals/{domain}/{slug}-{hash}.md``
in the corpus bucket, quarantined. A reviewer with **write** access to that domain
(see ``auth.authorize.writable_domains``) may accept it: promote it into the live
domain folder and trigger the index rebuild. Enforcement of *who may accept what*
lives in ``BrainService`` (it checks the proposal's domain against the caller's
writable domains); this module is just the storage/reindex mechanism, injectable so
the whole path is testable offline.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .review import live_name


@dataclass(frozen=True)
class ProposalRef:
    name: str  # bucket-relative staged path: proposals/{domain}/{slug}-{hash}.md
    domain: str  # the team domain it targets
    dest: str  # the live path it would land at: {domain}/{slug}.md


def proposal_domain(name: str, prefix: str = "proposals") -> str:
    """The team domain a staged proposal targets (its first path segment under the prefix)."""
    marker = prefix.strip("/") + "/"
    rel = name[len(marker) :] if name.startswith(marker) else name
    return rel.split("/", 1)[0]


def _ref(name: str, prefix: str = "proposals") -> ProposalRef:
    return ProposalRef(
        name=name, domain=proposal_domain(name, prefix), dest=live_name(name, prefix)
    )


@runtime_checkable
class Reviewer(Protocol):
    def list_proposals(self) -> list[ProposalRef]: ...
    def accept(self, name: str) -> str: ...  # returns the live dest path


class MemoryReviewer:
    """In-process reviewer; the default and the test double. ``accept`` moves the
    proposal to its live name within the in-memory map and records the reindex."""

    def __init__(self, staged: dict[str, bytes] | None = None, prefix: str = "proposals") -> None:
        self.prefix = prefix.strip("/")
        self.staged = dict(staged or {})
        self.live: dict[str, bytes] = {}

    def list_proposals(self) -> list[ProposalRef]:
        return [_ref(name, self.prefix) for name in sorted(self.staged)]

    def accept(self, name: str) -> str:
        if name not in self.staged:
            raise FileNotFoundError(name)
        dest = live_name(name, self.prefix)
        self.live[dest] = self.staged.pop(name)
        return dest


class GcsReviewer:
    """Promotes proposals in the corpus bucket: copy to the live path, delete the
    staged one. The reindex that follows is triggered by the service (``reindex``),
    not here, so all live writes share one reindex path."""

    def __init__(self, bucket: str, prefix: str = "proposals") -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def _bucket(self):
        from google.cloud import storage

        return storage.Client().bucket(self.bucket)

    def list_proposals(self) -> list[ProposalRef]:
        refs = []
        for blob in self._bucket().list_blobs(prefix=f"{self.prefix}/"):
            if blob.name.endswith(".md"):
                refs.append(_ref(blob.name, self.prefix))
        return refs

    def accept(self, name: str) -> str:
        bucket = self._bucket()
        dest = live_name(name, self.prefix)
        source = bucket.blob(name)
        bucket.copy_blob(source, bucket, new_name=dest)
        source.delete()
        return dest


def get_reviewer() -> Reviewer:
    """GCS-backed when a corpus bucket is configured (deployed), else in-process."""
    bucket = os.environ.get("BRAIN_CORPUS_BUCKET")
    return GcsReviewer(bucket) if bucket else MemoryReviewer()
