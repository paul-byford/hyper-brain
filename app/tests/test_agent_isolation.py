"""Pillar 2/3 (security): the agent never surfaces content across the domain boundary.

Unlike the ROUGE eval, this asserts directly on the agent's real tool outputs: a
domain-scoped agent's search results must contain no chunk from a domain the caller
may not see. The boundary is enforced by the brain service the tools call, so this
proves the agent inherits it (ARCHITECTURE.md section 7).
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("google.adk")

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from brain_app.agent import agent as agent_mod  # noqa: E402
from brain_app.agent import tools  # noqa: E402

from .conftest import FINSERV, RECRUITMENT  # noqa: E402


async def _run(query: str) -> tuple[str, str]:
    agent = agent_mod.build_brain_agent("offline")
    runner = InMemoryRunner(agent=agent, app_name="brain")
    session = await runner.session_service.create_session(app_name="brain", user_id="u")
    tool_output = ""
    final = ""
    async for event in runner.run_async(
        user_id="u",
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text=query)]),
    ):
        for part in (event.content.parts if event.content else []) or []:
            response = getattr(part, "function_response", None)
            if response is not None:
                tool_output += str(response.response)
            if getattr(part, "text", None) and event.is_final_response():
                final = part.text
    return tool_output, final


@pytest.fixture(autouse=True)
def _reset_caches():
    tools.reset_caches()
    yield
    tools.reset_caches()


def test_finserv_agent_never_surfaces_recruitment(monkeypatch):
    monkeypatch.setenv("BRAIN_AGENT_GROUPS", "finserv-eng@example.com")
    tools.reset_caches()
    tool_output, final = asyncio.run(
        _run("interview copilots and candidate sourcing and hiring bias for recruiters")
    )
    assert RECRUITMENT not in tool_output
    assert RECRUITMENT not in final
    # It still retrieved, just from its own domain.
    assert FINSERV in tool_output


def test_recruiter_agent_never_surfaces_finserv(monkeypatch):
    monkeypatch.setenv("BRAIN_AGENT_GROUPS", "recruiting@example.com")
    tools.reset_caches()
    tool_output, final = asyncio.run(
        _run("real-time fraud detection, trade surveillance and model risk")
    )
    assert FINSERV not in tool_output
    assert RECRUITMENT in tool_output
