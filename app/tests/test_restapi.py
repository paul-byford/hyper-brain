"""The JSON REST facade the browser UI calls. Same enforcement as MCP, over HTTP.

Uses the SDK's real Starlette app (so the routes are wired exactly as deployed), an
HS256 verifier, and an in-process reviewer, so the whole thing runs with no cloud.
"""

from __future__ import annotations

import pytest

# The [mcp] extra provides the FastMCP app the facade mounts onto.
pytest.importorskip("mcp")

import base64  # noqa: E402

from starlette.testclient import TestClient  # noqa: E402

from brain_app.auth import HmacVerifier, encode_hs256  # noqa: E402
from brain_app.config import load_policy  # noqa: E402
from brain_app.serving import BrainService  # noqa: E402
from brain_app.serving.reviewer import MemoryReviewer  # noqa: E402
from brain_app.serving.server import build_server  # noqa: E402

from .conftest import FINSERV, RECRUITMENT  # noqa: E402

SECRET = "test-secret"
FRAUD_PROP = f"proposals/{FINSERV}/new-fraud-model-aabbccdd.md"


def _token(groups, *, scope="read", email="u@example.com", sub=None):
    return encode_hs256(
        {"sub": sub or email, "email": email, "groups": groups, "scope": scope}, SECRET
    )


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(index, embeddings):
    svc = BrainService(
        index,
        embeddings,
        load_policy(prof="personal"),
        reviewer=MemoryReviewer({FRAUD_PROP: b"# body"}),
    )
    server = build_server(svc, HmacVerifier(SECRET))
    with TestClient(server.streamable_http_app()) as c:
        yield c


def test_me_requires_authentication(client):
    assert client.get("/api/me").status_code == 401


def test_me_returns_the_callers_spaces(client):
    r = client.get("/api/me", headers=_auth(_token(["finserv-eng@example.com"], sub="sub-1")))
    assert r.status_code == 200
    assert r.json()["personal"]["domain"] == "personal:sub-1"


def test_search_is_scoped(client):
    r = client.post(
        "/api/search",
        json={"query": "candidate sourcing interview copilots recruiting"},
        headers=_auth(_token(["finserv-eng@example.com"])),
    )
    assert r.status_code == 200
    assert all(hit["domain"] != RECRUITMENT for hit in r.json()["results"])


def test_proposals_are_scoped_to_writable_domains(client):
    admin = client.get("/api/proposals", headers=_auth(_token(["brain-admins@example.com"])))
    assert any(p["name"] == FRAUD_PROP for p in admin.json()["proposals"])
    recruiter = client.get("/api/proposals", headers=_auth(_token(["recruiting@example.com"])))
    assert recruiter.json()["proposals"] == []


def test_accept_requires_write_access(client):
    r = client.post(
        "/api/accept", json={"name": FRAUD_PROP}, headers=_auth(_token(["recruiting@example.com"]))
    )
    assert r.status_code == 403


def test_accept_succeeds_for_a_writer(client):
    r = client.post(
        "/api/accept",
        json={"name": FRAUD_PROP},
        headers=_auth(_token(["brain-admins@example.com"])),
    )
    assert r.status_code == 200
    assert r.json()["dest"] == f"{FINSERV}/new-fraud-model.md"


def test_upload_lands_in_the_personal_space(client):
    body = base64.b64encode(b"# Uploaded\n\nSome text.").decode()
    r = client.post(
        "/api/upload",
        json={"filename": "notes.md", "content_base64": body},
        headers=_auth(_token([], sub="up-1")),
    )
    assert r.status_code == 200
    assert r.json()["status"] in {"proposed", "saved"}


FRAUD_DOC = f"{FINSERV}/realtime-fraud-detection"


def test_edit_requires_moderation(client):
    # A finserv reader can write commons (wildcard) but is not a moderator of the finserv
    # team domain, so editing its content is refused.
    r = client.post(
        "/api/edit",
        json={"doc_id": FRAUD_DOC, "content": "hijacked"},
        headers=_auth(_token(["finserv-eng@example.com"])),
    )
    assert r.status_code == 403


def test_moderator_can_edit_a_team_document(client):
    r = client.post(
        "/api/edit",
        json={"doc_id": FRAUD_DOC, "content": "# Realtime fraud detection\n\nrewritten"},
        headers=_auth(_token(["brain-admins@example.com"])),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "saved"


def test_report_then_moderator_sees_and_resolves(client):
    reader = _auth(_token(["finserv-eng@example.com"], sub="reader-1"))
    admin = _auth(_token(["brain-admins@example.com"]))
    assert (
        client.post(
            "/api/report", json={"doc_id": FRAUD_DOC, "reason": "stale"}, headers=reader
        ).status_code
        == 200
    )
    queue = client.get("/api/reports", headers=admin).json()["reports"]
    assert any(rep["doc_id"] == FRAUD_DOC for rep in queue)
    # The reporter, not a moderator of finserv, sees an empty queue.
    assert client.get("/api/reports", headers=reader).json()["reports"] == []
    resolved = client.post(
        "/api/report/resolve", json={"doc_id": FRAUD_DOC, "remove": False}, headers=admin
    )
    assert resolved.status_code == 200
    assert client.get("/api/reports", headers=admin).json()["reports"] == []
