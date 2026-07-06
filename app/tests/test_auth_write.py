"""Pillar 2 (security): write authorization holds two ways, and never exceeds read.

A caller may propose if a policy grant marks them ``write: true`` (works for Google
OIDC tokens, which carry no custom scope) OR the token carries the ``propose`` scope
(for API/demo tokens). Either way, write is bounded by what the caller may read.
"""

from __future__ import annotations

from brain_app.auth.authorize import can_propose, read_domains, writable_domains
from brain_app.auth.identity import identity_from_claims
from brain_app.config import Grant, Policy

from .conftest import FINSERV, RECRUITMENT


def _ident(groups=(), scope=""):
    return identity_from_claims(
        {"sub": "u", "email": "u@bank.com", "groups": list(groups), "scope": scope}
    )


def _policy(*grants):
    return Policy(1, (FINSERV, RECRUITMENT), tuple(grants))


def test_policy_write_grant_authorizes_a_google_token_without_scope():
    # A Google-style token has no `scope` claim; a policy write grant still lets it write.
    policy = _policy(Grant("u@bank.com", (FINSERV,), write=True))
    identity = _ident(scope="")
    assert writable_domains(identity, policy) == {FINSERV}
    assert can_propose(identity, policy)


def test_read_only_grant_confers_no_write():
    policy = _policy(Grant("u@bank.com", (FINSERV, RECRUITMENT)))  # write defaults False
    identity = _ident()
    assert writable_domains(identity, policy) == set()
    assert not can_propose(identity, policy)


def test_token_propose_scope_still_authorizes_writes():
    policy = _policy(Grant("group:eng@bank.com", (FINSERV,)))  # read-only grant
    identity = _ident(groups=["eng@bank.com"], scope="read propose")
    # The scope authorises writing the caller's readable domains.
    assert writable_domains(identity, policy) == {FINSERV}
    assert can_propose(identity, policy)


def test_a_write_grant_also_confers_read():
    policy = _policy(Grant("u@bank.com", (FINSERV,), write=True))
    identity = _ident()
    # Read includes the granted domain plus the caller's own personal domain (every
    # signed-in caller has one); the personal domain is never in the reviewed write set.
    assert read_domains(identity, policy) == {FINSERV, "personal:u"}
    assert writable_domains(identity, policy) == {FINSERV}


def test_write_is_bounded_by_declared_domains():
    policy = _policy(Grant("u@bank.com", (FINSERV, "ghost-domain"), write=True))
    assert writable_domains(_ident(), policy) == {FINSERV}  # ghost-domain not declared
