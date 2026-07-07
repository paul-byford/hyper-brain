"""Accepting a proposal: the stage-path -> live-path transform.

The move + reindex drive gcloud (exercised in deployment), but the path mapping is
pure and load-bearing (a wrong live path would land a proposal in the wrong place),
so it is unit-tested here.
"""

from __future__ import annotations

import pytest

from brain_app.serving.review import live_name, resolve_proposal

PROPOSALS = [
    "proposals/finserv-ai-engineering/streaming-feature-ttls-ce240687.md",
    "proposals/finserv-ai-engineering/model-risk-memo-a1b2c3d4.md",
]


def test_strips_prefix_and_checksum_suffix():
    assert (
        live_name("proposals/finserv-ai-engineering/feature-flags-for-models-a1b2c3d4.md")
        == "finserv-ai-engineering/feature-flags-for-models.md"
    )


def test_slug_with_no_hyphens():
    assert live_name("proposals/commons/welcome-0f1e2d3c.md") == "commons/welcome.md"


def test_a_bucket_relative_name_without_the_prefix_is_left_domain_scoped():
    # If already prefix-less, just drop the checksum suffix.
    assert live_name("finserv-ai-engineering/note-deadbeef.md") == "finserv-ai-engineering/note.md"


def test_only_a_trailing_8_hex_suffix_is_stripped():
    # A hyphenated word that is not an 8-hex checksum is preserved.
    assert live_name("proposals/team/quarterly-review.md") == "team/quarterly-review.md"
    # A personal-domain proposal keeps its colon-bearing domain segment.
    assert live_name("proposals/personal:sub-9/roadmap-0011aabb.md") == "personal:sub-9/roadmap.md"


def test_resolve_proposal_accepts_the_staged_path_directly():
    assert resolve_proposal(PROPOSALS[0], PROPOSALS) == PROPOSALS[0]


def test_resolve_proposal_maps_a_live_path_back_to_its_staged_proposal():
    # This is exactly what a user pastes from the right-hand column of `review`.
    live = "finserv-ai-engineering/streaming-feature-ttls.md"
    assert resolve_proposal(live, PROPOSALS) == PROPOSALS[0]


def test_resolve_proposal_errors_when_nothing_matches():
    with pytest.raises(FileNotFoundError):
        resolve_proposal("finserv-ai-engineering/does-not-exist.md", PROPOSALS)
