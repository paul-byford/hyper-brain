"""Accept a reviewed proposal into the live corpus, then reindex.

``propose_document`` stages a document under ``proposals/{domain}/{slug}-{hash}.md``
in the corpus bucket: quarantined, never live (ARCHITECTURE.md section 12).
Acceptance is a deliberate human step. This moves an approved proposal into its live
domain folder and (optionally) runs the index Job so it becomes searchable within
the index TTL. It drives the ``gcloud`` CLI (already required to deploy), so it adds
no Python cloud dependency and uses the operator's own credentials.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess  # nosec B404 - drives the gcloud CLI the operator already uses
import sys

# The stage path is ``{prefix}/{domain}/{slug}-{checksum8}.md``; the live path drops
# the prefix and the ``-{checksum8}`` suffix, landing at ``{domain}/{slug}.md``.
_HASH_SUFFIX = re.compile(r"-[0-9a-f]{8}(?=\.md$)")


def live_name(proposal_name: str, prefix: str = "proposals") -> str:
    """Map ``proposals/{domain}/{slug}-{hash}.md`` to ``{domain}/{slug}.md``."""
    name = proposal_name
    marker = prefix.strip("/") + "/"
    if name.startswith(marker):
        name = name[len(marker) :]
    return _HASH_SUFFIX.sub("", name)


def _gcloud(*args: str, capture: bool = True) -> str:
    # Resolve the full path so this works on Windows, where gcloud is ``gcloud.cmd``
    # and subprocess (unlike a shell) does not search PATHEXT for a bare name.
    exe = shutil.which("gcloud")
    if not exe:
        raise FileNotFoundError("gcloud CLI not found on PATH (install the Google Cloud CLI)")
    # capture=True to parse output; capture=False to let gcloud stream its own live
    # progress to the terminal (so a slow step is not a silent freeze).
    result = subprocess.run(  # nosec B603 - fixed argv, no shell, operator's gcloud
        [exe, *args], check=True, capture_output=capture, text=True
    )
    return result.stdout or "" if capture else ""


def list_proposals(bucket: str, prefix: str = "proposals") -> list[str]:
    """The bucket-relative names of every staged proposal awaiting review."""
    try:
        out = _gcloud("storage", "ls", "-r", f"gs://{bucket}/{prefix.strip('/')}/")
    except subprocess.CalledProcessError:
        return []
    marker = f"gs://{bucket}/"
    names = []
    for line in out.splitlines():
        line = line.strip()
        if line.endswith(".md") and line.startswith(marker):
            names.append(line[len(marker) :])
    return names


def resolve_proposal(name: str, proposals: list[str], prefix: str = "proposals") -> str:
    """Return the staged proposal path for ``name``, which may be given either as the
    staged path (``proposals/...``) or as the live destination path (the right-hand
    side ``brain review`` prints). Raises if it cannot be matched unambiguously."""
    marker = prefix.strip("/") + "/"
    if name.startswith(marker):
        return name
    matches = [p for p in proposals if live_name(p, prefix) == name]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise FileNotFoundError(
            f"no staged proposal matches {name!r}; pass a name from `brain review` "
            f"(either the '{marker}...' path or its destination)"
        )
    raise ValueError(
        f"{name!r} is ambiguous ({len(matches)} proposals map to it); pass the exact "
        f"'{marker}...' path from `brain review`"
    )


def accept(
    bucket: str,
    proposal: str,
    *,
    prefix: str = "proposals",
    indexer_job: str | None = None,
    project: str | None = None,
    region: str | None = None,
    wait: bool = False,
) -> str:
    """Promote one proposal to its live path and, if given a Job, reindex.

    ``proposal`` may be the staged path or its live destination (either column of
    ``brain review``); a live path is resolved back to its staged proposal. The index
    job is kicked off asynchronously by default (the brain reloads within its TTL);
    pass ``wait=True`` to block until it finishes.
    """
    name = proposal
    uri_prefix = f"gs://{bucket}/"
    if name.startswith(uri_prefix):
        name = name[len(uri_prefix) :]
    print("Locating the proposal ...", flush=True)
    name = resolve_proposal(name, list_proposals(bucket, prefix), prefix)
    dest = live_name(name, prefix)

    print(f"Moving into the live domain: {dest}", flush=True)
    _gcloud("storage", "mv", f"gs://{bucket}/{name}", f"gs://{bucket}/{dest}", capture=False)

    if indexer_job:
        args = ["run", "jobs", "execute", indexer_job]
        if wait:
            args.append("--wait")
            print(f"Rebuilding the index (job {indexer_job}); waiting for it ...", flush=True)
        else:
            print(f"Starting the index rebuild (job {indexer_job}) in the background ...")
        if project:
            args += ["--project", project]
        if region:
            args += ["--region", region]
        _gcloud(*args, capture=False)
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review and accept staged proposals.")
    parser.add_argument("action", choices=["list", "accept"])
    parser.add_argument("--bucket", required=True, help="corpus bucket name")
    parser.add_argument("--name", help="proposal to accept (bucket-relative or gs:// URI)")
    parser.add_argument("--prefix", default="proposals")
    parser.add_argument("--indexer-job", help="Cloud Run indexer Job to run after accepting")
    parser.add_argument("--project")
    parser.add_argument("--region")
    parser.add_argument(
        "--wait", action="store_true", help="block until the index rebuild finishes"
    )
    args = parser.parse_args(argv)

    if args.action == "list":
        names = list_proposals(args.bucket, args.prefix)
        if not names:
            print("No proposals awaiting review.")
            return 0
        print(f"{len(names)} proposal(s) awaiting review:")
        for name in names:
            print(f"  {name}")
            print(f"      -> would land at: {live_name(name, args.prefix)}")
        print("\nAccept one by passing its name (either line) to: brain accept <name>")
        return 0

    if not args.name:
        parser.error("accept requires --name")
    try:
        dest = accept(
            args.bucket,
            args.name,
            prefix=args.prefix,
            indexer_job=args.indexer_job,
            project=args.project,
            region=args.region,
            wait=args.wait,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"Could not accept: {exc}", file=sys.stderr)
        return 1
    print(f"\nAccepted -> gs://{args.bucket}/{dest}")
    if not args.indexer_job:
        print("Run the index job to make it searchable.")
    elif args.wait:
        print("Reindexed; the document is now searchable.")
    else:
        print("Index rebuild running in the background; the document appears within the")
        print("index TTL (a few minutes). Re-run with --wait to block until it finishes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
