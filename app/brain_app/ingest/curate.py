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
        raise NotImplementedError(
            "in-tenancy Gemini curation is wired in a later cloud phase "
            "(ARCHITECTURE.md section 12). Set BRAIN_CURATE=off for the offline core."
        )
    raise ValueError(f"unknown curator {name!r}")
