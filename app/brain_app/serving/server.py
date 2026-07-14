"""MCP-over-streamable-HTTP binding for the brain.

Thin by design: every request extracts the caller's bearer token, verifies it into
an ``Identity``, and delegates to ``BrainService``, which owns all authorisation.
The server is the trustworthy enforcement point (ARCHITECTURE.md section 7); this
module only wires transport and identity to that enforcement. It requires the
``[mcp]`` extra, so it is imported lazily (never from ``serving/__init__``) and the
offline core installs without it.
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import Context, FastMCP

from ..auth import ShareError, TokenError, TokenVerifier
from ..models import Answer, SearchResult
from .service import AccessError, BrainService, DocumentNotFound


def _bearer_from_context(ctx: Context) -> str:
    """Pull the bearer token off the incoming HTTP request, or refuse."""
    request = getattr(ctx.request_context, "request", None)
    header = request.headers.get("authorization") if request is not None else None
    if not header or not header.lower().startswith("bearer "):
        raise PermissionError("missing or malformed Authorization: Bearer header")
    return header.split(" ", 1)[1].strip()


def _result_to_dict(result: SearchResult) -> dict:
    return {
        "doc_id": result.doc_id,
        "domain": result.domain,
        "title": result.title,
        "heading": result.heading,
        "text": result.text,
        "score": result.score,
        "via": result.via,
    }


def _answer_to_dict(result: Answer) -> dict:
    return {
        "text": result.text,
        "citations": [_result_to_dict(c) for c in result.citations],
        "gaps": list(result.gaps),
        "used_domains": list(result.used_domains),
    }


class _MCPTokenVerifier:
    """Adapts our ``TokenVerifier`` to the MCP SDK's async token-verifier interface.

    With this wired in, FastMCP serves the OAuth protected-resource metadata and
    answers an unauthenticated call with 401 + ``WWW-Authenticate`` pointing at the
    AS -- the discovery trigger a remote connector needs. Returning ``None`` means
    'reject' (the SDK turns it into the 401).
    """

    def __init__(self, verifier: TokenVerifier, resource: str) -> None:
        self.verifier = verifier
        self.resource = resource

    async def verify_token(self, token: str):
        from mcp.server.auth.provider import AccessToken

        try:
            ident = self.verifier.verify(token)
        except Exception:  # any verification failure is simply 'unauthenticated'
            return None
        exp = ident.claims.get("exp")
        return AccessToken(
            token=token,
            client_id=str(ident.claims.get("azp") or ident.claims.get("aud") or ""),
            scopes=list(ident.scopes) or ["mcp"],
            expires_at=int(exp) if exp else None,
            resource=self.resource,
            subject=ident.subject,
            claims=dict(ident.claims),
        )


def build_server(
    service: BrainService,
    verifier: TokenVerifier,
    *,
    name: str = "hyper-brain",
    auth_issuer: str | None = None,
    resource: str | None = None,
) -> FastMCP:
    """Wire the five brain tools onto a FastMCP server. Each verifies identity first.

    When ``auth_issuer`` and ``resource`` are given, the server also runs as an
    OAuth 2.1 resource server for our in-tenancy AS, so remote connectors can
    discover the AS and sign in.
    """
    # The MCP transport's DNS-rebinding protection only allows localhost hosts by
    # default, which 421s a request to the Cloud Run URL. That protection guards a
    # browser POSTing to a local MCP server; our endpoint is server-to-server and
    # authenticated in-app (OIDC/OAuth), so we disable it.
    from mcp.server.transport_security import TransportSecuritySettings

    kwargs: dict = {
        "transport_security": TransportSecuritySettings(enable_dns_rebinding_protection=False),
    }
    if auth_issuer and resource:
        from mcp.server.auth.settings import AuthSettings

        kwargs["token_verifier"] = _MCPTokenVerifier(verifier, resource)
        kwargs["auth"] = AuthSettings(
            issuer_url=auth_issuer,
            resource_server_url=resource,
            required_scopes=[],
        )

    mcp = FastMCP(name, **kwargs)

    def identity(ctx: Context):
        try:
            return verifier.verify(_bearer_from_context(ctx))
        except TokenError as exc:
            # Do not echo token internals back to the caller.
            raise PermissionError("token rejected") from exc

    @mcp.tool(
        description=(
            "List the knowledge domains the caller may retrieve from, including their "
            "own personal space (even when empty)."
        )
    )
    def list_domains(ctx: Context) -> list[str]:
        return service.list_domains(identity(ctx))

    @mcp.tool(
        description=(
            "Describe the caller's spaces and how to use them: their private personal "
            "space (write to it with add_note), the shared commons, their team domains, "
            "and anything shared with them. Call this to discover where to put content."
        )
    )
    def my_spaces(ctx: Context) -> dict:
        return service.my_spaces(identity(ctx))

    @mcp.tool(description="Search the brain; results are scoped to the caller's domains.")
    def search(query: str, ctx: Context, top_k: int = 5) -> list[dict]:
        return [_result_to_dict(r) for r in service.search(identity(ctx), query, top_k=top_k)]

    @mcp.tool(description="Answer a question with citations and an honest gap statement.")
    def answer(query: str, ctx: Context, top_k: int = 5) -> dict:
        return _answer_to_dict(service.answer(identity(ctx), query, top_k=top_k))

    @mcp.tool(description="Fetch one document by id, if it is in a domain the caller may see.")
    def get_document(doc_id: str, ctx: Context) -> dict:
        try:
            return service.get_document(identity(ctx), doc_id)
        except DocumentNotFound as exc:
            raise ValueError(f"document not found: {doc_id}") from exc

    @mcp.tool(
        description=(
            "Propose a new document into a shared TEAM domain. Goes to review, never a "
            "live write, and the target domain must be one you may write. For content "
            "private to you, use add_note instead (your personal space, no review)."
        )
    )
    def propose_document(
        domain: str,
        title: str,
        content: str,
        ctx: Context,
        source_url: str | None = None,
    ) -> dict:
        try:
            result = service.propose_document(
                identity(ctx),
                domain=domain,
                title=title,
                content=content,
                source_url=source_url,
            )
        except AccessError as exc:
            raise PermissionError(str(exc)) from exc
        return {
            "status": result.status,
            "path": result.path,
            "branch": result.branch,
            "checksum": result.checksum,
            "detail": result.detail,
        }

    @mcp.tool(
        description=(
            "Save a note into your own private personal space. Only you can see it "
            "until you share it. Searchable once the index next rebuilds."
        )
    )
    def add_note(title: str, content: str, ctx: Context, source_url: str | None = None) -> dict:
        try:
            result = service.add_note(
                identity(ctx), title=title, content=content, source_url=source_url
            )
        except AccessError as exc:
            raise PermissionError(str(exc)) from exc
        return {
            "status": result.status,
            "path": result.path,
            "checksum": result.checksum,
            "detail": result.detail,
        }

    @mcp.tool(
        description=(
            "Ingest an uploaded file (PDF, Word .docx, markdown, HTML, text) as a "
            "document. content_base64 is the file's bytes, base64-encoded. Defaults to "
            "your personal space; pass a team domain to propose it there for review. "
            "The file is parsed to searchable text and the original is kept as a link."
        )
    )
    def ingest_file(
        filename: str,
        content_base64: str,
        ctx: Context,
        domain: str | None = None,
        title: str | None = None,
    ) -> dict:
        try:
            result = service.ingest_file(
                identity(ctx),
                filename=filename,
                content_base64=content_base64,
                domain=domain,
                title=title,
            )
        except AccessError as exc:
            raise PermissionError(str(exc)) from exc
        return {
            "status": result.status,
            "path": result.path,
            "checksum": result.checksum,
            "detail": result.detail,
        }

    @mcp.tool(
        description=(
            "Share a domain or a single document you own with another person "
            "(their email) or a group (group:name). Set write to let them add to it."
        )
    )
    def share(
        principal: str,
        ctx: Context,
        domain: str | None = None,
        doc_id: str | None = None,
        write: bool = False,
    ) -> dict:
        try:
            return service.share(
                identity(ctx), principal=principal, domain=domain, doc_id=doc_id, write=write
            )
        except DocumentNotFound as exc:
            raise ValueError(f"document not found: {doc_id}") from exc
        except (AccessError, ShareError) as exc:
            raise PermissionError(str(exc)) from exc

    @mcp.tool(description="Revoke a share you created. Returns how many were removed.")
    def unshare(
        principal: str,
        ctx: Context,
        domain: str | None = None,
        doc_id: str | None = None,
    ) -> dict:
        removed = service.unshare(identity(ctx), principal=principal, domain=domain, doc_id=doc_id)
        return {"removed": removed}

    @mcp.tool(description="List what you have shared, and what has been shared with you.")
    def list_shares(ctx: Context) -> dict:
        return service.list_shares(identity(ctx))

    @mcp.tool(
        description=(
            "List documents proposed into team domains you can write, awaiting your "
            "review. Empty if you have no write (review) access anywhere."
        )
    )
    def list_proposals(ctx: Context) -> list[dict]:
        return service.list_proposals(identity(ctx))

    @mcp.tool(
        description=(
            "Accept a proposed document into its live domain and reindex. Requires "
            "write (review) access to that domain."
        )
    )
    def accept_proposal(name: str, ctx: Context) -> dict:
        try:
            return service.accept_proposal(identity(ctx), name)
        except AccessError as exc:
            raise PermissionError(str(exc)) from exc

    # A thin JSON REST facade over the same service + verifier, for the browser UI.
    from .restapi import register_rest_routes

    register_rest_routes(mcp, service, verifier)

    return mcp


def _load_service() -> BrainService:
    """Assemble a service from the environment for a real run.

    Everything model-facing is env-selected so the same container runs the
    offline fakes or the in-tenancy Vertex path: BRAIN_EMBEDDINGS (fake|vertex),
    BRAIN_SYNTH (extractive|gemini), and the proposal gate (memory|git|gcs).
    Auth and its audience are read by get_verifier from BRAIN_AUTH*.
    """
    from ..agent.studio import get_agent_store
    from ..auth import get_shares_store
    from ..config import policy_source
    from ..embeddings import get_embeddings
    from ..retrieval import BrainIndex, get_synthesiser
    from .attachments import get_attachment_store
    from .modelcache import CachingEmbeddings, CachingSynthesiser
    from .proposals import GcsCorpusDeleter, GcsCorpusGate, MemoryDeleter, MemoryGate, get_gate
    from .reindex import get_reindexer
    from .reports import get_reports_store
    from .reviewer import get_reviewer

    index_path = os.environ.get("BRAIN_INDEX", ".brain/index.json")
    # BRAIN_POLICY may point at a gs:// object so grants take effect without a
    # rebuild; unset falls back to the profile's policy file baked in the image.
    source = policy_source(os.environ.get("BRAIN_POLICY"))
    # Personal notes land live into the corpus bucket (owned, no review) when one is
    # configured; otherwise they are recorded in-process (the safe local default).
    corpus_bucket = os.environ.get("BRAIN_CORPUS_BUCKET")
    note_gate = GcsCorpusGate(corpus_bucket) if corpus_bucket else MemoryGate()
    deleter = GcsCorpusDeleter(corpus_bucket) if corpus_bucket else MemoryDeleter()
    # Cache the two repeating model calls (query embedding, composed answer) so a
    # re-asked question serves from memory with no Vertex call: fewer calls, fewer 429s
    # under load, and no quota increase. The caches are per-instance and clear on a cold
    # start, so they never serve stale content across a redeploy or reindex.
    embeddings = CachingEmbeddings(get_embeddings())
    synthesiser = CachingSynthesiser(get_synthesiser())
    return BrainService(
        None,
        embeddings,
        source(),
        gate=get_gate(),
        synthesiser=synthesiser,
        policy_source=source,
        # Lazy: the container starts before the index exists; loaded on first query.
        index_loader=lambda: BrainIndex.load(index_path),
        shares_store=get_shares_store(),
        note_gate=note_gate,
        deleter=deleter,
        attachment_store=get_attachment_store(),
        reviewer=get_reviewer(),
        reindexer=get_reindexer(),
        reports_store=get_reports_store(),
        agent_store=get_agent_store(),
    )


def main() -> int:
    from ..auth import get_verifier
    from ..observability import configure

    # Turn on tracing if BRAIN_OTEL is set (gcp in production; a no-op otherwise).
    configure()
    # If an OAuth AS is configured, advertise it so remote connectors can sign in.
    auth_issuer = os.environ.get("BRAIN_OAUTH_ISSUER")
    resource = os.environ.get("BRAIN_AUTH_AUDIENCE")
    server = build_server(
        _load_service(),
        get_verifier(),
        auth_issuer=auth_issuer,
        resource=resource if auth_issuer else None,
    )
    host = os.environ.get("HOST", "0.0.0.0")  # nosec B104
    port = int(os.environ.get("PORT", "8080"))

    # The browser UI is served from a different origin, so the REST facade needs CORS
    # for it. When BRAIN_CORS_ORIGINS is set we build the app ourselves and wrap it;
    # otherwise the plain streamable-HTTP server runs as before (agents/MCP clients).
    origins = [o.strip() for o in os.environ.get("BRAIN_CORS_ORIGINS", "").split(",") if o.strip()]
    if origins:
        import uvicorn
        from starlette.middleware.cors import CORSMiddleware

        app = CORSMiddleware(
            server.streamable_http_app(),
            allow_origins=origins,
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=False,
        )
        uvicorn.run(app, host=host, port=port)
    else:
        # Streamable HTTP is the transport the ADK agent and MCP clients connect over.
        server.settings.host = host
        server.settings.port = port
        server.run(transport="streamable-http")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
