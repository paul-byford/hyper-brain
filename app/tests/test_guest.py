"""Read-only guest access: a token the AS mints without Google login.

A guest reads the commons (via the wildcard grant) and can use the read/compute
features (search, answer, Studio drafting), but every persistence step is refused
in-app, whatever the policy says. That server-side block is the load-bearing property,
because the commons wildcard grants write to everyone and a guest must not inherit it.
"""

from __future__ import annotations

import pytest

from brain_app.auth import HmacVerifier, encode_hs256
from brain_app.config import load_policy
from brain_app.ingest.curate import PassthroughCurator
from brain_app.serving import BrainService, GuestReadOnly

SECRET = "test-secret"


@pytest.fixture(scope="module")
def policy():
    return load_policy(prof="personal")


def _guest():
    token = encode_hs256({"sub": "guest:abc123", "scope": "read", "guest": True}, SECRET)
    return HmacVerifier(SECRET).verify(token)


def _svc(index, embeddings, policy):
    return BrainService(index, embeddings, policy, curator=PassthroughCurator())


def test_guest_identity_is_flagged():
    assert _guest().is_guest is True


def test_guest_cannot_add_a_note(index, embeddings, policy):
    with pytest.raises(GuestReadOnly):
        _svc(index, embeddings, policy).add_note(_guest(), title="x", content="y")


def test_guest_cannot_write_commons_despite_the_wildcard(index, embeddings, policy):
    # The commons wildcard grants write to everyone; the guest guard must override it.
    with pytest.raises(GuestReadOnly):
        _svc(index, embeddings, policy).add_document(
            _guest(), domain="commons", title="x", content="y"
        )


def test_guest_cannot_share_or_upload(index, embeddings, policy):
    svc = _svc(index, embeddings, policy)
    with pytest.raises(GuestReadOnly):
        svc.share(_guest(), principal="a@b.com", domain="commons")
    with pytest.raises(GuestReadOnly):
        svc.ingest_file(_guest(), filename="x.md", content_base64="", domain=None)


def test_guest_can_read_the_commons(index, embeddings, policy):
    svc = _svc(index, embeddings, policy)
    results = svc.search(_guest(), "welcome getting started")
    assert all(r.domain == "commons" for r in results)  # only the shared commons


def test_guest_can_draft_in_studio(index, embeddings, policy):
    # Drafting is read/compute, nothing persisted, so a guest may do it (the demo point).
    draft = _svc(index, embeddings, policy).make_draft(
        _guest(), kind="text", text="Some pasted source text.", curate=False
    )
    assert draft["content"]
