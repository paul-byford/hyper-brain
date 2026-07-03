from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import ParsedDoc


@runtime_checkable
class Parser(Protocol):
    """Turns raw bytes of a known content type into clean markdown.

    This is the second extension seam (after ``SourceAdapter``). Rich formats are
    added by implementing this one method; the pipeline never cares how a byte
    stream became markdown, only that it did.
    """

    def parse(self, content: bytes, mime: str) -> ParsedDoc: ...
