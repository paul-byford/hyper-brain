"""Content-type parsers, selected by MIME type.

Markdown and HTML parse offline with no dependencies. PDF sits behind the Vertex
AI Document AI seam (parse in-tenancy, ARCHITECTURE.md section 12) and is not
wired until a cloud phase, so importing it here would pull nothing heavy into the
offline core; it is resolved lazily like the Vertex embeddings adapter.
"""

from __future__ import annotations

from .base import Parser
from .html import HtmlParser
from .markdown import MarkdownParser

__all__ = ["Parser", "HtmlParser", "MarkdownParser", "get_parser"]

# Longest-prefix match so "text/markdown; charset=utf-8" still resolves.
_MARKDOWN = ("text/markdown", "text/x-markdown", "text/plain")
_HTML = ("text/html", "application/xhtml+xml")
_PDF = ("application/pdf",)


def get_parser(mime: str) -> Parser:
    """Return the parser for a MIME type (ignoring any ``; charset=`` suffix)."""
    base = mime.split(";", 1)[0].strip().lower()
    if base in _MARKDOWN:
        return MarkdownParser()
    if base in _HTML:
        return HtmlParser()
    if base in _PDF:
        # Lazy: the real parser needs the cloud, so it is not imported offline.
        from .pdf import PdfParser

        return PdfParser()
    raise ValueError(f"no parser for content type {mime!r}")
