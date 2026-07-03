"""Git-repo adapter.

Clones a repository (shallow) into a temporary directory, then yields its
markdown files with the resolved commit sha as provenance, so a landed document
records exactly which revision it came from. A local path is accepted as well as
a URL, which keeps tests hermetic: they point at a repo created in a temp dir, no
network required.

``git`` is invoked via ``subprocess`` with a fixed argument list and no shell, so
there is no injection surface; the ``nosec`` markers document that the inputs are
config-controlled, not attacker-controlled.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404: used with a fixed argv and shell=False, see below.
import tempfile
from collections.abc import Iterable
from pathlib import Path

from ..models import RawItem

_EXT_MIME = {".md": "text/markdown", ".markdown": "text/markdown", ".txt": "text/plain"}


def _git(*args: str, cwd: str | None = None) -> str:
    if not shutil.which("git"):
        raise RuntimeError("git is not installed; the git adapter needs the git CLI on PATH")
    # Fixed argv, shell=False; "git" is resolved from PATH after the shutil.which
    # check above, and args are config-controlled, not a user shell string.
    result = subprocess.run(  # nosec B603 B607
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class GitAdapter:
    def __init__(
        self,
        source_id: str,
        *,
        repo: str,
        ref: str | None = None,
        glob: str = "*.md",
    ) -> None:
        self.source_id = source_id
        self.repo = repo
        self.ref = ref
        self.glob = glob

    def _mime(self, path: Path) -> str:
        return _EXT_MIME.get(path.suffix.lower(), "text/plain")

    def fetch(self) -> Iterable[RawItem]:
        workdir = tempfile.mkdtemp(prefix="brain-git-")
        try:
            clone = ["clone", "--depth", "1"]
            if self.ref:
                clone += ["--branch", self.ref]
            _git(*clone, self.repo, workdir)
            sha = _git("rev-parse", "HEAD", cwd=workdir)
            root = Path(workdir)
            for path in sorted(root.rglob(self.glob)):
                if not path.is_file() or ".git" in path.parts:
                    continue
                rel = path.relative_to(root).as_posix()
                yield RawItem(
                    identifier=rel,
                    content=path.read_bytes(),
                    mime=self._mime(path),
                    source_url=f"{self.repo}@{sha}:{rel}",
                    title=None,
                )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
