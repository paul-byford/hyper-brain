"""Pillar 3 (AI evals, offline tier): the ADK AgentEvaluator over the golden sets.

Deterministic and free: the agent runs the FakeBrainModel with the brain tools
bound in-process, so tool_trajectory and response_match are reproducible with no
cloud. Skipped cleanly if the [agent] extra (google-adk) is not installed.
"""

from __future__ import annotations

import asyncio
import pathlib

import pytest

pytest.importorskip("google.adk")

from google.adk.evaluation.agent_evaluator import AgentEvaluator  # noqa: E402

EVALS = pathlib.Path(__file__).resolve().parents[1] / "brain_app" / "agent" / "evals"

# The agent module ADK loads (must end in ".agent" and expose root_agent).
AGENT_MODULE = "brain_app.agent.agent"


def _evaluate(dataset: str) -> None:
    asyncio.run(
        AgentEvaluator.evaluate(
            agent_module=AGENT_MODULE,
            eval_dataset_file_path_or_dir=str(EVALS / dataset),
            num_runs=1,
        )
    )


@pytest.mark.eval
def test_golden_evalset_passes():
    _evaluate("golden.evalset.json")


@pytest.mark.eval
def test_isolation_eval_stays_in_domain():
    # A finserv-scoped agent asked a recruitment question must still only surface
    # finserv material; the eval reference names finserv and no other domain.
    _evaluate("isolation.evalset.json")
