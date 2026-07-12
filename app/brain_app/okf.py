"""Open Knowledge Format (OKF) support: conformance checking and bundle export.

OKF (https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf) is
Google's open, vendor-neutral standard for portable, agent-readable knowledge: a
directory tree of markdown files, each with YAML frontmatter whose one required field
is ``type``. That is exactly the shape of our corpus, so this module is thin:

- :func:`validate_bundle` checks a corpus tree for OKF v0.1 conformance (parseable
  frontmatter with a non-empty ``type`` on every non-reserved file), used in CI.
- :func:`to_okf_markdown` renders a document into a pristine OKF concept for export:
  OKF-native field names (``resource``/``timestamp``), and ``[[wikilinks]]`` rewritten
  as the standard markdown links OKF consumers expect.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import yaml

from .indexer.chunk import parse_frontmatter

# OKF reserves these filenames for directory listings and update logs.
RESERVED = {"index.md", "log.md"}
_WIKILINK = re.compile(r"\[\[([^\]|]+?)\]\]")


def _slug(title: str) -> str:
    from .ingest.pipeline import _slugify

    return _slugify(title)


def validate_bundle(root: str | Path) -> list[str]:
    """Return a list of OKF v0.1 conformance violations for a bundle directory.

    A bundle conforms if every non-reserved ``.md`` file has parseable YAML
    frontmatter containing a non-empty ``type``. An empty list means it conforms.
    """
    root = Path(root)
    violations: list[str] = []
    for path in sorted(root.rglob("*.md")):
        if path.name in RESERVED:
            continue
        rel = path.relative_to(root).as_posix()
        try:
            meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            violations.append(f"{rel}: frontmatter is not parseable YAML ({exc})")
            continue
        if not meta:
            violations.append(f"{rel}: missing YAML frontmatter")
        elif not str(meta.get("type") or "").strip():
            violations.append(f"{rel}: missing required OKF field 'type'")
    return violations


def wikilinks_to_markdown(body: str) -> str:
    """Rewrite ``[[Title]]`` into a standard, bundle-relative markdown link, so an OKF
    consumer sees links it understands. Same-domain concepts sit in the same directory,
    which is exactly where our wikilinks resolve, so a relative ``slug.md`` is correct."""
    return _WIKILINK.sub(lambda m: f"[{m.group(1).strip()}]({_slug(m.group(1))}.md)", body)


def to_okf_markdown(doc: dict, body: str) -> str:
    """Render one document (a ``_document_view`` dict + reconstructed body) as a
    conformant OKF concept: OKF-native frontmatter, then the body with markdown links.

    The body already begins with the ``# Title`` heading, so frontmatter carries the
    structured fields OKF tools read.
    """
    meta: dict[str, object] = {"type": doc.get("type") or "Note", "title": doc.get("title", "")}
    if doc.get("tags"):
        meta["tags"] = list(doc["tags"])
    if doc.get("source_url"):
        meta["resource"] = doc["source_url"]  # OKF: canonical URI of the underlying asset
    if doc.get("fetched_at"):
        meta["timestamp"] = doc["fetched_at"]  # OKF: ISO 8601 last-modified
    meta["domain"] = doc.get("domain", "")  # producer extension, kept for isolation context
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
    return f"---\n{front}---\n\n{wikilinks_to_markdown(body).strip()}\n"


def bundle_zip(docs: list[tuple[dict, str]]) -> bytes:
    """Zip a set of ``(doc_view, body)`` pairs into an OKF bundle: ``<domain>/<slug>.md``
    concepts plus a generated ``index.md`` listing per domain."""
    buf = io.BytesIO()
    by_domain: dict[str, list[dict]] = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for doc, body in docs:
            doc_id = doc["doc_id"]
            zf.writestr(f"{doc_id}.md", to_okf_markdown(doc, body))
            by_domain.setdefault(doc["domain"], []).append(doc)
        for domain, items in by_domain.items():
            lines = [f"# {domain}", "", "An Open Knowledge Format bundle from Hyper Brain.", ""]
            for d in sorted(items, key=lambda x: x.get("title", "")):
                slug = d["doc_id"].split("/", 1)[-1]
                lines.append(f"- [{d.get('title', slug)}]({slug}.md) ({d.get('type') or 'Note'})")
            zf.writestr(f"{domain}/index.md", "\n".join(lines) + "\n")
    return buf.getvalue()
