"""Vertex embeddings batch requests under the 250-instance-per-prediction limit.

A single get_embeddings call over the whole corpus fails once there are >250 chunks
(``400 250 instance(s) is allowed``), which silently broke every reindex. embed()
must split the work into batches. Tested with a fake model, so no cloud is needed.
"""

from __future__ import annotations

from brain_app.embeddings.vertex import VertexEmbeddings


class _FakeEmbedding:
    def __init__(self, values):
        self.values = values


class _FakeModel:
    def __init__(self):
        self.batch_sizes: list[int] = []

    def get_embeddings(self, texts):
        self.batch_sizes.append(len(texts))
        return [_FakeEmbedding([0.0, float(i)]) for i in range(len(texts))]


def _emb_with(model):
    # Bypass __init__ (which imports the Vertex SDK); we only exercise embed().
    emb = VertexEmbeddings.__new__(VertexEmbeddings)
    emb._model = model
    emb.dim = 2
    return emb


def test_embed_batches_under_the_instance_limit():
    model = _FakeModel()
    emb = _emb_with(model)
    out = emb.embed([f"chunk {i}" for i in range(450)])  # short texts: instance cap bites
    assert len(out) == 450  # every input got an embedding, in order
    assert all(size <= 250 for size in model.batch_sizes)  # never over the 250 cap
    assert model.batch_sizes == [200, 200, 50]  # default instance batch of 200


def test_embed_batches_under_the_token_limit():
    model = _FakeModel()
    emb = _emb_with(model)
    # ~10k estimated tokens each (30k chars / 3), so only one fits per 16k-token request.
    out = emb.embed(["x" * 30000, "y" * 30000, "z" * 30000])
    assert len(out) == 3
    assert model.batch_sizes == [1, 1, 1]  # the token budget, not the instance cap, split these


def test_embed_empty_makes_no_request():
    model = _FakeModel()
    assert _emb_with(model).embed([]) == []
    assert model.batch_sizes == []
