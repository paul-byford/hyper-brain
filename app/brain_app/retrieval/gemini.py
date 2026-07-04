"""In-tenancy Gemini synthesis for `answer` mode (the production Synthesiser).

This is the real counterpart to `ExtractiveSynthesiser`: a Gemini model on Vertex,
in the caller's own tenancy and region (the data boundary, ARCHITECTURE.md section
4), grounded strictly on the retrieved, domain-scoped chunks. The honest gap
statement is preserved and computed deterministically, so a model that glosses over
a gap cannot hide it.

Lazy import: google-genai is only needed when this synthesiser actually runs, so
the offline core and its tests never require it. The model call is injectable, so
the prompt construction and answer shaping are testable with no cloud.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from ..models import Answer, SearchResult
from .answer import _missing_terms

INSTRUCTION = (
    "You are the hyper-brain assistant. Answer the question using ONLY the numbered "
    "context below, which comes from the caller's permitted knowledge domains. Cite "
    "the sources you use by their title in square brackets, e.g. [Real-time fraud "
    "detection]. If the context does not support part of the question, say so plainly "
    "rather than guessing. Be concise and grounded."
)

_EMPTY = "I don't have anything on that in the domains you can access."


class GeminiSynthesiser:
    def __init__(
        self,
        *,
        model: str | None = None,
        project: str | None = None,
        location: str | None = None,
        generate: Callable[[str], str] | None = None,
    ) -> None:
        self.model = model or os.environ.get("BRAIN_SYNTH_MODEL", "gemini-2.5-flash")
        self.project = project or os.environ.get("GOOGLE_CLOUD_PROJECT")
        self.location = location or os.environ.get("GOOGLE_CLOUD_LOCATION", "europe-west2")
        # Injectable model call (str prompt -> str answer). Real one is lazy.
        self._generate = generate

    def _call(self, prompt: str) -> str:
        if self._generate is not None:
            return self._generate(prompt)
        from google import genai

        client = genai.Client(vertexai=True, project=self.project, location=self.location)
        response = client.models.generate_content(model=self.model, contents=prompt)
        return response.text or ""

    @staticmethod
    def build_prompt(query: str, results: list[SearchResult]) -> str:
        context = "\n\n".join(
            f"[{i + 1}] {r.title} - {r.heading}\n{r.text}" for i, r in enumerate(results[:5])
        )
        return f"{INSTRUCTION}\n\nQuestion: {query}\n\nContext:\n{context}\n\nAnswer:"

    def synthesise(self, query: str, results: list[SearchResult]) -> Answer:
        if not results:
            return Answer(
                text=_EMPTY,
                citations=[],
                gaps=[query.strip()] if query.strip() else [],
                used_domains=[],
            )
        text = self._call(self.build_prompt(query, results)).strip()
        return Answer(
            text=text or _EMPTY,
            citations=results,
            # The gap statement stays deterministic: the model cannot bury a gap.
            gaps=_missing_terms(query, results),
            used_domains=sorted({r.domain for r in results}),
        )
