"""The live agent-run trace mapping: real (author, tool) calls -> animation steps.

The run itself needs Gemini, but the mapping from ADK events to the Agents-page edges
is pure and load-bearing (a wrong edge would mislead the animation), so it is tested
here with synthetic calls.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from brain_app.serving.agent_run import _sse, _steps_for_call, build_trace, stream_agent_run


def test_transfer_maps_to_the_coordinator_edge():
    to_research = _steps_for_call("brain_agent", "transfer_to_agent", {"agent_name": "researcher"})
    to_curate = _steps_for_call("brain_agent", "transfer_to_agent", {"agent_name": "curator"})
    assert to_research[0]["edge"] == ["coord", "research"]
    assert to_curate[0]["edge"] == ["coord", "curate"]


def test_transfer_to_analyst_maps_to_its_edge():
    steps = _steps_for_call("brain_agent", "transfer_to_agent", {"agent_name": "analyst"})
    assert steps[0]["edge"] == ["coord", "analyst"]


def test_code_run_then_result_map_to_the_sandbox_edges_and_block():
    types = pytest.importorskip("google.genai").types
    from brain_app.serving.agent_run import frames_for_code_part

    pending: dict = {}
    run = frames_for_code_part(
        types.Part(executable_code=types.ExecutableCode(code="print(2+2)", language="PYTHON")),
        pending,
    )
    assert run[0]["step"]["edge"] == ["analyst", "sandbox"]
    assert pending["code"] == "print(2+2)"  # code stashed for pairing with the result

    result = frames_for_code_part(
        types.Part(
            code_execution_result=types.CodeExecutionResult(outcome="OUTCOME_OK", output="4\n")
        ),
        pending,
    )
    edges = [f["step"]["edge"] for f in result if "step" in f]
    blocks = [f["code"] for f in result if "code" in f]
    assert ["sandbox", "analyst"] in edges
    assert blocks and blocks[0] == {"code": "print(2+2)", "output": "4\n", "ok": True}


def test_code_result_flags_a_failed_outcome():
    types = pytest.importorskip("google.genai").types
    from brain_app.serving.agent_run import frames_for_code_part

    frames = frames_for_code_part(
        types.Part(
            code_execution_result=types.CodeExecutionResult(outcome="OUTCOME_FAILED", output="Boom")
        ),
        {},
    )
    block = next(f["code"] for f in frames if "code" in f)
    assert block["ok"] is False


def test_live_team_has_an_analyst_with_an_isolated_code_sandbox():
    # The UI's live run builds the team in-process (no MCP token needed), so this checks
    # the team the caller actually gets: a third specialist that computes in a sandbox.
    pytest.importorskip("google.adk")
    from brain_app.serving.agent_run import _build_team

    class _Identity:
        subject = "sub-1"

    team = _build_team(None, _Identity(), "gemini-2.5-flash")
    analysts = [a for a in team.sub_agents if a.name == "analyst"]
    assert analysts, "the live team should include an analyst sub-agent"
    analyst = analysts[0]
    assert analyst.code_executor is not None  # it computes in a sandbox
    assert not analyst.tools  # and carries no brain tools (isolated from the corpus)
    # Gemini rejects the built-in code tool alongside any function tool, so the analyst
    # must disallow the auto-injected transfer_to_agent (carry only the sandbox).
    assert analyst.disallow_transfer_to_parent and analyst.disallow_transfer_to_peers


def test_code_executor_selects_managed_sandbox_when_configured(monkeypatch):
    # Default (env unset) -> Gemini's in-region built-in sandbox. With
    # BRAIN_CODE_INTERPRETER set -> the managed Vertex Code Interpreter (us-central1).
    pytest.importorskip("google.adk")
    import google.adk.code_executors as ce
    from google.adk.code_executors import BuiltInCodeExecutor

    from brain_app.agent.code_executor import code_executor

    monkeypatch.delenv("BRAIN_CODE_INTERPRETER", raising=False)
    assert isinstance(code_executor(), BuiltInCodeExecutor)

    # A real VertexAiCodeExecutor calls the extension API on construction, so stub it to
    # just record the resource name it was pointed at.
    captured: dict = {}

    class _FakeVertex:
        def __init__(self, resource_name=None):
            captured["resource_name"] = resource_name

    monkeypatch.setattr(ce, "VertexAiCodeExecutor", _FakeVertex)
    resource = "projects/p/locations/us-central1/extensions/123"
    monkeypatch.setenv("BRAIN_CODE_INTERPRETER", resource)
    assert isinstance(code_executor(), _FakeVertex)
    assert captured["resource_name"] == resource


def test_search_lights_brain_then_corpus():
    edges = [s["edge"] for s in _steps_for_call("researcher", "search", {})]
    assert edges == [["research", "brain"], ["brain", "corpus"]]


def test_answer_reaches_gemini():
    edges = [s["edge"] for s in _steps_for_call("researcher", "answer", {})]
    assert ["brain", "gemini"] in edges


def test_propose_reaches_the_review_queue():
    edges = [s["edge"] for s in _steps_for_call("curator", "propose_document", {})]
    assert ["curate", "brain"] in edges and ["brain", "review"] in edges


def test_build_trace_frames_the_whole_flow():
    calls = [
        ("brain_agent", "transfer_to_agent", {"agent_name": "researcher"}),
        ("researcher", "answer", {}),
    ]
    trace = build_trace(
        "how do we detect fraud?", calls, "Fresh features catch fraud.", "researcher"
    )
    edges = [s["edge"] for s in trace["steps"]]
    assert edges[0] == ["you", "coord"]  # starts with the caller
    assert ["coord", "research"] in edges  # the delegation
    assert edges[-1] == ["research", "you"]  # the researcher answers the caller
    assert trace["answer"] == "Fresh features catch fraud."


def test_sse_frame_is_a_json_data_line():
    frame = _sse({"step": {"edge": ["you", "coord"], "caption": "hi"}})
    assert frame.startswith("data: ") and frame.endswith("\n\n")
    assert json.loads(frame[6:].strip())["step"]["edge"] == ["you", "coord"]


def test_stream_opens_with_the_caller_edge_before_any_run():
    # The first SSE frame is emitted before the ADK run starts, so the animation
    # reacts instantly. It must not touch the service.
    pytest.importorskip("google.adk")

    class _Identity:
        subject = "sub-1"

    async def _first_frame():
        stream = stream_agent_run(None, _Identity(), "how do we detect fraud?")
        frame = await stream.__anext__()
        await stream.aclose()
        return frame

    frame = asyncio.run(_first_frame())
    assert json.loads(frame[6:].strip())["step"]["edge"] == ["you", "coord"]
