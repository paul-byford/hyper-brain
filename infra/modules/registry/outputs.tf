output "repository_id" {
  value = google_artifact_registry_repository.docker.repository_id
}

output "repository_url" {
  value = "${google_artifact_registry_repository.docker.location}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker.repository_id}"
}
