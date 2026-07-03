# Profiles: the single switch between the two audiences

The whole design is one codebase serving two audiences. The mechanism is a single
environment variable, `BRAIN_PROFILE`, with two values:

- `personal` (default): an effortless demo on an ordinary personal Google Cloud
  account.
- `controlled`: the same architecture, configured for a cost- and
  security-controlled environment.

`BRAIN_PROFILE` selects exactly two things, and nothing in the application code
branches on it:

| File | Purpose |
| --- | --- |
| `config/<profile>.tfvars` | Infrastructure differences (identity source, network posture, region, toggles). Added in the infrastructure phase. |
| `config/<profile>.policy.yaml` | The domain access policy: which principals may retrieve from which domains. Same schema for both. |

## What differs, and what does not

Identical across profiles: all application code, the retrieval logic, the Terraform
modules, the agent, and the UI.

Differs by configuration only:

- **Identity source.** Personal: Google accounts and a Google Group. Controlled:
  the bank's identity provider federated to Google via Workforce Identity
  Federation.
- **Principals in the policy.** Personal uses example groups and the provisioner's
  email; controlled uses the bank's groups.
- **Network and data posture.** Controlled adds internal ingress and a VPC Service
  Controls perimeter around Vertex AI and Cloud Storage.
- **Evaluation and observability.** Controlled can enable the paid Vertex Gen AI
  Evaluation service and full Agent Observability; personal uses the free offline
  eval tier and basic tracing.

See `ARCHITECTURE.md` sections 3 and 10 for the full rationale.
