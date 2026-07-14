# The analyst's managed code sandbox: a Vertex AI **Code Interpreter** extension.
#
# There is no native Terraform resource for Vertex extensions, and the Code Interpreter is
# **us-central1-only**, so this provisions it (idempotently) through
# scripts/provision_code_interpreter.py via an `external` data source, and exports the
# resource name for BRAIN_CODE_INTERPRETER. The program must run where `terraform apply`
# runs (needs python + google-cloud-aiplatform + ADC). This whole module is instantiated
# with count in the root, so nothing runs unless enable_code_interpreter = true.
#
# IAM is already in place: the brain and agent service accounts hold roles/aiplatform.user
# (see modules/iam), which includes aiplatform.extensions.execute — the permission needed
# to call the extension. So no extra binding is created here (adding a duplicate would
# conflict with that grant).

terraform {
  required_providers {
    external = {
      source = "hashicorp/external"
    }
  }
}

data "external" "extension" {
  program = [
    "python",
    "${path.root}/../scripts/provision_code_interpreter.py",
    "--project", var.project_id,
    "--location", var.location,
  ]
}
