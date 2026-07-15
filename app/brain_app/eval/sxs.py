"""Auto SxS: a pairwise "which version ships" eval over the brain's grounded answers.

A **candidate** is ``{label, model, instruction}`` -- so two candidates can differ on the
answer-synthesis **prompt**, the **model**, or both. For a small set of real queries we retrieve
the same domain-scoped context, have each candidate compose a grounded answer, then Google's
**GenAI Evaluation Service** (a managed pairwise autorater) judges which answer is better per
query on BOTH *groundedness* and *question-answering quality*, and we report the win rate. This
is the "which prompt/model ships" gate, complementing the offline correctness/isolation evals.

The autorater runs on Vertex; the eval region prefers the configured location and falls back to
``us-central1`` (the widely-supported region) if that location isn't supported for the service.
Best-effort and quota-aware: a busy-quota run returns a clear error rather than raising.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# The two managed pairwise judgments.
METRICS = ("pairwise_groundedness", "pairwise_question_answering_quality")
_METRIC_LABEL = {
    "pairwise_groundedness": "groundedness",
    "pairwise_question_answering_quality": "qa quality",
}
# The Vertex GenAI Evaluation Service is us-central1-only -- both pairwise and rubric metrics
# 400 ("Unsupported region") elsewhere, so the autorater always runs there (cross-region, the
# same trade-off the Code Interpreter makes), regardless of the brain's in-region location.
_EVAL_LOCATION = "us-central1"

# A neutral baseline synthesis instruction; a candidate may override it to A/B a prompt change.
DEFAULT_INSTRUCTION = (
    "You are the hyper-brain researcher. Answer the question using ONLY the provided sources. "
    "Cite the sources you use by title. If the sources do not cover the question, say so plainly "
    "rather than guessing."
)

# A candidate variant prompt, so the CLI does a meaningful A/B out of the box (baseline vs this).
CONCISE_INSTRUCTION = (
    "You are the hyper-brain researcher. Answer the question in 2-3 tight sentences, grounded "
    "STRICTLY in the provided sources and citing each source title you draw on. Never speculate "
    "beyond the sources; if they fall short, say exactly what is missing."
)

_PROMPT_PRESETS = {"default": DEFAULT_INSTRUCTION, "concise": CONCISE_INSTRUCTION}


@dataclass
class Candidate:
    label: str
    model: str
    instruction: str = DEFAULT_INSTRUCTION


@dataclass
class SxSResult:
    a_label: str
    b_label: str
    metrics: dict = field(default_factory=dict)  # metric -> {a_wins,b_wins,ties,win_rate_b}
    rows: list = field(default_factory=list)  # per query: {query, answer_a, answer_b, verdicts}
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "a_label": self.a_label,
            "b_label": self.b_label,
            "metrics": self.metrics,
            "rows": self.rows,
            "error": self.error,
        }


def load_queries(limit: int = 5) -> list[str]:
    """Reuse the golden eval set's questions as the SxS query set (deduped, capped)."""
    import json
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[1] / "agent" / "evals" / "golden.evalset.json"
    out: list[str] = []
    with contextlib_suppress():
        data = json.loads(path.read_text(encoding="utf-8"))
        for case in data.get("eval_cases", []):
            for inv in case.get("conversation", []):
                text = (((inv.get("user_content") or {}).get("parts") or [{}])[0]).get("text", "")
                text = (text or "").strip()
                if text and "?" in text and text not in out:
                    out.append(text)
    return out[:limit]


def contextlib_suppress():
    import contextlib

    return contextlib.suppress(Exception)


def _project_location() -> tuple[str | None, str]:
    return (
        os.environ.get("GOOGLE_CLOUD_PROJECT"),
        os.environ.get("GOOGLE_CLOUD_LOCATION", "europe-west2"),
    )


def _client(location: str):
    from google import genai

    from ..genai_retry import http_options

    project, _ = _project_location()
    return genai.Client(
        vertexai=True, project=project, location=location, http_options=http_options()
    )


def _context(service, identity, query: str) -> str:
    """The same domain-scoped retrieval both candidates are grounded against + judged on."""
    hits = service.search(identity, query, top_k=5)
    return "\n\n".join(f"[{h.title}] {h.text}" for h in hits) or "(no sources found)"


def _answer(client, model: str, instruction: str, query: str, context: str) -> str:
    from google.genai import types

    resp = client.models.generate_content(
        model=model,
        contents=f"Question: {query}\n\nSources:\n{context}",
        config=types.GenerateContentConfig(system_instruction=instruction, temperature=0.2),
    )
    return (getattr(resp, "text", "") or "").strip()


def _win_counts(metrics_table, metric: str) -> dict:
    """Tally the autorater's per-row pairwise choice into A/B wins + ties."""
    col = f"{metric}/pairwise_choice"
    a_wins = b_wins = ties = 0
    choices = list(metrics_table[col]) if col in getattr(metrics_table, "columns", []) else []
    for choice in choices:
        c = str(choice).upper()
        if "BASELINE" in c:
            a_wins += 1
        elif "CANDIDATE" in c:
            b_wins += 1
        else:
            ties += 1
    total = a_wins + b_wins + ties or 1
    return {
        "a_wins": a_wins,
        "b_wins": b_wins,
        "ties": ties,
        "win_rate_b": round(b_wins / total, 2),
    }


def run_sxs(service, identity, a: Candidate, b: Candidate, queries: list[str]) -> SxSResult:
    """Generate both candidates' grounded answers for each query, then judge them pairwise on
    groundedness + QA quality. ``response`` is candidate B, ``baseline_model_response`` is A, so
    a ``CANDIDATE`` win is a win for B."""
    from ..genai_retry import QUOTA_MESSAGE, is_quota_error

    result = SxSResult(a_label=a.label, b_label=b.label)
    project, location = _project_location()
    try:
        client = _client(location)
        rows = []
        for q in queries:
            context = _context(service, identity, q)
            ans_a = _answer(client, a.model, a.instruction, q, context)
            ans_b = _answer(client, b.model, b.instruction, q, context)
            rows.append(
                {
                    "prompt": q,
                    "context": context,
                    "baseline_model_response": ans_a,
                    "response": ans_b,
                }
            )
        table = _evaluate(rows, project, location)
        for metric in METRICS:
            result.metrics[_METRIC_LABEL[metric]] = _win_counts(table, metric)
        result.rows = [
            {
                "query": r["prompt"],
                "answer_a": r["baseline_model_response"],
                "answer_b": r["response"],
                "verdicts": {
                    _METRIC_LABEL[m]: str(_cell(table, i, f"{m}/pairwise_choice")) for m in METRICS
                },
            }
            for i, r in enumerate(rows)
        ]
    except Exception as exc:  # noqa: BLE001 - the eval must surface, not crash the caller
        result.error = QUOTA_MESSAGE if is_quota_error(exc) else f"eval failed: {exc}"
    return result


def _cell(table, i, col):
    try:
        return table[col].iloc[i]
    except Exception:
        return "?"


def _evaluate(rows: list[dict], project: str | None, location: str):
    """Run the managed pairwise autorater (us-central1, cross-region). Returns the per-row
    metrics table."""
    import pandas as pd

    return _run_eval_task(pd.DataFrame(rows), project)


def _run_eval_task(dataset, project: str | None):
    import vertexai
    from vertexai.evaluation import EvalTask, MetricPromptTemplateExamples, PairwiseMetric

    vertexai.init(project=project, location=_EVAL_LOCATION)
    metrics = [
        PairwiseMetric(
            metric=name,
            metric_prompt_template=MetricPromptTemplateExamples.get_prompt_template(name),
        )
        for name in METRICS
    ]
    task = EvalTask(dataset=dataset, metrics=metrics)
    return task.evaluate().metrics_table


# ---- CLI: `brain eval sxs` -- the "which prompt/model ships" A/B gate -------------------
def _build_service():
    """A local BrainService over the corpus, for a CLI eval run (real retrieval + Gemini)."""
    from ..config import load_policy
    from ..embeddings import get_embeddings
    from ..indexer.build import build_index
    from ..serving import BrainService

    corpus = os.environ.get("BRAIN_CORPUS", "corpus")
    embeddings = get_embeddings()
    index = build_index(corpus, embeddings=embeddings)
    policy = load_policy(prof=os.environ.get("BRAIN_PROFILE", "personal"))
    return BrainService(index, embeddings, policy)


def _eval_identity():
    """A local reviewer-grade identity (reads the team + commons domains) for the eval run."""
    from ..auth import Identity

    return Identity(
        subject="sxs-eval",
        email="sxs-eval@local",
        principals=("group:brain-admins@example.com",),
        scopes=frozenset({"read"}),
        claims={},
    )


def _candidate(flag: str, model: str, prompt: str) -> Candidate:
    instruction = _PROMPT_PRESETS.get(prompt, prompt)  # a preset name, or literal prompt text
    return Candidate(label=f"{flag} ({model}, {prompt})", model=model, instruction=instruction)


def main(argv: list[str] | None = None) -> int:
    """Run the pairwise SxS gate and print the verdict. Two candidates differ on model and/or
    the synthesis prompt (a preset name -- default/concise -- or literal text)."""
    import argparse

    default_model = os.environ.get("BRAIN_AGENT_MODEL", "gemini-2.5-flash")
    ap = argparse.ArgumentParser(description="Pairwise 'which prompt/model ships' SxS eval.")
    ap.add_argument("--a-model", default=default_model)
    ap.add_argument("--b-model", default=default_model)
    ap.add_argument("--a-prompt", default="default", help="preset (default/concise) or text")
    ap.add_argument("--b-prompt", default="concise", help="preset (default/concise) or text")
    ap.add_argument("--limit", type=int, default=5, help="number of golden queries to judge")
    args = ap.parse_args(argv)

    a = _candidate("A", args.a_model, args.a_prompt)
    b = _candidate("B", args.b_model, args.b_prompt)
    queries = load_queries(args.limit)
    print(f"Auto SxS: A={a.label!r}  vs  B={b.label!r}  over {len(queries)} queries\n")
    result = run_sxs(_build_service(), _eval_identity(), a, b, queries)
    if result.error:
        print(f"eval error: {result.error}")
        return 1
    for metric, tally in result.metrics.items():
        rate = int(round(tally["win_rate_b"] * 100))
        print(
            f"  {metric:12} -> B wins {tally['b_wins']}, A wins {tally['a_wins']}, "
            f"ties {tally['ties']}  (B win rate {rate}%)"
        )
    b_total = sum(m["b_wins"] for m in result.metrics.values())
    a_total = sum(m["a_wins"] for m in result.metrics.values())
    verdict = "SHIP B" if b_total > a_total else "KEEP A" if a_total > b_total else "TOO CLOSE"
    print(f"\n  Verdict: {verdict}  (B {b_total} vs A {a_total} across both metrics)")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
