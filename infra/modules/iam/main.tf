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

# Brain reads/writes the corpus bucket: it stages proposals under proposals/, lands
# personal notes into personal: domains, and (on server-side accept) moves an approved
# proposal into its live domain and removes the staged copy. objectAdmin covers the
# move+delete that create-only would not; the index it serves stays a separate bucket.
resource "google_storage_bucket_iam_member" "brain_corpus_curate" {
  bucket = var.corpus_bucket
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.brain.email}"
}

# Brain fully owns the shares bucket: it creates, overwrites (re-share) and deletes
# (unshare) per-owner overlay files there. Kept separate from the index bucket so the
# brain stays read-only on the index it serves.
resource "google_storage_bucket_iam_member" "brain_shares_admin" {
  bucket = var.shares_bucket
  role   = "roles/storage.objectAdmin"
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

# Ingest reads its sources config (sources.yaml) from the index bucket.
resource "google_storage_bucket_iam_member" "ingest_index_read" {
  bucket = var.index_bucket
  role   = "roles/storage.objectViewer"
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

# The brain parses scanned/image PDFs with Document AI in-tenancy (Studio uploads),
# so it may call the OCR processor. apiUser is the least role that allows processing.
resource "google_project_iam_member" "brain_documentai_user" {
  project = var.project_id
  role    = "roles/documentai.apiUser"
  member  = "serviceAccount:${google_service_account.brain.email}"
}

# When the Model Armor content guard is on, the brain sanitizes written content and answers
# through it, so it needs to call the sanitize APIs. modelarmor.user is the least role for that.
resource "google_project_iam_member" "brain_model_armor_user" {
  count   = var.model_armor_enabled ? 1 : 0
  project = var.project_id
  role    = "roles/modelarmor.user"
  member  = "serviceAccount:${google_service_account.brain.email}"
}

# When the team is catalogued in the Agent Registry, the /api/registry surface reads the
# catalogue, so the brain SA needs read access. viewer is the least role for that (registration
# itself is an operator action via `brain registry sync`, not the brain's).
resource "google_project_iam_member" "brain_agent_registry_viewer" {
  count   = var.agent_registry_enabled ? 1 : 0
  project = var.project_id
  role    = "roles/agentregistry.viewer"
  member  = "serviceAccount:${google_service_account.brain.email}"
}
