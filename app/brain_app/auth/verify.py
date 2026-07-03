"""Token verifiers: turn a bearer string into a trusted ``Identity``, or reject.

The server is the only trustworthy place to enforce isolation (ARCHITECTURE.md
section 7), and verification is where that trust starts. Two implementations
behind one interface:

- ``HmacVerifier`` (HS256, standard library): the offline core and personal demo.
- ``GoogleOidcVerifier`` (RS256, lazy ``google-auth``): production, verifying
  Google-signed ID tokens against Google's public keys with the service URL as the
  audience.

The interface is the seam; the ADK agent and any MCP client send the same bearer,
and only the server decides who they are.
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

from .identity import Identity, identity_from_claims
from .tokens import TokenError, decode_hs256


@runtime_checkable
class TokenVerifier(Protocol):
    def verify(self, token: str) -> Identity: ...


class HmacVerifier:
    """Verifies HS256 tokens with a shared secret. Deterministic and offline."""

    def __init__(
        self,
        secret: str,
        *,
        audience: str | None = None,
        issuer: str | None = None,
        leeway: int = 60,
    ) -> None:
        self.secret = secret
        self.audience = audience
        self.issuer = issuer
        self.leeway = leeway

    def verify(self, token: str) -> Identity:
        claims = decode_hs256(
            token,
            self.secret,
            audience=self.audience,
            issuer=self.issuer,
            leeway=self.leeway,
        )
        return identity_from_claims(claims)


class GoogleOidcVerifier:
    """Verifies Google-signed OIDC ID tokens. Production seam (lazy import)."""

    def __init__(self, audience: str) -> None:
        self.audience = audience

    def verify(self, token: str) -> Identity:
        # Imported lazily: the offline core and its tests never need google-auth.
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token

        try:
            claims = google_id_token.verify_oauth2_token(
                token, google_requests.Request(), self.audience
            )
        except ValueError as exc:  # google-auth raises ValueError on any failure
            raise TokenError(str(exc)) from exc
        return identity_from_claims(claims)


def get_verifier(provider: str | None = None) -> TokenVerifier:
    """Return the configured verifier.

    Selected by ``BRAIN_AUTH`` (``hs256`` default). ``hs256`` reads its secret and
    optional audience/issuer from the environment; ``google`` needs the service URL
    as ``BRAIN_AUTH_AUDIENCE``. There is deliberately no unauthenticated mode: a
    missing secret is an error, not an open door.
    """
    provider = provider or os.environ.get("BRAIN_AUTH", "hs256")
    if provider == "hs256":
        secret = os.environ.get("BRAIN_AUTH_SECRET")
        if not secret:
            raise ValueError("BRAIN_AUTH=hs256 requires BRAIN_AUTH_SECRET to be set")
        return HmacVerifier(
            secret,
            audience=os.environ.get("BRAIN_AUTH_AUDIENCE"),
            issuer=os.environ.get("BRAIN_AUTH_ISSUER"),
        )
    if provider == "google":
        audience = os.environ.get("BRAIN_AUTH_AUDIENCE")
        if not audience:
            raise ValueError("BRAIN_AUTH=google requires BRAIN_AUTH_AUDIENCE (the service URL)")
        return GoogleOidcVerifier(audience)
    raise ValueError(f"unknown auth provider {provider!r}")
