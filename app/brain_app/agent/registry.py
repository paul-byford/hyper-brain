"""Official GCP **Agent Registry** integration: register our agents as A2A-card Services.

The Gemini Enterprise Agent Platform's Agent Registry (``agentregistry.googleapis.com``) is the
governance catalog for agents, MCP servers and tools. We register each of our agents -- the
built-in team (coordinator, researcher, curator, analyst) **and** every Agent Studio custom
specialist -- as a ``Service`` with an ``A2A_AGENT_CARD`` spec, **in-region** (europe-west2), so
the whole team is a queryable, audited inventory in the platform. Each card carries the agent's
**version** (its prompt version), its **skills** (the MCP tools it may call), and, in the
description, its framework/model/prompt content-hash.

Sync is idempotent (create-or-patch a Service per agent). Reads come straight from the
platform's ``agents.list``. All REST, via the caller's ADC / the brain service account.
"""

from __future__ import annotations

import os

from .studio import get_agent_store

_HOST = "https://agentregistry.googleapis.com/v1"
_PROTOCOL = "0.3.0"
_SERVICE_PREFIX = "hb-"  # our Services are namespaced, so we never touch others on sync

# The built-in team, described from the versioned prompts + each role's MCP tools. Kept here
# (not introspected from the live ADK objects) so the registry can be built without importing
# google-adk or standing up a runner.
RESEARCH_TOOLS = ["search", "answer", "get_document", "list_domains"]
CURATE_TOOLS = ["search", "get_document", "propose_document"]
_BUILTINS = [
    ("coordinator", "coordinator", "Routes each request to the right specialist.", []),
    (
        "researcher",
        "researcher",
        "Answers questions from the brain's governed read tools.",
        RESEARCH_TOOLS,
    ),
    (
        "curator",
        "curator",
        "Drafts and proposes new documents (staged to human review).",
        CURATE_TOOLS,
    ),
    ("analyst", "analyst", "Computes quantitative answers in an isolated code sandbox.", []),
]


def _location() -> str:
    return os.environ.get("BRAIN_AGENT_REGISTRY_LOCATION", "europe-west2")


def _project() -> str | None:
    return os.environ.get("GOOGLE_CLOUD_PROJECT")


def enabled() -> bool:
    """Reads are attempted when a project is known; a flag opts the sync path in explicitly."""
    return bool(_project())


def _parent(project: str, location: str) -> str:
    return f"projects/{project}/locations/{location}"


def _model() -> str:
    return os.environ.get("BRAIN_AGENT_MODEL", "gemini-2.5-flash")


def _prompt_sha(name: str) -> tuple[str, str]:
    """(version, short content-hash) for a named built-in prompt, from the versioned registry."""
    from ..prompts import registry

    for p in registry():
        if p.name == name:
            return p.version, p.sha
    return "1.0.0", ""


def _card(name: str, description: str, version: str, tools: list[str], meta: str) -> dict:
    base = os.environ.get("BRAIN_URL", "https://hyper-brain.invalid").rstrip("/")
    return {
        "protocolVersion": _PROTOCOL,
        "name": name,
        "description": f"{description} ({meta})",
        "url": f"{base}/agents/{name}",
        "version": version,
        "capabilities": {},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {"id": t, "name": t, "description": f"brain tool: {t}", "tags": ["brain-tool"]}
            for t in tools
        ]
        or [{"id": name, "name": name, "description": description, "tags": ["agent"]}],
    }


def agent_cards(agent_store=None) -> list[dict]:
    """A registrable descriptor per agent: the built-in team plus Agent Studio custom agents.
    Each is ``{service_id, display_name, description, card}``."""
    model = _model()
    out: list[dict] = []
    for name, prompt_name, description, tools in _BUILTINS:
        version, sha = _prompt_sha(prompt_name)
        meta = f"google-adk | {model} | prompt {prompt_name}@{version} {sha}".strip()
        out.append(
            {
                "service_id": f"{_SERVICE_PREFIX}{name}",
                "display_name": name,
                "description": description,
                "card": _card(name, description, version, tools, meta),
            }
        )
    store = agent_store or get_agent_store()
    for spec in store.all():
        meta = f"google-adk | {model} | custom (Agent Studio)"
        out.append(
            {
                "service_id": f"{_SERVICE_PREFIX}custom-{spec.name}",
                "display_name": spec.name,
                "description": spec.description,
                "card": _card(spec.name, spec.description, "1.0.0", list(spec.tools), meta),
            }
        )
    return out


def _session():
    import google.auth
    import google.auth.transport.requests

    creds, _ = google.auth.default()
    return google.auth.transport.requests.AuthorizedSession(creds)


def sync(project: str | None = None, location: str | None = None) -> dict:
    """Idempotently register every agent as a Service (create, or patch if it already exists).
    Returns a small summary. Best-effort per agent; a single failure doesn't abort the rest."""
    project = project or _project()
    location = location or _location()
    if not project:
        return {"error": "no project (GOOGLE_CLOUD_PROJECT)"}
    session = _session()
    parent = _parent(project, location)
    created, patched, failed = [], [], []
    for entry in agent_cards():
        body = {
            "displayName": entry["display_name"],
            "description": entry["description"],
            "agentSpec": {"type": "A2A_AGENT_CARD", "content": entry["card"]},
        }
        sid = entry["service_id"]
        name = f"{parent}/services/{sid}"
        try:
            got = session.get(f"{_HOST}/{name}", timeout=30)
            if got.status_code == 200:
                session.patch(f"{_HOST}/{name}", json=body, timeout=60).raise_for_status()
                patched.append(entry["display_name"])
            else:
                session.post(
                    f"{_HOST}/{parent}/services",
                    params={"serviceId": sid},
                    json=body,
                    timeout=60,
                ).raise_for_status()
                created.append(entry["display_name"])
        except Exception as exc:  # noqa: BLE001 - report per-agent, keep going
            failed.append(f"{entry['display_name']}: {exc}")
    return {"created": created, "patched": patched, "failed": failed, "location": location}


def list_registered(project: str | None = None, location: str | None = None) -> list[dict]:
    """The agents catalogued in the platform Agent Registry (our Services show here alongside
    auto-registered Google agents and our Agent Engine). Normalised for the UI/CLI."""
    project = project or _project()
    location = location or _location()
    if not project:
        return []
    out: list[dict] = []
    import contextlib

    with contextlib.suppress(Exception):
        resp = _session().get(f"{_HOST}/{_parent(project, location)}/agents", timeout=30)
        resp.raise_for_status()
        for a in resp.json().get("agents", []):
            out.append(
                {
                    "name": a.get("displayName") or a.get("agentId"),
                    "version": a.get("version"),
                    "description": a.get("description", ""),
                    "skills": [s.get("id") for s in (a.get("skills") or []) if s.get("id")],
                    "ours": f"services:{_SERVICE_PREFIX}" in str(a.get("agentId", "")),
                }
            )
    return out


def main(argv: list[str] | None = None) -> int:
    """CLI: ``sync`` registers/updates our agents in the Agent Registry; ``list`` (default)
    prints the catalogued agents."""
    import sys

    args = argv if argv is not None else sys.argv[1:]
    action = args[0] if args else "list"
    if action == "sync":
        result = sync()
        print(
            f"Agent Registry sync ({result.get('location')}): "
            f"created {result.get('created')}, patched {result.get('patched')}"
        )
        if result.get("failed"):
            print(f"  failed: {result['failed']}")
    else:
        agents = list_registered()
        print(f"Registered agents ({len(agents)}):")
        for a in agents:
            tag = "  [ours]" if a["ours"] else ""
            print(f"  {a['name']:22} v{a.get('version') or '-':8} skills={a.get('skills')}{tag}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
