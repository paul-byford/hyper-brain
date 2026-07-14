"""Pillar 1 (functional): the agent is wired correctly in both modes."""

from __future__ import annotations

import pytest

pytest.importorskip("google.adk")

from google.adk.agents import LlmAgent  # noqa: E402

from brain_app.agent.agent import CURATE_TOOLS, RESEARCH_TOOLS, build_brain_agent  # noqa: E402
from brain_app.agent.fake_model import FakeBrainModel  # noqa: E402


def _tool_name(tool) -> str:
    return getattr(tool, "name", None) or getattr(tool, "__name__", "")


def test_offline_agent_uses_fake_model_and_brain_tools():
    # Offline stays a single deterministic researcher (hermetic evals).
    agent = build_brain_agent("offline")
    assert isinstance(agent, LlmAgent)
    assert isinstance(agent.model, FakeBrainModel)
    assert {_tool_name(t) for t in agent.tools} == {
        "search",
        "answer",
        "get_document",
        "list_domains",
    }


def test_live_agent_is_a_coordinator_delegating_to_three_specialists(monkeypatch):
    monkeypatch.setenv("BRAIN_URL", "http://localhost:8080/mcp")
    monkeypatch.setenv("BRAIN_TOKEN", "test-token")
    from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset

    coordinator = build_brain_agent("live")
    # The coordinator delegates; it holds no tools of its own.
    by_name = {a.name: a for a in coordinator.sub_agents}
    assert set(by_name) == {"researcher", "curator", "analyst"}

    # Each brain-facing sub-agent gets its own MCP toolset, filtered to its role's tools.
    researcher_tools = by_name["researcher"].tools[0]
    curator_tools = by_name["curator"].tools[0]
    assert isinstance(researcher_tools, MCPToolset) and isinstance(curator_tools, MCPToolset)
    assert set(researcher_tools.tool_filter) == set(RESEARCH_TOOLS)
    assert set(curator_tools.tool_filter) == set(CURATE_TOOLS)
    # The curator can propose (write path); the researcher cannot.
    assert "propose_document" in CURATE_TOOLS and "propose_document" not in RESEARCH_TOOLS

    # The analyst has a code sandbox and no brain tools, so it is isolated from the corpus.
    # It also disallows transfer, so its Gemini request carries only the built-in code tool
    # (mixing that with the auto-injected transfer_to_agent is a 400 from Gemini).
    analyst = by_name["analyst"]
    assert analyst.code_executor is not None
    assert not analyst.tools
    assert analyst.disallow_transfer_to_parent and analyst.disallow_transfer_to_peers


def test_unknown_mode_rejected():
    with pytest.raises(ValueError, match="unknown agent mode"):
        build_brain_agent("carrier-pigeon")
