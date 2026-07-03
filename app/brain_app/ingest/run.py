"""``python -m brain_app.ingest.run``: run batch ingestion for configured sources.

Offline and idempotent. Turns dropped/configured sources into provenance-stamped
markdown under ``corpus/``; because the corpus is under git, the resulting diff is
itself the review surface (the review gate; ARCHITECTURE.md section 12). Re-running
converges rather than duplicating.
"""

from __future__ import annotations

import argparse

from .pipeline import ingest_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run hyper-brain batch ingestion.")
    parser.add_argument("--sources", default="config/sources.yaml", help="sources config file")
    parser.add_argument("--corpus", default="corpus", help="corpus directory to land into")
    parser.add_argument(
        "--state",
        default=None,
        help="ingestion cursor directory (defaults to .brain/ingest-state)",
    )
    args = parser.parse_args(argv)

    reports = ingest_all(args.sources, args.corpus, state_dir=args.state)

    total_new = total_updated = total_skipped = 0
    for report in reports:
        print(report.summary())
        total_new += report.written
        total_updated += report.updated
        total_skipped += report.skipped

    print(
        f"Ingestion complete: {total_new} new, {total_updated} updated, "
        f"{total_skipped} unchanged. Review the corpus diff, then rebuild the index."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
