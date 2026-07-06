"""The dynamic sharing overlay: user-authored grants merged over the base policy.

Covers the overlay's evaluation and serialisation, and the serving-layer contract:
a user can share a domain or a single document they own, the grantee gains exactly
that (and no more), sharing is owner-checked, revoking removes access immediately,
and the wildcard is never a valid share principal.
"""

from __future__ import annotations

import numpy as np
import pytest
import yaml

from brain_app.auth import (
    MemorySharesStore,
    Share,
    ShareError,
    identity_from_claims,
    validate_share,
)
from brain_app.auth.shares import dump_shares, parse_shares
from brain_app.config import load_policy
from brain_app.models import Chunk, Document
from brain_app.retrieval.index import BrainIndex
from brain_app.serving import (
    AccessError,
    BrainService,
    DocumentNotFound,
    DomainNotAuthorized,
    MemoryGate,
)

from .conftest import COMMONS, FINSERV, RECRUITMENT

FRAUD_DOC = f"{FINSERV}/realtime-fraud-detection"
OTHER_FINSERV_DOC = f"{FINSERV}/model-risk-governance-llms"
RECRUIT_GROUP = "group:recruiting@example.com"


def _ident(sub, email=None, groups=()):
    return identity_from_claims({"sub": sub, "email": email or sub, "groups": list(groups)})


ADMIN = _ident("admin@example.com", groups=["brain-admins@example.com"])
RECRUITER = _ident("rex@example.com", groups=["recruiting@example.com"])


@pytest.fixture
def svc(index, embeddings):
    # A fresh store per test so shares never leak between them.
    return BrainService(
        index, embeddings, load_policy(prof="personal"), shares_store=MemorySharesStore()
    )


# --- Overlay evaluation and serialisation ----------------------------------------


def test_validate_share_rejects_wildcard_and_empty_principal():
    with pytest.raises(ShareError):
        validate_share(Share(principal="*", domain="d", granted_by="o"))
    with pytest.raises(ShareError):
        validate_share(Share(principal="", domain="d", granted_by="o"))


def test_shares_round_trip_through_yaml():
    shares = [
        Share("a@e.com", "personal:o", "o", doc_id=None, write=True, granted_at="t"),
        Share("group:x", "personal:o", "o", doc_id="personal:o/note", granted_at="t"),
    ]
    assert parse_shares({"shares": [s.__dict__ for s in shares]})  # dict form loads
    reparsed = parse_shares(yaml.safe_load(dump_shares(shares)))
    assert reparsed == shares


def test_memory_store_is_per_owner():
    store = MemorySharesStore()
    store.put_owner("o1", [Share("a@e.com", "personal:o1", "o1")])
    store.put_owner("o2", [Share("b@e.com", "personal:o2", "o2")])
    assert len(store.all_shares()) == 2
    assert len(store.for_owner("o1")) == 1
    store.put_owner("o1", [])  # emptying deletes the owner's file
    assert len(store.all_shares()) == 1


# --- Document-level sharing (serving layer) --------------------------------------


def test_doc_share_grants_exactly_one_document(svc):
    # Before: the recruiter cannot see any finserv document.
    with pytest.raises(DocumentNotFound):
        svc.get_document(RECRUITER, FRAUD_DOC)

    svc.share(ADMIN, principal=RECRUIT_GROUP, doc_id=FRAUD_DOC)

    # After: exactly that one document is visible, and it is the real thing.
    doc = svc.get_document(RECRUITER, FRAUD_DOC)
    assert doc["domain"] == FINSERV and "fraud" in doc["text"].lower()
    # A different finserv document stays hidden: the share widened by one doc only.
    with pytest.raises(DocumentNotFound):
        svc.get_document(RECRUITER, OTHER_FINSERV_DOC)


def test_doc_share_surfaces_in_search_without_leaking_neighbours(svc):
    svc.share(ADMIN, principal=RECRUIT_GROUP, doc_id=FRAUD_DOC)
    results = svc.search(RECRUITER, "real-time fraud detection")
    # The shared doc can appear; any finserv hit must be exactly the shared doc,
    # never one of its (unshared) domain neighbours pulled in by link expansion.
    assert any(r.doc_id == FRAUD_DOC for r in results)
    assert all(r.doc_id == FRAUD_DOC for r in results if r.domain == FINSERV)


def test_unshare_revokes_access(svc):
    svc.share(ADMIN, principal=RECRUIT_GROUP, doc_id=FRAUD_DOC)
    assert svc.get_document(RECRUITER, FRAUD_DOC)  # granted
    removed = svc.unshare(ADMIN, principal=RECRUIT_GROUP, doc_id=FRAUD_DOC)
    assert removed == 1
    with pytest.raises(DocumentNotFound):
        svc.get_document(RECRUITER, FRAUD_DOC)


# --- Whole-domain sharing --------------------------------------------------------


def test_domain_share_grants_the_whole_domain(svc):
    svc.share(ADMIN, principal=RECRUIT_GROUP, domain=FINSERV)
    assert FINSERV in svc.list_domains(RECRUITER)
    # Now any finserv document is retrievable, not just one.
    assert svc.get_document(RECRUITER, OTHER_FINSERV_DOC)["domain"] == FINSERV


# --- Owner checks and list_shares ------------------------------------------------


def test_cannot_share_content_you_do_not_own(svc):
    # The recruiter may read recruitment, but read access is not the right to share.
    with pytest.raises(DomainNotAuthorized):
        svc.share(RECRUITER, principal="someone@example.com", domain=RECRUITMENT)


def test_cannot_reshare_a_document_merely_shared_to_you(svc):
    svc.share(ADMIN, principal=RECRUIT_GROUP, doc_id=FRAUD_DOC)  # recruiter can now read it
    # ...but not pass it on: they do not own or write the finserv domain.
    with pytest.raises(DomainNotAuthorized):
        svc.share(RECRUITER, principal="friend@example.com", doc_id=FRAUD_DOC)


def test_sharing_a_document_you_cannot_see_is_indistinguishable_from_missing(svc):
    # The recruiter cannot probe for finserv docs by trying to share them.
    with pytest.raises(DocumentNotFound):
        svc.share(RECRUITER, principal="friend@example.com", doc_id=FRAUD_DOC)


def test_list_shares_shows_granted_and_received(svc):
    svc.share(ADMIN, principal=RECRUIT_GROUP, doc_id=FRAUD_DOC)
    assert len(svc.list_shares(ADMIN)["granted"]) == 1
    assert svc.list_shares(ADMIN)["received"] == []
    received = svc.list_shares(RECRUITER)["received"]
    assert len(received) == 1 and received[0]["doc_id"] == FRAUD_DOC
    assert svc.list_shares(RECRUITER)["granted"] == []


def test_commons_is_visible_to_everyone(svc):
    # The wildcard grant means even a brand-new caller sees commons.
    newcomer = _ident("nobody@example.com")
    assert COMMONS in svc.list_domains(newcomer)


# --- Personal-domain sharing (over in-memory personal content) -------------------


def _personal_index(embeddings, sub):
    """A one-document index living in a caller's personal domain."""
    domain = f"personal:{sub}"
    doc_id = f"{domain}/roadmap"
    text = "My private roadmap: ship the sharing overlay, then the personal notes UI."
    doc = Document(doc_id=doc_id, domain=domain, title="Roadmap", path="mem")
    chunk = Chunk(
        id=f"{doc_id}#0",
        doc_id=doc_id,
        domain=domain,
        title="Roadmap",
        heading="",
        text=text,
        order=0,
    )
    vecs = np.asarray(embeddings.embed([text]), dtype=np.float32)
    return BrainIndex([chunk], vecs, {doc_id: doc}, {}, embeddings.dim, "fake", "h"), doc_id


def test_personal_content_is_private_then_shareable(embeddings):
    index, doc_id = _personal_index(embeddings, "owner-1")
    owner = _ident("owner-1")
    friend = _ident("friend-1", email="friend@example.com")
    svc = BrainService(
        index, embeddings, load_policy(prof="personal"), shares_store=MemorySharesStore()
    )

    # The owner sees their own note; the friend sees nothing of it.
    assert svc.get_document(owner, doc_id)["title"] == "Roadmap"
    with pytest.raises(DocumentNotFound):
        svc.get_document(friend, doc_id)

    # The owner shares their whole personal domain with the friend.
    svc.share(owner, principal="friend@example.com", domain="personal:owner-1")
    assert svc.get_document(friend, doc_id)["title"] == "Roadmap"

    # Revoking makes it private again, for good.
    svc.unshare(owner, principal="friend@example.com", domain="personal:owner-1")
    with pytest.raises(DocumentNotFound):
        svc.get_document(friend, doc_id)


# --- Personal notes (ungated write into your own space) --------------------------


def test_add_note_lands_in_the_callers_personal_domain(index, embeddings):
    gate = MemoryGate()
    svc = BrainService(index, embeddings, load_policy(prof="personal"), note_gate=gate)
    owner = _ident("sub-42", email="me@example.com")
    result = svc.add_note(owner, title="Standup notes", content="Shipped the overlay.")
    assert result.status in {"proposed", "saved"}
    assert len(gate.proposals) == 1
    landed = gate.proposals[0]
    # It landed in the caller's own personal domain, provenance-stamped.
    assert landed.domain == "personal:sub-42"
    assert "domain: personal:sub-42" in landed.content


def test_anonymous_caller_cannot_add_a_note(index, embeddings):
    svc = BrainService(index, embeddings, load_policy(prof="personal"))
    with pytest.raises(AccessError):
        svc.add_note(identity_from_claims({}), title="x", content="y")
