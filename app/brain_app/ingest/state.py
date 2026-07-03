"""Per-source ingestion cursor.

Records, per source, the checksum last landed for each item identifier. Re-runs
consult it so only changed items are rewritten: the same idempotency discipline
as the indexer's content hash, applied at the item level. State is a small JSON
file per source; deleting it forces a full re-land (which converges to the same
corpus, since landing is itself idempotent).
"""

from __future__ import annotations

import json
from pathlib import Path

# Default location for cursors. Kept out of the corpus so it is never indexed.
DEFAULT_STATE_DIR = Path(".brain") / "ingest-state"


class SourceState:
    def __init__(self, source_id: str, state_dir: str | Path | None = None) -> None:
        self.source_id = source_id
        base = Path(state_dir) if state_dir is not None else DEFAULT_STATE_DIR
        self.path = base / f"{source_id}.json"
        self._checksums: dict[str, str] = {}
        if self.path.is_file():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._checksums = dict(data.get("checksums", {}))

    def checksum_for(self, identifier: str) -> str | None:
        return self._checksums.get(identifier)

    def record(self, identifier: str, checksum: str) -> None:
        self._checksums[identifier] = checksum

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"source_id": self.source_id, "checksums": self._checksums}
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
