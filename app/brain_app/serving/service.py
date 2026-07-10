"""BrainService: the MCP tool logic, and the place domain isolation is enforced.

Every method takes a verified ``Identity`` and applies the domain ACL before any
signal runs, so the boundary of ARCHITECTURE.md section 7 holds regardless of what
a client asks for. The write path additionally requires the ``propose`` scope and
validates the target domain. This class is pure Python with no MCP or cloud
dependency, so the whole security contract is testable offline.
"""

from __future__ import annotations

import base64
import binascii
import os
import time
from collections.abc import Callable

from ..auth import (
    Identity,
    MemorySharesStore,
    Share,
    SharesStore,
    can_share,
    is_personal_domain,
    personal_domain,
    personal_owner,
    read_domains,
    readable_docs,
    utc_now,
    validate_share,
    writable_domains,
)
from ..config import WILDCARD, Policy
from ..embeddings.base import EmbeddingProvider
from ..models import Answer, SearchResult
from ..observability import span
from ..retrieval import BrainIndex, ExtractiveSynthesiser, Synthesiser, answer, search
from .attachments import AttachmentStore, MemoryAttachmentStore, safe_filename
from .proposals import MemoryGate, ProposalResult, ReviewGate, build_proposal
from .reindex import MemoryReindexer, Reindexer
from .reviewer import MemoryReviewer, Reviewer, proposal_domain

# Uploaded file types we can extract text from (markdown/HTML/Word offline; PDF via
# in-tenancy Document AI when configured). Anything else is refused, not silently
# dropped, so a caller knows their file was not ingested.
_EXT_MIME = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".html": "text/html",
    ".htm": "text/html",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


# Cap the text sent to the curator (~12k tokens). A larger source still yields a good
# structured digest, and a smaller call is far less likely to hit the Gemini quota.
_CURATE_MAX_CHARS = 48000


def _title_from_filename(filename: str) -> str:
    stem = os.path.splitext(safe_filename(filename))[0]
    words = [w for w in stem.replace("_", " ").replace("-", " ").split() if w]
    return " ".join(w.capitalize() for w in words) or "Attachment"


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
        attachment_store: AttachmentStore | None = None,
        reviewer: Reviewer | None = None,
        reindexer: Reindexer | None = None,
        curator=None,
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
        # Where an uploaded original file is kept (so a document can link to it).
        self.attachment_store: AttachmentStore = attachment_store or MemoryAttachmentStore()
        # Promotes staged proposals to live; who may do so is checked here.
        self.reviewer: Reviewer = reviewer or MemoryReviewer()
        # Triggers the index rebuild after a live write (note/upload/accept), so new
        # content becomes searchable promptly instead of at the next scheduled build.
        self.reindexer: Reindexer = reindexer or MemoryReindexer()
        # The raw-to-wiki curator used to clean up a draft. Defaults to the offline
        # passthrough (no rewriting); the deployed brain sets BRAIN_CURATE=gemini so
        # the Studio "clean up with AI" toggle runs a real in-tenancy Gemini pass.
        from ..ingest.curate import get_curator

        self.curator = curator or get_curator()

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

    def visible_documents(self, identity: Identity) -> list[dict]:
        """Metadata for every document the caller may see (their domains + shared
        docs). Enough for the live UI to render the domain browser and link graph
        without exposing anything cross-domain."""
        domains = self._visible_domains(identity)
        extra = self._extra_doc_ids(identity)
        out = []
        for doc in self.index.documents.values():
            if doc.domain in domains or doc.doc_id in extra:
                out.append(
                    {
                        "doc_id": doc.doc_id,
                        "domain": doc.domain,
                        "title": doc.title,
                        "links": list(doc.links),
                        "tags": list(doc.tags),
                        "source": doc.source,
                        "source_url": doc.source_url,
                        "fetched_at": doc.fetched_at,
                    }
                )
        return out

    def list_domains(self, identity: Identity) -> list[str]:
        domains = self._visible_domains(identity)
        # Always advertise the caller's own personal space, even before it has any
        # content, so a client can discover it exists (and that add_note writes here).
        personal = personal_domain(identity)
        if personal:
            domains = domains | {personal}
        return sorted(domains)

    def _domain_kind(self, domain: str, identity: Identity, policy: Policy) -> str:
        """Classify a domain for the caller: personal, commons, team, or shared."""
        if is_personal_domain(domain):
            return "personal" if personal_owner(domain) == identity.subject else "shared"
        principals = set(identity.principals)
        for grant in policy.grants:
            if grant.principal == WILDCARD and domain in grant.domains:
                return "commons"
        if domain in policy.domains_for(principals):
            return "team"
        return "shared"

    def my_spaces(self, identity: Identity) -> dict:
        """A self-describing map of the caller's spaces and how to use them.

        The discovery affordance an MCP client needs: it names the caller's private
        personal domain (where add_note writes), the shared commons, the team domains
        they were granted, and anything shared with them, plus which tool does what.
        """
        policy = self._policy_source()
        doc_counts: dict[str, int] = {}
        for doc in self.index.documents.values():
            doc_counts[doc.domain] = doc_counts.get(doc.domain, 0) + 1

        personal = personal_domain(identity)
        buckets: dict[str, list] = {"commons": [], "team": [], "shared": []}
        for domain in sorted(self._visible_domains(identity)):
            if is_personal_domain(domain):
                continue
            kind = self._domain_kind(domain, identity, policy)
            buckets.setdefault(kind, []).append(
                {"domain": domain, "documents": doc_counts.get(domain, 0)}
            )

        shared_docs = sorted(self._extra_doc_ids(identity))
        return {
            "you": {"subject": identity.subject, "email": identity.email},
            "personal": {
                "domain": personal,
                "documents": doc_counts.get(personal, 0) if personal else 0,
                "how_to": "Private to you. Use add_note to save notes here; nobody else "
                "can see them until you share. Use share to share this space or a "
                "single document, unshare to revoke.",
            },
            "commons": buckets["commons"],
            "teams": buckets["team"],
            "shared_with_you": {"domains": buckets["shared"], "documents": shared_docs},
            "writable": sorted(writable_domains(identity, policy, self._shares())),
            "how_to": {
                "private_note": "add_note(title, content) -> your personal space",
                "team_document": "propose_document(domain, title, content) -> reviewed",
                "share": "share(principal, domain= or doc_id=) / unshare / list_shares",
            },
        }

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

    def add_document(
        self,
        identity: Identity,
        *,
        domain: str,
        title: str,
        content: str,
        source_url: str | None = None,
        tags: list[str] | None = None,
    ) -> ProposalResult:
        """Write a document LIVE into a domain the caller may write. A write grant is
        trust, so this is direct with no review, exactly like a personal note; the
        agent's ``propose_document`` path still stages to the review queue. Personal
        targets delegate to :meth:`add_note`."""
        if is_personal_domain(domain):
            return self.add_note(
                identity, title=title, content=content, source_url=source_url, tags=tags
            )
        with span(
            "brain.add_document",
            **{"brain.domain": domain, "brain.principal": identity.subject},
        ):
            writable = writable_domains(identity, self._policy_source())
            if not writable:
                raise WriteScopeError(
                    "identity has no write access (policy grant or propose scope)"
                )
            if domain not in writable:
                raise DomainNotAuthorized(domain)
            proposal = build_proposal(
                domain=domain,
                title=title,
                content=content,
                author=identity.email or identity.subject,
                source_url=source_url,
                tags=tags,
            )
            result = self.note_gate.submit(proposal)  # note_gate = live corpus write
            self.reindexer.trigger()
            return result

    # --- Personal notes and dynamic sharing (the overlay) ------------------------

    def add_note(
        self,
        identity: Identity,
        *,
        title: str,
        content: str,
        source_url: str | None = None,
        tags: list[str] | None = None,
    ) -> ProposalResult:
        """Write a note into the caller's own personal domain. Ungated: the caller
        owns this space, so there is nothing to review. The note is searchable once
        the index rebuilds (the path any content takes), same as commons content.

        The slug is derived from the title, so re-submitting a note with the same
        title overwrites it: that is how :meth:`link_notes` edits a note in place."""
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
                tags=tags,
            )
            result = self.note_gate.submit(proposal)
            self.reindexer.trigger()  # make the note searchable promptly
            return result

    # ---- Autolinker: suggest and create links among the caller's own notes -------
    def _personal_note_ids(self, identity: Identity) -> list[str]:
        personal = personal_domain(identity)
        if personal is None:
            return []
        return [d.doc_id for d in self.index.documents.values() if d.domain == personal]

    def suggest_note_links(self, identity: Identity, *, top_k: int = 8) -> list[dict]:
        """Candidate links among the caller's personal notes, by embedding similarity.

        Only the caller's own personal notes are considered (a link can only resolve
        within a domain), and pairs already linked are excluded. Each suggestion is a
        pair of notes with a similarity score; the caller decides which to create."""
        from .linker import suggest_links

        note_ids = self._personal_note_ids(identity)
        if len(note_ids) < 2:
            return []
        with span("brain.suggest_note_links", **{"brain.principal": identity.subject}):
            index = self.index
            pairs = suggest_links(index, note_ids, index.adjacency, top_k=top_k)
            docs = index.documents
            return [
                {
                    "source": a,
                    "target": b,
                    "source_title": docs[a].title,
                    "target_title": docs[b].title,
                    "score": round(score, 3),
                    "reason": "Semantically similar content",
                }
                for score, a, b in pairs
            ]

    def suggest_links_for_text(
        self, identity: Identity, text: str, *, domain: str | None = None, top_k: int = 6
    ) -> list[dict]:
        """Existing documents most similar to a draft, to link from it. Scoped to a
        domain the caller may read (links resolve within a domain), so the suggestions
        are only ever documents the draft could actually link to."""
        import numpy as np

        from .linker import _doc_vectors

        text = (text or "").strip()
        if not text:
            return []
        index = self.index
        personal = personal_domain(identity)
        visible = self._visible_domains(identity)
        if domain:
            targets = {domain} if (domain in visible or domain == personal) else set()
        else:
            targets = set(visible) | ({personal} if personal else set())
        candidate_ids = {d.doc_id for d in index.documents.values() if d.domain in targets}
        if not candidate_ids:
            return []
        with span("brain.suggest_links_for_text", **{"brain.principal": identity.subject}):
            vec = np.asarray(self.embeddings.embed([text])[0], dtype=np.float32)
            norm = float(np.linalg.norm(vec))
            vec = vec / norm if norm else vec
            doc_vectors = _doc_vectors(index, candidate_ids)
            scored = sorted(
                ((float(np.dot(vec, v)), doc_id) for doc_id, v in doc_vectors.items()),
                reverse=True,
            )
            return [
                {"doc_id": doc_id, "title": index.documents[doc_id].title, "score": round(s, 3)}
                for s, doc_id in scored[:top_k]
                if s >= 0.35
            ]

    @staticmethod
    def _strip_title(text: str, title: str) -> str:
        """Drop the leading ``# Title`` heading from a reconstructed note body, so a
        re-added note is not given a duplicate title heading."""
        head = f"# {title}"
        if text.startswith(head):
            return text[len(head) :].lstrip("\n")
        return text

    @staticmethod
    def _append_related(body: str, link_line: str) -> str:
        """Append a link under a ``## Related`` section, creating it if absent."""
        marker = "## Related"
        if marker in body:
            return f"{body.rstrip()}\n{link_line}\n"
        return f"{body.rstrip()}\n\n{marker}\n\n{link_line}\n"

    def link_notes(self, identity: Identity, source_id: str, target_id: str) -> dict:
        """Link one personal note to another by adding a ``[[wikilink]]`` to the
        source note (which the next index build turns into a graph edge).

        Both notes must be in the caller's own personal space; anything else is
        refused, matching the intra-domain rule the link graph already enforces."""
        personal = personal_domain(identity)
        if personal is None:
            raise AccessError("an anonymous caller has no personal space to link within")
        if source_id == target_id:
            raise ValueError("a note cannot be linked to itself")
        for doc_id in (source_id, target_id):
            if doc_id.rsplit("/", 1)[0] != personal:
                raise AccessError("you can only link notes in your own personal space")
        with span(
            "brain.link_notes",
            **{"brain.principal": identity.subject, "brain.doc_id": source_id},
        ):
            source = self.get_document(identity, source_id)  # also enforces visibility
            target = self.get_document(identity, target_id)
            wikilink = f"[[{target['title']}]]"
            body = self._strip_title(source["text"], source["title"])
            if wikilink in body:
                return {
                    "status": "exists",
                    "source": source_id,
                    "target": target_id,
                    "detail": "these notes are already linked",
                }
            new_body = self._append_related(body, f"- {wikilink}")
            result = self.add_note(
                identity, title=source["title"], content=new_body, tags=source.get("tags")
            )
            return {
                "status": "linked",
                "source": source_id,
                "target": target_id,
                "detail": result.detail,
            }

    def ingest_file(
        self,
        identity: Identity,
        *,
        filename: str,
        content_base64: str,
        domain: str | None = None,
        title: str | None = None,
        source_url: str | None = None,
    ) -> ProposalResult:
        """Ingest an uploaded file (PDF, Word, markdown, HTML, text) as a document.

        The file is parsed to markdown and indexed as text; the original is stored as
        a linked attachment. Defaults to the caller's personal space (ungated); a team
        domain goes through the reviewed propose path. Retrieval is text-only, so the
        extracted text is what becomes searchable, with the original kept downloadable.
        """
        try:
            raw = base64.b64decode(content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise AccessError("content must be base64-encoded file bytes") from exc

        ext = os.path.splitext(filename.lower())[1]
        mime = _EXT_MIME.get(ext)
        if not mime:
            raise AccessError(
                f"unsupported file type {ext or filename!r}; supported: .md .txt .html .pdf .docx"
            )

        personal = personal_domain(identity)
        target = domain or personal
        if not target:
            raise AccessError("no target domain, and an anonymous caller has no personal space")

        with span(
            "brain.ingest_file",
            **{"brain.domain": target, "brain.principal": identity.subject},
        ):
            from ..ingest.parsers import get_parser

            # Any parser failure (corrupt/unsupported content, or a format that needs
            # a component not configured here) becomes a clean client error, never a
            # 500. NotImplementedError covers the PDF-via-Document-AI stub when unset.
            try:
                body = get_parser(mime).parse(raw, mime).body.strip()
            except NotImplementedError as exc:
                raise ValueError(str(exc)) from exc
            except ValueError:
                raise  # the parser already produced a clean, user-facing message
            except Exception as exc:  # any other parser/library/cloud failure -> clean 400
                raise ValueError(f"could not read {filename}: {exc}") from exc
            if not body:
                raise ValueError(
                    "no text could be extracted (a scanned/image-only PDF needs Document AI)"
                )
            resolved_title = (title or _title_from_filename(filename)).strip() or filename

            uri = self.attachment_store.put(target, filename, raw)
            content = f"{body}\n\n> Ingested from [{safe_filename(filename)}]({uri})\n"

            if is_personal_domain(target):
                # Your own personal space: ungated, like add_note.
                if personal_owner(target) != identity.subject:
                    raise DomainNotAuthorized(target)
                proposal = build_proposal(
                    domain=target,
                    title=resolved_title,
                    content=content,
                    author=identity.email or identity.subject,
                    source_url=source_url or uri,
                )
                result = self.note_gate.submit(proposal)
                self.reindexer.trigger()  # searchable promptly, like add_note
                return result

        # A team domain: a write grant is trust, so this is a direct live write (the
        # agent's propose path still goes to review). add_document enforces the grant.
        return self.add_document(
            identity,
            domain=target,
            title=resolved_title,
            content=content,
            source_url=source_url or uri,
        )

    # ---- Draft-first ingestion: URL / file / text -> editable draft (no write) ----
    def _extract_upload_body(self, filename: str, content_base64: str) -> str:
        """Decode + parse an uploaded file to its text body (Document AI for scanned
        PDFs when configured). Shared by the draft flow; raises clean client errors."""
        try:
            raw = base64.b64decode(content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise AccessError("content must be base64-encoded file bytes") from exc
        ext = os.path.splitext(filename.lower())[1]
        mime = _EXT_MIME.get(ext)
        if not mime:
            raise AccessError(
                f"unsupported file type {ext or filename!r}; supported: .md .txt .html .pdf .docx"
            )
        from ..ingest.parsers import get_parser

        try:
            return get_parser(mime).parse(raw, mime).body.strip()
        except NotImplementedError as exc:
            raise ValueError(str(exc)) from exc
        except ValueError:
            raise  # the parser already produced a clean, user-facing message
        except Exception as exc:  # any other parser/library/cloud failure -> clean 400
            raise ValueError(f"could not read {filename}: {exc}") from exc

    def _known_titles(self, identity: Identity) -> list[str]:
        """Titles the caller can see, offered to the curator as wikilink targets."""
        return [d["title"] for d in self.visible_documents(identity)][:60]

    @staticmethod
    def _first_heading(body: str) -> str:
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip()
        return ""

    def make_draft(
        self,
        identity: Identity,
        *,
        kind: str,
        url: str | None = None,
        text: str | None = None,
        filename: str | None = None,
        content_base64: str | None = None,
        curate: bool = True,
    ) -> dict:
        """Turn a URL, file, or pasted text into an editable draft. Nothing is written:
        the caller reviews/edits, then creates it via add_note or propose_document."""
        from ..ingest.models import ParsedDoc

        kind = (kind or "").lower()
        source_url: str | None = None
        default_title = ""
        with span("brain.make_draft", **{"brain.kind": kind, "brain.principal": identity.subject}):
            if kind == "url":
                from .drafts import extract_main_text, fetch_url

                if not url or not url.strip():
                    raise ValueError("a URL is required")
                raw, mime = fetch_url(url.strip())
                if mime.split(";", 1)[0].strip().lower() in ("text/html", "application/xhtml+xml"):
                    default_title, body = extract_main_text(raw)
                else:
                    body = raw.decode("utf-8", errors="replace")
                source_url = url.strip()
            elif kind == "text":
                if not text or not text.strip():
                    raise ValueError("some text is required")
                body = text
            elif kind == "file":
                if not filename or not content_base64:
                    raise ValueError("a file is required")
                body = self._extract_upload_body(filename, content_base64)
                default_title = _title_from_filename(filename)
            else:
                raise ValueError(f"unknown draft source {kind!r}")

            body = body.strip()
            if not body:
                raise ValueError("no readable content was found at that source")

            curated = False
            tags: list[str] = []
            if curate:
                # Best-effort: a model error, safety block, or quota limit must never fail
                # the draft, so on any failure we keep the extracted content un-curated
                # (curated=false). A very large source is capped so it makes a smaller,
                # faster call that is far less likely to hit the per-minute token quota;
                # the prompt condenses it into a structured digest regardless.
                source = body[:_CURATE_MAX_CHARS]
                try:
                    cleaned = self.curator.curate(
                        ParsedDoc(body=source), self._known_titles(identity)
                    ).body.strip()
                    if cleaned and cleaned != source:
                        cleaned, tags = self._split_tags(cleaned)
                        body, curated = cleaned, True
                except Exception:  # noqa: BLE001 - enhancement, never fatal to the draft
                    curated = False

            title = (default_title or self._first_heading(body) or "Untitled draft").strip()[:120]
            return {
                "title": title,
                "content": body,
                "source_url": source_url,
                "curated": curated,
                "tags": tags,
            }

    @staticmethod
    def _split_tags(text: str) -> tuple[str, list[str]]:
        """Split a trailing 'Tags: a, b, c' line off the curated markdown."""
        lines = text.rstrip().splitlines()
        if lines and lines[-1].strip().lower().startswith("tags:"):
            raw = lines[-1].split(":", 1)[1]
            tags = [t.strip().lower().lstrip("#") for t in raw.split(",") if t.strip()][:6]
            return "\n".join(lines[:-1]).rstrip(), tags
        return text, []

    def simplify_text(self, identity: Identity, text: str) -> dict:
        """Rewrite a draft in plain language for a newcomer (best-effort, on demand)."""
        text = (text or "").strip()
        if not text:
            raise ValueError("some text is required")
        instruction = (
            "Rewrite the following markdown in plain, simple language for someone new to "
            "the topic. Keep the same structure, headings and facts, but use short "
            "sentences and explain any jargon. Return only the markdown, no preamble."
        )
        with span("brain.simplify_text", **{"brain.principal": identity.subject}):
            try:
                rewritten = self.curator.rewrite(text[:_CURATE_MAX_CHARS], instruction).strip()
                return {"content": rewritten or text, "simplified": bool(rewritten)}
            except Exception:  # noqa: BLE001 - best-effort, never fatal
                return {"content": text, "simplified": False}

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

    # --- Review queue: promote staged proposals (write access = review access) -----

    def _writable(self, identity: Identity) -> set[str]:
        return writable_domains(identity, self._policy_source(), self._shares())

    def list_proposals(self, identity: Identity) -> list[dict]:
        """Staged proposals the caller may review: those in domains they can write.

        A caller with no write access sees an empty queue (and the UI hides the tab).
        """
        writable = self._writable(identity)
        return [
            {"name": ref.name, "domain": ref.domain, "dest": ref.dest}
            for ref in self.reviewer.list_proposals()
            if ref.domain in writable
        ]

    def accept_proposal(self, identity: Identity, name: str) -> dict:
        """Promote a staged proposal to live and reindex. The caller must have write
        access to the proposal's domain; otherwise it is refused (and, for a domain
        they cannot even see, indistinguishable from a missing proposal)."""
        domain = proposal_domain(name)
        writable = self._writable(identity)
        with span(
            "brain.accept_proposal",
            **{"brain.domain": domain, "brain.principal": identity.subject},
        ):
            if domain not in writable:
                raise DomainNotAuthorized(domain)
            dest = self.reviewer.accept(name)
            self.reindexer.trigger()  # promote + rebuild so it is searchable promptly
            return {"accepted": name, "dest": dest, "domain": domain}
