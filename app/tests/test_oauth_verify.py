"""Phase 3: the brain validating OAuth access tokens (and still Google tokens).

Hermetic: tokens are minted by an in-process TokenIssuer and verified against its
public key directly (no JWKS fetch), so there is no network and no cloud.
"""

from __future__ import annotations

import time

import pytest

# The [oauth] extra (PyJWT) is optional; skip cleanly where it is not installed
# (e.g. the offline evals job) instead of erroring collection.
pytest.importorskip("jwt")

from brain_app.auth import CompositeVerifier, OAuthJwtVerifier, TokenError  # noqa: E402
from brain_app.oauth import SigningKey, TokenIssuer  # noqa: E402

AS = "https://auth.example.com"
BRAIN = "https://brain.example.com"


@pytest.fixture(scope="module")
def key():
    return SigningKey.generate()


@pytest.fixture
def issuer(key):
    return TokenIssuer(key, issuer=AS, resource=BRAIN)


@pytest.fixture
def verifier(key):
    return OAuthJwtVerifier(AS, BRAIN, public_pem=key.public_pem())


def test_valid_access_token_becomes_identity(issuer, verifier):
    token = issuer.mint_access_token(sub="google-1", email="you@example.com", scope="mcp")
    ident = verifier.verify(token)
    assert ident.email == "you@example.com"
    assert "you@example.com" in ident.principals  # matches the policy on the bare email
    assert ident.subject == "google-1"


def test_wrong_audience_rejected(issuer, key):
    token = issuer.mint_access_token(sub="u", email="e@x", scope="mcp")
    other = OAuthJwtVerifier(AS, "https://other-brain", public_pem=key.public_pem())
    with pytest.raises(TokenError):
        other.verify(token)


def test_non_access_token_rejected(verifier, key):
    now = int(time.time())
    refresh_shaped = key.sign(
        {
            "typ": "refresh",
            "iss": AS,
            "aud": BRAIN,
            "iat": now,
            "exp": now + 60,
            "sub": "u",
            "email": "e@x",
        }
    )
    with pytest.raises(TokenError, match="not an access token"):
        verifier.verify(refresh_shaped)


def test_token_from_other_key_rejected(issuer):
    stranger = OAuthJwtVerifier(AS, BRAIN, public_pem=SigningKey.generate().public_pem())
    token = issuer.mint_access_token(sub="u", email="e@x", scope="mcp")
    with pytest.raises(TokenError):
        stranger.verify(token)


class _Reject:
    def verify(self, token):
        raise TokenError("nope")


def test_composite_accepts_if_any_verifier_does(issuer, verifier):
    token = issuer.mint_access_token(sub="u", email="e@x", scope="mcp")
    composite = CompositeVerifier([_Reject(), verifier])  # e.g. Google first, then OAuth
    assert composite.verify(token).email == "e@x"


def test_composite_rejects_if_all_do(issuer):
    composite = CompositeVerifier([_Reject(), _Reject()])
    with pytest.raises(TokenError, match="no configured verifier"):
        composite.verify("anything")
