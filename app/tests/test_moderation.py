"""Content lifecycle and community moderation (edit / delete / report).

Commons is writable by everyone (a wildcard write grant), so edit and delete are
deliberately narrower than "can write the domain": only the personal owner, or a
holder of an EXPLICIT (non-wildcard) write grant, may moderate. A wildcard commons
writer can add, but cannot edit or delete other people's content. Reports are the
lightweight counterweight: any reader flags, a moderator dismisses or removes.
"""

from __future__ import annotations

import numpy as np
import pytest

from brain_app.auth import HmacVerifier, encode_hs256
from brain_app.config import load_policy
from brain_app.models import Chunk, Document
from brain_app.retrieval import BrainIndex
from brain_app.serving import AccessError, BrainService, RateLimitError
from brain_app.serving.reports import MemoryReportsStore

from .conftest import COMMONS, FINSERV

SECRET = "test-secret"

FINSERV_ENG = ["finserv-eng@example.com"]
ADMIN = ["brain-admins@example.com"]

FINSERV_DOC = f"{FINSERV}/realtime-fraud-detection"
COMMONS_DOC = f"{COMMONS}/welcome-to-hyper-brain"


@pytest.fixture(scope="module")
def policy():
    return load_policy(prof="personal")


def _identity(groups, scope="read propose", email="user@bank.com"):
    token = encode_hs256({"sub": email, "email": email, "groups": groups, "scope": scope}, SECRET)
    return HmacVerifier(SECRET).verify(token)


def _service(index, embeddings, policy, **kw):
    return BrainService(index, embeddings, policy, **kw)


def _index_with_note(index, embeddings, *, owner, slug, title):
    """A copy of the corpus index with one extra personal-domain note, so the owner's
    edit/delete path (which reads the doc from the index first) can be exercised."""
    domain = f"personal:{owner}"
    doc_id = f"{domain}/{slug}"
    text = f"note body for {title}"
    chunk = Chunk(
        id=f"{doc_id}#0", doc_id=doc_id, domain=domain, title=title, heading="", text=text, order=0
    )
    chunks = [*index.chunks, chunk]
    emb = np.vstack([index.embeddings, np.asarray(embeddings.embed([text]), dtype=np.float32)])
    docs = {
        **index.documents,
        doc_id: Document(
            doc_id=doc_id, domain=domain, title=title, path=f"corpus/{domain}/{slug}.md"
        ),
    }
    adjacency = {**index.adjacency, doc_id: []}
    return BrainIndex(
        chunks, emb, docs, adjacency, index.embedding_dim, index.provider, index.content_hash
    )


# --- moderatable scope -------------------------------------------------------


def test_moderatable_domains_excludes_wildcard_commons(index, embeddings, policy):
    svc = _service(index, embeddings, policy)
    # An explicit write grant (admin on the team domains) is moderatable; the wildcard
    # commons write is not, and the caller's own personal space always is.
    mod = svc.moderatable_domains(_identity(ADMIN, email="ada@bank.com"))
    assert FINSERV in mod
    assert COMMONS not in mod
    assert "personal:ada@bank.com" in mod


def test_wildcard_writer_moderates_only_their_personal_space(index, embeddings, policy):
    svc = _service(index, embeddings, policy)
    mod = svc.moderatable_domains(_identity(FINSERV_ENG, email="fin@bank.com"))
    assert mod == ["personal:fin@bank.com"]


# --- edit --------------------------------------------------------------------


def test_owner_can_edit_their_personal_note(index, embeddings, policy):
    idx = _index_with_note(index, embeddings, owner="pat@bank.com", slug="my-note", title="My note")
    svc = _service(idx, embeddings, policy)
    who = _identity(FINSERV_ENG, email="pat@bank.com")
    result = svc.edit_document(
        who, "personal:pat@bank.com/my-note", content="# My note\n\nrevised body", tags=["x"]
    )
    assert result["status"] == "saved"
    assert svc.note_gate.proposals[-1].domain == "personal:pat@bank.com"


def test_a_different_user_cannot_edit_your_personal_note(index, embeddings, policy):
    idx = _index_with_note(index, embeddings, owner="pat@bank.com", slug="my-note", title="My note")
    svc = _service(idx, embeddings, policy)
    # A different signed-in caller cannot even see the note: indistinguishable from missing.
    from brain_app.serving import DocumentNotFound

    with pytest.raises(DocumentNotFound):
        svc.edit_document(
            _identity(FINSERV_ENG, email="other@bank.com"),
            "personal:pat@bank.com/my-note",
            content="hijack",
        )


def test_moderator_can_edit_team_document(index, embeddings, policy):
    svc = _service(index, embeddings, policy)
    result = svc.edit_document(
        _identity(ADMIN), FINSERV_DOC, content="# Realtime fraud detection\n\nrewritten"
    )
    assert result["status"] == "saved"
    assert svc.note_gate.proposals[-1].domain == FINSERV


def test_wildcard_writer_cannot_edit_commons_content(index, embeddings, policy):
    # A caller with only the wildcard commons write can ADD to commons, but must not be
    # able to edit content they do not own: that is the moderation boundary.
    svc = _service(index, embeddings, policy)
    with pytest.raises(AccessError):
        svc.edit_document(_identity(FINSERV_ENG), COMMONS_DOC, content="hijacked")


def test_edit_rename_removes_the_old_slug(index, embeddings, policy):
    idx = _index_with_note(
        index, embeddings, owner="ren@bank.com", slug="first-title", title="First title"
    )
    svc = _service(idx, embeddings, policy)
    who = _identity(FINSERV_ENG, email="ren@bank.com")
    svc.edit_document(
        who, "personal:ren@bank.com/first-title", content="body", title="Second title"
    )
    assert ("personal:ren@bank.com", "first-title") in svc.deleter.deleted


# --- delete ------------------------------------------------------------------


def test_owner_can_delete_their_note(index, embeddings, policy):
    idx = _index_with_note(index, embeddings, owner="del@bank.com", slug="doomed", title="Doomed")
    svc = _service(idx, embeddings, policy)
    who = _identity(FINSERV_ENG, email="del@bank.com")
    result = svc.delete_document(who, "personal:del@bank.com/doomed")
    assert result["status"] == "deleted"
    assert ("personal:del@bank.com", "doomed") in svc.deleter.deleted


def test_non_moderator_cannot_delete_commons_content(index, embeddings, policy):
    svc = _service(index, embeddings, policy)
    with pytest.raises(AccessError):
        svc.delete_document(_identity(FINSERV_ENG), COMMONS_DOC)


def test_delete_of_unseen_document_is_not_found(index, embeddings, policy):
    from brain_app.serving import DocumentNotFound

    svc = _service(index, embeddings, policy)
    with pytest.raises(DocumentNotFound):
        svc.delete_document(_identity(FINSERV_ENG), f"{FINSERV}/does-not-exist")


# --- report / moderate -------------------------------------------------------


def test_report_is_visible_only_to_a_moderator_of_the_domain(index, embeddings, policy):
    store = MemoryReportsStore()
    svc = _service(index, embeddings, policy, reports_store=store)
    reporter = _identity(FINSERV_ENG, email="reader@bank.com")
    svc.report_document(reporter, FINSERV_DOC, reason="looks stale")
    # The reporter (not a moderator of finserv) sees nothing in their queue.
    assert svc.reports_for_moderator(reporter) == []
    # A finserv moderator sees the flag.
    queue = svc.reports_for_moderator(_identity(ADMIN))
    assert len(queue) == 1
    assert queue[0]["doc_id"] == FINSERV_DOC
    assert queue[0]["reason"] == "looks stale"


def test_dismiss_clears_the_flag_without_deleting(index, embeddings, policy):
    store = MemoryReportsStore()
    svc = _service(index, embeddings, policy, reports_store=store)
    svc.report_document(_identity(FINSERV_ENG), FINSERV_DOC, reason="typo")
    svc.resolve_report(_identity(ADMIN), FINSERV_DOC, remove=False)
    assert svc.reports_for_moderator(_identity(ADMIN)) == []
    assert svc.deleter.deleted == []  # dismiss never deletes


def test_remove_deletes_the_document_and_clears_flags(index, embeddings, policy):
    store = MemoryReportsStore()
    svc = _service(index, embeddings, policy, reports_store=store)
    svc.report_document(_identity(FINSERV_ENG), FINSERV_DOC, reason="wrong")
    result = svc.resolve_report(_identity(ADMIN), FINSERV_DOC, remove=True)
    assert result["status"] == "deleted"
    assert ("finserv-ai-engineering", "realtime-fraud-detection") in svc.deleter.deleted
    assert store.open_reports() == []


def test_non_moderator_cannot_resolve_a_report(index, embeddings, policy):
    store = MemoryReportsStore()
    svc = _service(index, embeddings, policy, reports_store=store)
    svc.report_document(_identity(FINSERV_ENG), FINSERV_DOC, reason="x")
    with pytest.raises(AccessError):
        svc.resolve_report(_identity(FINSERV_ENG), FINSERV_DOC, remove=False)


# --- rate limit --------------------------------------------------------------


def test_write_rate_limit_blocks_a_flood(index, embeddings, policy):
    svc = _service(index, embeddings, policy)
    who = _identity(FINSERV_ENG, email="flood@bank.com")
    # The budget is generous but finite; a flood past it is refused.
    with pytest.raises(RateLimitError):
        for i in range(500):
            svc.add_note(who, title=f"note {i}", content="body")
