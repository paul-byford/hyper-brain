variable "project_id" {
  type = string
}

variable "location" {
  type = string
}

variable "name_prefix" {
  type = string
}

variable "labels" {
  type    = map(string)
  default = {}
}

variable "force_destroy" {
  type    = bool
  default = false
}
