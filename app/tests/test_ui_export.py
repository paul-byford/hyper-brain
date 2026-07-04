"""Pillar 1: the UI data exporter produces the contract the SPA depends on."""

from __future__ import annotations

import importlib.util
import json
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load_exporter():
    spec = importlib.util.spec_from_file_location(
        "export_ui_data", REPO_ROOT / "scripts" / "export_ui_data.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_export_writes_index_and_policy(tmp_path):
    exporter = _load_exporter()
    out = tmp_path / "data"
    # Force a fresh build from the corpus (no prebuilt artefact) so the test is hermetic.
    exporter.export(
        index_path=str(tmp_path / "missing.json"),
        corpus=str(REPO_ROOT / "corpus"),
        profile="personal",
        out_dir=str(out),
    )

    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    # The shape the SPA reads.
    assert {"documents", "chunks", "adjacency", "content_hash"} <= index.keys()
    assert (
        index["documents"]
        and {"doc_id", "domain", "title", "links"} <= index["documents"][0].keys()
    )
    assert (
        index["chunks"]
        and {"doc_id", "domain", "heading", "text", "order"} <= index["chunks"][0].keys()
    )

    policy = json.loads((out / "policy.json").read_text(encoding="utf-8"))
    assert policy["domains"] and policy["grants"]
    assert {"principal", "domains"} <= policy["grants"][0].keys()
