# Infrastructure (Terraform)

All infrastructure is declarative Terraform, not shell `gcloud` calls
(ARCHITECTURE.md section 5). One config serves both audiences; only the tfvars
differ. The whole thing is **validated in CI with no cloud** (fmt, validate,
checkov, conftest); a live `terraform apply` needs a Google Cloud project and
credentials.

## Layout

```
infra/
  versions.tf providers.tf variables.tf   # root: provider, inputs, backend
  services.tf main.tf controlled.tf outputs.tf
  bootstrap/                               # create-if-not-exists state bucket
  modules/
    storage/        # private, versioned corpus + index buckets
    registry/       # Docker Artifact Registry
    iam/            # one least-privilege service account per workload
    run_service/    # Cloud Run v2 service (scale-to-zero, IAM-gated)
    run_job/        # Cloud Run v2 job (indexer, ingestion)
    vertex/         # Vertex AI + Document AI API enablement
    observability/  # Cloud Trace/Monitoring/Logging (toggled)
policy/             # conftest/OPA rego (see policy/README.md)
config/*.tfvars     # personal (applies live) and controlled (validate-only) profiles
```

## The two profiles

A single `profile` variable selects behaviour; `config/*.tfvars` supply the rest.

- **personal** applies live: all-ingress-but-IAM-gated services, force-destroyable
  buckets, every cloud-costly toggle off. Near-zero idle cost, clean teardown.
- **controlled** (Option B) is authored in the same modules behind toggles:
  internal-only ingress, a VPC-SC perimeter, Workforce Identity Federation, and
  observability on. It is **not** applied in the personal demo; it is proven by
  `validate`, a plan where feasible, and the policy checks. Resources that need an
  Organization (VPC-SC, Workforce Identity) cannot `plan` without one, so they fall
  back to validate plus the static `perimeter present` policy assertion.

## Validate locally (no cloud, no credentials)

```sh
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra init -backend=false && terraform -chdir=infra validate
checkov -d infra
conftest test $(find infra -name '*.tf') -p infra/policy/security.rego
conftest test $(find infra -name '*.tf') --combine --namespace controlled -p infra/policy/controlled.rego
```

CI runs exactly these (Pillar 2 job).

## Apply for real (needs a project + credentials)

```sh
gcloud auth application-default login          # or a service-account key
gcloud config set project <your-project>

# 1. Create the state bucket once (its own local state).
terraform -chdir=infra/bootstrap init
terraform -chdir=infra/bootstrap apply -var project_id=<your-project>

# 2. Point the main config's backend at that bucket and apply the personal profile.
terraform -chdir=infra init -backend-config=bucket=<state-bucket-from-step-1>
terraform -chdir=infra apply -var-file=../config/personal.tfvars

# ... and to remove everything cleanly:
terraform -chdir=infra destroy -var-file=../config/personal.tfvars
```

The `image_*` variables default to a placeholder Cloud Run image so the stack
stands up before the real images exist; the one-command `brain` entrypoint (phase
6) builds and pushes the real images and wires this together.
