# Vertex AI enablement: first-party, in-tenancy embeddings and Gemini synthesis
# (the data boundary, section 4), plus Document AI for in-tenancy rich-format
# parsing during ingestion (section 12).
resource "google_project_service" "vertex" {
  for_each = toset([
    "aiplatform.googleapis.com",
    "documentai.googleapis.com",
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}
