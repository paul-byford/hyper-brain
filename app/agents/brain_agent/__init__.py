"""ADK entry point for ``adk web`` / ``adk api_server``.

``adk web`` lists every sub-directory of its target as an app, so pointing it at the
whole ``brain_app`` package shows a confusing list of non-agent packages. This tiny
dedicated agents directory exposes exactly one app, ``brain_agent``, re-exporting the
real agent from ``brain_app.agent`` (offline or live per ``BRAIN_AGENT_MODE``).
"""

from __future__ import annotations

from brain_app.agent import agent, root_agent

__all__ = ["agent", "root_agent"]
