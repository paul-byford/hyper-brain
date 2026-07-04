"""Build the index artefact from a corpus directory.

Layout expected:

    corpus/
      domains.yaml            (optional registry, not required to build)
      <domain>/*.md
      <other-domain>/*.md

The build is deterministic and idempotent: the same corpus and provider produce
an identical artefact, and re-running never duplicates chunks. Idempotency is by
content hash, so a re-index is a no-op when nothing changed.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import numpy as np

from ..embeddings import get_embeddings
from ..embeddings.base import EmbeddingProvider
from ..models import Chunk, Document
from ..retrieval.index import BrainIndex
from .chunk import build_chunks, load_document
from .graph import build_adjacency, resolve_links


def _content_hash(pairs: list[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for rel_path, text in sorted(pairs):
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(text.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def load_corpus(
    corpus_dir: str | Path,
) -> tuple[dict[str, Document], list[Chunk], dict[str, list[str]], str]:
    """Load and chunk a corpus. Returns (documents, chunks, adjacency, content_hash)."""
    corpus_path = Path(corpus_dir)
    if not corpus_path.is_dir():
        raise NotADirectoryError(f"corpus directory not found: {corpus_path}")

    raw_documents: list[Document] = []
    bodies: dict[str, str] = {}
    hash_pairs: list[tuple[str, str]] = []

    for domain_dir in sorted(p for p in corpus_path.iterdir() if p.is_dir()):
        domain = domain_dir.name
        for md_path in sorted(domain_dir.glob("*.md")):
            document, body = load_document(md_path, domain_hint=domain)
            if document.domain != domain:
                raise ValueError(
                    f"{md_path}: frontmatter domain {document.domain!r} does not match "
                    f"folder {domain!r}"
                )
            if document.doc_id in bodies:
                raise ValueError(f"duplicate doc_id {document.doc_id!r} ({md_path})")
            raw_documents.append(document)
            bodies[document.doc_id] = body
            hash_pairs.append((str(md_path.relative_to(corpus_path)), md_path.read_text("utf-8")))

    documents = resolve_links(raw_documents)
    adjacency = build_adjacency(documents)

    chunks: list[Chunk] = []
    for document in documents:
        chunks.extend(build_chunks(document, bodies[document.doc_id]))

    documents_by_id = {d.doc_id: d for d in documents}
    return documents_by_id, chunks, adjacency, _content_hash(hash_pairs)


def _materialise_corpus(corpus_dir: str | Path) -> str | Path:
    """Return a local corpus path, downloading from GCS first if given a gs:// URI.

    Lets the cloud index Job read the corpus bucket (source content stays
    in-tenancy) while load_corpus stays a simple local-directory walk.
    """
    if not str(corpus_dir).startswith("gs://"):
        return corpus_dir

    import tempfile

    from google.cloud import storage

    bucket_name, _, prefix = str(corpus_dir)[len("gs://") :].partition("/")
    client = storage.Client()
    tmp = Path(tempfile.mkdtemp(prefix="brain-corpus-"))
    for blob in client.list_blobs(bucket_name, prefix=prefix):
        if blob.name.endswith("/"):
            continue
        rel = blob.name[len(prefix) :].lstrip("/") if prefix else blob.name
        dest = tmp / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(dest))
    return tmp


def build_index(
    corpus_dir: str | Path,
    embeddings: EmbeddingProvider | None = None,
    provider_name: str | None = None,
) -> BrainIndex:
    documents, chunks, adjacency, content_hash = load_corpus(_materialise_corpus(corpus_dir))
    provider = embeddings or get_embeddings(provider_name)
    vectors = (
        np.asarray(provider.embed([c.text for c in chunks]), dtype=np.float32)
        if chunks
        else np.zeros((0, provider.dim), dtype=np.float32)
    )
    return BrainIndex(
        chunks=chunks,
        embeddings=vectors,
        documents=documents,
        adjacency=adjacency,
        embedding_dim=provider.dim,
        provider=provider_name or type(provider).__name__,
        content_hash=content_hash,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a hyper-brain index artefact.")
    parser.add_argument("--corpus", default="corpus", help="corpus directory")
    parser.add_argument("--out", default=".brain/index.json", help="output artefact path")
    args = parser.parse_args(argv)

    index = build_index(args.corpus)
    index.save(args.out)
    print(
        f"Built index: {len(index.chunks)} chunks across {len(index.domains)} domains "
        f"({len(index.documents)} documents) -> {args.out}"
    )
    print(f"content_hash={index.content_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
