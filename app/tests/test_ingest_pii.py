"""Pillar 2 (security): a basic PII scan runs over landed content."""

from __future__ import annotations

import pathlib

from brain_app.ingest.pii import scan_pii

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "raw"


def test_scan_flags_email_and_id_shapes():
    text = "Contact jane.doe@example.com, SSN 123-45-6789, card 4111 1111 1111 1111."
    kinds = {f.kind for f in scan_pii(text)}
    assert kinds == {"email", "national-id", "credit-card"}


def test_scan_is_clean_on_ordinary_prose():
    text = "Streaming features keep the fraud model's state fresh within milliseconds."
    assert scan_pii(text) == []


def test_findings_are_deduplicated():
    text = "a@b.com and again a@b.com"
    emails = [f for f in scan_pii(text) if f.kind == "email"]
    assert len(emails) == 1


def test_shipped_raw_drop_has_no_pii():
    # The demo corpus and drops must never seed the brain with personal data.
    for path in RAW.rglob("*.md"):
        assert scan_pii(path.read_text(encoding="utf-8")) == [], f"PII in {path}"
