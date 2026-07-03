"""Local-files adapter: the ``raw/`` drop, the Karpathy pattern.

Point it at a directory, drop files in, ingest. The stable identifier is the path
relative to the configured root, so re-dropping an edited file updates the same
landed document instead of creating a second one.
"""

from __future__ import annotations

import mimetypes
from collections.abc import Iterable
from pathlib import Path

from ..models import RawItem

# Map the extensions we care about to the MIME types the parser registry keys on.
_EXT_MIME = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".html": "text/html",
    ".htm": "text/html",
    ".pdf": "application/pdf",
}


class LocalAdapter:
    def __init__(self, source_id: str, *, path: str, glob: str = "*.md") -> None:
        self.source_id = source_id
        self.root = Path(path)
        self.glob = glob

    def _mime(self, path: Path) -> str:
        ext = path.suffix.lower()
        if ext in _EXT_MIME:
            return _EXT_MIME[ext]
        guessed, _ = mimetypes.guess_type(path.name)
        return guessed or "text/plain"

    def fetch(self) -> Iterable[RawItem]:
        if not self.root.is_dir():
            raise NotADirectoryError(f"local source {self.source_id!r}: {self.root} is not a dir")
        for path in sorted(self.root.rglob(self.glob)):
            if not path.is_file():
                continue
            identifier = path.relative_to(self.root).as_posix()
            yield RawItem(
                identifier=identifier,
                content=path.read_bytes(),
                mime=self._mime(path),
                source_url=path.resolve().as_uri(),
                title=None,
            )
