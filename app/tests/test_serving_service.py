"""Pillar 2 (security): the service enforces domain isolation and write scope.

The boundary is asserted at the server layer here, on top of the retrieval-level
isolation of test_isolation.py: a token scoped to one domain cannot retrieve
another, cross-domain documents cannot even be probed for, and a read-only token
cannot use the write path.
"""

from __future__ import annotations

import pytest

from brain_app.auth import HmacVerifier, encode_hs256
from brain_app.config import load_policy
from brain_app.serving import (
    BrainService,
    DocumentNotFound,
    DomainNotAuthorized,
    MemoryGate,
)

from .conftest import COMMONS, FINSERV, RECRUITMENT

SECRET = "test-secret"


@pytest.fixture(scope="module")
def policy():
    return load_policy(prof="personal")


def _identity(groups, scope="read", email="user@bank.com"):
    """Mint a token and verify it, so tests exercise the real token->identity path."""
    token = encode_hs256({"sub": email, "email": email, "groups": groups, "scope": scope}, SECRET)
    return HmacVerifier(SECRET).verify(token)


FINSERV_ENG = ["finserv-eng@example.com"]
RECRUITER = ["recruiting@example.com"]
ADMIN = ["brain-admins@example.com"]


def _service(index, embeddings, policy, gate=None):
    return BrainService(index, embeddings, policy, gate=gate)


def test_list_domains_is_scoped(index, embeddings, policy):
    svc = _service(index, embeddings, policy)
    # Everyone also sees the commons domain (wildcard) and their own personal space.
    personal = "personal:user@bank.com"  # _identity mints sub == email
    assert svc.list_domains(_identity(FINSERV_ENG)) == sorted([COMMONS, FINSERV, personal])
    assert svc.list_domains(_identity(RECRUITER)) == sorted([COMMONS, RECRUITMENT, personal])
    assert svc.list_domains(_identity(ADMIN)) == sorted([COMMONS, FINSERV, RECRUITMENT, personal])


def test_search_never_crosses_domain(index, embeddings, policy):
    svc = _service(index, embeddings, policy)
    # A finserv caller asks a recruitment question: recruitment never comes back
    # (commons is shared and may appear, but the other team's domain never does).
    results = svc.search(_identity(FINSERV_ENG), "candidate sourcing and interview copilots")
    assert results
    assert all(r.domain != RECRUITMENT for r in results)


def test_answer_citations_never_cross_domain(index, embeddings, policy):
    svc = _service(index, embeddings, policy)
    result = svc.answer(_identity(RECRUITER), "real-time fraud detection and trade surveillance")
    assert all(c.domain != FINSERV for c in result.citations)


def test_get_document_in_scope_succeeds(index, embeddings, policy):
    svc = _service(index, embeddings, policy)
    doc = svc.get_document(_identity(FINSERV_ENG), f"{FINSERV}/realtime-fraud-detection")
    assert doc["domain"] == FINSERV
    assert "fraud" in doc["text"].lower()


def test_get_document_cross_domain_is_indistinguishable_from_missing(index, embeddings, policy):
    svc = _service(index, embeddings, policy)
    # The document exists, but not in a domain this caller may see. The error must
    # be the same as for a truly missing id, so existence cannot be probed.
    with pytest.raises(DocumentNotFound):
        svc.get_document(_identity(RECRUITER), f"{FINSERV}/realtime-fraud-detection")
    with pytest.raises(DocumentNotFound):
        svc.get_document(_identity(RECRUITER), f"{RECRUITMENT}/does-not-exist")


def test_readonly_token_cannot_propose_into_a_team_domain(index, embeddings, policy):
    # Commons is writable by everyone (wildcard write), but a team domain still needs an
    # explicit write grant, so a read-only finserv caller is refused there.
    svc = _service(index, embeddings, policy, gate=MemoryGate())
    with pytest.raises(DomainNotAuthorized):
        svc.propose_document(
            _identity(FINSERV_ENG, scope="read"),
            domain=FINSERV,
            title="Sneaky",
            content="body",
        )


def test_propose_into_ungranted_domain_rejected(index, embeddings, policy):
    svc = _service(index, embeddings, policy, gate=MemoryGate())
    # Has the write scope, but not for the recruitment domain.
    with pytest.raises(DomainNotAuthorized):
        svc.propose_document(
            _identity(FINSERV_ENG, scope="read propose"),
            domain=RECRUITMENT,
            title="Cross domain",
            content="body",
        )


def test_valid_proposal_reaches_the_gate(index, embeddings, policy):
    gate = MemoryGate()
    svc = _service(index, embeddings, policy, gate=gate)
    result = svc.propose_document(
        _identity(FINSERV_ENG, scope="read propose"),
        domain=FINSERV,
        title="Feature flags for models",
        content="# Feature flags\n\nGate model rollouts behind flags.\n",
    )
    assert result.status == "proposed"
    assert result.path == f"corpus/{FINSERV}/feature-flags-for-models.md"
    assert len(gate.proposals) == 1
    # Provenance stamped, and it landed in the caller's domain only.
    assert f"domain: {FINSERV}" in gate.proposals[0].content
    assert "source: agent:user@bank.com" in gate.proposals[0].content


def test_add_document_direct_write_with_a_write_grant(index, embeddings, policy):
    # A write grant is trust: the write lands live through the corpus gate (note_gate),
    # not the review gate, so a trusted member contributes without a review round-trip.
    svc = _service(index, embeddings, policy)
    result = svc.add_document(
        _identity(ADMIN), domain=FINSERV, title="Ops runbook", content="steps"
    )
    assert svc.note_gate.proposals[-1].domain == FINSERV
    assert svc.gate.proposals == []  # the review gate was never used
    assert result.checksum


def test_add_document_refused_for_a_team_domain_without_grant(index, embeddings, policy):
    # A finserv reader can write commons (wildcard), but not the finserv team domain.
    svc = _service(index, embeddings, policy)
    with pytest.raises(DomainNotAuthorized):
        svc.add_document(_identity(FINSERV_ENG), domain=FINSERV, title="x", content="y")


def test_add_document_to_commons_allowed_for_everyone(index, embeddings, policy):
    # The wildcard write grant lets any signed-in caller contribute to the commons
    # directly (no manual grant), landing live through the corpus gate.
    svc = _service(index, embeddings, policy)
    svc.add_document(_identity(FINSERV_ENG), domain=COMMONS, title="Handy tip", content="body")
    assert svc.note_gate.proposals[-1].domain == COMMONS
