"""The in-memory index artefact.

This is the whole datastore. There is no running database: the index is a file in
object storage (or on disk locally) that a scale-to-zero container loads into
memory. At small-team corpus sizes a normalised embedding matrix scanned by dot
product is fast, and it costs nothing when idle.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from ..models import Chunk, Document

_ARTEFACT_VERSION = 1


def normalise(matrix: np.ndarray) -> np.ndarray:
    """L2-normalise rows so cosine similarity is a dot product."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


class BrainIndex:
    def __init__(
        self,
        chunks: list[Chunk],
        embeddings: np.ndarray,
        documents: dict[str, Document],
        adjacency: dict[str, list[str]],
        embedding_dim: int,
        provider: str,
        content_hash: str,
    ) -> None:
        if len(chunks) != embeddings.shape[0]:
            raise ValueError("chunks and embeddings length mismatch")
        self.chunks = chunks
        self.embeddings = normalise(np.asarray(embeddings, dtype=np.float32))
        self.documents = documents
        self.adjacency = adjacency
        self.embedding_dim = embedding_dim
        self.provider = provider
        self.content_hash = content_hash

    @property
    def domains(self) -> set[str]:
        return {c.domain for c in self.chunks}

    def to_dict(self) -> dict:
        return {
            "version": _ARTEFACT_VERSION,
            "provider": self.provider,
            "embedding_dim": self.embedding_dim,
            "content_hash": self.content_hash,
            "documents": [asdict(d) for d in self.documents.values()],
            "adjacency": self.adjacency,
            "chunks": [asdict(c) for c in self.chunks],
            "embeddings": self.embeddings.astype(float).tolist(),
        }

    def save(self, path: str | Path) -> None:
        payload = json.dumps(self.to_dict())
        if _is_gcs(path):
            _gcs_write_text(str(path), payload)
            return
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")

    @classmethod
    def from_dict(cls, data: dict) -> BrainIndex:
        chunks = [Chunk(**c) for c in data["chunks"]]
        documents = {d["doc_id"]: Document(**d) for d in data["documents"]}
        embeddings = np.asarray(data["embeddings"], dtype=np.float32)
        if embeddings.ndim != 2:
            embeddings = embeddings.reshape(len(chunks), -1)
        return cls(
            chunks=chunks,
            embeddings=embeddings,
            documents=documents,
            adjacency=data.get("adjacency", {}),
            embedding_dim=int(data["embedding_dim"]),
            provider=str(data["provider"]),
            content_hash=str(data["content_hash"]),
        )

    @classmethod
    def load(cls, path: str | Path) -> BrainIndex:
        text = _gcs_read_text(str(path)) if _is_gcs(path) else Path(path).read_text("utf-8")
        return cls.from_dict(json.loads(text))


def _is_gcs(path: str | Path) -> bool:
    return str(path).startswith("gs://")


def _split_gcs(uri: str) -> tuple[str, str]:
    bucket, _, blob = uri[len("gs://") :].partition("/")
    return bucket, blob


def _gcs_read_text(uri: str) -> str:
    # Lazy import: the offline core never needs the cloud storage client. In
    # production the scale-to-zero container loads the index from its bucket here.
    from google.cloud import storage

    bucket, blob = _split_gcs(uri)
    return storage.Client().bucket(bucket).blob(blob).download_as_text()


def _gcs_write_text(uri: str, text: str) -> None:
    from google.cloud import storage

    bucket, blob = _split_gcs(uri)
    storage.Client().bucket(bucket).blob(blob).upload_from_string(text)
