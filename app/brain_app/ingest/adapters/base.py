from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from ..models import RawItem


@runtime_checkable
class SourceAdapter(Protocol):
    """Pulls raw items and their provenance from a single source.

    This is the first extension seam and the whole point of the design: adding a
    source (Confluence, Jira, SharePoint, GCS, ...) is implementing this one
    method plus a config entry, with no change to the retrieval core. An adapter
    is constructed with its own config slice and knows nothing about domains,
    landing, or isolation; the pipeline owns all of that.
    """

    def fetch(self) -> Iterable[RawItem]: ...
