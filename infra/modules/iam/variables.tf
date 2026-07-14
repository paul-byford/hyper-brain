variable "project_id" {
  type = string
}

variable "name_prefix" {
  type = string
}

variable "index_bucket" {
  type = string
}

variable "corpus_bucket" {
  type = string
}

variable "model_armor_enabled" {
  type        = bool
  default     = false
  description = "When true, grant the brain SA roles/modelarmor.user (the content guard is on)."
}

variable "shares_bucket" {
  type = string
}
