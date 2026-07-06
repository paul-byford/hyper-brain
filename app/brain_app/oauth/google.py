"""Sign in with Google, upstream of our Authorization Server.

The user authenticates to Google (not to us); we only ever learn their verified
email and subject. The AS is a confidential client to Google, so this needs a
Google OAuth client (id + secret) whose authorized redirect URI is our callback.
The token exchange sits behind an injectable ``exchange`` so the service tests
run without touching the network.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Callable

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleOidc:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        *,
        exchange: Callable[[str], dict] | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri  # our /oauth2/callback, registered with Google
        self._exchange = exchange or self._default_exchange

    def authorize_url(self, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid email",
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
        return GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)

    def exchange(self, code: str) -> dict:
        """Return ``{'sub', 'email'}`` for the signed-in Google user."""
        return self._exchange(code)

    def _default_exchange(self, code: str) -> dict:
        # Lazy imports: tests inject a fake exchange and never import these.
        import requests
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token

        resp = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=15,
        )
        resp.raise_for_status()
        id_tok = resp.json().get("id_token")
        if not id_tok:
            raise ValueError("Google token response had no id_token")
        claims = google_id_token.verify_oauth2_token(
            id_tok, google_requests.Request(), self.client_id
        )
        return {"sub": claims["sub"], "email": claims.get("email", "")}
