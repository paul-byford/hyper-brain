variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "europe-west2"
}

variable "name_prefix" {
  type    = string
  default = "brain"
}

variable "labels" {
  type    = map(string)
  default = { app = "hyper-brain", managed-by = "terraform" }
}
