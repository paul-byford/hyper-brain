"""The hyper-brain ADK agent package.

``agent.root_agent`` is the entry point ``adk web`` and the eval harness load. See
agent.py for the offline (deterministic, free) and live (Gemini + MCP) wirings.
"""

from __future__ import annotations

# Expose the `agent` submodule and `root_agent` as package members so both
# `adk web` and `adk eval` (which look for a member named `agent` carrying
# `root_agent`) can discover the agent from the package path.
from . import agent
from .agent import root_agent

__all__ = ["agent", "root_agent"]
