"""Idempotently ensure a Vertex AI **Code Interpreter** extension exists, and print its
resource name as JSON: ``{"resource_name": "projects/.../locations/us-central1/extensions/..."}``.

This backs the managed-sandbox option for the analyst (Phase 2). The Code Interpreter
extension has **no native Terraform resource** and is **us-central1-only**, so Terraform
provisions it through this script (an ``external`` data source in
``infra/modules/code_interpreter``) rather than a provider resource. Run standalone to see
the name, or let ``terraform apply`` call it when ``enable_code_interpreter = true``.

  python scripts/provision_code_interpreter.py --project <id>

Requires ``google-cloud-aiplatform`` and ADC credentials with Vertex AI access. Reused if
one already exists (matched by display name), so repeated runs return the same extension.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# The Code Interpreter extension is only offered in us-central1.
LOCATION = "us-central1"
DISPLAY_NAME = "hyper-brain-code-interpreter"


def ensure_extension(project: str, location: str, display_name: str) -> str:
    import vertexai
    from vertexai.preview import extensions

    vertexai.init(project=project, location=location)

    # Reuse an existing one (match by our display name) so applies are idempotent.
    for ext in extensions.Extension.list():
        if getattr(ext, "display_name", "") == display_name:
            return ext.resource_name

    created = extensions.Extension.from_hub(
        "code_interpreter",
        # from_hub accepts a display name on recent SDKs; ignored gracefully otherwise.
        **({"display_name": display_name} if _from_hub_takes_name() else {}),
    )
    return created.resource_name


def _from_hub_takes_name() -> bool:
    import inspect

    from vertexai.preview import extensions

    try:
        return "display_name" in inspect.signature(extensions.Extension.from_hub).parameters
    except (TypeError, ValueError):
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    ap.add_argument("--location", default=LOCATION)
    ap.add_argument("--display-name", default=DISPLAY_NAME)
    args = ap.parse_args()
    if not args.project:
        print(json.dumps({"error": "a --project (or GOOGLE_CLOUD_PROJECT) is required"}))
        return 2

    resource_name = ensure_extension(args.project, args.location, args.display_name)
    # The `external` data source reads one JSON object of strings from stdout.
    print(json.dumps({"resource_name": resource_name}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
