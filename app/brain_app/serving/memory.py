"""User-scoped long-term memory (Vertex AI Agent Engine **Memory Bank**) and persistent
**Sessions**, kept in-region in europe-west2.

Isolation by design
-------------------
Every read and write is scoped to ``user_id = identity.subject`` — the verified token
subject, derived **server-side**. There is no parameter for "whose memory", so a caller can
never reach another user's memories, and the agents are never given a memory-fetch tool
(recall is injected into the run by the server, so a prompt injection can't exfiltrate it).
**Guests** (ephemeral ``guest:<hex>`` identities) get no persistence at all.

Enabled only when ``BRAIN_AGENT_ENGINE`` names a provisioned Agent Engine instance (see
``scripts/provision_agent_engine.py``); otherwise sessions stay in-memory and no memory is
stored or recalled — the agent run behaves exactly as it did before.

adk / vertex are imported lazily so this module stays cheap to import on the brain's normal
request path.
"""

from __future__ import annotations

import contextlib
import os

from ..auth import Identity

_APP = "brain"


def agent_engine_id() -> str | None:
    """The reasoning-engine id from ``BRAIN_AGENT_ENGINE`` (a full resource name), or None."""
    resource = os.environ.get("BRAIN_AGENT_ENGINE", "").strip()
    return resource.rsplit("/", 1)[-1] if resource else None


def enabled() -> bool:
    return agent_engine_id() is not None


def _project_location() -> tuple[str | None, str]:
    return (
        os.environ.get("GOOGLE_CLOUD_PROJECT"),
        os.environ.get("GOOGLE_CLOUD_LOCATION", "europe-west2"),
    )


def session_service(identity: Identity | None = None):
    """Agent Engine Sessions when configured, else in-memory. Guests always get in-memory
    (their ``guest:<hex>`` identity is ephemeral, so nothing about them is persisted)."""
    eid = agent_engine_id()
    if eid is None or (identity is not None and identity.is_guest):
        from google.adk.sessions import InMemorySessionService

        return InMemorySessionService()
    from google.adk.sessions import VertexAiSessionService

    project, location = _project_location()
    return VertexAiSessionService(project=project, location=location, agent_engine_id=eid)


def memory_service():
    """Agent Engine Memory Bank when configured, else None (no long-term memory)."""
    eid = agent_engine_id()
    if eid is None:
        return None
    from google.adk.memory import VertexAiMemoryBankService

    project, location = _project_location()
    return VertexAiMemoryBankService(project=project, location=location, agent_engine_id=eid)


def _texts(search_response) -> list[str]:
    """The text of each returned MemoryEntry (``entry.content.parts[*].text``)."""
    out: list[str] = []
    for entry in getattr(search_response, "memories", []) or []:
        content = getattr(entry, "content", None)
        if content is not None:
            text = " ".join(
                p.text for p in (content.parts or []) if getattr(p, "text", None)
            ).strip()
            if text:
                out.append(text)
    return out


async def recall(mem, identity: Identity, query: str, top_k: int = 5) -> list[str]:
    """Memories relevant to ``query`` for THIS caller only (``user_id`` = verified subject).

    Empty for guests, unconfigured deployments, or on any error — memory is best-effort and
    must never fail a run.
    """
    if mem is None or identity.is_guest:
        return []
    try:
        resp = await mem.search_memory(app_name=_APP, user_id=identity.subject, query=query)
    except Exception:
        return []
    return _texts(resp)[:top_k]


async def remember(mem, identity: Identity, session) -> None:
    """Extract + store durable memories from a finished session, scoped to the caller.

    Managed extraction (Memory Bank decides what is durable); best-effort, never raises,
    skipped for guests.

    We drive Memory Bank's ``generate`` from the session **awaited to completion** rather than
    ADK's ``add_session_to_memory``: that fires the store as a fire-and-forget background task
    ("without blocking"), which Cloud Run's post-response CPU throttling kills before it ever
    runs — so nothing is stored. Generating in-request keeps the store on allocated CPU.
    """
    resource = os.environ.get("BRAIN_AGENT_ENGINE", "").strip()
    session_id = getattr(session, "id", None)
    if mem is None or identity.is_guest or not resource or not session_id:
        return
    with contextlib.suppress(Exception):  # best-effort: never fail a run over memory
        import asyncio

        import vertexai

        project, location = _project_location()
        client = vertexai.Client(project=project, location=location)
        await asyncio.to_thread(
            client.agent_engines.memories.generate,
            name=resource,
            vertex_session_source={"session": f"{resource}/sessions/{session_id}"},
            scope={"app_name": _APP, "user_id": identity.subject},
            config={"wait_for_completion": True},
        )


def format_recall(memories: list[str]) -> str:
    """The recalled memories as a preamble the server prepends to the run (not a tool)."""
    if not memories:
        return ""
    lines = "\n".join(f"- {m}" for m in memories)
    return (
        "What you already know about this user from earlier sessions (use only if it helps "
        f"answer, and do not repeat it verbatim unless asked):\n{lines}\n\n"
    )


def list_memories(identity: Identity, top_k: int = 25) -> list[str]:
    """The caller's OWN memories, for the "what the brain remembers about you" panel.

    A true list (not a relevance search, which could miss items), scoped to the verified
    subject by a **server-side filter** AND a **client-side check** (defense in depth), so it
    can never surface another user's memory. Empty for guests / unconfigured / on any error.
    """
    resource = os.environ.get("BRAIN_AGENT_ENGINE", "").strip()
    if not resource or identity.is_guest:
        return []
    out: list[str] = []
    with contextlib.suppress(Exception):
        import vertexai

        project, location = _project_location()
        client = vertexai.Client(project=project, location=location)
        subject = identity.subject
        for m in client.agent_engines.memories.list(
            name=resource, config={"filter": f'scope.user_id="{subject}"'}
        ):
            scope = getattr(m, "scope", None) or {}
            uid = (
                scope.get("user_id")
                if isinstance(scope, dict)
                else getattr(scope, "user_id", None)
            )
            if uid != subject:  # defense in depth: never return another user's memory
                continue
            fact = (getattr(m, "fact", None) or "").strip()
            if fact:
                out.append(fact)
            if len(out) >= top_k:
                break
    return out
