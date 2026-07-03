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
        embeddings = self._model.get_embeddings(list(texts))
        return [e.values for e in embeddings]
