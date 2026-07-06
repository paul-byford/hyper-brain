"""BrainService: the MCP tool logic, and the place domain isolation is enforced.

Every method takes a verified ``Identity`` and applies the domain ACL before any
signal runs, so the boundary of ARCHITECTURE.md section 7 holds regardless of what
a client asks for. The write path additionally requires the ``propose`` scope and
validates the target domain. This class is pure Python with no MCP or cloud
dependency, so the whole security contract is testable offline.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable

from ..auth import (
    Identity,
    MemorySharesStore,
    Share,
    SharesStore,
    can_share,
    personal_domain,
    read_domains,
    readable_docs,
    utc_now,
    validate_share,
    writable_domains,
)
from ..config import Policy
from ..embeddings.base import EmbeddingProvider
from ..models import Answer, SearchResult
from ..observability import span
from ..retrieval import BrainIndex, ExtractiveSynthesiser, Synthesiser, answer, search
from .proposals import MemoryGate, ProposalResult, ReviewGate, build_proposal


def _share_view(share: Share) -> dict:
    return {
        "principal": share.principal,
        "domain": share.domain,
        "doc_id": share.doc_id,
        "write": share.write,
        "granted_by": share.granted_by,
        "granted_at": share.granted_at,
    }


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
        synthesiser: Synthesiser | None = None,
        policy_source: Callable[[], Policy] | None = None,
        index_loader: Callable[[], BrainIndex] | None = None,
        index_ttl: float | None = None,
        shares_store: SharesStore | None = None,
        note_gate: ReviewGate | None = None,
    ) -> None:
        # The index can be passed directly, or loaded lazily on first use. Lazy
        # loading lets a scale-to-zero container start (and pass its health check)
        # before the index artefact exists in the bucket, and keeps cold start fast.
        # With a loader and a positive index_ttl, the index is reloaded after that
        # many seconds, so a re-index appears without a redeploy (mirrors the policy
        # TTL). Default 0 = load once and cache for the instance's life.
        self._index = index
        self._index_loader = index_loader
        self._index_ttl = (
            index_ttl if index_ttl is not None else float(os.environ.get("BRAIN_INDEX_TTL", "0"))
        )
        self._index_at = 0.0
        self.embeddings = embeddings
        self.policy = policy
        # Resolve the policy per request through a source, so a grant that updates a
        # shared policy (a gs:// object) takes effect without a redeploy. Defaults to
        # the fixed policy passed in.
        self._policy_source = policy_source or (lambda: policy)
        # Default to the no-write MemoryGate: safe unless a real gate is wired in.
        self.gate = gate or MemoryGate()
        # Default to deterministic extractive synthesis; production injects Gemini.
        self.synthesiser = synthesiser or ExtractiveSynthesiser()
        # The dynamic sharing overlay (user-authored grants), and the gate personal
        # notes land through. Both default to in-process/no-write, so the offline
        # core and tests are self-contained; the deployed brain wires GCS-backed ones.
        self.shares_store: SharesStore = shares_store or MemorySharesStore()
        self.note_gate = note_gate or MemoryGate()

    @property
    def index(self) -> BrainIndex:
        if self._index_loader is not None:
            now = time.monotonic()
            stale = self._index_ttl > 0 and now - self._index_at > self._index_ttl
            if self._index is None or stale:
                self._index = self._index_loader()
                self._index_at = now
        if self._index is None:
            raise RuntimeError("BrainService has neither an index nor an index_loader")
        return self._index

    def _shares(self) -> list[Share]:
        return self.shares_store.all_shares()

    def _visible_domains(self, identity: Identity) -> set[str]:
        # Intersect what the caller may read (base policy + personal + shared domains)
        # with the domains that actually exist in the index.
        return read_domains(identity, self._policy_source(), self._shares()) & self.index.domains

    def _extra_doc_ids(self, identity: Identity) -> set[str]:
        # Individual documents shared with the caller, admitted on top of their domains.
        return readable_docs(identity, self._shares())

    def list_domains(self, identity: Identity) -> list[str]:
        return sorted(self._visible_domains(identity))

    def search(self, identity: Identity, query: str, *, top_k: int = 5) -> list[SearchResult]:
        domains = self._visible_domains(identity)
        extra = self._extra_doc_ids(identity)
        with span(
            "brain.search",
            **{
                "brain.domain_count": len(domains),
                "brain.top_k": top_k,
                "brain.principal": identity.subject,
            },
        ) as s:
            results = search(
                self.index, query, domains, self.embeddings, top_k=top_k, extra_doc_ids=extra
            )
            if s is not None:
                s.set_attribute("brain.result_count", len(results))
            return results

    def answer(self, identity: Identity, query: str, *, top_k: int = 5) -> Answer:
        domains = self._visible_domains(identity)
        extra = self._extra_doc_ids(identity)
        with span(
            "brain.answer",
            **{
                "brain.domain_count": len(domains),
                "brain.top_k": top_k,
                "brain.principal": identity.subject,
            },
        ) as s:
            result = answer(
                self.index,
                query,
                domains,
                self.embeddings,
                self.synthesiser,
                top_k=top_k,
                extra_doc_ids=extra,
            )
            if s is not None:
                s.set_attribute("brain.citation_count", len(result.citations))
                s.set_attribute("brain.gap_count", len(result.gaps))
            return result

    def get_document(self, identity: Identity, doc_id: str) -> dict:
        domains = self._visible_domains(identity)
        extra = self._extra_doc_ids(identity)
        with span(
            "brain.get_document", **{"brain.doc_id": doc_id, "brain.principal": identity.subject}
        ):
            document = self.index.documents.get(doc_id)
            if document is None or (document.domain not in domains and doc_id not in extra):
                raise DocumentNotFound(doc_id)
            return self._document_view(document)

    def _document_view(self, document) -> dict:
        return {
            "doc_id": document.doc_id,
            "domain": document.domain,
            "title": document.title,
            "tags": list(document.tags),
            "links": list(document.links),
            "source": document.source,
            "fetched_at": document.fetched_at,
            "text": self._reconstruct(document.doc_id, document.title),
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
        with span(
            "brain.propose_document",
            **{"brain.domain": domain, "brain.principal": identity.subject},
        ):
            policy = self._policy_source()
            writable = writable_domains(identity, policy)
            # Write is separate from read: a caller with no write grant (and no
            # propose scope) cannot reach this path, however broad their read access.
            if not writable:
                raise WriteScopeError(
                    "identity has no write access (policy grant or propose scope)"
                )
            # And the target domain must be one the caller may actually write.
            if domain not in writable:
                raise DomainNotAuthorized(domain)
            proposal = build_proposal(
                domain=domain,
                title=title,
                content=content,
                author=identity.email or identity.subject,
                source_url=source_url,
            )
            return self.gate.submit(proposal)

    # --- Personal notes and dynamic sharing (the overlay) ------------------------

    def add_note(
        self,
        identity: Identity,
        *,
        title: str,
        content: str,
        source_url: str | None = None,
    ) -> ProposalResult:
        """Write a note into the caller's own personal domain. Ungated: the caller
        owns this space, so there is nothing to review. The note is searchable once
        the index rebuilds (the path any content takes), same as commons content."""
        personal = personal_domain(identity)
        if personal is None:
            raise AccessError("an anonymous caller has no personal domain to write to")
        with span(
            "brain.add_note", **{"brain.domain": personal, "brain.principal": identity.subject}
        ):
            proposal = build_proposal(
                domain=personal,
                title=title,
                content=content,
                author=identity.email or identity.subject,
                source_url=source_url,
            )
            return self.note_gate.submit(proposal)

    def _resolve_share_target(
        self, identity: Identity, domain: str | None, doc_id: str | None
    ) -> str:
        """Return the domain a share applies to, checking the caller may see the doc
        for a doc-level share, and that they own/can-write the domain for either."""
        policy = self._policy_source()
        shares = self._shares()
        if doc_id is not None:
            document = self.index.documents.get(doc_id)
            visible = read_domains(identity, policy, shares) & self.index.domains
            extra = readable_docs(identity, shares)
            if document is None or (document.domain not in visible and doc_id not in extra):
                # Same opacity as get_document: cannot probe for cross-domain docs.
                raise DocumentNotFound(doc_id)
            domain = document.domain
        if not domain:
            raise AccessError("a share needs a domain or a doc_id")
        if not can_share(identity, policy, domain, shares):
            raise DomainNotAuthorized(domain)
        return domain

    def share(
        self,
        identity: Identity,
        *,
        principal: str,
        domain: str | None = None,
        doc_id: str | None = None,
        write: bool = False,
    ) -> dict:
        """Grant ``principal`` read (or write) access to a domain or a single document
        the caller owns. Recorded in the caller's own overlay file."""
        with span("brain.share", **{"brain.principal": identity.subject}):
            resolved = self._resolve_share_target(identity, domain, doc_id)
            share = validate_share(
                Share(
                    principal=principal,
                    domain=resolved,
                    granted_by=identity.subject,
                    doc_id=doc_id,
                    write=bool(write),
                    granted_at=utc_now(),
                )
            )
            owned = [
                s for s in self.shares_store.for_owner(identity.subject) if s.key() != share.key()
            ]
            owned.append(share)
            self.shares_store.put_owner(identity.subject, owned)
            return _share_view(share)

    def unshare(
        self,
        identity: Identity,
        *,
        principal: str,
        domain: str | None = None,
        doc_id: str | None = None,
    ) -> int:
        """Revoke a share the caller previously created. Returns how many were removed."""
        with span("brain.unshare", **{"brain.principal": identity.subject}):
            owned = self.shares_store.for_owner(identity.subject)

            def matches(s: Share) -> bool:
                if s.principal != principal:
                    return False
                if doc_id is not None:
                    return s.doc_id == doc_id
                return s.doc_id is None and s.domain == domain

            remaining = [s for s in owned if not matches(s)]
            self.shares_store.put_owner(identity.subject, remaining)
            return len(owned) - len(remaining)

    def list_shares(self, identity: Identity) -> dict:
        """Shares the caller has granted, and shares granted to the caller."""
        shares = self._shares()
        principals = set(identity.principals)
        return {
            "granted": [_share_view(s) for s in shares if s.granted_by == identity.subject],
            "received": [_share_view(s) for s in shares if s.principal in principals],
        }
