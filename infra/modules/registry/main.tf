# Docker Artifact Registry for the brain, agent and UI images.
resource "google_artifact_registry_repository" "docker" {
  # checkov:skip=CKV_GCP_84: CSEK/CMEK adds KMS key cost and teardown complexity;
  # Google-managed encryption is on by default. CMEK is a controlled-profile option.
  project       = var.project_id
  location      = var.location
  repository_id = "${var.name_prefix}-images"
  format        = "DOCKER"
  description   = "Container images for the hyper-brain stack."
  labels        = var.labels
}
