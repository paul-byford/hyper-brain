"""Pillar 1/2: the write path stamps provenance and never touches main."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from brain_app.serving.proposals import GitBranchGate, MemoryGate, build_proposal

from .conftest import FINSERV


def test_build_proposal_stamps_provenance_and_slug():
    proposal = build_proposal(
        domain=FINSERV,
        title="Model Rollout Playbook",
        content="# Model Rollout Playbook\n\nStage, canary, promote.\n",
        author="eng@bank.com",
    )
    assert proposal.slug == "model-rollout-playbook"
    assert proposal.path == f"corpus/{FINSERV}/model-rollout-playbook.md"
    assert f"domain: {FINSERV}" in proposal.content
    assert "source: agent:eng@bank.com" in proposal.content
    assert len(proposal.checksum) == 64


def test_memory_gate_records_without_writing():
    gate = MemoryGate()
    proposal = build_proposal(domain=FINSERV, title="X", content="# X\n\nbody\n", author="a@b.com")
    result = gate.submit(proposal)
    assert result.branch is None
    assert result.status == "proposed"
    assert gate.proposals == [proposal]


@pytest.mark.skipif(not shutil.which("git"), reason="git CLI not available")
def test_git_branch_gate_quarantines_change(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> str:
        out = subprocess.run(  # nosec B603 B607
            ["git", *args], cwd=repo, check=True, capture_output=True, text=True
        )
        return out.stdout.strip()

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "Test")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    git("add", "README.md")
    git("commit", "-qm", "seed")

    proposal = build_proposal(
        domain=FINSERV,
        title="Streaming Cost Controls",
        content="# Streaming Cost Controls\n\nBudget the feature pipeline.\n",
        author="eng@bank.com",
    )
    result = GitBranchGate(repo_dir=str(repo)).submit(proposal)

    # We are back on main, and main is clean: the change never landed live.
    assert git("rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert git("status", "--porcelain") == ""
    assert not (repo / "corpus" / FINSERV / "streaming-cost-controls.md").exists()

    # The reviewable change exists on its own branch.
    assert result.branch == f"proposal/{FINSERV}/streaming-cost-controls-{proposal.checksum[:8]}"
    branches = git("branch", "--list", result.branch)
    assert result.branch in branches
    landed = git("show", f"{result.branch}:corpus/{FINSERV}/streaming-cost-controls.md")
    assert "Budget the feature pipeline." in landed
