variable "project_id" {
  type        = string
  description = "The GCP project the Code Interpreter extension is provisioned in."
}

variable "location" {
  type        = string
  default     = "us-central1"
  description = "The extension's region. The Code Interpreter is only offered in us-central1."
}
