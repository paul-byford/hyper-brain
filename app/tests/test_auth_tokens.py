"""Pillar 2 (security): JWT verification rejects every tampered or invalid token."""

from __future__ import annotations

import pytest

from brain_app.auth.tokens import (
    ExpiredToken,
    InvalidSignature,
    MalformedToken,
    NotYetValid,
    WrongAudience,
    WrongIssuer,
    decode_hs256,
    encode_hs256,
)

SECRET = "test-secret"
AUD = "https://brain.example.run.app"
ISS = "https://accounts.google.com"
NOW = 1_800_000_000


def _token(**overrides) -> str:
    claims = {"sub": "u1", "email": "u@x.com", "aud": AUD, "iss": ISS, "exp": NOW + 3600}
    claims.update(overrides)
    return encode_hs256(claims, SECRET)


def test_valid_token_roundtrips():
    claims = decode_hs256(_token(), SECRET, audience=AUD, issuer=ISS, now=NOW)
    assert claims["email"] == "u@x.com"


def test_wrong_secret_is_invalid_signature():
    with pytest.raises(InvalidSignature):
        decode_hs256(_token(), "not-the-secret", now=NOW)


def test_tampered_payload_is_invalid_signature():
    header, payload, sig = _token().split(".")
    forged = encode_hs256({"sub": "attacker", "aud": AUD}, "attacker-secret").split(".")[1]
    with pytest.raises(InvalidSignature):
        decode_hs256(f"{header}.{forged}.{sig}", SECRET, now=NOW)


def test_expired_token_rejected():
    with pytest.raises(ExpiredToken):
        decode_hs256(_token(exp=NOW - 3600), SECRET, now=NOW)


def test_not_yet_valid_token_rejected():
    with pytest.raises(NotYetValid):
        decode_hs256(_token(nbf=NOW + 3600), SECRET, now=NOW)


def test_wrong_audience_rejected():
    with pytest.raises(WrongAudience):
        decode_hs256(_token(aud="https://evil.example"), SECRET, audience=AUD, now=NOW)


def test_wrong_issuer_rejected():
    with pytest.raises(WrongIssuer):
        decode_hs256(_token(iss="https://evil.example"), SECRET, issuer=ISS, now=NOW)


def test_alg_none_downgrade_rejected():
    # A classic attack: swap the header to alg=none with an empty signature.
    import base64
    import json

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header = b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    payload = b64(json.dumps({"sub": "attacker", "aud": AUD}).encode())
    with pytest.raises(MalformedToken):
        decode_hs256(f"{header}.{payload}.", SECRET, now=NOW)


def test_garbage_is_malformed():
    with pytest.raises(MalformedToken):
        decode_hs256("not-a-jwt", SECRET, now=NOW)
