# Terraform and provider version constraints for the brain stack.
#
# State lives in the GCS bucket created by ./bootstrap (a create-if-not-exists
# step run once before the first apply). The backend is partially configured here
# and finished with `-backend-config=bucket=<name>` at init time, so the same
# config serves any project without editing this file.
terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  backend "gcs" {
    prefix = "brain/state"
  }
}
