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
