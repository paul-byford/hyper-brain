"""Phase 2: the OAuth AS HTTP service. Hermetic -- an in-process Starlette app,
an ephemeral key, and a faked Google exchange, so the whole register -> authorize
-> Google callback -> token -> refresh flow runs with no network."""

from __future__ import annotations

import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import pytest

# The [oauth] extra (PyJWT) is optional; skip cleanly where it is not installed
# (e.g. the offline evals job) instead of erroring collection.
pytest.importorskip("jwt")

import jwt  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from brain_app.oauth.app import build_app  # noqa: E402
from brain_app.oauth.google import GoogleOidc  # noqa: E402
from brain_app.oauth.issuer import TokenIssuer  # noqa: E402
from brain_app.oauth.keys import SigningKey  # noqa: E402

ISSUER = "https://auth.example.com"
RESOURCE = "https://brain.example.com"
REDIRECT = "https://claude.ai/api/mcp/auth_callback"
USER = {"sub": "google-123", "email": "you@example.com"}


@pytest.fixture(scope="module")
def key():
    return SigningKey.generate()


@pytest.fixture
def client(key):
    issuer = TokenIssuer(key, issuer=ISSUER, resource=RESOURCE)
    google = GoogleOidc("gid", "gsecret", f"{ISSUER}/oauth2/callback", exchange=lambda code: USER)
    return TestClient(build_app(issuer, google))


def _pkce():
    verifier = base64.urlsafe_b64encode(b"z" * 40).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


def _register(client):
    r = client.post("/register", json={"redirect_uris": [REDIRECT], "client_name": "Claude"})
    assert r.status_code == 201
    return r.json()["client_id"]


def _query(location):
    return {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}


def test_discovery_and_jwks(client):
    meta = client.get("/.well-known/oauth-authorization-server").json()
    assert meta["issuer"] == ISSUER
    assert meta["authorization_endpoint"] == f"{ISSUER}/authorize"
    assert meta["code_challenge_methods_supported"] == ["S256"]
    jwks = client.get("/jwks").json()
    assert jwks["keys"] and jwks["keys"][0]["kty"] == "RSA"


def test_full_oauth_flow(client, key):
    client_id = _register(client)
    verifier, challenge = _pkce()

    # 1. /authorize validates + PKCE, then bounces to Google carrying login state.
    r = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "mcp",
            "state": "client-nonce",
        },
        follow_redirects=False,
    )
    assert r.status_code == 302
    google_loc = r.headers["location"]
    assert google_loc.startswith("https://accounts.google.com/")
    login_state = _query(google_loc)["state"]

    # 2. Google returns to our callback; we mint OUR code and bounce to the client.
    r = client.get(
        "/oauth2/callback",
        params={"code": "google-code", "state": login_state},
        follow_redirects=False,
    )
    assert r.status_code == 302
    back = urlparse(r.headers["location"])
    assert f"{back.scheme}://{back.netloc}{back.path}" == REDIRECT
    returned = _query(r.headers["location"])
    assert returned["state"] == "client-nonce"  # the client's own state echoed back
    code = returned["code"]

    # 3. /token exchanges the code (with PKCE) for tokens.
    r = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "client_id": client_id,
            "redirect_uri": REDIRECT,
        },
    )
    assert r.status_code == 200
    tok = r.json()
    assert tok["token_type"] == "Bearer" and "refresh_token" in tok

    claims = jwt.decode(
        tok["access_token"],
        key.public_pem(),
        algorithms=["RS256"],
        audience=RESOURCE,
        issuer=ISSUER,
    )
    assert claims["email"] == USER["email"] and claims["typ"] == "access"

    # 4. Refresh yields a new access token.
    r = client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tok["refresh_token"],
            "client_id": client_id,
        },
    )
    assert r.status_code == 200 and "access_token" in r.json()


def test_authorize_rejects_unregistered_redirect(client):
    client_id = _register(client)
    _, challenge = _pkce()
    r = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "https://evil.example/cb",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert r.status_code == 400 and r.json()["error"] == "invalid_request"


def test_authorize_requires_pkce(client):
    client_id = _register(client)
    r = client.get(
        "/authorize",
        params={"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT},
        follow_redirects=False,
    )
    assert r.status_code == 400 and r.json()["error"] == "invalid_request"


def test_token_rejects_bad_pkce_verifier(client):
    client_id = _register(client)
    _, challenge = _pkce()
    r = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    login_state = _query(r.headers["location"])["state"]
    r = client.get(
        "/oauth2/callback", params={"code": "g", "state": login_state}, follow_redirects=False
    )
    code = _query(r.headers["location"])["code"]
    r = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": "wrong-verifier",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
        },
    )
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
