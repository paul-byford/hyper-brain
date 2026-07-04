"""Pillar 1: the index loads from gs:// (the production path) as well as disk."""

from __future__ import annotations

import json

from brain_app.retrieval import index as index_mod
from brain_app.retrieval.index import BrainIndex, _is_gcs, _split_gcs


def test_gcs_uri_detection_and_split():
    assert _is_gcs("gs://bucket/path/index.json")
    assert not _is_gcs("/local/index.json")
    assert _split_gcs("gs://my-bucket/a/b/index.json") == ("my-bucket", "a/b/index.json")


def test_load_routes_gcs_through_the_storage_helper(tmp_path, index, monkeypatch):
    # Serialise a real index, then serve its bytes via the (patched) gcs reader so
    # no network or credentials are touched.
    local = tmp_path / "index.json"
    index.save(local)
    payload = local.read_text(encoding="utf-8")

    captured = {}

    def fake_read(uri: str) -> str:
        captured["uri"] = uri
        return payload

    monkeypatch.setattr(index_mod, "_gcs_read_text", fake_read)

    loaded = BrainIndex.load("gs://brain-index/index.json")
    assert captured["uri"] == "gs://brain-index/index.json"
    assert loaded.content_hash == index.content_hash
    assert [c.id for c in loaded.chunks] == [c.id for c in index.chunks]


def test_save_routes_gcs_through_the_storage_helper(index, monkeypatch):
    written = {}

    def fake_write(uri: str, text: str) -> None:
        written["uri"] = uri
        written["text"] = text

    monkeypatch.setattr(index_mod, "_gcs_write_text", fake_write)

    index.save("gs://brain-index/index.json")
    assert written["uri"] == "gs://brain-index/index.json"
    assert json.loads(written["text"])["content_hash"] == index.content_hash
