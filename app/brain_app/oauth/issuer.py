"""The stateless token machine for the OAuth 2.1 Authorization Server.

Every OAuth artefact is a short-lived JWT signed by the AS key and tagged with a
``typ`` so one kind can never be replayed as another:

- ``client``   a Dynamic Client Registration (RFC 7591); the client_id *is* this JWT.
- ``code``     an authorization code, bound to the PKCE challenge and redirect_uri.
- ``access``   the bearer the resource server (the brain) validates; audience = brain.
- ``refresh``  exchanged at the token endpoint for a fresh access token.

Login is brokered to Google upstream (the HTTP layer, next phase); this module
only mints and redeems, so the whole machine is pure and hermetically testable.
Being stateless is what lets it run on multi-instance, scale-to-zero Cloud Run
with no session store: any instance can validate any artefact from the key alone.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time

import jwt

from .keys import SigningKey

SCOPES = ["mcp"]


class OAuthError(Exception):
    """An OAuth error, carrying the RFC 6749 ``error`` code for the HTTP response."""

    def __init__(self, error: str, description: str = "") -> None:
        super().__init__(f"{error}: {description}" if description else error)
        self.error = error
        self.description = description


def _now() -> int:
    return int(time.time())


def verify_pkce(code_verifier: str, code_challenge: str, method: str = "S256") -> bool:
    """RFC 7636: challenge == base64url(sha256(verifier)). Only S256 is accepted."""
    if method != "S256" or not code_verifier or not code_challenge:
        return False
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return secrets.compare_digest(expected, code_challenge)


class TokenIssuer:
    def __init__(
        self,
        key: SigningKey,
        *,
        issuer: str,
        resource: str,
        access_ttl: int = 3600,
        code_ttl: int = 300,
        refresh_ttl: int = 30 * 24 * 3600,
        client_ttl: int = 365 * 24 * 3600,
    ) -> None:
        self.key = key
        self.issuer = issuer
        self.resource = resource  # the brain URL; the access-token audience
        self.access_ttl = access_ttl
        self.code_ttl = code_ttl
        self.refresh_ttl = refresh_ttl
        self.client_ttl = client_ttl

    def _decode(self, token: str, *, typ: str, audience: str | None = None) -> dict:
        try:
            claims = jwt.decode(
                token,
                self.key.public_pem(),
                algorithms=["RS256"],
                audience=audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "iss"], "verify_aud": audience is not None},
            )
        except jwt.PyJWTError as exc:
            raise OAuthError("invalid_grant", str(exc)) from exc
        if claims.get("typ") != typ:
            raise OAuthError("invalid_grant", "wrong token type")
        return claims

    # --- Dynamic Client Registration (RFC 7591): the client_id is a signed JWT ---
    def register_client(self, *, redirect_uris: list[str], client_name: str = "") -> dict:
        if not redirect_uris:
            raise OAuthError("invalid_redirect_uri", "at least one redirect_uri is required")
        now = _now()
        client_id = self.key.sign(
            {
                "typ": "client",
                "iss": self.issuer,
                "iat": now,
                "exp": now + self.client_ttl,
                "redirect_uris": list(redirect_uris),
                "client_name": client_name,
            }
        )
        return {
            "client_id": client_id,
            "redirect_uris": list(redirect_uris),
            "client_name": client_name,
            "token_endpoint_auth_method": "none",  # public client, PKCE only
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "client_id_issued_at": now,
        }

    def read_client(self, client_id: str) -> dict:
        return self._decode(client_id, typ="client")

    def check_redirect_uri(self, client_id: str, redirect_uri: str) -> dict:
        client = self.read_client(client_id)
        if redirect_uri not in (client.get("redirect_uris") or []):
            raise OAuthError("invalid_request", "redirect_uri not registered for this client")
        return client

    # --- Authorization code, bound to PKCE + redirect_uri + client ---
    def mint_authorization_code(
        self,
        *,
        sub: str,
        email: str,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        scope: str,
    ) -> str:
        now = _now()
        return self.key.sign(
            {
                "typ": "code",
                "iss": self.issuer,
                "iat": now,
                "exp": now + self.code_ttl,
                "sub": sub,
                "email": email,
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_challenge": code_challenge,
                "scope": scope,
            }
        )

    def redeem_authorization_code(
        self, code: str, *, code_verifier: str, client_id: str, redirect_uri: str
    ) -> dict:
        claims = self._decode(code, typ="code")
        if claims.get("client_id") != client_id:
            raise OAuthError("invalid_grant", "authorization code was issued to another client")
        if claims.get("redirect_uri") != redirect_uri:
            raise OAuthError(
                "invalid_grant", "redirect_uri does not match the authorization request"
            )
        if not verify_pkce(code_verifier, claims.get("code_challenge", "")):
            raise OAuthError("invalid_grant", "PKCE verification failed")
        return {"sub": claims["sub"], "email": claims["email"], "scope": claims.get("scope", "")}

    # --- Login state: carries the client's authorize request across the Google
    #     round-trip, as a signed JWT (so /authorize and /callback stay stateless). ---
    def mint_login_state(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        scope: str,
        client_state: str,
    ) -> str:
        now = _now()
        return self.key.sign(
            {
                "typ": "login",
                "iss": self.issuer,
                "iat": now,
                "exp": now + 600,
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_challenge": code_challenge,
                "scope": scope,
                "client_state": client_state,
            }
        )

    def redeem_login_state(self, state: str) -> dict:
        return self._decode(state, typ="login")

    # --- Access + refresh tokens ---
    def mint_access_token(self, *, sub: str, email: str, scope: str) -> str:
        now = _now()
        return self.key.sign(
            {
                "typ": "access",
                "iss": self.issuer,
                "aud": self.resource,
                "iat": now,
                "exp": now + self.access_ttl,
                "sub": sub,
                "email": email,
                "scope": scope,
            }
        )

    def mint_refresh_token(self, *, sub: str, email: str, client_id: str, scope: str) -> str:
        now = _now()
        return self.key.sign(
            {
                "typ": "refresh",
                "iss": self.issuer,
                "iat": now,
                "exp": now + self.refresh_ttl,
                "sub": sub,
                "email": email,
                "client_id": client_id,
                "scope": scope,
            }
        )

    def redeem_refresh_token(self, token: str, *, client_id: str) -> dict:
        claims = self._decode(token, typ="refresh")
        if claims.get("client_id") != client_id:
            raise OAuthError("invalid_grant", "refresh token was issued to another client")
        return {"sub": claims["sub"], "email": claims["email"], "scope": claims.get("scope", "")}

    def issue_token_response(
        self, *, sub: str, email: str, scope: str, client_id: str, with_refresh: bool = True
    ) -> dict:
        """The RFC 6749 token endpoint response body."""
        out = {
            "access_token": self.mint_access_token(sub=sub, email=email, scope=scope),
            "token_type": "Bearer",
            "expires_in": self.access_ttl,
            "scope": scope,
        }
        if with_refresh:
            out["refresh_token"] = self.mint_refresh_token(
                sub=sub, email=email, client_id=client_id, scope=scope
            )
        return out


# --- Discovery metadata (pure; the HTTP layer serves these) ------------------
def authorization_server_metadata(issuer: str) -> dict:
    """RFC 8414 metadata, served at /.well-known/oauth-authorization-server."""
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/authorize",
        "token_endpoint": f"{issuer}/token",
        "registration_endpoint": f"{issuer}/register",
        "jwks_uri": f"{issuer}/jwks",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": SCOPES,
    }


def protected_resource_metadata(resource: str, issuer: str) -> dict:
    """RFC 9728 metadata, served by the brain at /.well-known/oauth-protected-resource."""
    return {
        "resource": resource,
        "authorization_servers": [issuer],
        "bearer_methods_supported": ["header"],
        "scopes_supported": SCOPES,
    }
