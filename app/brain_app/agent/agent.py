"""The hyper-brain ADK agent.

An ADK ``LlmAgent`` whose tools are the brain's tools, in two interchangeable
wirings behind one builder (ARCHITECTURE.md section 8):

- **live** (production/demo): a Gemini model on Vertex, tools attached over MCP
  streamable HTTP with the caller's OIDC token as a bearer, ``tool_filter`` limited
  to the brain's tools. The brain enforces the domain ACL, so the agent is
  automatically scoped to what the caller may see.
- **offline** (default; CI and evals): a deterministic ``FakeBrainModel`` and the
  same tool surface bound in-process, so the whole agent runs free with no cloud.

``root_agent`` is what ``adk web`` and the eval harness discover. It is offline by
default so the golden and isolation evals are hermetic; set ``BRAIN_AGENT_MODE=live``
(with a brain URL, a bearer token and Vertex creds) for the real thing.
"""

from __future__ import annotations

import os

from google.adk.agents import LlmAgent

from . import tools

# The brain's tool names, used to constrain the live MCP toolset to exactly these.
BRAIN_TOOLS = ["search", "answer", "get_document", "list_domains", "propose_document"]

INSTRUCTION = (
    "You are the hyper-brain assistant. Answer questions using ONLY the brain's "
    "tools (search, answer, get_document). Always call a tool before answering; "
    "never answer from your own memory. You can only see the caller's permitted "
    "domains, so if the tools return nothing relevant, say so honestly rather than "
    "guessing, and never claim knowledge the tools did not return. Cite the "
    "documents you used."
)


def _live_toolset():
    from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
    from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset

    url = os.environ.get("BRAIN_URL", "http://localhost:8080/mcp")
    token = os.environ.get("BRAIN_TOKEN", "")
    return MCPToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=url,
            headers={"Authorization": f"Bearer {token}"},
        ),
        # Restrict the agent to exactly the brain's tools, nothing else.
        tool_filter=BRAIN_TOOLS,
    )


def build_brain_agent(mode: str | None = None) -> LlmAgent:
    """Build the brain agent in the given mode (defaults to ``BRAIN_AGENT_MODE`` or offline)."""
    mode = mode or os.environ.get("BRAIN_AGENT_MODE", "offline")
    if mode == "live":
        model = os.environ.get("BRAIN_AGENT_MODEL", "gemini-2.5-flash")
        return LlmAgent(
            name="brain_agent",
            model=model,
            instruction=INSTRUCTION,
            tools=[_live_toolset()],
        )
    if mode == "offline":
        from .fake_model import FakeBrainModel

        return LlmAgent(
            name="brain_agent",
            model=FakeBrainModel(),
            instruction=INSTRUCTION,
            tools=[tools.search, tools.answer, tools.get_document, tools.list_domains],
        )
    raise ValueError(f"unknown agent mode {mode!r} (expected 'offline' or 'live')")


# Discovered by `adk web` and the eval harness.
root_agent = build_brain_agent()
