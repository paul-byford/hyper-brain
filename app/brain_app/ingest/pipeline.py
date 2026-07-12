"""The source-agnostic ingestion pipeline.

Per item: ``parse -> optional curate -> stamp provenance -> land``. Landing is an
idempotent upsert keyed by a checksum of the document body, so re-running
converges rather than duplicating (the same discipline as ``brain index``). The
domain is taken from the source's config and validated on the way out: the landed
path must sit inside ``corpus/<domain>/`` and its frontmatter domain must match,
so an adapter can never breach the isolation boundary of section 7.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import re
import uuid
from pathlib import Path

import yaml

from ..indexer.chunk import parse_frontmatter
from .adapters import build_adapter
from .curate import Curator, PassthroughCurator, get_curator
from .models import SKIPPED, UPDATED, WRITTEN, IngestReport, LandResult, ParsedDoc, RawItem
from .pii import scan_pii
from .sources import SourceConfig
from .state import SourceState

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    """A filesystem- and domain-safe slug: lowercase, ``[a-z0-9-]`` only.

    Stripping every path separator and dot here is also the first line of the
    isolation defence: an ``identifier`` like ``../other-domain/x`` cannot survive
    into a path that escapes the domain folder.
    """
    slug = _SLUG_STRIP.sub("-", value.strip().lower()).strip("-")
    return slug or "untitled"


def _title_from(identifier: str) -> str:
    stem = Path(identifier.split("?", 1)[0]).stem or identifier
    words = re.split(r"[-_\s]+", stem.strip())
    return " ".join(w.capitalize() for w in words if w) or "Untitled"


def _canonical_body(body: str) -> str:
    """Normalise a body so an unchanged source produces an unchanged checksum."""
    return body.strip() + "\n"


def _checksum(canonical_body: str) -> str:
    return hashlib.sha256(canonical_body.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")


def _new_run_id() -> str:
    return f"ingest-{uuid.uuid4().hex[:12]}"


def _stamp(
    *,
    title: str,
    domain: str,
    tags: list[str],
    source_id: str,
    source_url: str,
    fetched_at: str,
    checksum: str,
    run_id: str,
    canonical_body: str,
    doc_type: str = "Note",
) -> str:
    """Build the landed markdown: Open Knowledge Format frontmatter plus body.

    Leads with OKF's one required field, ``type``, then ``title`` / ``tags``; our
    provenance (``source``, ``source_url``, ``fetched_at``, ``checksum``,
    ``ingest_run``) rides along as OKF producer extensions, so a reader and the
    Explorer UI can see where a fact came from and re-ingestion stays idempotent by
    ``checksum``. The result is a conformant OKF concept (see docs/LINEAGE.md).
    """
    meta: dict[str, object] = {"type": doc_type or "Note", "title": title, "domain": domain}
    if tags:
        meta["tags"] = tags
    meta["source"] = source_id
    meta["source_url"] = source_url
    meta["fetched_at"] = fetched_at
    meta["checksum"] = checksum
    meta["ingest_run"] = run_id
    front = yaml.safe_dump(meta, sort_keys=False, default_flow_style=False, allow_unicode=True)
    return f"---\n{front}---\n\n{canonical_body}"


# A corpus is either a local directory or a GCS bucket. Landing goes through this
# narrow store so the same pipeline persists locally (dev/personal) or in-tenancy
# (the Cloud Run ingest Job writes straight to the corpus bucket).
class _LocalCorpus:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def path(self, rel: str) -> str:
        return str(self.root / rel)

    def exists(self, rel: str) -> bool:
        return (self.root / rel).is_file()

    def read_text(self, rel: str) -> str:
        return (self.root / rel).read_text(encoding="utf-8")

    def write_text(self, rel: str, content: str) -> None:
        target = self.root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


class _GcsCorpus:
    def __init__(self, uri: str) -> None:
        self.bucket, _, self.prefix = uri[len("gs://") :].partition("/")

    def _name(self, rel: str) -> str:
        return f"{self.prefix.rstrip('/')}/{rel}" if self.prefix else rel

    def _blob(self, rel: str):
        from google.cloud import storage

        return storage.Client().bucket(self.bucket).blob(self._name(rel))

    def path(self, rel: str) -> str:
        return f"gs://{self.bucket}/{self._name(rel)}"

    def exists(self, rel: str) -> bool:
        return self._blob(rel).exists()

    def read_text(self, rel: str) -> str:
        return self._blob(rel).download_as_text()

    def write_text(self, rel: str, content: str) -> None:
        self._blob(rel).upload_from_string(content)


def _corpus_store(corpus_dir: str | Path):
    if str(corpus_dir).startswith("gs://"):
        return _GcsCorpus(str(corpus_dir))
    return _LocalCorpus(corpus_dir)


# A landed document is always <domain>/<slug>.md with a clean single-segment slug.
_SAFE_SLUG = re.compile(r"[a-z0-9-]+")

# Map an ingest adapter to a sensible Open Knowledge Format concept ``type``.
_OKF_TYPE = {"local": "Note", "web": "Web article", "git": "Reference"}


def _land(
    parsed: ParsedDoc,
    item: RawItem,
    source: SourceConfig,
    store,
    *,
    known_checksum: str | None,
    run_id: str,
    now: str,
) -> LandResult:
    domain = source.domain
    canonical = _canonical_body(parsed.body)
    checksum = _checksum(canonical)

    title = parsed.title or _title_from(item.identifier)
    slug = _slugify(parsed.title or Path(item.identifier).stem or item.identifier)

    # Isolation guard: the slug must be a single clean path segment, so a landed
    # document can never escape its domain folder (holds for local and GCS alike).
    if not _SAFE_SLUG.fullmatch(slug):
        raise ValueError(
            f"source {source.id!r}: refusing to land {item.identifier!r} outside domain {domain!r}"
        )

    rel = f"{domain}/{slug}.md"
    doc_id = f"{domain}/{slug}"

    # Idempotent upsert. If the cursor already recorded this checksum and the object
    # is still present, nothing changed: leave it untouched so its original
    # fetched_at/ingest_run are preserved.
    if known_checksum == checksum and store.exists(rel):
        return LandResult(doc_id, store.path(rel), SKIPPED, checksum)

    status = WRITTEN
    if store.exists(rel):
        existing_meta, _ = parse_frontmatter(store.read_text(rel))
        if existing_meta.get("checksum") == checksum:
            return LandResult(doc_id, store.path(rel), SKIPPED, checksum)
        status = UPDATED

    content = _stamp(
        title=title,
        domain=domain,
        tags=parsed.tags,
        source_id=source.id,
        source_url=item.source_url,
        fetched_at=now,
        checksum=checksum,
        run_id=run_id,
        canonical_body=canonical,
        doc_type=_OKF_TYPE.get(source.type, "Note"),
    )
    store.write_text(rel, content)
    return LandResult(doc_id, store.path(rel), status, checksum)


def ingest_source(
    source: SourceConfig,
    corpus_dir: str | Path,
    *,
    state_dir: str | Path | None = None,
    curator: Curator | None = None,
    run_id: str | None = None,
    now: str | None = None,
) -> IngestReport:
    """Run the pipeline for one configured source and return what it landed.

    ``corpus_dir`` may be a local path or a ``gs://`` bucket; landing goes to either.
    """
    store = _corpus_store(corpus_dir)
    active_curator = curator or (get_curator() if source.curate else PassthroughCurator())
    adapter = build_adapter(source.type, source.id, source.options)
    state = SourceState(source.id, state_dir)
    run_id = run_id or _new_run_id()
    now = now or _utc_now()

    results: list[LandResult] = []
    for item in adapter.fetch():
        parser_doc = _parse_and_curate(item, source, active_curator)
        canonical = _canonical_body(parser_doc.body)
        checksum = _checksum(canonical)

        findings = scan_pii(canonical)
        if findings:
            kinds = ", ".join(sorted({f.kind for f in findings}))
            print(f"  ! PII in {source.id}:{item.identifier} ({kinds}); landing anyway, review it")

        result = _land(
            parser_doc,
            item,
            source,
            store,
            known_checksum=state.checksum_for(item.identifier),
            run_id=run_id,
            now=now,
        )
        state.record(item.identifier, checksum)
        results.append(result)

    state.save()
    return IngestReport(source_id=source.id, domain=source.domain, results=results)


def _parse_and_curate(item: RawItem, source: SourceConfig, curator: Curator) -> ParsedDoc:
    # Imported here to keep the parser registry (which lazily pulls the cloud PDF
    # parser) off the module import path of the offline core.
    from .parsers import get_parser

    parsed = get_parser(item.mime).parse(item.content, item.mime)
    if source.curate:
        parsed = curator.curate(parsed)
    return parsed


def ingest_all(
    sources_path: str | Path,
    corpus_dir: str | Path,
    *,
    state_dir: str | Path | None = None,
    run_id: str | None = None,
    now: str | None = None,
) -> list[IngestReport]:
    """Ingest every source in a sources.yaml file."""
    from .sources import load_sources

    run_id = run_id or _new_run_id()
    return [
        ingest_source(
            source,
            corpus_dir,
            state_dir=state_dir,
            run_id=run_id,
            now=now,
        )
        for source in load_sources(sources_path)
    ]
