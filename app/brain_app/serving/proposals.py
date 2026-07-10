"""The write path's review gate: a proposal is a quarantined change, never a live write.

The agent write tool (``propose_document``) reuses the Phase 2 stamping so an
agent-authored document is provenance-stamped exactly like a batch-ingested one,
then hands it to a ``ReviewGate``. The load-bearing property (ARCHITECTURE.md
section 12) is that a proposal never mutates the live corpus on ``main``: the
default ``GitBranchGate`` lands it on a fresh branch for review, and ``MemoryGate``
records it without touching the filesystem (the safe default, used in tests).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..ingest.pipeline import (
    _canonical_body,
    _checksum,
    _new_run_id,
    _slugify,
    _stamp,
    _title_from,
    _utc_now,
)


@dataclass(frozen=True)
class Proposal:
    domain: str
    slug: str
    path: str  # corpus-relative intended path
    content: str  # provenance-stamped markdown, ready to land
    checksum: str
    author: str


@dataclass(frozen=True)
class ProposalResult:
    status: str  # "proposed"
    path: str
    branch: str | None
    checksum: str
    detail: str


def build_proposal(
    *,
    domain: str,
    title: str,
    content: str,
    author: str,
    source_url: str | None = None,
    now: str | None = None,
    run_id: str | None = None,
    tags: list[str] | None = None,
) -> Proposal:
    """Stamp an agent-authored document into a landable proposal.

    Slug and stamping match the batch pipeline, so a proposal and an ingested
    document are indistinguishable once landed, and the ``_slugify`` sanitisation
    is the same first line of the domain-escape defence.
    """
    resolved_title = title.strip() or _title_from(author)
    canonical = _canonical_body(content)
    checksum = _checksum(canonical)
    slug = _slugify(resolved_title)
    stamped = _stamp(
        title=resolved_title,
        domain=domain,
        tags=list(tags or []),
        source_id=f"agent:{author}",
        source_url=source_url or f"proposal:{author}",
        fetched_at=now or _utc_now(),
        checksum=checksum,
        run_id=run_id or _new_run_id(),
        canonical_body=canonical,
    )
    return Proposal(
        domain=domain,
        slug=slug,
        path=f"corpus/{domain}/{slug}.md",
        content=stamped,
        checksum=checksum,
        author=author,
    )


@runtime_checkable
class ReviewGate(Protocol):
    def submit(self, proposal: Proposal) -> ProposalResult: ...


@runtime_checkable
class Deleter(Protocol):
    def delete(self, domain: str, slug: str) -> None: ...


class MemoryDeleter:
    """Records deletions without touching storage (the safe default and test double)."""

    def __init__(self) -> None:
        self.deleted: list[tuple[str, str]] = []

    def delete(self, domain: str, slug: str) -> None:
        self.deleted.append((domain, slug))


class GcsCorpusDeleter:
    """Deletes ``{domain}/{slug}.md`` from the corpus bucket (the live-write path's
    inverse). Missing objects are ignored, so delete is idempotent."""

    def __init__(self, bucket: str, prefix: str = "") -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def delete(self, domain: str, slug: str) -> None:
        from google.cloud import storage

        parts = [self.prefix] if self.prefix else []
        parts += [domain, f"{slug}.md"]
        blob = storage.Client().bucket(self.bucket).blob("/".join(parts))
        if blob.exists():
            blob.delete()


class MemoryGate:
    """Records proposals without writing anything. The safe default and test gate."""

    def __init__(self) -> None:
        self.proposals: list[Proposal] = []

    def submit(self, proposal: Proposal) -> ProposalResult:
        self.proposals.append(proposal)
        return ProposalResult(
            status="proposed",
            path=proposal.path,
            branch=None,
            checksum=proposal.checksum,
            detail="recorded for review (no write)",
        )


class GcsProposalGate:
    """Stages a proposal as an object under a review prefix in a bucket, never in the
    live corpus. The deployed brain has no git checkout, so this is the cloud review
    location: a human or a promotion step reviews ``gs://<bucket>/proposals/...`` and
    moves an approved proposal into the corpus, then re-indexes."""

    def __init__(self, bucket: str, prefix: str = "proposals") -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def submit(self, proposal: Proposal) -> ProposalResult:
        from google.cloud import storage

        blob_path = f"{self.prefix}/{proposal.domain}/{proposal.slug}-{proposal.checksum[:8]}.md"
        storage.Client().bucket(self.bucket).blob(blob_path).upload_from_string(proposal.content)
        uri = f"gs://{self.bucket}/{blob_path}"
        return ProposalResult(
            status="proposed",
            path=uri,
            branch=None,
            checksum=proposal.checksum,
            detail=f"staged for review at {uri}",
        )


class GcsCorpusGate:
    """Lands a document **live** into the corpus bucket under its domain, no review.

    Used only for personal-domain notes, which the caller owns, so there is nothing
    to review. It writes ``{domain}/{slug}.md`` in the corpus bucket exactly where a
    batch-ingested document would sit, so the next index build picks it up and it
    becomes searchable within the index TTL (the same path any content takes)."""

    def __init__(self, bucket: str, prefix: str = "") -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def submit(self, proposal: Proposal) -> ProposalResult:
        from google.cloud import storage

        parts = [self.prefix] if self.prefix else []
        parts += [proposal.domain, f"{proposal.slug}.md"]
        blob_path = "/".join(parts)
        storage.Client().bucket(self.bucket).blob(blob_path).upload_from_string(proposal.content)
        uri = f"gs://{self.bucket}/{blob_path}"
        return ProposalResult(
            status="saved",
            path=uri,
            branch=None,
            checksum=proposal.checksum,
            detail=f"saved to your personal space at {uri} (searchable after the next index build)",
        )


class GitBranchGate:
    """Lands a proposal on a fresh branch and returns to the original, so ``main``
    is never touched. The branch is the reviewable, revertible change."""

    def __init__(self, repo_dir: str | Path = ".", corpus_dir: str = "corpus") -> None:
        self.repo_dir = str(repo_dir)
        self.corpus_dir = corpus_dir

    def submit(self, proposal: Proposal) -> ProposalResult:
        # Imported here so the offline core never imports the subprocess helper
        # unless a real branch is actually being written.
        from ..ingest.adapters.git import _git

        original = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=self.repo_dir)
        branch = f"proposal/{proposal.domain}/{proposal.slug}-{proposal.checksum[:8]}"
        _git("checkout", "-b", branch, cwd=self.repo_dir)
        try:
            target = Path(self.repo_dir) / self.corpus_dir / proposal.domain / f"{proposal.slug}.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(proposal.content, encoding="utf-8")
            rel = target.relative_to(self.repo_dir).as_posix()
            _git("add", rel, cwd=self.repo_dir)
            _git(
                "-c",
                "user.email=brain@local",
                "-c",
                "user.name=hyper-brain",
                "commit",
                "-qm",
                f"proposal: {proposal.slug} by {proposal.author}",
                cwd=self.repo_dir,
            )
        finally:
            # Always return to the original branch, leaving the working tree clean.
            _git("checkout", original, cwd=self.repo_dir)
        return ProposalResult(
            status="proposed",
            path=rel,
            branch=branch,
            checksum=proposal.checksum,
            detail=f"committed to review branch {branch}",
        )


def get_gate(name: str | None = None) -> ReviewGate:
    """Return the configured review gate.

    Selected by ``BRAIN_PROPOSE_GATE``: ``git`` (default; a local branch, for the
    dev/personal flow), ``gcs`` (a review prefix in a bucket, for the deployed
    brain), or ``memory`` (records nothing to disk; the safe default in tests).
    """
    name = name or os.environ.get("BRAIN_PROPOSE_GATE", "git")
    if name == "memory":
        return MemoryGate()
    if name == "git":
        return GitBranchGate(os.environ.get("BRAIN_REPO", "."))
    if name == "gcs":
        bucket = os.environ.get("BRAIN_PROPOSALS_BUCKET")
        if not bucket:
            raise ValueError("BRAIN_PROPOSE_GATE=gcs requires BRAIN_PROPOSALS_BUCKET")
        return GcsProposalGate(bucket)
    raise ValueError(f"unknown proposal gate {name!r}")
