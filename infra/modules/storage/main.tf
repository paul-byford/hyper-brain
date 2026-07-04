# Corpus and index buckets. Both are private and locked down: uniform bucket-level
# access, public access prevention enforced, and object versioning so an index or
# corpus overwrite is recoverable. Per-domain isolation at storage is done with
# object prefixes and the IAM in the iam module; this is the storage substrate.

resource "google_storage_bucket" "corpus" {
  # checkov:skip=CKV_GCP_62: Access logging is controlled-profile hardening; the
  # personal demo keeps near-zero cost. Buckets are private (uniform access +
  # enforced public access prevention) and versioned regardless.
  name     = "${var.name_prefix}-corpus-${var.project_id}"
  project  = var.project_id
  location = var.location
  labels   = var.labels

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.force_destroy

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      num_newer_versions = 5
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_storage_bucket" "index" {
  # checkov:skip=CKV_GCP_62: Access logging is controlled-profile hardening; the
  # personal demo keeps near-zero cost. Buckets are private and versioned regardless.
  name     = "${var.name_prefix}-index-${var.project_id}"
  project  = var.project_id
  location = var.location
  labels   = var.labels

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.force_destroy

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      num_newer_versions = 5
    }
    action {
      type = "Delete"
    }
  }
}
