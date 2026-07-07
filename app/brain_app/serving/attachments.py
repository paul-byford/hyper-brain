"""Where an uploaded original file is kept when a document is ingested from it.

Retrieval is text-only, so an uploaded PDF or Word file is parsed to markdown and
indexed as text; the *original* rides along here so it stays downloadable and the
generated document can link to it. Attachments live next to their domain's content
in the corpus bucket (``{domain}/{filename}``), which the indexer ignores because it
only globs ``*.md`` -- so an attachment never becomes a phantom document.
"""

from __future__ import annotations

import os
import re
from typing import Protocol, runtime_checkable

# Keep a caller-supplied filename to a safe leaf (no path traversal, no separators).
_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def safe_filename(filename: str) -> str:
    leaf = filename.replace("\\", "/").rsplit("/", 1)[-1].strip() or "attachment"
    return _SAFE.sub("_", leaf)


@runtime_checkable
class AttachmentStore(Protocol):
    def put(self, domain: str, filename: str, content: bytes) -> str:
        """Store the original bytes and return a reference (a URI or path)."""
        ...


class MemoryAttachmentStore:
    """In-process store; the default and the test double."""

    def __init__(self) -> None:
        self.saved: dict[str, bytes] = {}

    def put(self, domain: str, filename: str, content: bytes) -> str:
        key = f"{domain}/{safe_filename(filename)}"
        self.saved[key] = content
        return f"memory://{key}"


class GcsAttachmentStore:
    """Stores the original alongside its domain's content in the corpus bucket."""

    def __init__(self, bucket: str) -> None:
        self.bucket = bucket

    def put(self, domain: str, filename: str, content: bytes) -> str:
        from google.cloud import storage

        name = f"{domain}/{safe_filename(filename)}"
        storage.Client().bucket(self.bucket).blob(name).upload_from_string(content)
        return f"gs://{self.bucket}/{name}"


def get_attachment_store() -> AttachmentStore:
    """GCS when a corpus bucket is configured (deployed), else in-process."""
    bucket = os.environ.get("BRAIN_CORPUS_BUCKET")
    return GcsAttachmentStore(bucket) if bucket else MemoryAttachmentStore()
