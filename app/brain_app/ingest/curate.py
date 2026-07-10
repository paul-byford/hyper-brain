"""Optional raw-to-wiki curation, behind an interface.

Karpathy's idea: drop a messy source, get a clean, well-structured page. In
production this is a Gemini pass that runs in-tenancy (ARCHITECTURE.md section
12), rewriting raw text into tidy markdown with suggested ``[[wikilinks]]``. It is
optional because it costs model calls and, more importantly, because an LLM
rewriting a source can introduce errors, which is why every curated document
still passes through the review gate.

Offline, a deterministic ``PassthroughCurator`` stands in: it does no rewriting,
so tests stay free and reproducible. The real Gemini curator is wired in a later
cloud phase behind this same interface, exactly like the Vertex embeddings seam.
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

from .models import ParsedDoc


@runtime_checkable
class Curator(Protocol):
    def curate(self, doc: ParsedDoc, known_titles: list[str] | None = None) -> ParsedDoc: ...

    def rewrite(self, text: str, instruction: str) -> str: ...


class PassthroughCurator:
    """Deterministic no-op: the document is landed as parsed."""

    def curate(self, doc: ParsedDoc, known_titles: list[str] | None = None) -> ParsedDoc:
        return doc

    def rewrite(self, text: str, instruction: str) -> str:
        return text


def get_curator(name: str | None = None) -> Curator:
    """Return the configured curator. Defaults to the offline passthrough.

    Selected by ``BRAIN_CURATE`` (``off`` by default). ``gemini`` is wired in a
    later cloud phase; naming it before then fails loudly rather than silently
    doing nothing.
    """
    name = name or os.environ.get("BRAIN_CURATE", "off")
    if name in ("off", "passthrough", "fake"):
        return PassthroughCurator()
    if name == "gemini":
        return GeminiCurator()
    raise ValueError(f"unknown curator {name!r}")


_CURATE_INSTRUCTION = (
    "Turn the following source text into a clear, well-structured markdown note that is "
    "easy to read and reference. Requirements:\n"
    "- Start with a single '# ' H1 title that names the topic.\n"
    "- Add a short '## Summary' near the top: 2-4 sentences or a few bullet points "
    "capturing the key takeaways.\n"
    "- Organise the body with '## ' (and '### ') section headings, short paragraphs, and "
    "bullet or numbered lists for enumerations and steps.\n"
    "- If the source is long, condense it faithfully into well-organised sections and key "
    "points rather than reproducing it verbatim; keep the important facts.\n"
    "- Do NOT invent anything that is not supported by the source.\n"
    "- Where the text refers to another likely document or concept, mark it with "
    "[[wikilink]] syntax.\n"
    "- If there are notable terms or concepts worth defining, add a '## Key terms' "
    "section with a short bullet-point glossary (term: one-line definition).\n"
    "- On the very last line, output 'Tags:' followed by 3 to 6 short, lowercase, "
    "comma-separated topic tags.\n"
    "Return only the markdown followed by that single Tags line, no other commentary."
)


class GeminiCurator:
    """In-tenancy Gemini curation (Karpathy's raw-to-wiki): rewrite messy source
    text into clean markdown with suggested links. Lazy google-genai import; the
    model call is injectable so the transform is testable with no cloud. Output is
    still provenance-stamped and passes the review gate, because an LLM rewrite can
    introduce errors (ARCHITECTURE.md section 12)."""

    def __init__(
        self,
        *,
        model: str | None = None,
        project: str | None = None,
        location: str | None = None,
        generate=None,
    ) -> None:
        self.model = model or os.environ.get("BRAIN_CURATE_MODEL", "gemini-2.5-flash")
        self.project = project or os.environ.get("GOOGLE_CLOUD_PROJECT")
        self.location = location or os.environ.get("GOOGLE_CLOUD_LOCATION", "europe-west2")
        self._generate = generate

    def _call(self, prompt: str) -> str:
        if self._generate is not None:
            return self._generate(prompt)
        from google import genai
        from google.genai import types

        from ..genai_retry import http_options

        # Bound the call so a throttled/slow model fails fast, and ride out the per-minute
        # quota (429 RESOURCE_EXHAUSTED) with the shared exponential-backoff-with-jitter
        # retry. If it still fails, make_draft falls back to the un-curated text rather
        # than erroring. Thinking is off: a rewrite needs none, and it roughly halves the
        # tokens spent, easing the Vertex quota in the first place.
        client = genai.Client(
            vertexai=True,
            project=self.project,
            location=self.location,
            http_options=http_options(60000),
        )
        config = types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=8192,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
        resp = client.models.generate_content(model=self.model, contents=prompt, config=config)
        return resp.text or ""

    def curate(self, doc: ParsedDoc, known_titles: list[str] | None = None) -> ParsedDoc:
        parts = [_CURATE_INSTRUCTION]
        if known_titles:
            listed = ", ".join(f"[[{t}]]" for t in known_titles[:60])
            parts.append(
                "Prefer linking to these existing documents, using their exact titles in "
                f"double brackets, when the article refers to them: {listed}."
            )
        parts.append("Source:\n" + doc.body)
        cleaned = self._call("\n\n".join(parts)).strip()
        return ParsedDoc(body=cleaned or doc.body, title=doc.title, tags=doc.tags)

    def rewrite(self, text: str, instruction: str) -> str:
        return self._call(instruction + "\n\nText:\n" + text).strip() or text
