"""Embedding providers.

The provider is deliberately behind a narrow interface. This is the load-bearing
seam for the data boundary: the default in-tenancy Vertex adapter can be swapped
for a self-hosted model without touching the indexer or retrieval, and a
deterministic fake keeps the whole core testable offline with no cloud and no
cost.
"""

from __future__ import annotations

import os

from .base import EmbeddingProvider
from .fake import FakeEmbeddings

__all__ = ["EmbeddingProvider", "FakeEmbeddings", "get_embeddings"]


def get_embeddings(provider: str | None = None) -> EmbeddingProvider:
    """Return the configured embedding provider.

    Selected by the ``BRAIN_EMBEDDINGS`` environment variable. Defaults to the
    deterministic fake so nothing reaches out to a cloud service unless asked.
    """
    provider = provider or os.environ.get("BRAIN_EMBEDDINGS", "fake")
    if provider == "vertex":
        from .vertex import VertexEmbeddings

        return VertexEmbeddings()
    if provider == "fake":
        return FakeEmbeddings()
    raise ValueError(f"unknown embeddings provider: {provider!r}")
