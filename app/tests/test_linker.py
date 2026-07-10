"""The autolinker: embedding-similarity suggestions and the wikilink write path.

Suggestions are scored from the index's own document vectors and never cross a
domain; creating a link edits the source note in place with a ``[[wikilink]]`` and
is refused for anything outside the caller's personal space.
"""

from __future__ import annotations

import numpy as np
import pytest

from brain_app.auth import HmacVerifier, encode_hs256
from brain_app.config import load_policy
from brain_app.embeddings.fake import FakeEmbeddings
from brain_app.models import Chunk, Document
from brain_app.retrieval import BrainIndex
from brain_app.serving import BrainService
from brain_app.serving.linker import suggest_links
from brain_app.serving.proposals import MemoryGate
from brain_app.serving.reindex import MemoryReindexer
from brain_app.serving.service import AccessError

SECRET = "test-secret"
PERSONAL = "personal:me@x"


def _identity(email="me@x"):
    token = encode_hs256({"sub": email, "email": email, "groups": [], "scope": "read"}, SECRET)
    return HmacVerifier(SECRET).verify(token)


def _doc(doc_id, domain, title, links=None):
    return Document(
        doc_id=doc_id,
        domain=domain,
        title=title,
        path="",
        tags=["note"],
        raw_links=[],
        links=links or [],
        source=None,
        source_url=None,
        fetched_at=None,
    )


def _chunk(doc_id, domain, title, text):
    return Chunk(
        id=f"{doc_id}#0", doc_id=doc_id, domain=domain, title=title, heading="", text=text, order=0
    )


def _index(docs, embeddings, adjacency=None):
    emb = np.array(embeddings, dtype=np.float32)
    chunks = [_chunk(d.doc_id, d.domain, d.title, f"{d.title} body") for d in docs]
    return BrainIndex(
        chunks=chunks,
        embeddings=emb,
        documents={d.doc_id: d for d in docs},
        adjacency=adjacency or {},
        embedding_dim=emb.shape[1],
        provider="fake",
        content_hash="x",
    )


def test_suggest_links_ranks_similar_and_excludes_linked():
    docs = [_doc("d/a", "d", "A"), _doc("d/b", "d", "B"), _doc("d/c", "d", "C")]
    # A and B nearly identical; C orthogonal.
    idx = _index(docs, [[1.0, 0.0], [0.98, 0.02], [0.0, 1.0]])
    pairs = suggest_links(idx, [d.doc_id for d in docs], idx.adjacency, threshold=0.5)
    assert pairs and pairs[0][1:] == ("d/a", "d/b")  # strongest pair first
    assert all({a, b} != {"d/a", "d/c"} for _, a, b in pairs)  # dissimilar not suggested


def test_suggest_links_skips_already_linked_pairs():
    docs = [_doc("d/a", "d", "A"), _doc("d/b", "d", "B")]
    idx = _index(docs, [[1.0, 0.0], [0.99, 0.01]], adjacency={"d/a": ["d/b"], "d/b": ["d/a"]})
    assert suggest_links(idx, [d.doc_id for d in docs], idx.adjacency, threshold=0.5) == []


def _personal_service():
    docs = [
        _doc(f"{PERSONAL}/note-a", PERSONAL, "Note A"),
        _doc(f"{PERSONAL}/note-b", PERSONAL, "Note B"),
    ]
    idx = _index(docs, [[1.0, 0.0], [0.97, 0.05]])
    return BrainService(
        idx,
        FakeEmbeddings(),
        load_policy(prof="personal"),
        note_gate=MemoryGate(),
        reindexer=MemoryReindexer(),
    )


def test_suggest_note_links_pairs_the_callers_notes():
    svc = _personal_service()
    out = svc.suggest_note_links(_identity())
    assert len(out) == 1
    assert {out[0]["source"], out[0]["target"]} == {f"{PERSONAL}/note-a", f"{PERSONAL}/note-b"}
    assert out[0]["score"] >= 0.5


def test_link_notes_adds_a_wikilink_to_the_source_note():
    svc = _personal_service()
    result = svc.link_notes(_identity(), f"{PERSONAL}/note-a", f"{PERSONAL}/note-b")
    assert result["status"] == "linked"
    # The edit was submitted as a note overwrite carrying the new wikilink.
    proposal = svc.note_gate.proposals[-1]
    assert "[[Note B]]" in proposal.content
    assert "## Related" in proposal.content


def test_link_notes_refuses_outside_personal_space():
    svc = _personal_service()
    with pytest.raises(AccessError):
        svc.link_notes(_identity(), "commons/welcome", f"{PERSONAL}/note-b")
    with pytest.raises(ValueError):
        svc.link_notes(_identity(), f"{PERSONAL}/note-a", f"{PERSONAL}/note-a")
