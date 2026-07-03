"""Pillar 1/2: a verified token becomes an Identity with the right principals and scopes."""

from __future__ import annotations

import pytest

from brain_app.auth import HmacVerifier, encode_hs256, get_verifier
from brain_app.auth.identity import identity_from_claims

SECRET = "s"


def test_verifier_builds_identity_with_principals_and_scopes():
    token = encode_hs256(
        {
            "sub": "u",
            "email": "eng@bank.com",
            "groups": ["finserv-eng@example.com"],
            "scope": "read propose",
        },
        SECRET,
    )
    identity = HmacVerifier(SECRET).verify(token)
    assert identity.email == "eng@bank.com"
    assert "eng@bank.com" in identity.principals
    assert "group:finserv-eng@example.com" in identity.principals
    assert identity.scopes == frozenset({"read", "propose"})


def test_groups_already_prefixed_are_not_double_prefixed():
    identity = identity_from_claims({"groups": ["group:admins@x.com"]})
    assert identity.principals == ("group:admins@x.com",)


def test_get_verifier_hs256_requires_secret(monkeypatch):
    monkeypatch.setenv("BRAIN_AUTH", "hs256")
    monkeypatch.delenv("BRAIN_AUTH_SECRET", raising=False)
    with pytest.raises(ValueError, match="BRAIN_AUTH_SECRET"):
        get_verifier()


def test_get_verifier_hs256_from_env(monkeypatch):
    monkeypatch.setenv("BRAIN_AUTH", "hs256")
    monkeypatch.setenv("BRAIN_AUTH_SECRET", "env-secret")
    assert isinstance(get_verifier(), HmacVerifier)


def test_get_verifier_unknown_provider():
    with pytest.raises(ValueError, match="unknown auth provider"):
        get_verifier("smoke-signals")
