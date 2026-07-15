"""A thin JSON REST facade over BrainService, for the browser UI.

The deployed Brain Explorer is a public landing page plus a signed-in app. Once a
visitor completes the OAuth PKCE flow against the in-tenancy AS, the SPA calls these
endpoints with the bearer token; every one verifies the token into an ``Identity``
and delegates to ``BrainService``, so the exact same domain isolation, write scope
and review checks apply as over MCP. This exists only to spare the browser from
speaking the MCP wire protocol; it adds no authority of its own.

Routes are registered on the same FastMCP Starlette app (``custom_route``); CORS for
the UI origin is wired in ``server.main`` when ``BRAIN_CORS_ORIGINS`` is set.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from ..auth import TokenError, TokenVerifier
from ..genai_retry import QUOTA_MESSAGE, is_quota_error
from ..models import Answer, SearchResult
from .service import AccessError, BrainService, DocumentNotFound, RateLimitError


def _result(result: SearchResult) -> dict:
    return {
        "doc_id": result.doc_id,
        "domain": result.domain,
        "title": result.title,
        "heading": result.heading,
        "text": result.text,
        "score": result.score,
        "via": result.via,
    }


def _answer(result: Answer) -> dict:
    return {
        "text": result.text,
        "citations": [_result(c) for c in result.citations],
        "gaps": list(result.gaps),
        "used_domains": list(result.used_domains),
    }


def register_rest_routes(mcp, service: BrainService, verifier: TokenVerifier) -> None:
    def identity_of(request: Request):
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise PermissionError("missing bearer token")
        return verifier.verify(header.split(" ", 1)[1].strip())

    def authed(handler):
        """Verify the token, map service errors to HTTP status codes."""

        async def wrapper(request: Request) -> JSONResponse:
            try:
                identity = identity_of(request)
            except (PermissionError, TokenError):
                return JSONResponse({"error": "authentication required"}, status_code=401)
            try:
                return await handler(request, identity)
            except DocumentNotFound:
                return JSONResponse({"error": "not found"}, status_code=404)
            except RateLimitError as exc:
                return JSONResponse({"error": str(exc)}, status_code=429)
            except AccessError as exc:
                return JSONResponse({"error": str(exc)}, status_code=403)
            except (ValueError, KeyError) as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            except Exception as exc:
                # A Gemini quota exhaustion (429) that survived the model's backoff is a
                # busy-demo condition, not a bug: surface it clearly with a 429 and a
                # "quota" flag the UI styles as a degraded-experience notice.
                if is_quota_error(exc):
                    return JSONResponse({"error": QUOTA_MESSAGE, "quota": True}, status_code=429)
                raise

        return wrapper

    def route(path, methods, handler):
        mcp.custom_route(path, methods=methods)(authed(handler))

    async def me(request, identity):
        return JSONResponse(service.my_spaces(identity))

    async def domains(request, identity):
        return JSONResponse({"domains": service.list_domains(identity)})

    async def documents(request, identity):
        return JSONResponse({"documents": service.visible_documents(identity)})

    async def search(request, identity):
        data = await request.json()
        top_k = int(data.get("top_k", 5))
        results = service.search(identity, str(data.get("query", "")), top_k=top_k)
        return JSONResponse({"results": [_result(r) for r in results]})

    async def answer(request, identity):
        data = await request.json()
        top_k = int(data.get("top_k", 5))
        result = service.answer(identity, str(data.get("query", "")), top_k=top_k)
        return JSONResponse(_answer(result))

    async def document(request, identity):
        doc_id = request.query_params.get("doc_id", "")
        return JSONResponse(service.get_document(identity, doc_id))

    async def note(request, identity):
        data = await request.json()
        tags = data.get("tags")
        result = service.add_note(
            identity,
            title=str(data.get("title", "")),
            content=str(data.get("content", "")),
            source_url=data.get("source_url"),
            tags=[str(t) for t in tags] if isinstance(tags, list) else None,
        )
        return JSONResponse({"status": result.status, "detail": result.detail})

    async def draft(request, identity):
        data = await request.json()
        result = service.make_draft(
            identity,
            kind=str(data.get("kind", "")),
            url=data.get("url"),
            text=data.get("text"),
            filename=data.get("filename"),
            content_base64=data.get("content_base64"),
            repo=data.get("repo"),
            ref=data.get("ref"),
            curate=bool(data.get("curate", True)),
        )
        return JSONResponse(result)

    async def edit(request, identity):
        data = await request.json()
        tags = data.get("tags")
        result = service.edit_document(
            identity,
            str(data["doc_id"]),
            content=str(data.get("content", "")),
            title=data.get("title"),
            tags=[str(t) for t in tags] if isinstance(tags, list) else None,
        )
        return JSONResponse(result)

    async def delete(request, identity):
        data = await request.json()
        return JSONResponse(service.delete_document(identity, str(data["doc_id"])))

    async def report(request, identity):
        data = await request.json()
        return JSONResponse(
            service.report_document(
                identity, str(data["doc_id"]), reason=str(data.get("reason", ""))
            )
        )

    async def reports(request, identity):
        return JSONResponse({"reports": service.reports_for_moderator(identity)})

    async def resolve_report(request, identity):
        data = await request.json()
        return JSONResponse(
            service.resolve_report(
                identity, str(data["doc_id"]), remove=bool(data.get("remove", False))
            )
        )

    async def simplify(request, identity):
        data = await request.json()
        return JSONResponse(service.simplify_text(identity, str(data.get("text", ""))))

    async def propose(request, identity):
        data = await request.json()
        result = service.propose_document(
            identity,
            domain=str(data["domain"]),
            title=str(data.get("title", "")),
            content=str(data.get("content", "")),
            source_url=data.get("source_url"),
            doc_type=str(data.get("type") or "Note"),
        )
        return JSONResponse({"status": result.status, "path": result.path, "detail": result.detail})

    async def create_document(request, identity):
        # Direct live write into a domain the caller may write (personal, or a team
        # domain they hold a write grant on). No review; the grant is the trust.
        data = await request.json()
        tags = data.get("tags")
        result = service.add_document(
            identity,
            domain=str(data["domain"]),
            title=str(data.get("title", "")),
            content=str(data.get("content", "")),
            source_url=data.get("source_url"),
            tags=[str(t) for t in tags] if isinstance(tags, list) else None,
            doc_type=str(data.get("type") or "Note"),
        )
        return JSONResponse({"status": result.status, "detail": result.detail})

    async def export_bundle(request, identity):
        from starlette.responses import Response

        domain = request.query_params.get("domain") or None
        data = service.export_bundle(identity, domain=domain)
        name = f"{domain or 'hyper-brain'}-okf-bundle.zip"
        return Response(
            data,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    async def upload(request, identity):
        data = await request.json()
        result = service.ingest_file(
            identity,
            filename=str(data["filename"]),
            content_base64=str(data["content_base64"]),
            domain=data.get("domain"),
            title=data.get("title"),
        )
        return JSONResponse({"status": result.status, "path": result.path, "detail": result.detail})

    async def share(request, identity):
        data = await request.json()
        return JSONResponse(
            service.share(
                identity,
                principal=str(data["principal"]),
                domain=data.get("domain"),
                doc_id=data.get("doc_id"),
                write=bool(data.get("write", False)),
            )
        )

    async def unshare(request, identity):
        data = await request.json()
        removed = service.unshare(
            identity,
            principal=str(data["principal"]),
            domain=data.get("domain"),
            doc_id=data.get("doc_id"),
        )
        return JSONResponse({"removed": removed})

    async def shares(request, identity):
        return JSONResponse(service.list_shares(identity))

    async def proposals(request, identity):
        return JSONResponse({"proposals": service.list_proposals(identity)})

    async def accept(request, identity):
        data = await request.json()
        return JSONResponse(service.accept_proposal(identity, str(data["name"])))

    async def link_suggestions(request, identity):
        return JSONResponse({"suggestions": service.suggest_note_links(identity)})

    async def link(request, identity):
        data = await request.json()
        source = str(data.get("source", "")).strip()
        target = str(data.get("target", "")).strip()
        if not source or not target:
            return JSONResponse({"error": "source and target are required"}, status_code=400)
        return JSONResponse(service.link_notes(identity, source, target))

    async def link_suggest_for(request, identity):
        data = await request.json()
        suggestions = service.suggest_links_for_text(
            identity, str(data.get("text", "")), domain=data.get("domain")
        )
        return JSONResponse({"suggestions": suggestions})

    async def agent_run(request, identity):
        # Run the real multi-agent ADK team, scoped to this caller, and return the
        # execution trace (for the Agents-page animation) plus the final answer.
        from .agent_run import run_agent_async

        data = await request.json()
        query = str(data.get("query", "")).strip()
        if not query:
            return JSONResponse({"error": "a query is required"}, status_code=400)
        session_id = str(data.get("session") or "") or None
        result = await run_agent_async(service, identity, query, session_id=session_id)
        return JSONResponse(result)

    async def agent_stream(request, identity):
        # Same real run, but streamed: each tool call/transfer is emitted as an SSE
        # frame the instant it fires, so the Agents page lights edges as they happen.
        from starlette.responses import StreamingResponse

        from .agent_run import stream_agent_run

        data = await request.json()
        query = str(data.get("query", "")).strip()
        if not query:
            return JSONResponse({"error": "a query is required"}, status_code=400)
        # A prior session id continues the conversation (short-term memory).
        session_id = str(data.get("session") or "") or None
        return StreamingResponse(
            stream_agent_run(service, identity, query, session_id=session_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def studio_agents(request, identity):
        # The registered custom specialists + whether this caller may edit them + the tool
        # palette (drives the Agent Studio panel and the Agents-map custom nodes).
        return JSONResponse(service.list_custom_agents(identity))

    async def studio_agent_save(request, identity):
        data = await request.json()
        return JSONResponse(service.save_custom_agent(identity, data))

    async def studio_agent_delete(request, identity):
        data = await request.json()
        return JSONResponse(service.delete_custom_agent(identity, str(data["name"])))

    async def studio_agent_preview(request, identity):
        # Admin-gated (composing/previewing shared agents needs moderator access), then run the
        # one-off agent against a sample question. Delegated to agent_run (ADK stays out of the
        # offline service).
        service._require_studio_admin(identity)
        from .agent_run import preview_custom_agent

        data = await request.json()
        question = str(data.get("question", "")).strip() or "What can you help me with?"
        result = await preview_custom_agent(service, identity, data.get("spec") or {}, question)
        return JSONResponse(result)

    async def registry_list(request, identity):
        # The agents + MCP-server skills catalogued in the official GCP Agent Registry (our
        # Services show here beside auto-registered Google agents + our Agent Engine). Read-only.
        import asyncio

        from ..agent.registry import enabled, list_registered, list_skills

        agents = await asyncio.to_thread(list_registered)
        skills = await asyncio.to_thread(list_skills)
        return JSONResponse({"agents": agents, "skills": skills, "enabled": enabled()})

    async def eval_rubrics(request, identity):
        # Adaptive-rubric assessment of an answer (in-region, ~2 Gemini calls), for the eval
        # workbench: generate the criteria for the query, critique the answer against them.
        import asyncio

        from ..eval.rubrics import evaluate_answer

        data = await request.json()
        query = str(data.get("query", "")).strip()
        answer = str(data.get("answer", "")).strip()
        if not query or not answer:
            return JSONResponse({"error": "a query and an answer are required"}, status_code=400)
        result = await asyncio.to_thread(evaluate_answer, service, identity, query, answer)
        return JSONResponse(result)

    async def memory_list(request, identity):
        # The caller's OWN long-term memories (scoped to their verified subject), for the
        # "what the brain remembers about you" panel. Empty for guests / when unconfigured.
        import asyncio

        from .memory import enabled, list_memories

        memories = await asyncio.to_thread(list_memories, identity)
        return JSONResponse({"memories": memories, "enabled": enabled()})

    route("/api/me", ["GET"], me)
    route("/api/domains", ["GET"], domains)
    route("/api/documents", ["GET"], documents)
    route("/api/search", ["POST"], search)
    route("/api/answer", ["POST"], answer)
    route("/api/document", ["GET"], document)
    route("/api/note", ["POST"], note)
    route("/api/draft", ["POST"], draft)
    route("/api/simplify", ["POST"], simplify)
    route("/api/propose", ["POST"], propose)
    route("/api/create", ["POST"], create_document)
    route("/api/edit", ["POST"], edit)
    route("/api/delete", ["POST"], delete)
    route("/api/report", ["POST"], report)
    route("/api/reports", ["GET"], reports)
    route("/api/report/resolve", ["POST"], resolve_report)
    route("/api/upload", ["POST"], upload)
    route("/api/export", ["GET"], export_bundle)
    route("/api/share", ["POST"], share)
    route("/api/unshare", ["POST"], unshare)
    route("/api/shares", ["GET"], shares)
    route("/api/proposals", ["GET"], proposals)
    route("/api/accept", ["POST"], accept)
    route("/api/agent/run", ["POST"], agent_run)
    route("/api/agent/stream", ["POST"], agent_stream)
    route("/api/memory", ["GET"], memory_list)
    route("/api/studio/agents", ["GET"], studio_agents)
    route("/api/studio/agents", ["POST"], studio_agent_save)
    route("/api/studio/agents/delete", ["POST"], studio_agent_delete)
    route("/api/studio/agents/preview", ["POST"], studio_agent_preview)
    route("/api/eval/rubrics", ["POST"], eval_rubrics)
    route("/api/registry", ["GET"], registry_list)
    route("/api/link/suggestions", ["GET"], link_suggestions)
    route("/api/link/suggest-for", ["POST"], link_suggest_for)
    route("/api/link", ["POST"], link)
