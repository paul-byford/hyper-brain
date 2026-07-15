output "brain_url" {
  description = "The brain MCP service URL."
  value       = module.brain_service.uri
}

output "agent_url" {
  description = "The ADK agent service URL."
  value       = module.agent_service.uri
}

output "ui_url" {
  description = "The Brain Explorer UI service URL."
  value       = module.ui_service.uri
}

output "auth_url" {
  description = "The OAuth Authorization Server URL (empty when OAuth is disabled)."
  value       = var.enable_oauth ? module.auth_service[0].uri : ""
}

output "index_bucket" {
  description = "The bucket holding the index artefacts."
  value       = module.storage.index_bucket
}

output "corpus_bucket" {
  description = "The bucket holding the corpus mirror."
  value       = module.storage.corpus_bucket
}

output "shares_bucket" {
  description = "The bucket holding the sharing overlay + Agent Studio's custom-agent registry."
  value       = module.storage.shares_bucket
}

output "artifact_registry" {
  description = "The Docker Artifact Registry repository."
  value       = module.registry.repository_id
}

output "profile" {
  description = "The active profile."
  value       = var.profile
}

output "name_prefix" {
  description = "Resource name prefix (services and jobs are <prefix>-brain, <prefix>-indexer, ...)."
  value       = var.name_prefix
}
