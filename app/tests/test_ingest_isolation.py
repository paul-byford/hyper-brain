"""Pillar 2 (security): ingestion cannot breach the domain boundary.

Domain is assigned by source config and validated on landing. An adapter cannot
land outside its configured domain, source content cannot override the domain,
and a hostile identifier cannot escape the domain folder by path traversal.
"""

from __future__ import annotations

import pathlib

import pytest

from brain_app.ingest import ingest_source
from brain_app.ingest.models import ParsedDoc, RawItem
from brain_app.ingest.pipeline import _land, _slugify
from brain_app.ingest.sources import SourceConfig

from .conftest import FINSERV, RECRUITMENT

NOW = "2026-07-03T00:00:00+00:00"
RUN = "ingest-test000000"


def _source(raw_dir, domain) -> SourceConfig:
    return SourceConfig(
        id="raw-test",
        type="local",
        domain=domain,
        curate=False,
        options={"path": str(raw_dir), "glob": "*.md"},
    )


def test_source_frontmatter_cannot_override_configured_domain(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    # The dropped file *claims* the recruitment domain in its own frontmatter.
    (raw / "sneaky.md").write_text(
        f"---\ntitle: Sneaky\ndomain: {RECRUITMENT}\n---\n\n# Sneaky\n\nBody.\n", "utf-8"
    )
    corpus = tmp_path / "corpus"

    # But the source is configured for finserv, so it must land there and nowhere else.
    ingest_source(_source(raw, FINSERV), corpus, state_dir=tmp_path / "s", run_id=RUN, now=NOW)

    assert (corpus / FINSERV / "sneaky.md").is_file()
    assert not (corpus / RECRUITMENT).exists()
    meta_line = (corpus / FINSERV / "sneaky.md").read_text(encoding="utf-8")
    assert f"domain: {FINSERV}" in meta_line
    assert f"domain: {RECRUITMENT}" not in meta_line


def test_every_landed_path_stays_within_domain_folder(tmp_path):
    raw = tmp_path / "raw"
    (raw / "deep").mkdir(parents=True)
    (raw / "deep" / "note.md").write_text("# Note\n\nBody.\n", "utf-8")
    corpus = tmp_path / "corpus"

    report = ingest_source(
        _source(raw, FINSERV), corpus, state_dir=tmp_path / "s", run_id=RUN, now=NOW
    )
    domain_root = (corpus / FINSERV).resolve()
    for result in report.results:
        assert pathlib.Path(result.path).resolve().parent == domain_root


def test_slugify_neutralises_path_traversal():
    assert _slugify("../../etc/passwd") == "etc-passwd"
    assert _slugify("..\\..\\evil") == "evil"
    assert "/" not in _slugify("a/b/c")


def test_land_guard_rejects_escaping_target(tmp_path, monkeypatch):
    # Force a slug that tries to escape, proving the resolved-path guard fires even
    # if slugification were ever bypassed.
    monkeypatch.setattr("brain_app.ingest.pipeline._slugify", lambda _v: "../escape")
    item = RawItem(identifier="x", content=b"", mime="text/markdown", source_url="file://x")
    with pytest.raises(ValueError, match="outside domain"):
        _land(
            ParsedDoc(body="hi"),
            item,
            _source(tmp_path, FINSERV),
            tmp_path / "corpus",
            known_checksum=None,
            run_id=RUN,
            now=NOW,
        )


@pytest.mark.eval
def test_ingest_isolation_eval_two_sources_stay_separated(tmp_path):
    finserv_raw = tmp_path / "fin"
    finserv_raw.mkdir()
    (finserv_raw / "f.md").write_text("# Fraud\n\nStreaming fraud detection.\n", "utf-8")
    recruit_raw = tmp_path / "rec"
    recruit_raw.mkdir()
    (recruit_raw / "r.md").write_text("# Sourcing\n\nCandidate sourcing.\n", "utf-8")
    corpus = tmp_path / "corpus"

    ingest_source(
        _source(finserv_raw, FINSERV), corpus, state_dir=tmp_path / "s1", run_id=RUN, now=NOW
    )
    ingest_source(
        _source(recruit_raw, RECRUITMENT), corpus, state_dir=tmp_path / "s2", run_id=RUN, now=NOW
    )

    # Each document landed only under its own domain; neither crossed over.
    # (No frontmatter title, so the landed slug comes from the file stem.)
    assert (corpus / FINSERV / "f.md").is_file()
    assert (corpus / RECRUITMENT / "r.md").is_file()
    assert list((corpus / FINSERV).glob("*.md")) == [corpus / FINSERV / "f.md"]
    assert list((corpus / RECRUITMENT).glob("*.md")) == [corpus / RECRUITMENT / "r.md"]
