"""In-region adaptive rubrics: generate assessment criteria per query, then critique the answer.

This mirrors the platform's ``RubricGenerationConfig`` + ``RubricBasedMetric`` approach -- the
autorater first **generates rubrics** (the yes/no criteria a good grounded answer must satisfy),
then **critiques** the answer against each, yielding per-rubric **verdicts** and a score. The
managed metric is us-central1-only and slow (many calls per row), so for the live workbench we
run the same idea in **two in-region Gemini calls**; the managed metric itself is exercised by
the ``brain eval`` CLI (:mod:`.managed`). Best-effort + quota-aware: errors surface, never raise.
"""

from __future__ import annotations

import json
import os
import re

_GEN_INSTRUCTION = (
    "You are an evaluation-rubric generator. Given a user QUESTION and the SOURCES available to "
    "answer it, produce 4-7 concise yes/no assessment criteria that a good, grounded answer must "
    "satisfy -- covering the key facts in the sources, citing them, and inventing nothing beyond "
    "the sources. Return ONLY a JSON array of short strings (each a yes/no criterion)."
)
_CRITIQUE_INSTRUCTION = (
    "You are a strict answer evaluator. For each rubric criterion, decide whether the ANSWER "
    "satisfies it, judging only against the SOURCES and the QUESTION. Return ONLY a JSON array of "
    'objects: {"rubric": <criterion>, "met": true|false, "reason": <one short sentence>}.'
)


def _client():
    from google import genai

    from ..genai_retry import http_options

    return genai.Client(
        vertexai=True,
        project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "europe-west2"),
        http_options=http_options(),
    )


def _json_array(text: str):
    match = re.search(r"\[.*\]", text or "", re.S)
    return json.loads(match.group(0)) if match else []


def _generate(client, model: str, query: str, context: str) -> list[str]:
    from google.genai import types

    resp = client.models.generate_content(
        model=model,
        contents=f"QUESTION: {query}\n\nSOURCES:\n{context}",
        config=types.GenerateContentConfig(system_instruction=_GEN_INSTRUCTION, temperature=0.2),
    )
    return [str(r).strip() for r in _json_array(getattr(resp, "text", "")) if str(r).strip()][:7]


def _critique(client, model: str, query: str, answer: str, context: str, rubrics: list[str]):
    from google.genai import types

    listed = "\n".join(f"- {r}" for r in rubrics)
    contents = (
        f"QUESTION: {query}\n\nSOURCES:\n{context}\n\nANSWER:\n{answer}\n\nRUBRICS:\n{listed}"
    )
    resp = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=_CRITIQUE_INSTRUCTION, temperature=0.0
        ),
    )
    out = []
    for obj in _json_array(getattr(resp, "text", "")):
        if isinstance(obj, dict) and str(obj.get("rubric", "")).strip():
            out.append(
                {
                    "rubric": str(obj["rubric"]).strip(),
                    "met": bool(obj.get("met")),
                    "reason": str(obj.get("reason", "")).strip(),
                }
            )
    return out


def evaluate_answer(
    service, identity, query: str, answer: str, *, model: str | None = None
) -> dict:
    """Adaptive-rubric assessment of one answer: generate criteria for the query, critique the
    answer against them, return ``{rubrics, verdicts, score, met, total}``. In-region, ~2 calls."""
    from ..genai_retry import QUOTA_MESSAGE, is_quota_error

    model = model or os.environ.get("BRAIN_AGENT_MODEL", "gemini-2.5-flash")
    try:
        hits = service.search(identity, query, top_k=5)
        context = "\n\n".join(f"[{h.title}] {h.text}" for h in hits) or "(no sources found)"
        client = _client()
        rubrics = _generate(client, model, query, context)
        verdicts = _critique(client, model, query, answer, context, rubrics)
        met = sum(1 for v in verdicts if v["met"])
        total = len(verdicts)
        return {
            "rubrics": rubrics,
            "verdicts": verdicts,
            "met": met,
            "total": total,
            "score": round(met / total, 2) if total else 0.0,
        }
    except Exception as exc:  # noqa: BLE001 - the eval surfaces, never crashes the run
        return {
            "error": QUOTA_MESSAGE if is_quota_error(exc) else f"eval failed: {exc}",
            "rubrics": [],
            "verdicts": [],
        }
