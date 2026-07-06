"""RSA signing key and JWKS for the in-tenancy OAuth Authorization Server.

The AS is stateless: every OAuth artefact (auth code, refresh token, registered
client) is a JWT this key signs, so any scale-to-zero Cloud Run instance can
validate any artefact with no shared datastore. The only durable secret is this
key -- production loads its PEM from Secret Manager; tests and local runs generate
an ephemeral one. RS256 so the resource server (the brain) can verify tokens from
the public JWKS without ever holding the private key.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def b64url(data: bytes) -> str:
    """URL-safe base64 without padding (the JOSE encoding)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


@dataclass
class SigningKey:
    private_pem: str
    kid: str = field(default="")
    _priv: object = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self._priv is None:
            self._priv = serialization.load_pem_private_key(
                self.private_pem.encode(), password=None
            )
        if not self.kid:
            self.kid = _kid(self._priv.public_key())

    @classmethod
    def generate(cls) -> SigningKey:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("ascii")
        return cls(private_pem=pem)

    def sign(self, claims: dict) -> str:
        return jwt.encode(claims, self.private_pem, algorithm="RS256", headers={"kid": self.kid})

    def public_pem(self) -> str:
        return (
            self._priv.public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode("ascii")
        )

    def jwks(self) -> dict:
        """The public key as a JWK Set, served at the AS's ``/jwks`` endpoint."""
        nums = self._priv.public_key().public_numbers()
        n = nums.n.to_bytes((nums.n.bit_length() + 7) // 8, "big")
        e = nums.e.to_bytes((nums.e.bit_length() + 7) // 8, "big")
        return {
            "keys": [
                {
                    "kty": "RSA",
                    "use": "sig",
                    "alg": "RS256",
                    "kid": self.kid,
                    "n": b64url(n),
                    "e": b64url(e),
                }
            ]
        }


def _kid(public_key) -> str:
    """A stable key id from the public key (its SHA-256 thumbprint, truncated)."""
    der = public_key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return b64url(hashlib.sha256(der).digest())[:16]
