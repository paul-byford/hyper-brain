"""Idempotently ensure a **Model Armor** template exists, and print its resource name as JSON:
``{"resource_name": "projects/.../locations/europe-west2/templates/brain-guard"}``.

The template is the content guard the brain scans through: **Sensitive Data Protection** (PII /
secrets, used for redact-then-allow), **prompt-injection / jailbreak**, and **responsible-AI**.
The **malicious-URI** filter is intentionally omitted because ``europe-west2`` does not support
it (creating a template with it returns ``CAPABILITY_NOT_SUPPORTED``); the rest run in-region.

Run this **once**, then put the printed resource name in ``model_armor_template`` in your
(gitignored) tfvars; Terraform enables the API, grants the brain ``roles/modelarmor.user``, and
wires ``BRAIN_MODEL_ARMOR_TEMPLATE`` from that variable. Reused if the template already exists,
so repeated runs return the same one.

  python scripts/provision_model_armor.py --project <id>

Requires ``requests`` + ``google-auth`` and ADC credentials with Model Armor admin access.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Model Armor supports europe-west2 (verified), so the guard stays in-region with the brain.
LOCATION = "europe-west2"
TEMPLATE_ID = "brain-guard"

# SDP (PII/secrets) + prompt-injection/jailbreak + responsible-AI. No malicious-URI: unsupported
# in europe-west2. SDP is basic mode -- we redact client-side from the returned finding ranges,
# so no Cloud DLP de-identify template is needed.
_FILTER_CONFIG = {
    "sdpSettings": {"basicConfig": {"filterEnforcement": "ENABLED"}},
    "piAndJailbreakFilterSettings": {
        "filterEnforcement": "ENABLED",
        "confidenceLevel": "MEDIUM_AND_ABOVE",
    },
    "raiSettings": {
        "raiFilters": [
            {"filterType": "HATE_SPEECH", "confidenceLevel": "MEDIUM_AND_ABOVE"},
            {"filterType": "DANGEROUS", "confidenceLevel": "MEDIUM_AND_ABOVE"},
            {"filterType": "HARASSMENT", "confidenceLevel": "MEDIUM_AND_ABOVE"},
            {"filterType": "SEXUALLY_EXPLICIT", "confidenceLevel": "MEDIUM_AND_ABOVE"},
        ]
    },
}


def _session():
    import google.auth
    import google.auth.transport.requests

    creds, _ = google.auth.default()
    return google.auth.transport.requests.AuthorizedSession(creds)


def ensure_template(project: str, location: str, template_id: str) -> str:
    base = f"https://modelarmor.{location}.rep.googleapis.com/v1"
    parent = f"projects/{project}/locations/{location}"
    name = f"{parent}/templates/{template_id}"
    session = _session()

    got = session.get(f"{base}/{name}", timeout=30)
    if got.status_code == 200:  # already exists -- reuse
        return name

    created = session.post(
        f"{base}/{parent}/templates?template_id={template_id}",
        json={"filterConfig": _FILTER_CONFIG},
        timeout=30,
    )
    created.raise_for_status()
    return name


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    ap.add_argument("--location", default=LOCATION)
    ap.add_argument("--template-id", default=TEMPLATE_ID)
    args = ap.parse_args()
    if not args.project:
        print(json.dumps({"error": "a --project (or GOOGLE_CLOUD_PROJECT) is required"}))
        return 2

    resource_name = ensure_template(args.project, args.location, args.template_id)
    print(json.dumps({"resource_name": resource_name}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
