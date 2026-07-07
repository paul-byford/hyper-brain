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


def export(
    index_path: str,
    corpus: str,
    profile: str,
    out_dir: str,
    mcp_url: str = "",
    auth_url: str = "",
    api_url: str = "",
) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Index: reuse a prebuilt artefact if present, else build one offline.
    src = Path(index_path)
    if src.is_file():
        shutil.copyfile(src, out / "index.json")
    else:
        build_index(corpus, embeddings=FakeEmbeddings(), provider_name="fake").save(
            out / "index.json"
        )

    # Policy: the identity panel needs principals -> domains to show isolation.
    policy = load_policy(prof=profile)
    payload = {
        "profile": profile,
        "version": policy.version,
        "domains": list(policy.domains),
        "grants": [
            {"principal": g.principal, "domains": list(g.domains)}
            for g in policy.grants
        ],
    }
    (out / "policy.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # Config the SPA needs but that isn't in the index: the deployed MCP endpoint
    # (connector modal), and for the live app the OAuth issuer + REST base it signs in
    # against and calls. Empty in local runs, so the UI stays in demo mode there.
    config = {
        "mcp_url": mcp_url or "https://<your-brain>.run.app/mcp",
        "auth_url": auth_url,  # OAuth AS issuer, for browser sign-in (PKCE)
        "api_url": api_url,  # brain REST facade base; live mode when set
    }
    (out / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    print(f"Exported UI data to {out}/ (index.json, policy.json, config.json)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export data for the Brain Explorer UI."
    )
    parser.add_argument("--index", default=".brain/index.json")
    parser.add_argument("--corpus", default="corpus")
    parser.add_argument("--profile", default="personal")
    parser.add_argument("--out", default="ui/data")
    parser.add_argument(
        "--mcp-url",
        default="",
        help="Deployed brain MCP endpoint for the connector modal.",
    )
    parser.add_argument(
        "--auth-url", default="", help="OAuth AS issuer URL for browser sign-in."
    )
    parser.add_argument(
        "--api-url", default="", help="Brain REST facade base URL (enables live mode)."
    )
    args = parser.parse_args(argv)
    export(
        args.index,
        args.corpus,
        args.profile,
        args.out,
        args.mcp_url,
        args.auth_url,
        args.api_url,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
