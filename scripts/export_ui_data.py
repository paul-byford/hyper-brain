"""Export the data the Brain Explorer SPA renders: the index artefact and the
policy (for the identity/isolation panel).

The UI holds no secrets and enforces nothing (ARCHITECTURE.md section 9): it
renders this data. In a live deployment the same artefacts come from the brain /
the index bucket; here they are exported locally so the SPA runs with no cloud.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from brain_app.config import load_policy
from brain_app.embeddings.fake import FakeEmbeddings
from brain_app.indexer.build import build_index
from brain_app.inventory import models as inventory_models
from brain_app.prompts import get_prompt

_REPO_ROOT = Path(__file__).resolve().parents[1]

# The live agent team, mapped to the Agents-page node ids. Each agent is built from a
# versioned prompt (brain_app.prompts) and a registered model (config/models.yaml); the
# UI reads this to show the inventory and let a user open any agent's exact prompt.
_AGENT_MODEL = "gemini-2.5-flash"
_AGENTS = [
    {
        "id": "coord",
        "name": "Coordinator",
        "prompt": "coordinator",
        "role": "Routes each request to exactly one specialist; holds no knowledge tools.",
        "tools": ["transfer_to_agent"],
    },
    {
        "id": "research",
        "name": "Researcher",
        "prompt": "researcher",
        "role": "Answers questions from the governed brain, grounded and cited.",
        "tools": ["search", "answer", "get_document", "list_domains"],
    },
    {
        "id": "curate",
        "name": "Curator",
        "prompt": "curator",
        "role": "Drafts and proposes documents into writable team domains (to review).",
        "tools": ["search", "get_document", "propose_document"],
    },
]


def _agents_manifest() -> dict:
    """Agents (with full prompt text + version + hash) and the model inventory."""
    registered = inventory_models()
    by_id = {m.get("id"): m for m in registered}
    agents = []
    for a in _AGENTS:
        p = get_prompt(a["prompt"])
        agents.append(
            {
                "id": a["id"],
                "name": a["name"],
                "role": a["role"],
                "tools": a["tools"],
                "model": _AGENT_MODEL,
                "model_detail": by_id.get(_AGENT_MODEL, {}),
                "prompt": {"name": p.name, "version": p.version, "sha": p.sha, "text": p.text},
            }
        )
    return {"agents": agents, "models": registered, "evals": _evals_manifest()}


# The agent evals live in brain_app/agent/evals as ADK EvalSets; the UI reads their
# thresholds, case counts and sample questions to showcase the eval tier.
_EVALS_DIR = _REPO_ROOT / "app" / "brain_app" / "agent" / "evals"
_EVAL_SUITES = [
    {
        "file": "golden.evalset.json",
        "name": "Golden",
        "about": "A finserv-scoped caller asks in-domain questions; the agent searches and answers from finserv-ai-engineering.",
        "asserts": "Correct tool trajectory, and the answer matches the finserv reference.",
    },
    {
        "file": "isolation.evalset.json",
        "name": "Isolation · domain boundary",
        "boundary": True,
        "about": "The same finserv-scoped caller asks a recruitment question. The agent must still only surface finserv material.",
        "asserts": "Any leak of enterprise-ai-recruitment content fails the build. The boundary is asserted by the suite, not just prose.",
    },
]


def _eval_questions(evalset: dict) -> list[str]:
    """The user questions across an ADK EvalSet's cases (for a sample display)."""
    out = []
    for case in evalset.get("eval_cases", []):
        for turn in case.get("conversation", []):
            for part in (turn.get("user_content") or {}).get("parts", []):
                if part.get("text"):
                    out.append(part["text"])
    return out


def _evals_manifest() -> dict:
    """The offline eval tier: framework, thresholds and the evalset suites."""
    config_path = _EVALS_DIR / "test_config.json"
    criteria = {}
    if config_path.is_file():
        criteria = json.loads(config_path.read_text(encoding="utf-8")).get("criteria", {})
    about = {
        "tool_trajectory_avg_score": "The agent must call the right tool with the right arguments.",
        "response_match_score": "ROUGE overlap of the final answer against the reference.",
    }
    metrics = [
        {"metric": k, "threshold": v, "about": about.get(k, "")} for k, v in criteria.items()
    ]
    suites = []
    for s in _EVAL_SUITES:
        path = _EVALS_DIR / s["file"]
        questions = _eval_questions(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else []
        suites.append(
            {
                "name": s["name"],
                "boundary": s.get("boundary", False),
                "about": s["about"],
                "asserts": s["asserts"],
                "cases": len(questions),
                "samples": questions,
            }
        )
    return {
        "framework": "Google ADK AgentEvaluator",
        "tier": "Offline and free: a deterministic FakeBrainModel with the brain tools bound in-process, run in CI on every pull request.",
        "metrics": metrics,
        "suites": suites,
        "paid_tier": ["final_response_match_v2", "hallucinations_v1", "safety_v1"],
    }


def export(
    index_path: str,
    corpus: str,
    profile: str,
    out_dir: str,
    mcp_url: str = "",
    auth_url: str = "",
    api_url: str = "",
) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Index: reuse a prebuilt artefact if present, else build one offline.
    src = Path(index_path)
    if src.is_file():
        shutil.copyfile(src, out / "index.json")
    else:
        build_index(corpus, embeddings=FakeEmbeddings(), provider_name="fake").save(
            out / "index.json"
        )

    # Policy: the identity panel needs principals -> domains to show isolation.
    policy = load_policy(prof=profile)
    payload = {
        "profile": profile,
        "version": policy.version,
        "domains": list(policy.domains),
        "grants": [
            {"principal": g.principal, "domains": list(g.domains)}
            for g in policy.grants
        ],
    }
    (out / "policy.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # Config the SPA needs but that isn't in the index: the deployed MCP endpoint
    # (connector modal), and for the live app the OAuth issuer + REST base it signs in
    # against and calls. Empty in local runs, so the UI stays in demo mode there.
    config = {
        "mcp_url": mcp_url or "https://<your-brain>.run.app/mcp",
        "auth_url": auth_url,  # OAuth AS issuer, for browser sign-in (PKCE)
        "api_url": api_url,  # brain REST facade base; live mode when set
    }
    (out / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    # Agents manifest: model inventory + versioned prompts, for the Agents page.
    (out / "agents.json").write_text(
        json.dumps(_agents_manifest(), indent=2), encoding="utf-8"
    )

    print(
        f"Exported UI data to {out}/ (index.json, policy.json, config.json, agents.json)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export data for the Brain Explorer UI."
    )
    parser.add_argument("--index", default=".brain/index.json")
    parser.add_argument("--corpus", default="corpus")
    parser.add_argument("--profile", default="personal")
    parser.add_argument("--out", default="ui/data")
    parser.add_argument(
        "--mcp-url",
        default="",
        help="Deployed brain MCP endpoint for the connector modal.",
    )
    parser.add_argument(
        "--auth-url", default="", help="OAuth AS issuer URL for browser sign-in."
    )
    parser.add_argument(
        "--api-url", default="", help="Brain REST facade base URL (enables live mode)."
    )
    args = parser.parse_args(argv)
    export(
        args.index,
        args.corpus,
        args.profile,
        args.out,
        args.mcp_url,
        args.auth_url,
        args.api_url,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
