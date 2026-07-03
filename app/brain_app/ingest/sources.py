"""Source configuration: the adapter registry's input.

``config/sources.yaml`` lists sources, each assigning a ``type`` (which adapter),
a ``domain`` (the isolation boundary the pipeline enforces), and adapter-specific
options. Domain lives here, in config, not in source content, which is what lets
the pipeline guarantee an adapter cannot land outside its configured domain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

_KNOWN = {"id", "type", "domain", "curate"}


@dataclass(frozen=True)
class SourceConfig:
    id: str
    type: str
    domain: str
    curate: bool = False
    # Adapter-specific options (path, urls, repo, ...), everything not in _KNOWN.
    options: dict = field(default_factory=dict)


def load_sources(path: str | Path) -> list[SourceConfig]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    sources: list[SourceConfig] = []
    seen: set[str] = set()
    for entry in data.get("sources", []):
        source_id = entry["id"]
        if source_id in seen:
            raise ValueError(f"duplicate source id {source_id!r} in {path}")
        seen.add(source_id)
        options = {k: v for k, v in entry.items() if k not in _KNOWN}
        sources.append(
            SourceConfig(
                id=source_id,
                type=entry["type"],
                domain=entry["domain"],
                curate=bool(entry.get("curate", False)),
                options=options,
            )
        )
    return sources
