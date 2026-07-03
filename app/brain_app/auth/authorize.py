"""From a verified identity to what it may do: which domains, and whether it may write.

Read access is the policy's domain ACL (``config.Policy``), resolved from the
identity's principals. Write access is gated separately by scope: a caller must
hold the ``propose`` scope *and* be granted the target domain. Keeping the two
checks distinct is the "write scope is separate from read scope" property from
ARCHITECTURE.md section 12.
"""

from __future__ import annotations

from ..config import Policy
from .identity import PROPOSE_SCOPE, Identity


def read_domains(identity: Identity, policy: Policy) -> set[str]:
    """Domains this identity may retrieve from."""
    return policy.domains_for(list(identity.principals))


def can_propose(identity: Identity) -> bool:
    """Whether this identity holds the write scope at all."""
    return PROPOSE_SCOPE in identity.scopes


def writable_domains(identity: Identity, policy: Policy) -> set[str]:
    """Domains this identity may propose into.

    The same domain ACL bounds writes as reads (you cannot propose into a domain
    you cannot see); the ``propose`` scope, checked separately, is what turns read
    access into write capability.
    """
    return read_domains(identity, policy)
