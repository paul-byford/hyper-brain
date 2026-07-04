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
    def curate(self, doc: ParsedDoc) -> ParsedDoc: ...


class PassthroughCurator:
    """Deterministic no-op: the document is landed as parsed."""

    def curate(self, doc: ParsedDoc) -> ParsedDoc:
        return doc


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
    "Rewrite the following source text into a clean, well-structured markdown "
    "article. Preserve every fact; do NOT invent anything not in the source. Use "
    "short paragraphs and headings. Where the text clearly refers to another likely "
    "document or concept, mark it with [[wikilink]] syntax. Return only the markdown, "
    "no preamble.\n\nSource:\n"
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

        client = genai.Client(vertexai=True, project=self.project, location=self.location)
        return client.models.generate_content(model=self.model, contents=prompt).text or ""

    def curate(self, doc: ParsedDoc) -> ParsedDoc:
        cleaned = self._call(_CURATE_INSTRUCTION + doc.body).strip()
        return ParsedDoc(body=cleaned or doc.body, title=doc.title, tags=doc.tags)
