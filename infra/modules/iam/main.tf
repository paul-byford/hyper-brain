# One service account per workload, each granted only what it needs. Bucket access
# is bound at the bucket (not the project) so the brain can read the index but not
# write it, the indexer can write the index but the ingest job cannot, and so on.

resource "google_service_account" "brain" {
  project      = var.project_id
  account_id   = "${var.name_prefix}-brain"
  display_name = "hyper-brain MCP service"
}

resource "google_service_account" "agent" {
  project      = var.project_id
  account_id   = "${var.name_prefix}-agent"
  display_name = "hyper-brain ADK agent"
}

resource "google_service_account" "ui" {
  project      = var.project_id
  account_id   = "${var.name_prefix}-ui"
  display_name = "hyper-brain Explorer UI"
}

resource "google_service_account" "indexer" {
  project      = var.project_id
  account_id   = "${var.name_prefix}-indexer"
  display_name = "hyper-brain index-build job"
}

resource "google_service_account" "ingest" {
  project      = var.project_id
  account_id   = "${var.name_prefix}-ingest"
  display_name = "hyper-brain ingestion job"
}

# --- Storage: read/write split by role ---

# Brain reads the index (and its policy object) only.
resource "google_storage_bucket_iam_member" "brain_index_read" {
  bucket = var.index_bucket
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.brain.email}"
}

# Brain may create (not overwrite) objects in the corpus bucket, so the gated
# propose_document tool can stage a quarantined proposal under proposals/ for review.
resource "google_storage_bucket_iam_member" "brain_corpus_propose" {
  bucket = var.corpus_bucket
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.brain.email}"
}

# Indexer writes the index and reads the corpus.
resource "google_storage_bucket_iam_member" "indexer_index_write" {
  bucket = var.index_bucket
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.indexer.email}"
}

resource "google_storage_bucket_iam_member" "indexer_corpus_read" {
  bucket = var.corpus_bucket
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.indexer.email}"
}

# Ingest writes the corpus.
resource "google_storage_bucket_iam_member" "ingest_corpus_write" {
  bucket = var.corpus_bucket
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.ingest.email}"
}

# --- Vertex AI: the workloads that call models get aiplatform.user, nothing broader ---

locals {
  aiplatform_users = {
    brain   = google_service_account.brain.email
    agent   = google_service_account.agent.email
    indexer = google_service_account.indexer.email
    ingest  = google_service_account.ingest.email
  }
}

resource "google_project_iam_member" "aiplatform_user" {
  for_each = local.aiplatform_users

  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${each.value}"
}

# The brain exports OpenTelemetry spans to Cloud Trace when observability is on, so
# it needs permission to write traces (cloudtrace.traces.patch).
resource "google_project_iam_member" "brain_trace_agent" {
  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${google_service_account.brain.email}"
}
