"""Pillar 1 (functional): the agent is wired correctly in both modes."""

from __future__ import annotations

import pytest

pytest.importorskip("google.adk")

from google.adk.agents import LlmAgent  # noqa: E402

from brain_app.agent.agent import BRAIN_TOOLS, build_brain_agent  # noqa: E402
from brain_app.agent.fake_model import FakeBrainModel  # noqa: E402


def _tool_name(tool) -> str:
    return getattr(tool, "name", None) or getattr(tool, "__name__", "")


def test_offline_agent_uses_fake_model_and_brain_tools():
    agent = build_brain_agent("offline")
    assert isinstance(agent, LlmAgent)
    assert isinstance(agent.model, FakeBrainModel)
    assert {_tool_name(t) for t in agent.tools} == {
        "search",
        "answer",
        "get_document",
        "list_domains",
    }


def test_live_agent_wires_mcp_toolset_filtered_to_brain_tools(monkeypatch):
    monkeypatch.setenv("BRAIN_URL", "http://localhost:8080/mcp")
    monkeypatch.setenv("BRAIN_TOKEN", "test-token")
    from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset

    agent = build_brain_agent("live")
    assert len(agent.tools) == 1
    toolset = agent.tools[0]
    assert isinstance(toolset, MCPToolset)
    assert set(toolset.tool_filter) == set(BRAIN_TOOLS)


def test_unknown_mode_rejected():
    with pytest.raises(ValueError, match="unknown agent mode"):
        build_brain_agent("carrier-pigeon")
