"""The OAuth 2.1 Authorization Server as a Starlette app.

Endpoints (all stateless -- state travels in signed JWTs, see ``issuer``):

- ``GET  /.well-known/oauth-authorization-server``  RFC 8414 discovery
- ``GET  /jwks``                                    the public signing key
- ``POST /register``                                RFC 7591 dynamic registration
- ``GET  /authorize``                               validate + PKCE, then bounce to Google
- ``GET  /oauth2/callback``                          Google returns here; mint our code
- ``POST /token``                                   code/refresh -> access (+ refresh) token

The brain is the resource server and validates the access tokens (Phase 3); this
service only issues them, after Google has vouched for the user.
"""

from __future__ import annotations

import urllib.parse

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route

from . import audit
from .google import GoogleOidc
from .issuer import OAuthError, TokenIssuer, authorization_server_metadata


def _err(status: int, error: str, description: str = "") -> JSONResponse:
    return JSONResponse({"error": error, "error_description": description}, status_code=status)


def _redirect(uri: str, params: dict) -> RedirectResponse:
    clean = {k: v for k, v in params.items() if v}
    sep = "&" if "?" in uri else "?"
    return RedirectResponse(uri + sep + urllib.parse.urlencode(clean), status_code=302)


def build_app(issuer: TokenIssuer, google: GoogleOidc) -> Starlette:
    async def metadata(request):
        return JSONResponse(authorization_server_metadata(issuer.issuer))

    async def jwks(request):
        return JSONResponse(issuer.key.jwks())

    async def guest(request):
        # A read-only guest token, minted with no Google login. The brain maps it to a
        # guest identity that reads the commons but cannot write. For frictionless demos.
        resp = JSONResponse(issuer.mint_guest_token())
        resp.headers["Cache-Control"] = "no-store"
        audit.record_guest()  # count guest sessions in the durable audit trail (anonymous)
        return resp

    async def register(request):
        try:
            body = await request.json()
        except Exception:
            return _err(400, "invalid_client_metadata", "request body must be JSON")
        try:
            reg = issuer.register_client(
                redirect_uris=body.get("redirect_uris") or [],
                client_name=body.get("client_name", ""),
            )
        except OAuthError as exc:
            return _err(400, exc.error, exc.description)
        return JSONResponse(reg, status_code=201)

    async def authorize(request):
        q = request.query_params
        if q.get("response_type") != "code":
            return _err(400, "unsupported_response_type", "only response_type=code is supported")
        if q.get("code_challenge_method", "S256") != "S256" or not q.get("code_challenge"):
            return _err(400, "invalid_request", "PKCE with S256 is required")
        client_id, redirect_uri = q.get("client_id", ""), q.get("redirect_uri", "")
        # A bad client_id/redirect_uri must not be reflected back to an unvetted URL.
        try:
            issuer.check_redirect_uri(client_id, redirect_uri)
        except OAuthError as exc:
            return _err(400, exc.error, exc.description)
        state = issuer.mint_login_state(
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=q.get("code_challenge"),
            scope=q.get("scope", "mcp"),
            client_state=q.get("state", ""),
        )
        return RedirectResponse(google.authorize_url(state), status_code=302)

    async def callback(request):
        q = request.query_params
        try:
            login = issuer.redeem_login_state(q.get("state", ""))
        except OAuthError:
            return _err(400, "invalid_request", "invalid or expired login state")
        if q.get("error"):
            return _redirect(
                login["redirect_uri"],
                {
                    "error": q.get("error"),
                    "error_description": q.get("error_description", ""),
                    "state": login.get("client_state", ""),
                },
            )
        try:
            guser = google.exchange(q.get("code", ""))
        except Exception:
            return _redirect(
                login["redirect_uri"],
                {
                    "error": "access_denied",
                    "error_description": "Google sign-in failed",
                    "state": login.get("client_state", ""),
                },
            )
        code = issuer.mint_authorization_code(
            sub=guser["sub"],
            email=guser["email"],
            client_id=login["client_id"],
            redirect_uri=login["redirect_uri"],
            code_challenge=login["code_challenge"],
            scope=login["scope"],
        )
        # Durable, write-once sign-in audit (best-effort; no-op unless BRAIN_AUDIT_BUCKET is set).
        audit.record_signin(guser["sub"], guser["email"])
        return _redirect(
            login["redirect_uri"], {"code": code, "state": login.get("client_state", "")}
        )

    async def token(request):
        form = await request.form()
        grant = form.get("grant_type")
        client_id = form.get("client_id", "")
        try:
            if grant == "authorization_code":
                ident = issuer.redeem_authorization_code(
                    form.get("code", ""),
                    code_verifier=form.get("code_verifier", ""),
                    client_id=client_id,
                    redirect_uri=form.get("redirect_uri", ""),
                )
            elif grant == "refresh_token":
                ident = issuer.redeem_refresh_token(
                    form.get("refresh_token", ""), client_id=client_id
                )
            else:
                return _err(
                    400, "unsupported_grant_type", "authorization_code or refresh_token only"
                )
        except OAuthError as exc:
            return _err(400, exc.error, exc.description)
        out = issuer.issue_token_response(
            sub=ident["sub"],
            email=ident["email"],
            scope=ident["scope"] or "mcp",
            client_id=client_id,
        )
        resp = JSONResponse(out)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    routes = [
        Route("/.well-known/oauth-authorization-server", metadata, methods=["GET"]),
        Route("/jwks", jwks, methods=["GET"]),
        Route("/guest", guest, methods=["GET"]),
        Route("/register", register, methods=["POST"]),
        Route("/authorize", authorize, methods=["GET"]),
        Route("/oauth2/callback", callback, methods=["GET"]),
        Route("/token", token, methods=["POST"]),
    ]
    middleware = [
        Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    ]
    return Starlette(routes=routes, middleware=middleware)
