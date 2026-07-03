"""hyper-brain application package.

The offline retrieval core (this package minus the cloud adapters) has no cloud
dependencies: it chunks markdown, builds an in-memory index with pluggable
embeddings, and serves hybrid semantic + keyword + link-graph retrieval with
per-domain isolation.
"""

__version__ = "0.1.0"
