"""In-tenancy OAuth 2.1 Authorization Server for remote MCP connectors.

Lets Claude/ChatGPT custom connectors register (RFC 7591 DCR), sign in via Google
upstream, and receive tokens the brain validates. Stateless by design: every
artefact is a signed JWT (see ``issuer``), so it runs on scale-to-zero Cloud Run
with no datastore. This package holds the pure core; the HTTP service and the
brain-side verification are wired in later phases.
"""

from __future__ import annotations

from .issuer import (
    SCOPES,
    OAuthError,
    TokenIssuer,
    authorization_server_metadata,
    protected_resource_metadata,
    verify_pkce,
)
from .keys import SigningKey

__all__ = [
    "SCOPES",
    "OAuthError",
    "SigningKey",
    "TokenIssuer",
    "authorization_server_metadata",
    "protected_resource_metadata",
    "verify_pkce",
]
