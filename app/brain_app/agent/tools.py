"""In-process brain tools for the offline agent (and its evals).

In production the agent reaches the brain over MCP (see agent.py), which enforces
the domain ACL server-side. Offline, the eval needs the same tool surface without
a running server, so these functions call ``BrainService`` directly with a fixed,
env-configured identity. The domain scoping is real: the service applies the same
policy filter, so the isolation eval genuinely exercises the boundary.

The index and identity are built lazily on first use and cached, so importing the
agent module (which ADK does eagerly) never needs the cloud or a prebuilt index.
"""

from __future__ import annotations

import os
from functools import lru_cache

# Absolute imports (not the package-relative style used elsewhere): the ADK CLI
# (`adk web` / `adk eval`) loads this agent package by file path as a standalone
# module, so package-relative parent imports would resolve beyond the top level.
from brain_app.auth.identity import identity_from_claims
from brain_app.config import load_policy
from brain_app.embeddings.fake import FakeEmbeddings
from brain_app.retrieval import BrainIndex
from brain_app.serving.service import BrainService, DocumentNotFound


@lru_cache(maxsize=1)
def _service() -> BrainService:
    index_path = os.environ.get("BRAIN_INDEX", ".brain/index.json")
    embeddings = FakeEmbeddings()
    if os.path.exists(index_path):
        index = BrainIndex.load(index_path)
    else:
        # No prebuilt artefact: build one from the corpus so the agent still runs.
        from brain_app.indexer.build import build_index

        index = build_index(os.environ.get("BRAIN_CORPUS", "corpus"), embeddings=embeddings)
    return BrainService(index, embeddings, load_policy())


@lru_cache(maxsize=1)
def _identity():
    """The identity the offline agent acts as, from the environment.

    Defaults to a financial-services engineer (single-domain), which is what makes
    the shipped isolation eval meaningful out of the box.
    """
    raw_groups = os.environ.get("BRAIN_AGENT_GROUPS", "finserv-eng@example.com")
    groups = [g for g in raw_groups.split(",") if g]
    claims = {
        "sub": os.environ.get("BRAIN_AGENT_EMAIL", "agent@demo"),
        "email": os.environ.get("BRAIN_AGENT_EMAIL", "agent@demo"),
        "groups": groups,
        "scope": os.environ.get("BRAIN_AGENT_SCOPE", "read"),
    }
    return identity_from_claims(claims)


def _format_hits(hits) -> str:
    lines = [f"[{h.domain}] {h.title} :: {h.heading}" for h in hits]
    return "\n".join(lines)


def search(query: str) -> str:
    """Search the brain for a question. Returns ranked hits scoped to your domains.

    Args:
        query: The natural-language question to search for.
    """
    hits = _service().search(_identity(), query, top_k=5)
    return _format_hits(hits) if hits else "No results in your permitted domains."


def answer(query: str) -> str:
    """Answer a question from the brain, with citations, scoped to your domains.

    Args:
        query: The natural-language question to answer.
    """
    result = _service().answer(_identity(), query)
    cites = _format_hits(result.citations)
    return f"{result.text}\n\nCitations:\n{cites}" if cites else result.text


def list_domains() -> str:
    """List the knowledge domains you are permitted to retrieve from."""
    return ", ".join(_service().list_domains(_identity())) or "(none)"


def get_document(doc_id: str) -> str:
    """Fetch one document by id, if it is in a domain you may see.

    Args:
        doc_id: The document id, for example ``finserv-ai-engineering/realtime-fraud-detection``.
    """
    try:
        document = _service().get_document(_identity(), doc_id)
    except DocumentNotFound:
        return f"No document '{doc_id}' in your permitted domains."
    return f"# {document['title']}\n\n{document['text']}"


def reset_caches() -> None:
    """Clear the cached service and identity. For tests that change the environment."""
    _service.cache_clear()
    _identity.cache_clear()
