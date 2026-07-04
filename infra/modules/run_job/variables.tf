variable "project_id" {
  type = string
}

variable "location" {
  type = string
}

variable "name" {
  type = string
}

variable "image" {
  type = string
}

variable "service_account" {
  type = string
}

variable "args" {
  description = "Container args (overrides the image CMD), e.g. the indexer command."
  type        = list(string)
  default     = []
}

variable "env" {
  type    = map(string)
  default = {}
}

variable "labels" {
  type    = map(string)
  default = {}
}
