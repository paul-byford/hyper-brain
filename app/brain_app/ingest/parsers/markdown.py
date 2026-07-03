"""Markdown passthrough parser.

Markdown is already the corpus format, so parsing is decode plus light
normalisation. If the source carries YAML frontmatter we lift its ``title`` and
``tags`` so provenance stamping can reuse them, and we drop the frontmatter block
from the body (the pipeline writes its own, authoritative frontmatter on landing).
"""

from __future__ import annotations

from ...indexer.chunk import parse_frontmatter
from ..models import ParsedDoc


class MarkdownParser:
    def parse(self, content: bytes, mime: str) -> ParsedDoc:
        # Normalise line endings first: sources authored on Windows carry CRLF,
        # and the frontmatter/heading regexes are LF-only, so a CRLF source would
        # otherwise silently lose its frontmatter.
        text = content.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
        meta, body = parse_frontmatter(text)
        title = meta.get("title")
        tags = [str(t) for t in (meta.get("tags") or [])]
        return ParsedDoc(body=body.strip(), title=str(title) if title else None, tags=tags)
