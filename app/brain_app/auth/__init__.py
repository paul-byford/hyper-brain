"""Identity, verification and authorisation for the serving layer.

The trust chain: a bearer token is *verified* into an ``Identity`` (verify.py),
that identity is *authorised* to a set of domains and, separately, a write scope
(authorize.py), and the service enforces both before anything is returned or
landed. All of it is offline-testable; production swaps the HS256 verifier for the
Google OIDC one behind the same interface.
"""

from __future__ import annotations

from .authorize import (
    PERSONAL_PREFIX,
    can_propose,
    can_share,
    is_personal_domain,
    personal_domain,
    personal_owner,
    read_domains,
    readable_docs,
    writable_domains,
)
from .identity import PROPOSE_SCOPE, Identity, identity_from_claims
from .shares import (
    GcsSharesStore,
    MemorySharesStore,
    Share,
    ShareError,
    SharesStore,
    get_shares_store,
    utc_now,
    validate_share,
)
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
from .verify import (
    CompositeVerifier,
    GoogleOidcVerifier,
    HmacVerifier,
    OAuthJwtVerifier,
    TokenVerifier,
    get_verifier,
)

__all__ = [
    "PERSONAL_PREFIX",
    "PROPOSE_SCOPE",
    "CompositeVerifier",
    "ExpiredToken",
    "GcsSharesStore",
    "GoogleOidcVerifier",
    "HmacVerifier",
    "Identity",
    "MemorySharesStore",
    "OAuthJwtVerifier",
    "InvalidSignature",
    "MalformedToken",
    "NotYetValid",
    "Share",
    "ShareError",
    "SharesStore",
    "TokenError",
    "TokenVerifier",
    "WrongAudience",
    "WrongIssuer",
    "can_propose",
    "can_share",
    "encode_hs256",
    "get_shares_store",
    "get_verifier",
    "identity_from_claims",
    "is_personal_domain",
    "personal_domain",
    "personal_owner",
    "read_domains",
    "readable_docs",
    "utc_now",
    "validate_share",
    "writable_domains",
]
