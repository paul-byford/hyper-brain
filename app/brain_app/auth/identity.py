"""The verified caller: principals for the domain ACL, scopes for write access.

An ``Identity`` is what a verified token becomes. It carries the *principals* the
policy grants domains to (the email plus any group memberships) and the *scopes*
that gate write actions, kept separate so a read token can never propose a
document (ARCHITECTURE.md section 12).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Scope that a token must carry to use the write path (propose_document).
PROPOSE_SCOPE = "propose"


@dataclass(frozen=True)
class Identity:
    subject: str
    email: str | None
    principals: tuple[str, ...]
    scopes: frozenset[str]
    claims: dict = field(default_factory=dict)

    @property
    def is_guest(self) -> bool:
        """A read-only guest (a token the AS minted without Google login). Guests read
        the commons but every write is refused server-side, whatever the policy says."""
        return bool(self.claims.get("guest"))


def _principals_from_claims(claims: dict) -> list[str]:
    """The principals a policy grant can match: the email and group memberships.

    Groups are normalised to the ``group:<name>`` form the policy files use, so a
    raw ``groups`` claim from an IdP lines up with the ACL without the ACL having
    to know the token's shape.
    """
    principals: list[str] = []
    email = claims.get("email")
    if email:
        principals.append(str(email))
    for group in claims.get("groups", []) or []:
        name = str(group)
        principals.append(name if name.startswith("group:") else f"group:{name}")
    return principals


def _scopes_from_claims(claims: dict) -> set[str]:
    # Accept both the OAuth space-delimited ``scope`` string and a ``scopes`` list.
    scope = claims.get("scope")
    if isinstance(scope, str):
        return set(scope.split())
    return {str(s) for s in (claims.get("scopes") or [])}


def identity_from_claims(claims: dict) -> Identity:
    email = claims.get("email")
    subject = str(claims.get("sub") or email or "anonymous")
    return Identity(
        subject=subject,
        email=str(email) if email else None,
        principals=tuple(_principals_from_claims(claims)),
        scopes=frozenset(_scopes_from_claims(claims)),
        claims=claims,
    )
