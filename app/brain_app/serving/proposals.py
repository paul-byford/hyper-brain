"""The write path's review gate: a proposal is a quarantined change, never a live write.

The agent write tool (``propose_document``) reuses the Phase 2 stamping so an
agent-authored document is provenance-stamped exactly like a batch-ingested one,
then hands it to a ``ReviewGate``. The load-bearing property (ARCHITECTURE.md
section 12) is that a proposal never mutates the live corpus on ``main``: the
default ``GitBranchGate`` lands it on a fresh branch for review, and ``MemoryGate``
records it without touching the filesystem (the safe default, used in tests).
"""

from __future__ import annotations

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
        tags=[],
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
