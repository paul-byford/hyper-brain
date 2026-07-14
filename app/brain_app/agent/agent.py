"""The hyper-brain ADK agent.

In **live** mode this is a multi-agent team (ARCHITECTURE.md section 8): a
``coordinator`` ``LlmAgent`` that delegates to two sub-agents over ADK's agent
transfer:

- **researcher** - answers questions using the brain's read tools (search, answer,
  get_document, list_domains);
- **curator** - drafts and *proposes* new documents (propose_document), grounded in
  existing material, landing them in the human review queue, never live.

Every tool is the brain's own, attached over MCP streamable HTTP with the caller's
OIDC token as a bearer and ``tool_filter`` limited to each role's tools; the brain
enforces the domain ACL, so the whole team is automatically scoped to what the
caller may see (and write).

In **offline** mode (default; CI and the hermetic eval tier) it is the single
deterministic researcher, backed by ``FakeBrainModel`` and the in-process tools, so
the golden and isolation evals run free with no cloud. ``root_agent`` is what
``adk web`` and the eval harness discover; set ``BRAIN_AGENT_MODE=live`` for the
real multi-agent team.
"""

from __future__ import annotations

import os

from google.adk.agents import LlmAgent

from ..prompts import prompt
from . import tools

# The brain tool names each role is limited to (the live MCP toolset is filtered to
# exactly these; the brain still enforces read/write access behind them).
RESEARCH_TOOLS = ["search", "answer", "get_document", "list_domains"]
CURATE_TOOLS = ["search", "get_document", "propose_document"]


def _brain_token(audience: str) -> str:
    """The bearer the agent presents to the IAM-gated brain.

    An explicit ``BRAIN_TOKEN`` wins (handy for local dev). Otherwise mint a Google
    ID token for the brain's audience from the Cloud Run metadata server / ADC, so
    the agent calls the brain service-to-service as its own service account.
    """
    explicit = os.environ.get("BRAIN_TOKEN")
    if explicit:
        return explicit
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token

    return id_token.fetch_id_token(Request(), audience)


def _live_toolset(tool_filter: list[str]):
    from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
    from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset

    url = os.environ.get("BRAIN_URL", "http://localhost:8080/mcp")
    # The token audience must match what the brain verifies (its own service URL).
    audience = os.environ.get("BRAIN_AUDIENCE") or url.rsplit("/mcp", 1)[0]
    return MCPToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=url,
            headers={"Authorization": f"Bearer {_brain_token(audience)}"},
        ),
        tool_filter=tool_filter,
    )


def _live_team() -> LlmAgent:
    # The analyst runs its Python in a server-side Google sandbox (managed Vertex Code
    # Interpreter when configured, else Gemini's built-in in-region sandbox). It carries no
    # brain tools, so the sandbox stays isolated from the corpus.
    from .code_executor import code_executor
    from .model import agent_model

    # Global Gemini endpoint + shared retry, one instance shared across the team.
    model = agent_model(os.environ.get("BRAIN_AGENT_MODEL", "gemini-2.5-flash"))
    # Each specialist is a leaf: it disallows transfer, so once the coordinator delegates the
    # specialist does its work and its reply ends the run. That makes the coordinator a single-
    # hop router and removes the sub-agent -> coordinator -> sub-agent ping-pong that can
    # otherwise loop forever, and it keeps the analyst's built-in code sandbox from colliding
    # with an auto-added transfer tool.
    leaf = {"disallow_transfer_to_parent": True, "disallow_transfer_to_peers": True}
    researcher = LlmAgent(
        name="researcher",
        model=model,
        instruction=prompt("researcher"),
        tools=[_live_toolset(RESEARCH_TOOLS)],
        **leaf,
    )
    curator = LlmAgent(
        name="curator",
        model=model,
        instruction=prompt("curator"),
        tools=[_live_toolset(CURATE_TOOLS)],
        **leaf,
    )
    analyst = LlmAgent(
        name="analyst",
        model=model,
        instruction=prompt("analyst"),
        code_executor=code_executor(),
        **leaf,
    )
    return LlmAgent(
        name="brain_agent",
        model=model,
        instruction=prompt("coordinator"),
        sub_agents=[researcher, curator, analyst],
    )


def _offline_researcher() -> LlmAgent:
    from .fake_model import FakeBrainModel

    return LlmAgent(
        name="brain_agent",
        model=FakeBrainModel(),
        instruction=prompt("researcher"),
        tools=[tools.search, tools.answer, tools.get_document, tools.list_domains],
    )


def build_brain_agent(mode: str | None = None) -> LlmAgent:
    """Build the brain agent for the given mode (defaults to ``BRAIN_AGENT_MODE`` or offline)."""
    mode = mode or os.environ.get("BRAIN_AGENT_MODE", "offline")
    if mode == "live":
        return _live_team()
    if mode == "offline":
        return _offline_researcher()
    raise ValueError(f"unknown agent mode {mode!r} (expected 'offline' or 'live')")


# Discovered by `adk web` and the eval harness.
root_agent = build_brain_agent()
