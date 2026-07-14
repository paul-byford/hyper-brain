"""Run the multi-agent ADK team in-process, scoped to the caller (for the live UI).

The Agents page can trigger a real run. This builds the same coordinator/researcher/
curator team (real Gemini on Vertex, the versioned prompts), but binds each tool to
the *caller's* ``Identity`` and calls ``BrainService`` directly. So it is genuinely
scoped to what the caller may see/write, and there is no MCP round-trip to fail. It
returns the real execution trace -- the transfers and tool calls that actually
happened -- mapped to the Agents-page animation, plus the final answer.

google-adk is imported lazily, so it never loads on the brain's normal request path.
"""

from __future__ import annotations

import os

from ..auth import Identity
from ..prompts import prompt
from .service import AccessError, BrainService, DocumentNotFound

# Which animation edges (Agents page node ids) a given agent+tool lights up.
_AGENT_ID = {
    "researcher": "research",
    "curator": "curate",
    "analyst": "analyst",
    "brain_agent": "coord",
}

# Animation steps for one sandbox code run by the analyst (BuiltInCodeExecutor runs the
# Python in Gemini's server-side sandbox). Kept as module constants so the UI mapping is
# unit-testable without a live model.
_CODE_RUN_STEP = {
    "edge": ["analyst", "sandbox"],
    "caption": "Analyst wrote Python and ran it in the sandbox",
}
_CODE_RESULT_STEP = {
    "edge": ["sandbox", "analyst"],
    "caption": "Sandbox returned the computed result",
}


def _agent_id(author: str) -> str:
    return _AGENT_ID.get(author or "", "research")


def _error_frame(exc: Exception) -> dict:
    """A terminal SSE payload for a failed run. A 429 that survives the model's
    backoff-and-jitter retries means the shared Gemini quota is genuinely busy, so we
    flag it as a quota issue (the UI styles it as a degraded-experience notice) rather
    than showing a stack-trace-like message."""
    from ..genai_retry import QUOTA_MESSAGE, is_quota_error

    if is_quota_error(exc):
        return {"error": QUOTA_MESSAGE, "quota": True}
    return {"error": str(exc)}


def _steps_for_call(author: str, name: str, args: dict) -> list[dict]:
    """Animation steps for one real tool call by one agent."""
    if name == "transfer_to_agent":
        target = _AGENT_ID.get(str((args or {}).get("agent_name", "")), "research")
        who = {"research": "researcher", "curate": "curator", "analyst": "analyst"}.get(
            target, "specialist"
        )
        return [{"edge": ["coord", target], "caption": f"Coordinator delegated to the {who}"}]
    who = _agent_id(author)
    label = {"research": "Researcher", "curate": "Curator", "analyst": "Analyst"}.get(who, "Agent")
    if name in ("search", "get_document", "list_domains"):
        steps = [
            {"edge": [who, "brain"], "caption": f"{label} called {name} over the governed brain"}
        ]
        if name != "list_domains":
            steps.append(
                {
                    "edge": ["brain", "corpus"],
                    "caption": "Brain retrieved your domain-scoped chunks",
                }
            )
        return steps
    if name == "answer":
        return [
            {"edge": [who, "brain"], "caption": f"{label} called answer"},
            {"edge": ["brain", "corpus"], "caption": "Brain retrieved your domain-scoped chunks"},
            {"edge": ["brain", "gemini"], "caption": "Gemini composed a grounded, cited answer"},
        ]
    if name == "propose_document":
        return [
            {"edge": [who, "brain"], "caption": f"{label} called propose_document"},
            {
                "edge": ["brain", "review"],
                "caption": "Proposal staged for human review, never live",
            },
        ]
    return [{"edge": [who, "brain"], "caption": f"{label} called {name}"}]


def frames_for_code_part(part, pending: dict) -> list[dict]:
    """SSE payloads for one code-execution part from the analyst.

    ``BuiltInCodeExecutor`` runs the Python in Gemini's server-side sandbox and returns
    an ``executable_code`` part (the code) and a ``code_execution_result`` part (the
    output); they may arrive in one event or two, so ``pending`` carries the code text
    across. Emits the "wrote + ran" step when the code appears, then the "result" step
    plus a ``{"code": ...}`` block (code + output) the UI renders when the sandbox returns.
    """
    out: list[dict] = []
    executable = getattr(part, "executable_code", None)
    if executable is not None:
        pending["code"] = executable.code or ""
        out.append({"step": _CODE_RUN_STEP})
    result = getattr(part, "code_execution_result", None)
    if result is not None:
        ok = str(getattr(result, "outcome", "")).endswith("OK")
        out.append({"step": _CODE_RESULT_STEP})
        out.append(
            {"code": {"code": pending.get("code", ""), "output": result.output or "", "ok": ok}}
        )
        pending["code"] = ""
    return out


def build_trace(query: str, calls: list[tuple], answer: str, final_author: str) -> dict:
    """Assemble the animation trace from the real (author, tool, args) calls."""
    steps = [{"edge": ["you", "coord"], "caption": f"You asked: “{query.strip()[:80]}”"}]
    for author, name, args in calls:
        steps.extend(_steps_for_call(author, name, args))
    dest = _agent_id(final_author)
    label = {"research": "Researcher", "curate": "Curator", "analyst": "Analyst"}.get(dest, "Agent")
    steps.append({"edge": [dest, "you"], "caption": f"{label} responded to you"})
    return {"steps": steps, "answer": answer}


def _bound_tools(service: BrainService, identity: Identity):
    def search(query: str) -> str:
        """Search the brain; returns ranked hits scoped to your domains.

        Args:
            query: the natural-language question to search for.
        """
        hits = service.search(identity, query, top_k=5)
        return "\n".join(f"[{h.domain}] {h.title}: {h.text[:200]}" for h in hits) or "No results."

    def answer(query: str) -> str:
        """Answer a question from the brain, with citations, scoped to your domains.

        Args:
            query: the natural-language question to answer.
        """
        result = service.answer(identity, query)
        cites = ", ".join(c.title for c in result.citations)
        return f"{result.text}\n\nCitations: {cites}" if cites else result.text

    def get_document(doc_id: str) -> str:
        """Fetch one document by id, if it is in a domain you may see.

        Args:
            doc_id: the document id, e.g. finserv-ai-engineering/realtime-fraud-detection.
        """
        try:
            document = service.get_document(identity, doc_id)
        except DocumentNotFound:
            return f"No document '{doc_id}' in your permitted domains."
        return f"# {document['title']}\n\n{document['text'][:1500]}"

    def list_domains() -> str:
        """List the knowledge domains you may retrieve from."""
        return ", ".join(service.list_domains(identity)) or "(none)"

    def propose_document(domain: str, title: str, content: str) -> str:
        """Propose a new document into a TEAM domain you may write (goes to review).

        Args:
            domain: the target team domain.
            title: the document title.
            content: the document body as markdown.
        """
        try:
            result = service.propose_document(identity, domain=domain, title=title, content=content)
        except AccessError as exc:
            return f"Refused: {exc}"
        return f"Proposed into {domain} ({result.status}): {result.detail}"

    return {
        "researcher": [search, answer, get_document, list_domains],
        "curator": [search, get_document, propose_document],
    }


def _build_team(service: BrainService, identity: Identity, model: str):
    from google.adk.agents import LlmAgent

    from ..agent.code_executor import code_executor
    from ..agent.model import agent_model

    tools = _bound_tools(service, identity)
    # One model instance (global endpoint + shared 429/503 retry), shared across the agents.
    llm = agent_model(model)
    # Each specialist is a leaf: it disallows transfer, so once the coordinator delegates the
    # specialist does its work and its reply ends the run. That makes the coordinator a single-
    # hop router and removes the sub-agent -> coordinator -> sub-agent ping-pong that can
    # otherwise loop forever (notably when a reused session replays earlier transfers). It also
    # keeps the analyst's built-in code sandbox from colliding with an auto-added transfer tool.
    leaf = {"disallow_transfer_to_parent": True, "disallow_transfer_to_peers": True}
    researcher = LlmAgent(
        name="researcher",
        model=llm,
        instruction=prompt("researcher"),
        tools=tools["researcher"],
        **leaf,
    )
    curator = LlmAgent(
        name="curator", model=llm, instruction=prompt("curator"), tools=tools["curator"], **leaf
    )
    # The analyst carries no brain tools: only Gemini's server-side code sandbox, kept
    # isolated from the corpus. It computes over figures already in the conversation.
    analyst = LlmAgent(
        name="analyst",
        model=llm,
        instruction=prompt("analyst"),
        code_executor=code_executor(),
        **leaf,
    )
    return LlmAgent(
        name="brain_agent",
        model=llm,
        instruction=prompt("coordinator"),
        sub_agents=[researcher, curator, analyst],
    )


def _guard_answer(text: str) -> str:
    """Redact PII/secrets from the agent's final answer before it reaches the user (the
    coordinator's and analyst's direct replies don't pass through service.answer). No-op when
    Model Armor is unconfigured."""
    from ..safety import model_armor

    return model_armor.scan(text).text


def _input_flags(query: str) -> list[str]:
    """Model Armor flags on the user's query (e.g. prompt-injection) -- surfaced, not blocked;
    the agents' tool-only guardrails already bound what an injected instruction could do."""
    from ..safety import model_armor

    return model_armor.scan(query, kind="prompt").flags


def _run_config():
    """A hard ceiling on model calls, so a pathological delegation loop terminates cleanly
    (a surfaced error) instead of hanging the Agents page at dozens of steps. A normal run is
    a handful of calls; this is generous headroom over that."""
    from google.adk.agents.run_config import RunConfig

    return RunConfig(max_llm_calls=20)


async def _prepare_run(service, identity, query, model, session_id):
    """Build the runner (with Agent Engine Sessions + Memory Bank when configured), reuse or
    create the caller's session, and build the message. Any memories recalled for THIS caller
    (``user_id`` = verified subject) are prepended by the server -- never fetched via a tool,
    so a prompt injection can't reach them and there is no built-in-tool conflict."""
    from google.genai import types

    from . import memory as mem_mod

    user = identity.subject or "user"
    # Persistent Agent Engine sessions + memory only for a signed-in caller when memory is
    # configured; guests and memory-off deployments keep the exact previous stateless path
    # (InMemoryRunner), so nothing about the existing behaviour changes for them.
    mem_svc = None if identity.is_guest else mem_mod.memory_service()
    team = _build_team(service, identity, model)
    if mem_svc is not None:
        from google.adk.artifacts import InMemoryArtifactService
        from google.adk.runners import Runner

        sess_svc = mem_mod.session_service(identity)
        # Match InMemoryRunner's service set (it wires an in-memory artifact service) so the
        # multi-agent flow behaves identically; only sessions + memory become persistent.
        runner = Runner(
            app_name="brain",
            agent=team,
            session_service=sess_svc,
            memory_service=mem_svc,
            artifact_service=InMemoryArtifactService(),
        )
    else:
        from google.adk.runners import InMemoryRunner

        runner = InMemoryRunner(agent=team, app_name="brain")
        sess_svc = runner.session_service
    session = None
    if session_id:  # continue the conversation if a valid, own session id was passed
        try:
            session = await sess_svc.get_session(
                app_name="brain", user_id=user, session_id=session_id
            )
        except Exception:
            session = None
    if session is None:
        session = await sess_svc.create_session(app_name="brain", user_id=user)
    recalled = await mem_mod.recall(mem_svc, identity, query)
    message = types.Content(
        role="user", parts=[types.Part(text=mem_mod.format_recall(recalled) + query)]
    )
    return runner, sess_svc, mem_svc, session, message, user


async def _store_memory(sess_svc, mem_svc, identity, user, session_id):
    """Extract + store durable memories from the finished session (managed, user-scoped)."""
    import contextlib

    from . import memory as mem_mod

    with contextlib.suppress(Exception):  # best-effort: memory never fails a run
        session = await sess_svc.get_session(app_name="brain", user_id=user, session_id=session_id)
        await mem_mod.remember(mem_svc, identity, session)


async def run_agent_async(
    service: BrainService,
    identity: Identity,
    query: str,
    model: str | None = None,
    session_id: str | None = None,
) -> dict:
    """Run the team and return {steps, answer, session}. Async so the REST handler awaits it."""
    model = model or os.environ.get("BRAIN_AGENT_MODEL", "gemini-2.5-flash")
    runner, sess_svc, mem_svc, session, message, user = await _prepare_run(
        service, identity, query, model, session_id
    )

    calls: list[tuple] = []
    code_blocks: list[dict] = []
    pending_code: dict = {}
    answer = ""
    final_author = "researcher"
    async for event in runner.run_async(
        user_id=user, session_id=session.id, new_message=message, run_config=_run_config()
    ):
        author = getattr(event, "author", "") or ""
        for part in (event.content.parts if event.content else []) or []:
            call = getattr(part, "function_call", None)
            if call is not None:
                calls.append((author, call.name, dict(call.args or {})))
            for frame in frames_for_code_part(part, pending_code):
                if "code" in frame:
                    code_blocks.append(frame["code"])
            if getattr(part, "text", None) and event.is_final_response():
                answer = part.text
                final_author = author
    await _store_memory(sess_svc, mem_svc, identity, user, session.id)
    answer = _guard_answer(answer)
    trace = build_trace(query, calls, answer, final_author)
    trace["session"] = session.id
    flags = _input_flags(query)
    if flags:
        trace["guard"] = flags
    if code_blocks:
        trace["code"] = code_blocks[-1]
    return trace


def run_agent(
    service: BrainService,
    identity: Identity,
    query: str,
    model: str | None = None,
    session_id: str | None = None,
) -> dict:
    """Sync wrapper (for a CLI or tests) around :func:`run_agent_async`."""
    import asyncio

    return asyncio.run(run_agent_async(service, identity, query, model, session_id))


def _sse(obj: dict) -> str:
    """One Server-Sent Events frame carrying a JSON payload."""
    import json

    return f"data: {json.dumps(obj)}\n\n"


async def stream_agent_run(
    service: BrainService, identity: Identity, query: str, model=None, session_id=None
):
    """Yield SSE frames as the real ADK run fires, so the UI lights each edge live.

    Emits ``{"session": id}`` (so the UI can continue the conversation), ``{"step": {...}}``
    per tool call/transfer, an optional ``{"code": {...}}`` sandbox block, then a final
    ``{"done": true, "answer": ...}`` (or ``{"error": ...}`` if the run fails).
    """
    model = model or os.environ.get("BRAIN_AGENT_MODEL", "gemini-2.5-flash")
    asked = f"You asked: “{query.strip()[:80]}”"
    yield _sse({"step": {"edge": ["you", "coord"], "caption": asked}})

    final_author = "researcher"
    answer = ""
    pending_code: dict = {}
    try:
        runner, sess_svc, mem_svc, session, message, user = await _prepare_run(
            service, identity, query, model, session_id
        )
        yield _sse({"session": session.id})  # so a follow-up can continue this conversation
        async for event in runner.run_async(
            user_id=user, session_id=session.id, new_message=message, run_config=_run_config()
        ):
            author = getattr(event, "author", "") or ""
            for part in (event.content.parts if event.content else []) or []:
                call = getattr(part, "function_call", None)
                if call is not None:
                    for step in _steps_for_call(author, call.name, dict(call.args or {})):
                        yield _sse({"step": step})
                for frame in frames_for_code_part(part, pending_code):
                    yield _sse(frame)
                if getattr(part, "text", None) and event.is_final_response():
                    answer = part.text
                    final_author = author
        await _store_memory(sess_svc, mem_svc, identity, user, session.id)
    except Exception as exc:  # a run failure becomes a clean terminal frame, not a hang
        yield _sse(_error_frame(exc))
        return

    dest = _agent_id(final_author)
    label = {"research": "Researcher", "curate": "Curator", "analyst": "Analyst"}.get(dest, "Agent")
    yield _sse({"step": {"edge": [dest, "you"], "caption": f"{label} responded to you"}})
    done = {"done": True, "answer": _guard_answer(answer)}
    flags = _input_flags(query)
    if flags:
        done["guard"] = flags  # e.g. prompt-injection in the question: surfaced, not blocked
    yield _sse(done)
