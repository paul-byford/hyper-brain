"""Open Knowledge Format conformance and export.

The bundle validator doubles as a CI conformance gate: the real seed corpus must be a
conformant OKF bundle. The export helpers turn our stored notes into pristine OKF
concepts (native field names, markdown links) for interchange with other OKF tools.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from brain_app.okf import (
    bundle_zip,
    to_okf_markdown,
    validate_bundle,
    wikilinks_to_markdown,
)

REPO = Path(__file__).resolve().parents[2]


def test_seed_corpus_is_a_conformant_okf_bundle():
    violations = validate_bundle(REPO / "corpus")
    assert violations == [], violations


def test_missing_type_is_flagged(tmp_path):
    (tmp_path / "a.md").write_text("---\ntitle: X\n---\nbody", encoding="utf-8")
    assert any("type" in v for v in validate_bundle(tmp_path))


def test_reserved_files_are_exempt(tmp_path):
    (tmp_path / "index.md").write_text("just a listing, no frontmatter", encoding="utf-8")
    assert validate_bundle(tmp_path) == []


def test_wikilinks_become_bundle_relative_markdown_links():
    out = wikilinks_to_markdown("See [[Real-time fraud detection]] and [[Guardrails]].")
    assert "[Real-time fraud detection](real-time-fraud-detection.md)" in out
    assert "[Guardrails](guardrails.md)" in out


def test_to_okf_markdown_uses_native_okf_fields():
    doc = {
        "doc_id": "commons/x",
        "domain": "commons",
        "title": "X",
        "type": "Note",
        "tags": ["a"],
        "source_url": "https://example.com/x",
        "fetched_at": "2026-01-01T00:00:00Z",
    }
    md = to_okf_markdown(doc, "# X\n\nBody with [[Y]].")
    assert md.startswith("---\ntype: Note\n")
    assert "resource: https://example.com/x" in md
    assert "timestamp:" in md
    assert "[Y](y.md)" in md  # wikilink rewritten for OKF consumers


def test_bundle_zip_has_concepts_and_generated_index():
    doc = {
        "doc_id": "commons/x",
        "domain": "commons",
        "title": "X",
        "type": "Note",
        "tags": [],
        "source_url": None,
        "fetched_at": None,
    }
    zf = zipfile.ZipFile(io.BytesIO(bundle_zip([(doc, "# X\n\nbody")])))
    names = zf.namelist()
    assert "commons/x.md" in names
    assert "commons/index.md" in names
