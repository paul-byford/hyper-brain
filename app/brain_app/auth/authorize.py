"""From a verified identity to what it may do: which domains, and whether it may write.

Read access is the base policy's domain ACL (``config.Policy``), resolved from the
identity's principals, plus two dynamic additions the policy never names:

- the caller's own **personal domain** (``personal:{subject}``), which every
  signed-in caller reads and writes and which a wildcard grant can never reach; and
- any domain or document **shared** with the caller through the overlay
  (``auth.shares``).

Write access is kept separate from read (ARCHITECTURE.md section 12) and can be
held two independent ways for the base policy: a grant marked ``write: true``, or
the ``propose`` scope on the token. A caller can only ever write into a domain they
may also read.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..config import WILDCARD, Policy
from .identity import PROPOSE_SCOPE, Identity
from .shares import (
    Share,
    shared_read_docs,
    shared_read_domains,
    shared_write_domains,
)

# A caller's private space is a domain derived from their stable subject. It is
# never declared in the base policy, so ``domains_for`` (which intersects with the
# declared domains) can never hand a wildcard grant someone's personal domain.
PERSONAL_PREFIX = "personal:"


def personal_domain(identity: Identity) -> str | None:
    """The caller's own private domain, or None for an anonymous caller.

    Derived from the opaque, stable subject (a Google ``sub``), so it survives an
    email change and never puts an email into a storage path.
    """
    subject = identity.subject
    if not subject or subject == "anonymous":
        return None
    return f"{PERSONAL_PREFIX}{subject}"


def is_personal_domain(domain: str) -> bool:
    return domain.startswith(PERSONAL_PREFIX)


def personal_owner(domain: str) -> str:
    """The subject that owns a ``personal:`` domain."""
    return domain[len(PERSONAL_PREFIX) :]


def read_domains(
    identity: Identity, policy: Policy, shares: Iterable[Share] | None = None
) -> set[str]:
    """Domains this identity may retrieve from.

    Base-policy grants (including commons via the wildcard), plus the caller's own
    personal domain, plus any whole domain shared with them. Personal and shared
    domains are added *outside* the policy's declared-domain check, which is exactly
    why a wildcard grant can never reach a personal domain.
    """
    domains = policy.domains_for(identity.principals)
    personal = personal_domain(identity)
    if personal:
        domains.add(personal)
    if shares:
        domains |= shared_read_domains(identity, shares)
    return domains


def readable_docs(identity: Identity, shares: Iterable[Share] | None = None) -> set[str]:
    """Individual documents shared with the caller (doc-level shares), admitted by
    retrieval in addition to whole domains the caller may read."""
    if not shares:
        return set()
    return shared_read_docs(identity, shares)


def writable_domains(
    identity: Identity, policy: Policy, shares: Iterable[Share] | None = None
) -> set[str]:
    """Base-policy domains this identity may propose into, plus any shared to it with
    write. The personal domain is deliberately *not* here: personal writes are
    ungated (``service.add_note``), not part of the reviewed propose path.
    """
    principals = set(identity.principals)
    allowed: set[str] = set()

    # Path 1: policy grants marked write: true.
    for grant in policy.grants:
        if grant.write and (grant.principal == WILDCARD or grant.principal in principals):
            allowed.update(grant.domains)

    # Path 2: a token carrying the propose scope may write its readable declared domains.
    if PROPOSE_SCOPE in identity.scopes:
        allowed |= policy.domains_for(principals)

    # Never grant write beyond declared domains, nor beyond what the caller can read.
    result = allowed & set(policy.domains) & policy.domains_for(principals)

    # A domain shared to the caller with write is proposable too (it is not declared,
    # so it is added after the declared-domain intersection above).
    if shares:
        result = result | shared_write_domains(identity, shares)
    return result


def can_propose(identity: Identity, policy: Policy, shares: Iterable[Share] | None = None) -> bool:
    """Whether this identity may use the reviewed write path at all."""
    return bool(writable_domains(identity, policy, shares))


def can_share(
    identity: Identity, policy: Policy, domain: str, shares: Iterable[Share] | None = None
) -> bool:
    """Whether the caller may create a share for content in ``domain``.

    You may share your own personal domain, or any domain you can write (an author
    or admin of a team domain). You cannot re-share content merely shared to you.
    """
    if is_personal_domain(domain):
        return personal_owner(domain) == identity.subject
    return domain in writable_domains(identity, policy, shares)
