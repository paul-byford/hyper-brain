"""Entrypoint for the OAuth Authorization Server (Cloud Run / local).

Everything is env-configured so the same image runs anywhere:

- ``OAUTH_ISSUER``          this service's own public URL (the token issuer)
- ``OAUTH_RESOURCE``        the brain URL (the access-token audience)
- ``OAUTH_SIGNING_KEY``     RSA private key PEM (Secret Manager in production)
- ``GOOGLE_CLIENT_ID`` / ``GOOGLE_CLIENT_SECRET``  the upstream Google OAuth client
- ``OAUTH_CALLBACK``        override the callback URL (default ``$OAUTH_ISSUER/oauth2/callback``)
"""

from __future__ import annotations

import os

from .app import build_app
from .google import GoogleOidc
from .issuer import TokenIssuer
from .keys import SigningKey


def load_key() -> SigningKey:
    pem = os.environ.get("OAUTH_SIGNING_KEY")
    if pem:
        return SigningKey(private_pem=pem)
    # No key supplied: an ephemeral one (dev only -- all tokens die on restart).
    return SigningKey.generate()


def build_from_env():
    issuer_url = os.environ["OAUTH_ISSUER"].rstrip("/")
    resource = os.environ["OAUTH_RESOURCE"].rstrip("/")
    issuer = TokenIssuer(load_key(), issuer=issuer_url, resource=resource)
    google = GoogleOidc(
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        redirect_uri=os.environ.get("OAUTH_CALLBACK") or f"{issuer_url}/oauth2/callback",
    )
    return build_app(issuer, google)


def main() -> int:
    import uvicorn

    uvicorn.run(
        build_from_env(),
        host=os.environ.get("HOST", "0.0.0.0"),  # nosec B104
        port=int(os.environ.get("PORT", "8080")),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
