"""BrainService: the MCP tool logic, and the place domain isolation is enforced.

Every method takes a verified ``Identity`` and applies the domain ACL before any
signal runs, so the boundary of ARCHITECTURE.md section 7 holds regardless of what
a client asks for. The write path additionally requires the ``propose`` scope and
validates the target domain. This class is pure Python with no MCP or cloud
dependency, so the whole security contract is testable offline.
"""

from __future__ import annotations

from ..auth import Identity, can_propose, read_domains, writable_domains
from ..config import Policy
from ..embeddings.base import EmbeddingProvider
from ..models import Answer, SearchResult
from ..retrieval import BrainIndex, answer, search
from .proposals import MemoryGate, ProposalResult, ReviewGate, build_proposal


class AccessError(Exception):
    """A caller tried something their identity does not permit."""


class WriteScopeError(AccessError):
    """The caller's token lacks the write (propose) scope."""


class DomainNotAuthorized(AccessError):
    """The caller tried to write into a domain they are not granted."""


class DocumentNotFound(Exception):
    """No such document *in the caller's visible domains*.

    Deliberately the same error whether the document does not exist or exists in a
    domain the caller may not see, so the response cannot be used to probe for the
    existence of cross-domain content.
    """


class BrainService:
    def __init__(
        self,
        index: BrainIndex,
        embeddings: EmbeddingProvider,
        policy: Policy,
        *,
        gate: ReviewGate | None = None,
    ) -> None:
        self.index = index
        self.embeddings = embeddings
        self.policy = policy
        # Default to the no-write MemoryGate: safe unless a real gate is wired in.
        self.gate = gate or MemoryGate()

    def _visible_domains(self, identity: Identity) -> set[str]:
        # Intersect the policy grant with domains that actually exist in the index.
        return read_domains(identity, self.policy) & self.index.domains

    def list_domains(self, identity: Identity) -> list[str]:
        return sorted(self._visible_domains(identity))

    def search(self, identity: Identity, query: str, *, top_k: int = 5) -> list[SearchResult]:
        return search(
            self.index, query, self._visible_domains(identity), self.embeddings, top_k=top_k
        )

    def answer(self, identity: Identity, query: str, *, top_k: int = 5) -> Answer:
        return answer(
            self.index, query, self._visible_domains(identity), self.embeddings, top_k=top_k
        )

    def get_document(self, identity: Identity, doc_id: str) -> dict:
        domains = self._visible_domains(identity)
        document = self.index.documents.get(doc_id)
        if document is None or document.domain not in domains:
            raise DocumentNotFound(doc_id)
        return {
            "doc_id": document.doc_id,
            "domain": document.domain,
            "title": document.title,
            "tags": list(document.tags),
            "links": list(document.links),
            "text": self._reconstruct(doc_id, document.title),
        }

    def _reconstruct(self, doc_id: str, title: str) -> str:
        """Rebuild a document's text from its chunks, so it serves from the index
        alone (no corpus files needed at serving time, matching the GCS model)."""
        chunks = sorted((c for c in self.index.chunks if c.doc_id == doc_id), key=lambda c: c.order)
        parts = [f"# {title}"]
        last_heading = None
        for chunk in chunks:
            if chunk.heading and chunk.heading != last_heading:
                parts.append(f"## {chunk.heading}")
                last_heading = chunk.heading
            parts.append(chunk.text)
        return "\n\n".join(parts)

    def propose_document(
        self,
        identity: Identity,
        *,
        domain: str,
        title: str,
        content: str,
        source_url: str | None = None,
    ) -> ProposalResult:
        # Write scope is checked separately from read access: a read-only token,
        # however broad its domain grant, cannot reach this path.
        if not can_propose(identity):
            raise WriteScopeError("token lacks the 'propose' scope")
        # And the target domain must be one the caller is actually granted.
        if domain not in writable_domains(identity, self.policy):
            raise DomainNotAuthorized(domain)
        proposal = build_proposal(
            domain=domain,
            title=title,
            content=content,
            author=identity.email or identity.subject,
            source_url=source_url,
        )
        return self.gate.submit(proposal)
