# Observability enablement, toggled. ADK and the brain emit OpenTelemetry spans;
# turning tracing on is configuration, not code (section 10). Personal keeps this
# off (basic Cloud Trace free tier is enough at demo volume); controlled turns it
# on for the full dashboards.
resource "google_project_service" "observability" {
  for_each = var.enabled ? toset([
    "cloudtrace.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
  ]) : toset([])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}
