"""A deterministic, dependency-free embedding provider for offline testing.

It hashes tokens into a fixed-dimension vector with signed buckets, so texts that
share vocabulary land near each other under cosine similarity. It is not a real
semantic model, but it is deterministic and good enough to exercise ranking,
fusion, link expansion and isolation without any cloud call. The real signal
comes from the Vertex adapter in production.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class FakeEmbeddings:
    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in _tokens(text):
            # Not a security hash: only used to spread tokens across buckets.
            raw = hashlib.sha1(token.encode("utf-8"), usedforsecurity=False)
            digest = int(raw.hexdigest(), 16)
            index = digest % self.dim
            sign = 1.0 if (digest >> 8) & 1 else -1.0
            vec[index] += sign
        return vec
