"""Git-repo ingestion for Studio: a public repo's docs, as an editable draft.

Rather than shell out to git (there is no git binary in the serving image, and an
unbounded clone could exhaust a scale-to-zero instance's in-memory filesystem), this
downloads the repository archive tarball over HTTPS with a hard, *streamed* byte cap,
then extracts only the doc-like files (markdown, rst, text) up to a file-count and
per-file size cap. Together these keep the demo to smaller codebases and bound the work
regardless of the repo's true size, and notify the caller when a repo is too large.

The archive is fetched through the same SSRF hardening as web ingestion (public address
only, every redirect hop re-validated), so a repo URL can never be turned into a request
for an internal address.
"""

from __future__ import annotations

import io
import tarfile
from urllib.parse import urljoin, urlparse

from .drafts import _open, _resolves_public  # reuse the SSRF-safe fetch primitives

# Demo capacity guards: keep it to smaller codebases, with bounded memory and time.
_MAX_ARCHIVE_BYTES = 20 * 1024 * 1024  # 20 MB compressed archive
_MAX_DOC_FILES = 40  # doc files pulled from the repo
_MAX_FILE_BYTES = 256 * 1024  # 256 KB per doc file
_MAX_TOTAL_DOC_BYTES = 500 * 1024  # assembled cap (keeps the curate call small)
_MAX_MEMBERS_SCANNED = 20000  # bound iteration over a pathological archive
_DOC_EXT = (".md", ".markdown", ".rst", ".txt")
_MAX_REDIRECTS = 4


class RepoFetchError(ValueError):
    """A repository could not be fetched (bad URL, unsupported host, HTTP error)."""


class RepoTooLarge(ValueError):
    """The repository archive exceeds the demo's capacity limit."""


def _archive_urls(repo_url: str, ref: str) -> list[str]:
    """Candidate archive (tar.gz) URLs for a public repo on a supported host."""
    parsed = urlparse(repo_url)
    host = (parsed.hostname or "").lower()
    parts = [seg for seg in parsed.path.split("/") if seg]
    if len(parts) < 2:
        raise RepoFetchError("That does not look like a repository URL (expected owner/repo).")
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if host in ("github.com", "www.github.com"):
        return [
            f"https://codeload.github.com/{owner}/{repo}/tar.gz/refs/heads/{ref}",
            f"https://codeload.github.com/{owner}/{repo}/tar.gz/refs/tags/{ref}",
            f"https://codeload.github.com/{owner}/{repo}/tar.gz/{ref}",
        ]
    if host in ("gitlab.com", "www.gitlab.com"):
        return [f"https://gitlab.com/{owner}/{repo}/-/archive/{ref}/{repo}-{ref}.tar.gz"]
    if host in ("bitbucket.org", "www.bitbucket.org"):
        return [f"https://bitbucket.org/{owner}/{repo}/get/{ref}.tar.gz"]
    raise RepoFetchError("Only public GitHub, GitLab or Bitbucket repositories are supported.")


def _fetch_capped(url: str) -> bytes | None:
    """Fetch a URL (SSRF-safe, redirects re-validated) into bytes, hard-capped. Returns
    the bytes on 200, or ``None`` on 404 so the caller can try the next candidate."""
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        parsed = urlparse(current)
        if parsed.scheme != "https":
            raise RepoFetchError("Only https repository URLs can be fetched.")
        if not parsed.hostname or not _resolves_public(parsed.hostname):
            raise RepoFetchError("That address is private or internal and cannot be fetched.")
        response = _open(current)
        status = getattr(response, "status", None) or response.getcode()
        if status in (301, 302, 303, 307, 308):
            location = response.headers.get("Location")
            if not location:
                raise RepoFetchError("The archive redirected without a destination.")
            current = urljoin(current, location)
            continue
        if status == 404:
            return None
        if status >= 400:
            raise RepoFetchError(f"The repository archive could not be fetched (HTTP {status}).")
        # Streamed read with a hard cap, so a huge repo never fills the instance's memory.
        buf = io.BytesIO()
        remaining = _MAX_ARCHIVE_BYTES + 1
        while remaining > 0:
            chunk = response.read(min(65536, remaining))
            if not chunk:
                break
            buf.write(chunk)
            remaining -= len(chunk)
        data = buf.getvalue()
        if len(data) > _MAX_ARCHIVE_BYTES:
            raise RepoTooLarge(
                "This repository is larger than the demo allows "
                f"(the limit is {_MAX_ARCHIVE_BYTES // (1024 * 1024)} MB). Try a smaller "
                "or docs-only repository."
            )
        return data
    raise RepoFetchError("The archive redirected too many times.")


def fetch_repo_docs(repo_url: str, ref: str = "main") -> list[tuple[str, str]]:
    """Return ``[(relative_path, text), ...]`` of the repo's doc files, within the caps.

    Raises :class:`RepoFetchError` / :class:`RepoTooLarge` with a user-friendly message.
    """
    ref = (ref or "main").strip() or "main"
    refs = ["main", "master"] if ref in ("main", "master") else [ref]
    data: bytes | None = None
    for candidate_ref in refs:
        for url in _archive_urls(repo_url, candidate_ref):
            data = _fetch_capped(url)
            if data is not None:
                break
        if data is not None:
            break
    if data is None:
        raise RepoFetchError(
            "Could not find that repository or branch. Check the URL and branch (the "
            "demo tries 'main' and 'master' by default)."
        )

    docs: list[tuple[str, str]] = []
    total = 0
    scanned = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar:
            scanned += 1
            if scanned > _MAX_MEMBERS_SCANNED:
                break
            if not member.isfile() or member.size > _MAX_FILE_BYTES:
                continue
            # Drop the archive's top-level "{repo}-{ref}/" directory from the path.
            name = member.name.split("/", 1)[-1]
            if not name.lower().endswith(_DOC_EXT):
                continue
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            raw = extracted.read(_MAX_FILE_BYTES + 1)
            if len(raw) > _MAX_FILE_BYTES:
                continue
            text = raw.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            docs.append((name, text))
            total += len(text)
            if len(docs) >= _MAX_DOC_FILES or total >= _MAX_TOTAL_DOC_BYTES:
                break

    if not docs:
        raise RepoFetchError(
            "No documentation files (.md, .rst, .txt) were found in that repository."
        )
    # README first, then the rest by path, so the assembled draft leads with the overview.
    docs.sort(key=lambda d: (0 if d[0].lower().startswith("readme") else 1, d[0].lower()))
    return docs
