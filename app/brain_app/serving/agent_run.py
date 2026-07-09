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
_AGENT_ID = {"researcher": "research", "curator": "curate", "brain_agent": "coord"}


def _agent_id(author: str) -> str:
    return _AGENT_ID.get(author or "", "research")


def _steps_for_call(author: str, name: str, args: dict) -> list[dict]:
    """Animation steps for one real tool call by one agent."""
    if name == "transfer_to_agent":
        target = _AGENT_ID.get(str((args or {}).get("agent_name", "")), "research")
        who = "researcher" if target == "research" else "curator"
        return [{"edge": ["coord", target], "caption": f"Coordinator delegated to the {who}"}]
    who = _agent_id(author)
    label = {"research": "Researcher", "curate": "Curator"}.get(who, "Agent")
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


def build_trace(query: str, calls: list[tuple], answer: str, final_author: str) -> dict:
    """Assemble the animation trace from the real (author, tool, args) calls."""
    steps = [{"edge": ["you", "coord"], "caption": f"You asked: “{query.strip()[:80]}”"}]
    for author, name, args in calls:
        steps.extend(_steps_for_call(author, name, args))
    dest = _agent_id(final_author)
    label = {"research": "Researcher", "curate": "Curator"}.get(dest, "Agent")
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

    tools = _bound_tools(service, identity)
    researcher = LlmAgent(
        name="researcher", model=model, instruction=prompt("researcher"), tools=tools["researcher"]
    )
    curator = LlmAgent(
        name="curator", model=model, instruction=prompt("curator"), tools=tools["curator"]
    )
    return LlmAgent(
        name="brain_agent",
        model=model,
        instruction=prompt("coordinator"),
        sub_agents=[researcher, curator],
    )


async def run_agent_async(
    service: BrainService, identity: Identity, query: str, model: str | None = None
) -> dict:
    """Run the team and return {steps, answer}. Async so the REST handler can await it."""
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    model = model or os.environ.get("BRAIN_AGENT_MODEL", "gemini-2.5-flash")
    user = identity.subject or "user"
    team = _build_team(service, identity, model)
    runner = InMemoryRunner(agent=team, app_name="brain")
    session = await runner.session_service.create_session(app_name="brain", user_id=user)

    calls: list[tuple] = []
    answer = ""
    final_author = "researcher"
    async for event in runner.run_async(
        user_id=user,
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text=query)]),
    ):
        author = getattr(event, "author", "") or ""
        for part in (event.content.parts if event.content else []) or []:
            call = getattr(part, "function_call", None)
            if call is not None:
                calls.append((author, call.name, dict(call.args or {})))
            if getattr(part, "text", None) and event.is_final_response():
                answer = part.text
                final_author = author
    return build_trace(query, calls, answer, final_author)


def run_agent(
    service: BrainService, identity: Identity, query: str, model: str | None = None
) -> dict:
    """Sync wrapper (for a CLI or tests) around :func:`run_agent_async`."""
    import asyncio

    return asyncio.run(run_agent_async(service, identity, query, model))


def _sse(obj: dict) -> str:
    """One Server-Sent Events frame carrying a JSON payload."""
    import json

    return f"data: {json.dumps(obj)}\n\n"


async def stream_agent_run(service: BrainService, identity: Identity, query: str, model=None):
    """Yield SSE frames as the real ADK run fires, so the UI lights each edge live.

    Emits ``{"step": {...}}`` per tool call/transfer as it happens, then a final
    ``{"done": true, "answer": ...}`` (or ``{"error": ...}`` if the run fails).
    """
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    model = model or os.environ.get("BRAIN_AGENT_MODEL", "gemini-2.5-flash")
    user = identity.subject or "user"
    asked = f"You asked: “{query.strip()[:80]}”"
    yield _sse({"step": {"edge": ["you", "coord"], "caption": asked}})

    final_author = "researcher"
    answer = ""
    try:
        team = _build_team(service, identity, model)
        runner = InMemoryRunner(agent=team, app_name="brain")
        session = await runner.session_service.create_session(app_name="brain", user_id=user)
        async for event in runner.run_async(
            user_id=user,
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=query)]),
        ):
            author = getattr(event, "author", "") or ""
            for part in (event.content.parts if event.content else []) or []:
                call = getattr(part, "function_call", None)
                if call is not None:
                    for step in _steps_for_call(author, call.name, dict(call.args or {})):
                        yield _sse({"step": step})
                if getattr(part, "text", None) and event.is_final_response():
                    answer = part.text
                    final_author = author
    except Exception as exc:  # a run failure becomes a clean terminal frame, not a hang
        yield _sse({"error": str(exc)})
        return

    dest = _agent_id(final_author)
    label = {"research": "Researcher", "curate": "Curator"}.get(dest, "Agent")
    yield _sse({"step": {"edge": [dest, "you"], "caption": f"{label} responded to you"}})
    yield _sse({"done": True, "answer": answer})
