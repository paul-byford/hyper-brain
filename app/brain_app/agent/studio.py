"""Custom specialist agents composed in Agent Studio (admin-authored, shared).

A custom specialist is **behaviour, not access**: ``{name, description, instruction, tools}``.
At run time its tools bind to *whoever runs it*, domain-scoped exactly like the built-in
researcher, so a custom agent can never exceed the caller's permissions -- the admin authors
what it *does*, never what it can *reach*. Its answers still pass the Model Armor guard.

Definitions live in one shared registry object (admin-owned), mirroring how shares/policy
persist, so a new specialist joins the live team within the cache TTL with no redeploy. The
store is in-memory by default (tests, personal profile) and GCS when configured.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Protocol

# The tools a custom specialist may be granted: the brain's read tools plus propose_document
# (staged to review). Deliberately NOT the code sandbox -- that stays the analyst's, because
# Gemini rejects mixing its built-in code tool with function tools.
ALLOWED_TOOLS = ("search", "answer", "get_document", "list_domains", "propose_document")

_RESERVED = {"researcher", "curator", "analyst", "brain_agent", "coordinator"}
_NAME = re.compile(r"^[a-z][a-z0-9_]{1,30}$")


@dataclass(frozen=True)
class AgentSpec:
    name: str
    description: str
    instruction: str
    tools: tuple[str, ...]

    def validate(self) -> None:
        if not _NAME.match(self.name):
            raise ValueError("name must be lower snake_case, 2-31 chars, starting with a letter")
        if self.name in _RESERVED:
            raise ValueError(f"'{self.name}' is a reserved built-in agent name")
        if not self.description.strip():
            raise ValueError("a description is required (it tells the coordinator when to route)")
        if not self.instruction.strip():
            raise ValueError("a system prompt is required")
        if not self.tools:
            raise ValueError("choose at least one tool")
        bad = [t for t in self.tools if t not in ALLOWED_TOOLS]
        if bad:
            raise ValueError(f"unknown tool(s): {', '.join(bad)}")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "instruction": self.instruction,
            "tools": list(self.tools),
        }

    @classmethod
    def from_dict(cls, data: dict) -> AgentSpec:
        return cls(
            name=str(data["name"]),
            description=str(data.get("description", "")),
            instruction=str(data.get("instruction", "")),
            tools=tuple(str(t) for t in (data.get("tools") or ())),
        )


class AgentStore(Protocol):
    def all(self) -> list[AgentSpec]: ...
    def put(self, spec: AgentSpec) -> None: ...
    def delete(self, name: str) -> None: ...


class MemoryAgentStore:
    """In-process store; the default and the test double."""

    def __init__(self, specs: list[AgentSpec] | None = None) -> None:
        self._by_name: dict[str, AgentSpec] = {s.name: s for s in specs or []}

    def all(self) -> list[AgentSpec]:
        return sorted(self._by_name.values(), key=lambda s: s.name)

    def put(self, spec: AgentSpec) -> None:
        self._by_name[spec.name] = spec

    def delete(self, name: str) -> None:
        self._by_name.pop(name, None)


class GcsAgentStore:
    """One shared ``custom-agents.json`` registry object in a bucket the brain owns.

    Reads are cached for ``ttl`` seconds (like the policy, index and shares), so a newly
    registered specialist joins the live team everywhere within the TTL with no redeploy; a
    write invalidates the local cache immediately.
    """

    def __init__(self, bucket: str, key: str = "custom-agents.json", ttl: float = 30.0) -> None:
        self.bucket = bucket
        self.key = key
        self.ttl = ttl
        self._cache: list[AgentSpec] | None = None
        self._at = 0.0

    def _blob(self):
        from google.cloud import storage

        return storage.Client().bucket(self.bucket).blob(self.key)

    def _read(self) -> list[AgentSpec]:
        blob = self._blob()
        if not blob.exists():
            return []
        raw = json.loads(blob.download_as_text() or "[]")
        return [AgentSpec.from_dict(d) for d in raw]

    def all(self) -> list[AgentSpec]:
        now = time.monotonic()
        if self._cache is not None and now - self._at <= self.ttl:
            return list(self._cache)
        specs = self._read()
        self._cache, self._at = specs, now
        return list(specs)

    def _write(self, specs: list[AgentSpec]) -> None:
        self._blob().upload_from_string(
            json.dumps([s.to_dict() for s in specs], indent=2), content_type="application/json"
        )
        self._cache = None  # force a reload on the next read

    def put(self, spec: AgentSpec) -> None:
        self._write([s for s in self._read() if s.name != spec.name] + [spec])

    def delete(self, name: str) -> None:
        self._write([s for s in self._read() if s.name != name])


def get_agent_store(name: str | None = None) -> AgentStore:
    """The configured custom-agent store: ``memory`` (default) or ``gcs`` (a shared
    ``custom-agents.json`` in ``BRAIN_SHARES_BUCKET`` / ``BRAIN_INDEX_BUCKET``)."""
    name = name or os.environ.get("BRAIN_AGENTS_STORE", "memory")
    if name == "memory":
        return MemoryAgentStore()
    if name == "gcs":
        bucket = os.environ.get("BRAIN_SHARES_BUCKET") or os.environ.get("BRAIN_INDEX_BUCKET")
        if not bucket:
            raise ValueError("BRAIN_AGENTS_STORE=gcs needs a bucket (BRAIN_SHARES/INDEX_BUCKET)")
        return GcsAgentStore(bucket)
    raise ValueError(f"unknown agent store {name!r}")
