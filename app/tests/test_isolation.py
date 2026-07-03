"""Security pillar: domain isolation is enforced in the retrieval path.

These tests assert the boundary the whole design rests on. They live with the
retrieval core because that is where the filter is applied; the serving layer adds
identity verification on top in a later phase.
"""

from __future__ import annotations

import pytest

from brain_app.retrieval import answer, search

from .conftest import FINSERV, RECRUITMENT


def test_finserv_scope_never_returns_recruitment(index, embeddings):
    # A query whose best matches live in the recruitment domain.
    results = search(
        index,
        "candidate sourcing, interview copilots and hiring bias audits",
        {FINSERV},
        embeddings,
    )
    assert results  # it still returns the best finserv chunks
    assert all(r.domain == FINSERV for r in results)


def test_recruitment_scope_never_returns_finserv(index, embeddings):
    results = search(
        index,
        "trade surveillance, model risk and real-time fraud detection",
        {RECRUITMENT},
        embeddings,
    )
    assert results
    assert all(r.domain == RECRUITMENT for r in results)


def test_empty_scope_returns_nothing(index, embeddings):
    assert search(index, "anything at all", set(), embeddings) == []


@pytest.mark.eval
def test_isolation_eval_answer_does_not_leak_across_domains(index, embeddings):
    # Caller can only see recruitment, but asks a finserv question. The answer must
    # not cite finserv content: no chunk from an unpermitted domain may appear.
    result = answer(
        index,
        "how do we run trade surveillance with retrieval augmented generation",
        {RECRUITMENT},
        embeddings,
    )
    assert all(c.domain == RECRUITMENT for c in result.citations)
