"""Phase 3 (integration): with the OAuth resource-server wiring on, the brain's
MCP endpoint serves protected-resource metadata and 401s unauthenticated calls
with a WWW-Authenticate pointer -- the discovery trigger a remote connector needs.

Uses the SDK's real Starlette app; the BrainService is a stub because no tool is
invoked (auth is enforced before any tool runs)."""

from __future__ import annotations

import pytest

# The [mcp] extra (the MCP SDK) is optional; skip cleanly where it is not
# installed (e.g. the offline evals job) instead of erroring collection.
pytest.importorskip("mcp")

from starlette.testclient import TestClient  # noqa: E402

from brain_app.auth import TokenError, identity_from_claims  # noqa: E402
from brain_app.serving.server import build_server  # noqa: E402

AS = "https://auth.example.com"
BRAIN = "https://brain.example.com"


class _Verifier:
    def verify(self, token: str):
        if token == "good":
            return identity_from_claims({"sub": "u", "email": "e@x", "scope": "mcp"})
        raise TokenError("rejected")


@pytest.fixture
def client():
    server = build_server(object(), _Verifier(), auth_issuer=AS, resource=BRAIN)
    # The `with` block runs the app's lifespan, which starts the streamable-HTTP
    # session manager (otherwise any authenticated request hits an uninitialised
    # task group). Auth itself is enforced ahead of that, so 401s work regardless.
    with TestClient(server.streamable_http_app()) as c:
        yield c


def test_protected_resource_metadata_points_at_the_as(client):
    r = client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200
    # The SDK normalises URLs with a trailing slash; compare host-and-path only.
    servers = [s.rstrip("/") for s in r.json().get("authorization_servers", [])]
    assert AS in servers


def test_unauthenticated_mcp_gets_401_with_www_authenticate(client):
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert r.status_code == 401
    assert "www-authenticate" in {k.lower() for k in r.headers}


def test_valid_token_clears_auth_gate(client):
    # A good token must clear the SDK's auth gate: no 401 and no auth challenge.
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "Authorization": "Bearer good",
        },
    )
    assert r.status_code != 401
    assert "www-authenticate" not in {k.lower() for k in r.headers}
