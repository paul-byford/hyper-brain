"""Export the data the Brain Explorer SPA renders: the index artefact and the
policy (for the identity/isolation panel).

The UI holds no secrets and enforces nothing (ARCHITECTURE.md section 9): it
renders this data. In a live deployment the same artefacts come from the brain /
the index bucket; here they are exported locally so the SPA runs with no cloud.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from brain_app.config import load_policy
from brain_app.embeddings.fake import FakeEmbeddings
from brain_app.indexer.build import build_index


def export(index_path: str, corpus: str, profile: str, out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Index: reuse a prebuilt artefact if present, else build one offline.
    src = Path(index_path)
    if src.is_file():
        shutil.copyfile(src, out / "index.json")
    else:
        build_index(corpus, embeddings=FakeEmbeddings(), provider_name="fake").save(out / "index.json")

    # Policy: the identity panel needs principals -> domains to show isolation.
    policy = load_policy(prof=profile)
    payload = {
        "profile": profile,
        "version": policy.version,
        "domains": list(policy.domains),
        "grants": [{"principal": g.principal, "domains": list(g.domains)} for g in policy.grants],
    }
    (out / "policy.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"Exported UI data to {out}/ (index.json, policy.json)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export data for the Brain Explorer UI.")
    parser.add_argument("--index", default=".brain/index.json")
    parser.add_argument("--corpus", default="corpus")
    parser.add_argument("--profile", default="personal")
    parser.add_argument("--out", default="ui/data")
    args = parser.parse_args(argv)
    export(args.index, args.corpus, args.profile, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
