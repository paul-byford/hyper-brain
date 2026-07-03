from __future__ import annotations

import pytest

from brain_app.retrieval import answer, search

from .conftest import FINSERV, RECRUITMENT


def test_search_returns_results_from_the_scoped_domain(index, embeddings):
    results = search(
        index,
        "how do we govern model risk for large language models",
        {FINSERV},
        embeddings,
    )
    assert results
    assert all(r.domain == FINSERV for r in results)


def test_link_expansion_pulls_neighbours(index, embeddings):
    # The overview links to the other finserv docs, so expansion should add
    # at least one "link" hit when the overview is a primary result.
    results = search(
        index,
        "overview of AI engineering for financial services",
        {FINSERV},
        embeddings,
        top_k=3,
    )
    assert any(r.via == "link" for r in results)


def test_answer_includes_citations_and_gap_list(index, embeddings):
    result = answer(
        index,
        "what is our policy on quantum key rotation schedules",
        {FINSERV},
        embeddings,
    )
    assert isinstance(result.gaps, list)
    assert all(c.domain == FINSERV for c in result.citations)


@pytest.mark.eval
def test_eval_finserv_governance_query_ranks_right_doc(index, embeddings):
    results = search(
        index,
        "SR 11-7 model risk governance and validation for LLMs",
        {FINSERV},
        embeddings,
        top_k=3,
    )
    assert any(r.doc_id == f"{FINSERV}/model-risk-governance-llms" for r in results[:3])


@pytest.mark.eval
def test_eval_recruitment_compliance_query_ranks_right_doc(index, embeddings):
    results = search(
        index,
        "bias audit Local Law 144 EEOC hiring compliance",
        {RECRUITMENT},
        embeddings,
        top_k=3,
    )
    assert any(r.doc_id == f"{RECRUITMENT}/bias-audits-compliance" for r in results[:3])
