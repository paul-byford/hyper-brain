output "state_bucket" {
  description = "The state bucket to pass to the main config: terraform init -backend-config=bucket=<this>."
  value       = google_storage_bucket.state.name
}
