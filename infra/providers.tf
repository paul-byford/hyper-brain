# The Google provider is configured entirely from variables so one config serves
# both the personal and controlled profiles; only the tfvars differ.
provider "google" {
  project = var.project_id
  region  = var.region
}
