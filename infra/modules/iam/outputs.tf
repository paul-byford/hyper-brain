output "brain_sa_email" {
  value = google_service_account.brain.email
}

output "agent_sa_email" {
  value = google_service_account.agent.email
}

output "ui_sa_email" {
  value = google_service_account.ui.email
}

output "indexer_sa_email" {
  value = google_service_account.indexer.email
}

output "ingest_sa_email" {
  value = google_service_account.ingest.email
}
