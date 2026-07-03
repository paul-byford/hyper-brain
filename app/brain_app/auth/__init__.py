"""Identity, verification and authorisation for the serving layer.

The trust chain: a bearer token is *verified* into an ``Identity`` (verify.py),
that identity is *authorised* to a set of domains and, separately, a write scope
(authorize.py), and the service enforces both before anything is returned or
landed. All of it is offline-testable; production swaps the HS256 verifier for the
Google OIDC one behind the same interface.
"""

from __future__ import annotations

from .authorize import can_propose, read_domains, writable_domains
from .identity import PROPOSE_SCOPE, Identity, identity_from_claims
from .tokens import (
    ExpiredToken,
    InvalidSignature,
    MalformedToken,
    NotYetValid,
    TokenError,
    WrongAudience,
    WrongIssuer,
    encode_hs256,
)
from .verify import GoogleOidcVerifier, HmacVerifier, TokenVerifier, get_verifier

__all__ = [
    "PROPOSE_SCOPE",
    "ExpiredToken",
    "GoogleOidcVerifier",
    "HmacVerifier",
    "Identity",
    "InvalidSignature",
    "MalformedToken",
    "NotYetValid",
    "TokenError",
    "TokenVerifier",
    "WrongAudience",
    "WrongIssuer",
    "can_propose",
    "encode_hs256",
    "get_verifier",
    "identity_from_claims",
    "read_domains",
    "writable_domains",
]
