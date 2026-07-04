# The Terraform state bucket, created idempotently before the first main apply.
# Versioned (state history is recoverable), private, and never force-destroyed, so
# a stray `destroy` cannot wipe the state that tracks everything else.
resource "google_storage_bucket" "state" {
  # checkov:skip=CKV_GCP_62: Access logging is controlled-profile hardening; the
  # state bucket is private, versioned, and destroy-protected regardless.
  name     = "${var.name_prefix}-tfstate-${var.project_id}"
  project  = var.project_id
  location = var.region
  labels   = var.labels

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  lifecycle {
    prevent_destroy = true
  }
}
