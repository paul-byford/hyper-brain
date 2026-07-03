"""A dependency-free JWT (HS256) codec for the offline core and the personal demo.

Production verifies Google-signed **RS256** OIDC ID tokens against Google's public
keys (see ``verify.GoogleOidcVerifier``, a lazy seam over ``google-auth``). But the
offline core, the tests, and the personal-demo path must run with nothing heavy
installed, so this implements just enough JWT with the standard library: HS256
sign/verify plus the claim checks the boundary depends on (``exp``, ``nbf``,
``aud``, ``iss``). Keeping it here means the whole authorisation path, the part
that actually enforces isolation, is testable with no cloud and no third-party
crypto library.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


class TokenError(Exception):
    """Base class for every token failure. Callers reject on any subclass."""


class MalformedToken(TokenError): ...


class InvalidSignature(TokenError): ...


class ExpiredToken(TokenError): ...


class NotYetValid(TokenError): ...


class WrongAudience(TokenError): ...


class WrongIssuer(TokenError): ...


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    pad = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + pad)


def encode_hs256(payload: dict, secret: str) -> str:
    """Sign a claims payload as a compact HS256 JWT. Test/demo helper."""
    header = {"alg": "HS256", "typ": "JWT"}
    segments = [
        _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8")),
        _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
    ]
    signing_input = ".".join(segments).encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    segments.append(_b64url_encode(signature))
    return ".".join(segments)


def decode_hs256(
    token: str,
    secret: str,
    *,
    audience: str | None = None,
    issuer: str | None = None,
    now: int | None = None,
    leeway: int = 60,
) -> dict:
    """Verify an HS256 JWT and return its claims, or raise a ``TokenError``.

    The signature is checked first (constant-time), then time and the
    audience/issuer binding. ``leeway`` tolerates modest clock skew on ``exp`` and
    ``nbf`` only; it never widens the audience or issuer match.
    """
    current = int(now if now is not None else time.time())

    parts = token.split(".")
    if len(parts) != 3:
        raise MalformedToken("expected a three-segment JWT")
    header_b64, payload_b64, signature_b64 = parts

    try:
        header = json.loads(_b64url_decode(header_b64))
        payload = json.loads(_b64url_decode(payload_b64))
        signature = _b64url_decode(signature_b64)
    except (ValueError, json.JSONDecodeError) as exc:
        raise MalformedToken("token is not valid base64url JSON") from exc

    # Reject anything not HS256: a permissive alg check is a classic JWT footgun
    # (for example an attacker downgrading to "none").
    if header.get("alg") != "HS256":
        raise MalformedToken(f"unexpected alg {header.get('alg')!r}")

    expected = hmac.new(
        secret.encode("utf-8"), f"{header_b64}.{payload_b64}".encode("ascii"), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(signature, expected):
        raise InvalidSignature("signature does not verify")

    exp = payload.get("exp")
    if exp is not None and current > int(exp) + leeway:
        raise ExpiredToken("token has expired")

    nbf = payload.get("nbf")
    if nbf is not None and current + leeway < int(nbf):
        raise NotYetValid("token is not yet valid")

    if audience is not None:
        claim = payload.get("aud")
        audiences = claim if isinstance(claim, list) else [claim]
        if audience not in audiences:
            raise WrongAudience("audience does not match this service")

    if issuer is not None and payload.get("iss") != issuer:
        raise WrongIssuer("issuer is not trusted")

    return payload
