from __future__ import annotations

from brain_app.config import load_policy

from .conftest import FINSERV, RECRUITMENT


def test_personal_admin_sees_all_domains():
    policy = load_policy(prof="personal")
    assert policy.domains_for(["group:brain-admins@example.com"]) == {FINSERV, RECRUITMENT}


def test_group_scoped_principal_sees_one_domain():
    policy = load_policy(prof="personal")
    assert policy.domains_for(["group:finserv-eng@example.com"]) == {FINSERV}
    assert policy.domains_for(["group:recruiting@example.com"]) == {RECRUITMENT}


def test_unknown_principal_sees_nothing():
    policy = load_policy(prof="personal")
    assert policy.domains_for(["nobody@example.com"]) == set()


def test_multiple_principals_union():
    policy = load_policy(prof="personal")
    principals = ["nobody@example.com", "group:finserv-eng@example.com"]
    assert policy.domains_for(principals) == {FINSERV}


def test_controlled_same_schema_different_principals():
    policy = load_policy(prof="controlled")
    # Bank admin group sees everything.
    assert policy.domains_for(["group:brain-admins@bank.example"]) == {FINSERV, RECRUITMENT}
    # A personal-profile principal has no access under the controlled policy.
    assert policy.domains_for(["group:brain-admins@example.com"]) == set()


def test_grant_cannot_widen_to_undeclared_domain():
    # domains_for only ever returns declared domains.
    policy = load_policy(prof="personal")
    resolved = policy.domains_for(["group:brain-admins@example.com"])
    assert resolved <= set(policy.domains)
