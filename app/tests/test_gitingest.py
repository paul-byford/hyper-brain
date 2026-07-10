"""Git-repo ingestion: archive URL construction, caps, and doc extraction.

The network fetch is monkeypatched to a fixture tarball, so these run offline and pin
the demo's capacity controls (supported hosts, size cap, doc-only extraction, README
first) without touching the network.
"""

from __future__ import annotations

import gzip
import io
import tarfile

import pytest

from brain_app.serving import gitingest
from brain_app.serving.gitingest import RepoFetchError, RepoTooLarge, _archive_urls, fetch_repo_docs


def _tar_gz(files: dict[str, bytes], root: str = "repo-main") -> bytes:
    """Build an in-memory .tar.gz with a top-level {root}/ dir, like a real archive."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(f"{root}/{name}")
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return gzip.compress(raw.getvalue())


def test_archive_urls_supported_hosts():
    gh = _archive_urls("https://github.com/owner/repo", "main")
    assert gh[0] == "https://codeload.github.com/owner/repo/tar.gz/refs/heads/main"
    gl = _archive_urls("https://gitlab.com/owner/repo.git", "dev")
    assert gl == ["https://gitlab.com/owner/repo/-/archive/dev/repo-dev.tar.gz"]
    assert _archive_urls("https://bitbucket.org/o/r", "main")[0].startswith(
        "https://bitbucket.org/o/r/get/"
    )


def test_archive_urls_rejects_unsupported_host():
    with pytest.raises(RepoFetchError):
        _archive_urls("https://example.com/o/r", "main")


def test_archive_urls_requires_owner_and_repo():
    with pytest.raises(RepoFetchError):
        _archive_urls("https://github.com/owner", "main")


def test_fetch_repo_docs_extracts_docs_readme_first(monkeypatch):
    archive = _tar_gz(
        {
            "README.md": b"# The project\n\nOverview.",
            "docs/guide.md": b"## Guide\n\nHow to use it.",
            "src/main.py": b"print('code, not a doc')",
            "notes.txt": b"a text note",
        }
    )
    monkeypatch.setattr(gitingest, "_fetch_capped", lambda url: archive)
    docs = fetch_repo_docs("https://github.com/owner/repo", "main")
    names = [name for name, _ in docs]
    assert names[0].lower().startswith("readme")  # README leads
    assert "docs/guide.md" in names and "notes.txt" in names
    assert "src/main.py" not in names  # non-doc files are excluded


def test_fetch_repo_docs_errors_when_no_docs(monkeypatch):
    monkeypatch.setattr(gitingest, "_fetch_capped", lambda url: _tar_gz({"src/main.py": b"code"}))
    with pytest.raises(RepoFetchError):
        fetch_repo_docs("https://github.com/owner/repo", "main")


def test_fetch_repo_docs_not_found(monkeypatch):
    # Every candidate URL 404s (fetcher returns None), so the repo/branch is not found.
    monkeypatch.setattr(gitingest, "_fetch_capped", lambda url: None)
    with pytest.raises(RepoFetchError):
        fetch_repo_docs("https://github.com/owner/repo", "nope")


def test_repo_too_large_is_surfaced(monkeypatch):
    def _boom(url):
        raise RepoTooLarge("too big")

    monkeypatch.setattr(gitingest, "_fetch_capped", _boom)
    with pytest.raises(RepoTooLarge):
        fetch_repo_docs("https://github.com/owner/repo", "main")
