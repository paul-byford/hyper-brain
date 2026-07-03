"""Source adapters, registered by ``type`` and configured in sources.yaml.

We ship three demo adapters (local files, web/URL, git repo). The bank extends
with its own by implementing ``SourceAdapter`` and registering a type here.
"""

from __future__ import annotations

from .base import SourceAdapter
from .git import GitAdapter
from .local import LocalAdapter
from .web import WebAdapter

__all__ = ["SourceAdapter", "GitAdapter", "LocalAdapter", "WebAdapter", "build_adapter"]


def build_adapter(source_type: str, source_id: str, options: dict) -> SourceAdapter:
    """Construct the adapter for a configured source.

    ``options`` is the adapter-specific config slice from sources.yaml. Each
    branch names the keys it reads, so a misconfigured source fails loudly here
    rather than deep in a fetch.
    """
    if source_type == "local":
        return LocalAdapter(source_id, path=options["path"], glob=options.get("glob", "*.md"))
    if source_type == "web":
        return WebAdapter(source_id, urls=options["urls"])
    if source_type == "git":
        return GitAdapter(
            source_id,
            repo=options["repo"],
            ref=options.get("ref"),
            glob=options.get("glob", "*.md"),
        )
    raise ValueError(f"unknown source type {source_type!r} for source {source_id!r}")
