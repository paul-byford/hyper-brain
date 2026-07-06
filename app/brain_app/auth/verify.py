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


class OAuthJwtVerifier:
    """Verifies access tokens issued by our in-tenancy OAuth AS.

    RS256, checked against the AS's public JWKS (so the brain never holds the
    signing key), with the AS as issuer and the brain URL as audience. This is the
    seam that lets a remote MCP connector -- which authenticated a human via the
    AS's Google-brokered flow -- reach the brain as any other caller.
    """

    def __init__(
        self,
        issuer: str,
        audience: str,
        *,
        jwks_url: str | None = None,
        public_pem: str | None = None,
    ) -> None:
        self.issuer = issuer
        self.audience = audience
        self.jwks_url = jwks_url
        self.public_pem = public_pem
        self._jwk_client = None

    def _key_for(self, token: str):
        if self.public_pem:  # tests / co-located key
            return self.public_pem
        import jwt

        if self._jwk_client is None:
            self._jwk_client = jwt.PyJWKClient(self.jwks_url)  # fetches + caches the JWKS
        return self._jwk_client.get_signing_key_from_jwt(token).key

    def verify(self, token: str) -> Identity:
        import jwt

        try:
            claims = jwt.decode(
                token,
                self._key_for(token),
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "iss"]},
            )
        except Exception as exc:  # PyJWT errors, or a JWKS fetch failure
            raise TokenError(str(exc)) from exc
        if claims.get("typ") != "access":
            raise TokenError("not an access token")
        return identity_from_claims(claims)


class CompositeVerifier:
    """Accepts a token if any wrapped verifier does; the first to accept wins.

    Lets one endpoint serve both the ADK agent (Google-signed ID tokens) and
    remote connectors (OAuth access tokens) without the caller declaring which.
    """

    def __init__(self, verifiers: list[TokenVerifier]) -> None:
        if not verifiers:
            raise ValueError("CompositeVerifier needs at least one verifier")
        self.verifiers = verifiers

    def verify(self, token: str) -> Identity:
        last: Exception | None = None
        for verifier in self.verifiers:
            try:
                return verifier.verify(token)
            except TokenError as exc:  # a verifier declining is expected, try the next
                last = exc
        raise TokenError("no configured verifier accepted the token") from last


def _oauth_verifier_from_env() -> OAuthJwtVerifier:
    audience = os.environ.get("BRAIN_AUTH_AUDIENCE")
    issuer = os.environ.get("BRAIN_OAUTH_ISSUER")
    if not audience or not issuer:
        raise ValueError("oauth verification requires BRAIN_AUTH_AUDIENCE and BRAIN_OAUTH_ISSUER")
    jwks_url = os.environ.get("BRAIN_OAUTH_JWKS") or f"{issuer.rstrip('/')}/jwks"
    return OAuthJwtVerifier(issuer, audience, jwks_url=jwks_url)


def get_verifier(provider: str | None = None) -> TokenVerifier:
    """Return the configured verifier.

    Selected by ``BRAIN_AUTH`` (``hs256`` default). ``hs256`` reads its secret and
    optional audience/issuer; ``google`` needs the service URL as
    ``BRAIN_AUTH_AUDIENCE``; ``oauth`` validates our AS's tokens (also needs
    ``BRAIN_OAUTH_ISSUER``); ``composite`` accepts both Google and OAuth tokens on
    one endpoint. There is deliberately no unauthenticated mode.
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
    if provider == "oauth":
        return _oauth_verifier_from_env()
    if provider == "composite":
        audience = os.environ.get("BRAIN_AUTH_AUDIENCE")
        if not audience:
            raise ValueError("BRAIN_AUTH=composite requires BRAIN_AUTH_AUDIENCE (the service URL)")
        return CompositeVerifier([GoogleOidcVerifier(audience), _oauth_verifier_from_env()])
    raise ValueError(f"unknown auth provider {provider!r}")
