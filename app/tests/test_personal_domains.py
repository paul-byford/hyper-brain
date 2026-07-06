"""Personal domains and the commons grant (the access model, no cloud).

Every signed-in caller owns a private ``personal:{subject}`` domain and shares the
``commons`` domain via the wildcard grant. The load-bearing invariant is that a
wildcard grant can never reach anyone's personal domain: personal domains are
derived from identity and never declared, so ``domains_for`` (which intersects with
the declared domains) cannot hand one out.
"""

from __future__ import annotations

from brain_app.auth import (
    can_share,
    identity_from_claims,
    is_personal_domain,
    personal_domain,
    personal_owner,
    read_domains,
    writable_domains,
)
from brain_app.config import Grant, Policy

# A base policy with a commons domain open to everyone via the wildcard, plus a
# team domain only one group may read.
POLICY = Policy(
    version=1,
    domains=("commons", "team-a"),
    grants=(
        Grant(principal="*", domains=("commons",)),
        Grant(principal="group:team-a@example.com", domains=("team-a",), write=True),
    ),
)


def _ident(sub, email=None, groups=()):
    return identity_from_claims({"sub": sub, "email": email, "groups": list(groups)})


def test_personal_domain_derives_from_subject_not_email():
    ident = _ident("sub-123", email="alice@example.com")
    assert personal_domain(ident) == "personal:sub-123"
    assert is_personal_domain("personal:sub-123")
    assert personal_owner("personal:sub-123") == "sub-123"


def test_anonymous_caller_has_no_personal_domain():
    assert personal_domain(_ident("anonymous")) is None
    assert personal_domain(identity_from_claims({})) is None


def test_every_caller_reads_commons_and_their_own_personal_domain():
    ident = _ident("sub-1", email="new@example.com")  # no group grants at all
    domains = read_domains(ident, POLICY)
    # A brand-new user with no team is never a dead end: commons + their own space.
    assert domains == {"commons", "personal:sub-1"}


def test_wildcard_grant_never_yields_another_users_personal_domain():
    alice = read_domains(_ident("alice"), POLICY)
    assert "personal:alice" in alice
    # The wildcard opened commons, but it must not open anyone else's personal domain.
    assert "personal:bob" not in alice
    assert alice == {"commons", "personal:alice"}


def test_team_member_sees_team_commons_and_personal():
    ident = _ident("sub-9", groups=["team-a@example.com"])
    assert read_domains(ident, POLICY) == {"commons", "team-a", "personal:sub-9"}


def test_personal_domain_is_not_in_the_reviewed_write_set():
    # writable_domains is the reviewed (propose) path; personal writes are ungated
    # and handled by add_note, so the personal domain is deliberately absent here.
    ident = _ident("sub-9", groups=["team-a@example.com"])
    assert writable_domains(ident, POLICY) == {"team-a"}
    assert "personal:sub-9" not in writable_domains(ident, POLICY)


def test_can_share_own_personal_but_not_someone_elses():
    alice = _ident("alice")
    assert can_share(alice, POLICY, "personal:alice")
    assert not can_share(alice, POLICY, "personal:bob")


def test_can_share_a_domain_you_may_write_but_not_one_you_only_read():
    writer = _ident("w", groups=["team-a@example.com"])  # write on team-a
    reader = _ident("r")  # only commons
    assert can_share(writer, POLICY, "team-a")
    assert not can_share(reader, POLICY, "team-a")
    assert not can_share(reader, POLICY, "commons")  # read-only via wildcard
