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

from ..auth import TokenError, TokenVerifier
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


def build_server(
    service: BrainService,
    verifier: TokenVerifier,
    *,
    name: str = "hyper-brain",
) -> FastMCP:
    """Wire the five brain tools onto a FastMCP server. Each verifies identity first."""
    # The MCP transport's DNS-rebinding protection only allows localhost hosts by
    # default, which 421s a request to the Cloud Run URL. That protection guards a
    # browser POSTing to a local MCP server; our endpoint is server-to-server and
    # already gated by Cloud Run IAM plus app-level OIDC, so we disable it.
    from mcp.server.transport_security import TransportSecuritySettings

    mcp = FastMCP(
        name,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    def identity(ctx: Context):
        try:
            return verifier.verify(_bearer_from_context(ctx))
        except TokenError as exc:
            # Do not echo token internals back to the caller.
            raise PermissionError("token rejected") from exc

    @mcp.tool(description="List the knowledge domains the caller may retrieve from.")
    def list_domains(ctx: Context) -> list[str]:
        return service.list_domains(identity(ctx))

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
            "Propose a new document (write scope required). Lands as a reviewable "
            "change, never a live write. The target domain must be one you may write."
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

    return mcp


def _load_service() -> BrainService:
    """Assemble a service from the environment for a real run.

    Everything model-facing is env-selected so the same container runs the
    offline fakes or the in-tenancy Vertex path: BRAIN_EMBEDDINGS (fake|vertex),
    BRAIN_SYNTH (extractive|gemini), and the proposal gate (memory|git|gcs).
    Auth and its audience are read by get_verifier from BRAIN_AUTH*.
    """
    from ..config import policy_source
    from ..embeddings import get_embeddings
    from ..retrieval import BrainIndex, get_synthesiser
    from .proposals import get_gate

    index_path = os.environ.get("BRAIN_INDEX", ".brain/index.json")
    # BRAIN_POLICY may point at a gs:// object so grants take effect without a
    # rebuild; unset falls back to the profile's policy file baked in the image.
    source = policy_source(os.environ.get("BRAIN_POLICY"))
    return BrainService(
        None,
        get_embeddings(),
        source(),
        gate=get_gate(),
        synthesiser=get_synthesiser(),
        policy_source=source,
        # Lazy: the container starts before the index exists; loaded on first query.
        index_loader=lambda: BrainIndex.load(index_path),
    )


def main() -> int:
    from ..auth import get_verifier
    from ..observability import configure

    # Turn on tracing if BRAIN_OTEL is set (gcp in production; a no-op otherwise).
    configure()
    server = build_server(_load_service(), get_verifier())
    # Streamable HTTP is the transport the ADK agent and MCP clients connect over.
    server.settings.host = os.environ.get("HOST", "0.0.0.0")  # nosec B104
    server.settings.port = int(os.environ.get("PORT", "8080"))
    server.run(transport="streamable-http")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
