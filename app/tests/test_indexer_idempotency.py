from __future__ import annotations

import numpy as np

from brain_app.indexer.build import build_index
from brain_app.retrieval.index import BrainIndex

from .conftest import CORPUS


def test_build_is_deterministic_and_idempotent(embeddings):
    first = build_index(CORPUS, embeddings=embeddings, provider_name="fake")
    second = build_index(CORPUS, embeddings=embeddings, provider_name="fake")

    # Same content hash and same chunks: re-indexing converges, never duplicates.
    assert first.content_hash == second.content_hash
    assert [c.id for c in first.chunks] == [c.id for c in second.chunks]
    assert np.allclose(first.embeddings, second.embeddings)


def test_no_duplicate_chunk_ids(index):
    ids = [c.id for c in index.chunks]
    assert len(ids) == len(set(ids))


def test_artefact_roundtrip(tmp_path, index):
    out = tmp_path / "index.json"
    index.save(out)
    loaded = BrainIndex.load(out)
    assert loaded.content_hash == index.content_hash
    assert [c.id for c in loaded.chunks] == [c.id for c in index.chunks]
    assert loaded.embeddings.shape == index.embeddings.shape
    assert np.allclose(loaded.embeddings, index.embeddings, atol=1e-6)
