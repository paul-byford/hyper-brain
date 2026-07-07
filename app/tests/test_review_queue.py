"""Server-side review queue: write access to a domain is review access.

A caller may see and accept only proposals in domains they can write; a read-only
caller sees an empty queue and cannot accept. Accepting promotes the proposal and
triggers a reindex. This is the enforcement the in-browser review queue backs onto.
"""

from __future__ import annotations

import pytest

from brain_app.auth import identity_from_claims
from brain_app.config import load_policy
from brain_app.serving import BrainService, DomainNotAuthorized
from brain_app.serving.reindex import MemoryReindexer
from brain_app.serving.reviewer import MemoryReviewer

from .conftest import FINSERV, RECRUITMENT

FRAUD_PROP = f"proposals/{FINSERV}/new-fraud-model-aabbccdd.md"
REC_PROP = f"proposals/{RECRUITMENT}/sourcing-strategy-11223344.md"


def _ident(sub, groups=(), scope="read"):
    return identity_from_claims({"sub": sub, "email": sub, "groups": list(groups), "scope": scope})


ADMIN = _ident("admin@example.com", groups=["brain-admins@example.com"])
FINSERV_WRITER = _ident("fin@example.com", groups=["finserv-eng@example.com"], scope="read propose")
RECRUITER_RO = _ident("rex@example.com", groups=["recruiting@example.com"])


def _svc(index, embeddings, reviewer=None):
    return BrainService(
        index,
        embeddings,
        load_policy(prof="personal"),
        reviewer=reviewer or MemoryReviewer({FRAUD_PROP: b"# body", REC_PROP: b"# body"}),
    )


def test_admin_sees_the_whole_queue(index, embeddings):
    svc = _svc(index, embeddings)
    assert {p["name"] for p in svc.list_proposals(ADMIN)} == {FRAUD_PROP, REC_PROP}


def test_writer_sees_only_proposals_in_domains_they_can_write(index, embeddings):
    svc = _svc(index, embeddings)
    names = {p["name"] for p in svc.list_proposals(FINSERV_WRITER)}
    assert FRAUD_PROP in names and REC_PROP not in names


def test_readonly_caller_sees_an_empty_queue(index, embeddings):
    svc = _svc(index, embeddings)
    # The recruiter has read but no write on recruitment, and no write anywhere.
    assert svc.list_proposals(RECRUITER_RO) == []


def test_accept_promotes_and_reindexes(index, embeddings):
    reviewer = MemoryReviewer({FRAUD_PROP: b"# body"})
    reindexer = MemoryReindexer()
    svc = BrainService(
        index, embeddings, load_policy(prof="personal"), reviewer=reviewer, reindexer=reindexer
    )
    result = svc.accept_proposal(ADMIN, FRAUD_PROP)
    assert result["dest"] == f"{FINSERV}/new-fraud-model.md"
    assert FRAUD_PROP not in reviewer.staged  # moved out of the queue
    assert reviewer.live[f"{FINSERV}/new-fraud-model.md"] == b"# body"
    assert reindexer.triggers == 1  # promoted content triggers a rebuild


def test_accept_without_write_access_is_refused(index, embeddings):
    reviewer = MemoryReviewer({FRAUD_PROP: b"# body"})
    reindexer = MemoryReindexer()
    svc = BrainService(
        index, embeddings, load_policy(prof="personal"), reviewer=reviewer, reindexer=reindexer
    )
    with pytest.raises(DomainNotAuthorized):
        svc.accept_proposal(RECRUITER_RO, FRAUD_PROP)
    assert reindexer.triggers == 0  # nothing happened
