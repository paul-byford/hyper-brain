"""Pillar 1 (functional): the source-adapter seam and contract.

Every adapter yields RawItems with a stable identifier, content, mime and
provenance URL, and satisfies the SourceAdapter protocol. Adapters are driven
from fixtures (a temp dir, a file:// URL, a temp git repo) so no network is used.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

from brain_app.ingest.adapters import LocalAdapter, WebAdapter, build_adapter
from brain_app.ingest.adapters.base import SourceAdapter
from brain_app.ingest.adapters.git import GitAdapter

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def test_local_adapter_contract(tmp_path):
    (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "b.md").write_text("# B\n", encoding="utf-8")

    adapter = LocalAdapter("local-test", path=str(tmp_path))
    assert isinstance(adapter, SourceAdapter)
    items = list(adapter.fetch())

    assert [i.identifier for i in items] == ["a.md", "sub/b.md"]
    assert all(i.content for i in items)
    assert all(i.mime == "text/markdown" for i in items)
    assert all(i.source_url.startswith("file://") for i in items)


def test_web_adapter_with_injected_opener():
    calls: list[str] = []

    def opener(url: str) -> tuple[bytes, str]:
        calls.append(url)
        return b"<h1>Hi</h1>", "text/html"

    adapter = WebAdapter("web-test", urls=["https://example.com/x"], opener=opener)
    items = list(adapter.fetch())
    assert calls == ["https://example.com/x"]
    assert items[0].mime == "text/html"
    assert items[0].source_url == "https://example.com/x"


def test_web_adapter_reads_file_url_via_default_opener():
    url = (FIXTURES / "sample.html").resolve().as_uri()
    items = list(WebAdapter("web-file", urls=[url]).fetch())
    assert b"Streaming features" in items[0].content


def test_web_adapter_rejects_disallowed_scheme():
    adapter = WebAdapter("web-bad", urls=["ftp://example.com/x"])
    with pytest.raises(ValueError, match="scheme"):
        list(adapter.fetch())


def test_build_adapter_dispatch_and_unknown_type():
    assert isinstance(build_adapter("local", "s", {"path": "raw"}), LocalAdapter)
    with pytest.raises(ValueError, match="unknown source type"):
        build_adapter("carrier-pigeon", "s", {})


@pytest.mark.skipif(not shutil.which("git"), reason="git CLI not available")
def test_git_adapter_contract(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)  # nosec B603 B607

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "Test")
    (repo / "note.md").write_text("# Note\n\nBody.\n", encoding="utf-8")
    git("add", "note.md")
    git("commit", "-qm", "add note")

    items = list(GitAdapter("git-test", repo=str(repo)).fetch())
    assert isinstance(GitAdapter("git-test", repo=str(repo)), SourceAdapter)
    assert len(items) == 1
    assert items[0].identifier == "note.md"
    assert "@" in items[0].source_url  # repo@sha:path provenance
    assert b"Body." in items[0].content
