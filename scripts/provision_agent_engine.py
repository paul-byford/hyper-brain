"""Idempotently ensure a bare Vertex AI **Agent Engine** instance exists, and print its
resource name as JSON: ``{"resource_name": "projects/.../locations/europe-west2/reasoningEngines/..."}``.

This instance is the container for Agent Engine **Sessions** (short-term conversation state)
and **Memory Bank** (long-term, user-scoped memory) that the analyst/agent team uses. We do
NOT deploy our agent to it (the team runs in-process in the brain); we only need the
instance id, which ADK's ``VertexAiSessionService`` / ``VertexAiMemoryBankService`` bind to.

Agent Engine is available in europe-west2, so this stays **in-region** with the rest of the
tenancy. Run this **once**, then put the printed resource name in ``agent_engine_resource``
in your (gitignored) tfvars; Terraform wires ``BRAIN_AGENT_ENGINE`` from that variable, with
no apply-time script to depend on. Reused if one already exists (matched by display name),
so repeated runs return the same instance.

  python scripts/provision_agent_engine.py --project <id>

Requires ``google-cloud-aiplatform`` and ADC credentials with Vertex AI access.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Agent Engine (and Sessions + Memory Bank) is supported in europe-west2, so the memory
# store stays in the same region as the brain and the models.
LOCATION = "europe-west2"
DISPLAY_NAME = "hyper-brain-memory"


def ensure_agent_engine(project: str, location: str, display_name: str) -> str:
    import vertexai
    from vertexai import agent_engines

    vertexai.init(project=project, location=location)

    # Reuse an existing instance (match by display name) so applies are idempotent.
    for engine in agent_engines.list():
        if getattr(engine, "display_name", "") == display_name:
            return engine.resource_name

    # A bare instance (no deployed agent) -- just the Sessions + Memory Bank container.
    created = agent_engines.create(
        display_name=display_name,
        description="Sessions + user-scoped Memory Bank for the Hyper Brain agent team.",
    )
    return created.resource_name


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    ap.add_argument("--location", default=LOCATION)
    ap.add_argument("--display-name", default=DISPLAY_NAME)
    args = ap.parse_args()
    if not args.project:
        print(json.dumps({"error": "a --project (or GOOGLE_CLOUD_PROJECT) is required"}))
        return 2

    resource_name = ensure_agent_engine(args.project, args.location, args.display_name)
    print(json.dumps({"resource_name": resource_name}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
