from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Turns text into fixed-length vectors.

    Implementations should return vectors of length ``dim``. Callers normalise
    vectors before storing them, so providers need not return unit vectors.
    """

    dim: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...
