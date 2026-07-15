# Baseline Google APIs the stack needs. Vertex and the observability APIs are
# enabled in their own modules so those concerns stay self-contained and toggleable.
locals {
  base_services = [
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "iam.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "storage.googleapis.com",
    # Holds the OAuth AS signing key and the upstream Google client credentials.
    "secretmanager.googleapis.com",
  ]
}

resource "google_project_service" "base" {
  for_each = toset(local.base_services)

  project = var.project_id
  service = each.value

  # Leave APIs enabled on destroy: other things in the project may rely on them,
  # and re-enabling is the expensive/slow operation, not leaving them on.
  disable_on_destroy = false
}

# Model Armor is enabled only when the content guard is configured (model_armor_template set),
# so a deployment that does not use it never turns the API on.
resource "google_project_service" "model_armor" {
  count = var.model_armor_template != "" ? 1 : 0

  project            = var.project_id
  service            = "modelarmor.googleapis.com"
  disable_on_destroy = false
}

# Agent Registry is enabled only when the team is catalogued there (enable_agent_registry).
resource "google_project_service" "agent_registry" {
  count = var.enable_agent_registry ? 1 : 0

  project            = var.project_id
  service            = "agentregistry.googleapis.com"
  disable_on_destroy = false
}
