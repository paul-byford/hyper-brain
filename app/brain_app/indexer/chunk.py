"""Markdown chunking and link extraction.

Documents are split by heading and then by length, preserving the document title,
the section heading, and the domain from frontmatter. `[[wikilinks]]` are pulled
out for the link graph. This is the gbrain-style "markdown as source of truth"
kept from the lineage; the operational substrate around it is what we changed.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from ..models import Chunk, Document

_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)

# Chunk sizing. Sections longer than this are split on paragraph boundaries.
_MAX_CHARS = 1200


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split leading YAML frontmatter from the body. Returns (meta, body)."""
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text
    meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, text[match.end() :]


def extract_wikilinks(text: str) -> list[str]:
    """Return wikilink targets, de-duplicated and order-preserving.

    Supports ``[[target]]`` and ``[[target|alias]]``.
    """
    seen: dict[str, None] = {}
    for match in _WIKILINK.finditer(text):
        target = match.group(1).split("|", 1)[0].strip()
        if target:
            seen.setdefault(target, None)
    return list(seen)


def _split_sections(body: str) -> list[tuple[str, str]]:
    """Split a body into (heading, content) pairs by markdown headings."""
    matches = list(_HEADING.finditer(body))
    if not matches:
        stripped = body.strip()
        return [("", stripped)] if stripped else []

    sections: list[tuple[str, str]] = []
    preamble = body[: matches[0].start()].strip()
    if preamble:
        sections.append(("", preamble))

    for i, match in enumerate(matches):
        heading = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        content = body[start:end].strip()
        if content:
            sections.append((heading, content))
    return sections


def _split_length(content: str, max_chars: int = _MAX_CHARS) -> list[str]:
    """Split overly long content on paragraph boundaries, keeping paragraphs whole."""
    if len(content) <= max_chars:
        return [content]
    parts: list[str] = []
    current = ""
    for paragraph in content.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) > max_chars and current:
            parts.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def load_document(path: Path, domain_hint: str | None = None) -> tuple[Document, str]:
    """Load a markdown file into a Document (links unresolved) plus its body."""
    text = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    domain = meta.get("domain") or domain_hint
    if not domain:
        raise ValueError(f"{path}: no domain in frontmatter and no domain hint")
    # doc_id is namespaced by domain so the same filename can exist in two domains
    # (for example each domain has its own index.md) without colliding.
    doc_id = f"{domain}/{path.stem}"
    title = str(meta.get("title") or path.stem)
    tags = [str(t) for t in (meta.get("tags") or [])]
    document = Document(
        doc_id=doc_id,
        domain=str(domain),
        title=title,
        path=str(path),
        tags=tags,
        raw_links=extract_wikilinks(body),
        links=[],
        source=_opt_str(meta.get("source")),
        source_url=_opt_str(meta.get("source_url")),
        fetched_at=_opt_str(meta.get("fetched_at")),
    )
    return document, body


def _opt_str(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


def build_chunks(document: Document, body: str, max_chars: int = _MAX_CHARS) -> list[Chunk]:
    """Chunk a document body into retrievable pieces."""
    chunks: list[Chunk] = []
    order = 0
    for heading, content in _split_sections(body):
        for piece in _split_length(content, max_chars):
            chunks.append(
                Chunk(
                    id=f"{document.doc_id}#{order}",
                    doc_id=document.doc_id,
                    domain=document.domain,
                    title=document.title,
                    heading=heading,
                    text=piece,
                    order=order,
                )
            )
            order += 1
    return chunks
