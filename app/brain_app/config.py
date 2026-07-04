"""Profile and policy loading.

The single switch between the two audiences is ``BRAIN_PROFILE`` (``personal`` or
``controlled``). It selects one policy file. The policy maps principals (an
identity or a group) to the domains they may retrieve from. This module only
*loads and resolves* policy; enforcement happens server-side in the retrieval
path, and identity verification (turning a request into a set of principals) is
the serving layer's job in a later phase.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_PROFILE = "personal"
# Principal that matches every caller, for open personal demos.
WILDCARD = "*"

# Repo root is three levels up from this file: app/brain_app/config.py -> repo.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_DIR = _REPO_ROOT / "config"


def profile() -> str:
    """The active profile, from the environment."""
    return os.environ.get("BRAIN_PROFILE", DEFAULT_PROFILE)


@dataclass(frozen=True)
class Grant:
    principal: str
    domains: tuple[str, ...]


@dataclass(frozen=True)
class Policy:
    version: int
    domains: tuple[str, ...]
    grants: tuple[Grant, ...]

    def domains_for(self, principals: list[str] | set[str]) -> set[str]:
        """Domains the given principals may retrieve from.

        A caller is described by a set of principals (for example their email and
        their group memberships). A grant applies if its principal is the
        wildcard or is one of the caller's principals. Only domains declared in
        the policy are ever returned, so a typo in a grant cannot widen access to
        a domain that does not exist.
        """
        principal_set = set(principals)
        allowed: set[str] = set()
        for grant in self.grants:
            if grant.principal == WILDCARD or grant.principal in principal_set:
                allowed.update(grant.domains)
        return allowed & set(self.domains)


def policy_path(prof: str | None = None) -> Path:
    prof = prof or profile()
    return _CONFIG_DIR / f"{prof}.policy.yaml"


def _read_policy_text(source: str | Path) -> str:
    text = str(source)
    if text.startswith("gs://"):
        # The deployed brain can load its policy from a bucket, so `brain grant`
        # takes effect (via policy_source's TTL) without rebuilding the image.
        from google.cloud import storage

        bucket, _, blob = text[len("gs://") :].partition("/")
        return storage.Client().bucket(bucket).blob(blob).download_as_text()
    return Path(source).read_text(encoding="utf-8")


def load_policy(path: str | Path | None = None, prof: str | None = None) -> Policy:
    source = path if path is not None else policy_path(prof)
    data = yaml.safe_load(_read_policy_text(source)) or {}
    domains = tuple(data.get("domains", []))
    grants = tuple(
        Grant(principal=g["principal"], domains=tuple(g.get("domains", [])))
        for g in data.get("grants", [])
    )
    return Policy(version=int(data.get("version", 1)), domains=domains, grants=grants)


def policy_source(
    path: str | Path | None = None, prof: str | None = None, ttl: float = 30.0
) -> Callable[[], Policy]:
    """A cached policy loader that reloads from its source after ``ttl`` seconds.

    The server holds one of these instead of a fixed Policy, so a `brain grant`
    that updates the source (a file, or a gs:// object) takes effect within the TTL
    with no redeploy. The reload is a small YAML parse, so the cost is negligible.
    """
    state: dict[str, object] = {"policy": None, "at": 0.0}

    def load() -> Policy:
        now = time.monotonic()
        if state["policy"] is None or now - float(state["at"]) > ttl:
            state["policy"] = load_policy(path, prof)
            state["at"] = now
        return state["policy"]  # type: ignore[return-value]

    return load
