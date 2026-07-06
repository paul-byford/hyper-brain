"""Dynamic sharing overlay: user-authored grants merged over the base policy.

The base policy (``config.Policy``, authored in tfvars) is admin-owned and
slow-changing: company/team domains and the commons grant every signed-in user
gets. This overlay is its opposite -- grants a user creates at runtime to share
their own content, taking effect within a short TTL with no redeploy. Each owner
writes only their own file (``shares/{owner}.yaml`` in the index bucket), so owners
never contend on a write and revoking everything is deleting one file.

Two safety rules the base policy does not need, enforced here and where shares are
created (``serving.service``):

- a share's ``principal`` is never the wildcard ``*``; opening content to everyone
  is an admin act in the base policy, not something a user can do from a share.
- a share only ever grants content the sharer owns, so it can widen access, never
  escalate it.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

import yaml

from .identity import Identity

_SCHEMA_VERSION = 1
# Owner subjects are opaque (a Google ``sub``); keep the object name filesystem-safe.
_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class ShareError(Exception):
    """A share was rejected (wildcard/empty principal, or nothing to share)."""


@dataclass(frozen=True)
class Share:
    """One dynamic grant.

    ``principal`` is who gains access (an email or ``group:x``, never ``*``);
    ``domain`` is the shared content's domain (often ``personal:{owner}``);
    ``granted_by`` is the owner subject who created it. ``doc_id`` None means the
    whole domain, set means a single document within it.
    """

    principal: str
    domain: str
    granted_by: str
    doc_id: str | None = None
    write: bool = False
    granted_at: str = ""

    def key(self) -> tuple[str, str, str | None]:
        return (self.principal, self.domain, self.doc_id)


def validate_share(share: Share) -> Share:
    if not share.principal or share.principal == "*":
        raise ShareError("a share principal may not be empty or the wildcard '*'")
    if not share.domain:
        raise ShareError("a share needs a domain")
    return share


# --- Evaluation: what a caller gains from a set of shares -------------------------


def shared_read_domains(identity: Identity, shares: Iterable[Share]) -> set[str]:
    """Whole domains shared with the caller (doc_id is None)."""
    principals = set(identity.principals)
    return {s.domain for s in shares if s.doc_id is None and s.principal in principals}


def shared_read_docs(identity: Identity, shares: Iterable[Share]) -> set[str]:
    """Individual documents shared with the caller (doc-level shares)."""
    principals = set(identity.principals)
    return {s.doc_id for s in shares if s.doc_id and s.principal in principals}  # type: ignore[misc]


def shared_write_domains(identity: Identity, shares: Iterable[Share]) -> set[str]:
    """Whole domains shared with the caller with ``write: true``."""
    principals = set(identity.principals)
    return {s.domain for s in shares if s.doc_id is None and s.write and s.principal in principals}


# --- Serialisation ---------------------------------------------------------------


def parse_shares(data: dict | None) -> list[Share]:
    data = data or {}
    out: list[Share] = []
    for s in data.get("shares", []) or []:
        out.append(
            Share(
                principal=str(s["principal"]),
                domain=str(s["domain"]),
                granted_by=str(s.get("granted_by", "")),
                doc_id=(str(s["doc_id"]) if s.get("doc_id") else None),
                write=bool(s.get("write", False)),
                granted_at=str(s.get("granted_at", "")),
            )
        )
    return out


def dump_shares(shares: Iterable[Share]) -> str:
    payload = {
        "version": _SCHEMA_VERSION,
        "shares": [
            {
                "principal": s.principal,
                "domain": s.domain,
                "granted_by": s.granted_by,
                "doc_id": s.doc_id,
                "write": s.write,
                "granted_at": s.granted_at,
            }
            for s in shares
        ],
    }
    return yaml.safe_dump(payload, sort_keys=False)


# --- Stores ----------------------------------------------------------------------


@runtime_checkable
class SharesStore(Protocol):
    def all_shares(self) -> list[Share]: ...
    def for_owner(self, owner: str) -> list[Share]: ...
    def put_owner(self, owner: str, shares: list[Share]) -> None: ...


class MemorySharesStore:
    """In-process store; the default and the test double."""

    def __init__(self, shares: Iterable[Share] | None = None) -> None:
        self._by_owner: dict[str, list[Share]] = {}
        for s in shares or []:
            self._by_owner.setdefault(s.granted_by, []).append(s)

    def all_shares(self) -> list[Share]:
        return [s for lst in self._by_owner.values() for s in lst]

    def for_owner(self, owner: str) -> list[Share]:
        return list(self._by_owner.get(owner, []))

    def put_owner(self, owner: str, shares: list[Share]) -> None:
        if shares:
            self._by_owner[owner] = list(shares)
        else:
            self._by_owner.pop(owner, None)


class GcsSharesStore:
    """Per-owner ``shares/{owner}.yaml`` objects in a bucket.

    Reads are cached for ``ttl`` seconds (like the policy and index), so a new share
    is visible everywhere within the TTL with no redeploy; a write invalidates the
    local cache immediately. One file per owner means owners never contend on a
    write, and "unshare everything" is deleting one object.
    """

    def __init__(self, bucket: str, prefix: str = "shares", ttl: float = 30.0) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.ttl = ttl
        self._cache: list[Share] | None = None
        self._at = 0.0

    def _bucket(self):
        from google.cloud import storage

        return storage.Client().bucket(self.bucket)

    def _blob_name(self, owner: str) -> str:
        return f"{self.prefix}/{_SAFE.sub('_', owner)}.yaml"

    def all_shares(self) -> list[Share]:
        now = time.monotonic()
        if self._cache is not None and now - self._at <= self.ttl:
            return list(self._cache)
        shares: list[Share] = []
        for blob in self._bucket().list_blobs(prefix=f"{self.prefix}/"):
            if blob.name.endswith("/"):
                continue
            shares.extend(parse_shares(yaml.safe_load(blob.download_as_text())))
        self._cache = shares
        self._at = now
        return list(shares)

    def for_owner(self, owner: str) -> list[Share]:
        blob = self._bucket().blob(self._blob_name(owner))
        if not blob.exists():
            return []
        return parse_shares(yaml.safe_load(blob.download_as_text()))

    def put_owner(self, owner: str, shares: list[Share]) -> None:
        blob = self._bucket().blob(self._blob_name(owner))
        if shares:
            blob.upload_from_string(dump_shares(shares))
        elif blob.exists():
            blob.delete()
        self._cache = None  # force a reload on the next read


def get_shares_store(name: str | None = None) -> SharesStore:
    """Return the configured shares store.

    ``BRAIN_SHARES_STORE``: ``memory`` (default, in-process) or ``gcs`` (per-owner
    objects under ``shares/`` in ``BRAIN_SHARES_BUCKET``, defaulting to the index
    bucket ``BRAIN_INDEX_BUCKET``).
    """
    name = name or os.environ.get("BRAIN_SHARES_STORE", "memory")
    if name == "memory":
        return MemorySharesStore()
    if name == "gcs":
        bucket = os.environ.get("BRAIN_SHARES_BUCKET") or os.environ.get("BRAIN_INDEX_BUCKET")
        if not bucket:
            raise ValueError("BRAIN_SHARES_STORE=gcs requires BRAIN_SHARES_BUCKET")
        return GcsSharesStore(bucket)
    raise ValueError(f"unknown shares store {name!r}")
