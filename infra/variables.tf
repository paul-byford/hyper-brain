# Root variables. The single `profile` switch, plus the handful of values that
# actually differ between a personal demo and a controlled deployment. Sensible,
# secure defaults so a personal apply needs to set only project_id and the
# invoker/admin identities.

variable "profile" {
  description = "Audience profile: 'personal' (applies live) or 'controlled' (validate/plan/policy only)."
  type        = string
  default     = "personal"
  validation {
    condition     = contains(["personal", "controlled"], var.profile)
    error_message = "profile must be 'personal' or 'controlled'."
  }
}

variable "project_id" {
  description = "The Google Cloud project to deploy into."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, buckets and Artifact Registry (in-region data boundary)."
  type        = string
  default     = "europe-west2"
}

variable "name_prefix" {
  description = "Prefix for resource names, so several brains can coexist in one project."
  type        = string
  default     = "brain"
}

variable "labels" {
  description = "Labels applied to all labelable resources."
  type        = map(string)
  default     = { app = "hyper-brain", managed-by = "terraform" }
}

# --- Identity (section 7): coarse authorisation is Cloud Run IAM at the edge ---

variable "invoker_members" {
  description = "IAM members granted run.invoker on the services (a Google Group, never allUsers)."
  type        = list(string)
  default     = []
  validation {
    condition     = !contains([for m in var.invoker_members : lower(m)], "allusers")
    error_message = "The brain must never be public: allUsers cannot be an invoker."
  }
}

variable "image_brain" {
  description = "Container image for the brain MCP service."
  type        = string
  default     = "gcr.io/cloudrun/hello"
}

variable "image_agent" {
  description = "Container image for the ADK agent service."
  type        = string
  default     = "gcr.io/cloudrun/hello"
}

variable "image_ui" {
  description = "Container image for the Brain Explorer UI service."
  type        = string
  default     = "gcr.io/cloudrun/hello"
}

variable "image_indexer" {
  description = "Container image for the index-build job."
  type        = string
  default     = "gcr.io/cloudrun/hello"
}

variable "image_ingest" {
  description = "Container image for the ingestion job."
  type        = string
  default     = "gcr.io/cloudrun/hello"
}

variable "force_destroy_buckets" {
  description = "Allow non-empty buckets to be destroyed (true for the disposable personal demo)."
  type        = bool
  default     = true
}

variable "brain_audience" {
  description = "OIDC audience the brain verifies (its own Cloud Run URL). Set on the second apply once the URL is known; the entrypoint passes it automatically."
  type        = string
  default     = ""
}

variable "ui_origin" {
  description = "The deployed UI's origin (its Cloud Run URL), allowed to call the brain's REST facade via CORS. Set on the second apply once the URL is known; the entrypoint passes it automatically."
  type        = string
  default     = ""
}

variable "agent_model" {
  description = "Gemini model the live agent and answer synthesis use on Vertex."
  type        = string
  default     = "gemini-2.5-flash"
}

# --- OAuth Authorization Server (lets remote MCP connectors sign in) ---
variable "enable_oauth" {
  description = "Provision the in-tenancy OAuth AS and open the brain to remote connectors."
  type        = bool
  default     = true
}

variable "auth_audience" {
  description = "The OAuth AS's own Cloud Run URL (the token issuer). Set on the second apply once known; the entrypoint passes it automatically."
  type        = string
  default     = ""
}

variable "google_client_id" {
  description = "Upstream Google OAuth client id for Sign in with Google (created in the console). Empty until you add it."
  type        = string
  default     = ""
}

variable "google_client_secret" {
  description = "Upstream Google OAuth client secret. Empty until you add it; kept out of the repo (gitignored tfvars)."
  type        = string
  default     = ""
  sensitive   = true
}

# Extra policy grants merged into the published policy. Put real identities here
# (in gitignored personal.tfvars) so they are granted declaratively without ever
# committing an email to the tracked config. Principal is a bare email, a
# `group:...`, or a service-account email; write is optional (default read-only).
variable "extra_grants" {
  description = "Real policy grants merged with the profile's base @example.com policy."
  type = list(object({
    principal = string
    domains   = list(string)
    write     = optional(bool, false)
  }))
  default = []
}

# --- Toggles: off for personal (near-zero idle cost), available for controlled ---

variable "enable_observability" {
  description = "Enable Cloud Trace/Monitoring/Logging APIs (paid dashboards are a controlled opt-in)."
  type        = bool
  default     = false
}

variable "enable_vpc_sc" {
  description = "Create a VPC Service Controls perimeter (controlled only; needs an Organization)."
  type        = bool
  default     = false
}

variable "enable_workforce_identity" {
  description = "Create a Workforce Identity Federation pool (controlled only; needs an Organization)."
  type        = bool
  default     = false
}

# --- Controlled-only inputs, unused (and unvalidated) in the personal profile ---

variable "org_id" {
  description = "Organization id, required only when enable_vpc_sc or enable_workforce_identity is set."
  type        = string
  default     = ""
}

variable "workforce_pool_issuer_uri" {
  description = "OIDC issuer URI of the bank IdP for Workforce Identity Federation."
  type        = string
  default     = ""
}

variable "enable_code_interpreter" {
  type        = bool
  default     = false
  description = <<-EOT
    Give the analyst the managed Vertex AI Code Interpreter sandbox instead of Gemini's
    in-region built-in one. When true, terraform provisions the extension (via
    scripts/provision_code_interpreter.py) and passes BRAIN_CODE_INTERPRETER to the brain
    and agent. NOTE: the Code Interpreter is us-central1-only, so enabling this runs the
    analyst's code CROSS-REGION from the europe-west2 stack.
  EOT
}

variable "code_interpreter_location" {
  type        = string
  default     = "us-central1"
  description = "Region for the Code Interpreter extension (only us-central1 is supported)."
}
