"""First-party, in-tenancy embeddings via Vertex AI (Gemini Enterprise Agent
Platform).

This is the default in production. Content is embedded by a Google-managed model
inside the user's own tenancy and region, not a third party, which is the
load-bearing decision for the data boundary (see ARCHITECTURE.md section 4). The
import is lazy so the offline core never needs the cloud SDK installed.

The exact model id and dimension are on the "facts to verify" list in
ARCHITECTURE.md section 15 and should be confirmed before production use.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

# Default embedding model and dimension. Verify against current Vertex docs.
_DEFAULT_MODEL = "text-embedding-005"
_DEFAULT_DIM = 768
# Vertex enforces two per-request limits: at most 250 instances, and at most 20000
# total input tokens. We batch under both so a large corpus (many documents/uploads)
# is embedded across several calls rather than one oversized request the API rejects.
_MAX_BATCH = 200
_MAX_BATCH_TOKENS = 16000


# Rough token estimate: ~3 chars/token overestimates for prose and is about right for
# dense text (code), so a batch that fits this budget stays safely under 20000 actual.
def _est_tokens(text: str) -> int:
    return len(text) // 3 + 1


class VertexEmbeddings:
    def __init__(
        self,
        model: str | None = None,
        dim: int = _DEFAULT_DIM,
        project: str | None = None,
        location: str | None = None,
    ) -> None:
        # Imported lazily: only needed when actually embedding against Vertex.
        import vertexai
        from vertexai.language_models import TextEmbeddingModel

        vertexai.init(
            project=project or os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=location or os.environ.get("GOOGLE_CLOUD_LOCATION", "europe-west2"),
        )
        self._model = TextEmbeddingModel.from_pretrained(model or _DEFAULT_MODEL)
        self.dim = dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        max_n = int(os.environ.get("BRAIN_EMBED_BATCH", str(_MAX_BATCH)))
        max_tokens = int(os.environ.get("BRAIN_EMBED_MAX_TOKENS", str(_MAX_BATCH_TOKENS)))
        out: list[list[float]] = []
        batch: list[str] = []
        batch_tokens = 0

        def flush() -> None:
            nonlocal batch, batch_tokens
            if batch:
                out.extend(e.values for e in self._model.get_embeddings(batch))
                batch, batch_tokens = [], 0

        for text in texts:
            tokens = _est_tokens(text)
            # Start a new request before exceeding either the instance or token cap.
            if batch and (len(batch) >= max_n or batch_tokens + tokens > max_tokens):
                flush()
            batch.append(text)
            batch_tokens += tokens
        flush()
        return out
