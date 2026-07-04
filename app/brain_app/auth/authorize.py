"""From a verified identity to what it may do: which domains, and whether it may write.

Read access is the policy's domain ACL (``config.Policy``), resolved from the
identity's principals. Write access is kept separate from read (ARCHITECTURE.md
section 12) and can be held two independent ways, either of which suffices:

- a policy grant marked ``write: true`` for one of the caller's principals. This
  works for any verified identity, including Google OIDC ID tokens, which cannot
  carry a custom ``propose`` scope; and
- the ``propose`` scope on the token, which authorises writing to the caller's
  readable domains (for API / demo tokens whose claims you control, e.g. HS256).

A caller can only ever write into a domain they may also read.
"""

from __future__ import annotations

from ..config import WILDCARD, Policy
from .identity import PROPOSE_SCOPE, Identity


def read_domains(identity: Identity, policy: Policy) -> set[str]:
    """Domains this identity may retrieve from."""
    return policy.domains_for(list(identity.principals))


def writable_domains(identity: Identity, policy: Policy) -> set[str]:
    """Domains this identity may propose into (never beyond what it may read)."""
    principals = set(identity.principals)
    allowed: set[str] = set()

    # Path 1: policy grants marked write: true.
    for grant in policy.grants:
        if grant.write and (grant.principal == WILDCARD or grant.principal in principals):
            allowed.update(grant.domains)

    # Path 2: a token carrying the propose scope may write its readable domains.
    if PROPOSE_SCOPE in identity.scopes:
        allowed |= read_domains(identity, policy)

    # Never grant write beyond declared domains, nor beyond what the caller can read.
    return allowed & set(policy.domains) & read_domains(identity, policy)


def can_propose(identity: Identity, policy: Policy) -> bool:
    """Whether this identity may use the write path at all."""
    return bool(writable_domains(identity, policy))
