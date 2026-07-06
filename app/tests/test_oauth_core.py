"""Phase 1: the stateless OAuth AS core. Hermetic -- an ephemeral RSA key, no cloud.

Exercises the full register -> authorize-code -> token -> refresh flow and the
failure modes that make it safe: PKCE, redirect/client binding, token-type
confusion, expiry, and tampering.
"""

from __future__ import annotations

import base64
import hashlib

import jwt
import pytest

from brain_app.oauth import (
    OAuthError,
    SigningKey,
    TokenIssuer,
    authorization_server_metadata,
    protected_resource_metadata,
    verify_pkce,
)

ISSUER = "https://auth.example.com"
RESOURCE = "https://brain.example.com"
REDIRECT = "https://claude.ai/api/mcp/auth_callback"


@pytest.fixture(scope="module")
def key():
    return SigningKey.generate()


@pytest.fixture
def iss(key):
    return TokenIssuer(key, issuer=ISSUER, resource=RESOURCE)


def _pkce():
    verifier = base64.urlsafe_b64encode(b"a" * 40).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


def _register(iss):
    return iss.register_client(redirect_uris=[REDIRECT], client_name="Test")["client_id"]


# --- Happy path: the whole flow a connector runs ------------------------------
def test_full_authorization_code_flow(iss, key):
    client_id = _register(iss)
    assert iss.check_redirect_uri(client_id, REDIRECT)  # registered

    verifier, challenge = _pkce()
    code = iss.mint_authorization_code(
        sub="google-123",
        email="you@example.com",
        client_id=client_id,
        redirect_uri=REDIRECT,
        code_challenge=challenge,
        scope="mcp",
    )
    ident = iss.redeem_authorization_code(
        code, code_verifier=verifier, client_id=client_id, redirect_uri=REDIRECT
    )
    assert ident == {"sub": "google-123", "email": "you@example.com", "scope": "mcp"}

    tokens = iss.issue_token_response(
        sub=ident["sub"], email=ident["email"], scope="mcp", client_id=client_id
    )
    assert tokens["token_type"] == "Bearer" and tokens["expires_in"] == 3600

    # The resource server (brain) validates the access token against the public key.
    claims = jwt.decode(
        tokens["access_token"],
        key.public_pem(),
        algorithms=["RS256"],
        audience=RESOURCE,
        issuer=ISSUER,
    )
    assert claims["email"] == "you@example.com" and claims["typ"] == "access"

    # Refresh yields a fresh access token for the same identity.
    refreshed = iss.redeem_refresh_token(tokens["refresh_token"], client_id=client_id)
    assert refreshed["email"] == "you@example.com"


# --- PKCE and binding failures ------------------------------------------------
def test_pkce_wrong_verifier_rejected(iss):
    client_id = _register(iss)
    _, challenge = _pkce()
    code = iss.mint_authorization_code(
        sub="u",
        email="e@x",
        client_id=client_id,
        redirect_uri=REDIRECT,
        code_challenge=challenge,
        scope="mcp",
    )
    with pytest.raises(OAuthError, match="PKCE"):
        iss.redeem_authorization_code(
            code, code_verifier="not-the-verifier", client_id=client_id, redirect_uri=REDIRECT
        )


def test_code_bound_to_client_and_redirect(iss):
    client_id = _register(iss)
    verifier, challenge = _pkce()
    code = iss.mint_authorization_code(
        sub="u",
        email="e@x",
        client_id=client_id,
        redirect_uri=REDIRECT,
        code_challenge=challenge,
        scope="mcp",
    )
    with pytest.raises(OAuthError, match="another client"):
        iss.redeem_authorization_code(
            code, code_verifier=verifier, client_id="other", redirect_uri=REDIRECT
        )
    with pytest.raises(OAuthError, match="redirect_uri"):
        iss.redeem_authorization_code(
            code,
            code_verifier=verifier,
            client_id=client_id,
            redirect_uri="https://evil.example/cb",
        )


def test_unregistered_redirect_uri_rejected(iss):
    client_id = _register(iss)
    with pytest.raises(OAuthError, match="not registered"):
        iss.check_redirect_uri(client_id, "https://evil.example/cb")


def test_verify_pkce_only_s256():
    v, c = _pkce()
    assert verify_pkce(v, c) is True
    assert verify_pkce(v, c, method="plain") is False
    assert verify_pkce("", c) is False


# --- Token-type confusion cannot be exploited ---------------------------------
def test_token_type_confusion_rejected(iss):
    client_id = _register(iss)
    tokens = iss.issue_token_response(sub="u", email="e@x", scope="mcp", client_id=client_id)
    # An access token is not a refresh token.
    with pytest.raises(OAuthError, match="wrong token type"):
        iss.redeem_refresh_token(tokens["access_token"], client_id=client_id)
    # A refresh token is not a client_id.
    with pytest.raises(OAuthError, match="wrong token type"):
        iss.read_client(tokens["refresh_token"])


# --- Expiry and tampering -----------------------------------------------------
def test_expired_code_rejected(iss, key):
    client_id = _register(iss)
    verifier, challenge = _pkce()
    expired = key.sign(
        {
            "typ": "code",
            "iss": ISSUER,
            "iat": 1000,
            "exp": 2000,  # long past
            "sub": "u",
            "email": "e@x",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "scope": "mcp",
        }
    )
    with pytest.raises(OAuthError):
        iss.redeem_authorization_code(
            expired, code_verifier=verifier, client_id=client_id, redirect_uri=REDIRECT
        )


def test_token_signed_by_other_key_rejected(iss):
    other = TokenIssuer(SigningKey.generate(), issuer=ISSUER, resource=RESOURCE)
    client_id = _register(other)  # signed by the wrong key
    with pytest.raises(OAuthError):
        iss.read_client(client_id)


def test_access_token_audience_enforced(iss, key):
    tok = iss.mint_access_token(sub="u", email="e@x", scope="mcp")
    with pytest.raises(jwt.InvalidAudienceError):
        jwt.decode(
            tok, key.public_pem(), algorithms=["RS256"], audience="https://wrong", issuer=ISSUER
        )


# --- Discovery metadata + JWKS ------------------------------------------------
def test_metadata_documents():
    asm = authorization_server_metadata(ISSUER)
    assert asm["issuer"] == ISSUER
    assert asm["registration_endpoint"] == f"{ISSUER}/register"
    assert asm["code_challenge_methods_supported"] == ["S256"]
    assert asm["token_endpoint_auth_methods_supported"] == ["none"]

    prm = protected_resource_metadata(RESOURCE, ISSUER)
    assert prm["resource"] == RESOURCE and prm["authorization_servers"] == [ISSUER]


def test_jwks_shape(key):
    jwks = key.jwks()
    (jwk,) = jwks["keys"]
    assert jwk["kty"] == "RSA" and jwk["alg"] == "RS256" and jwk["use"] == "sig"
    assert jwk["kid"] == key.kid and jwk["n"] and jwk["e"]
