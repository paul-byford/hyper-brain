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

variable "ingress" {
  type    = string
  default = "INGRESS_TRAFFIC_ALL"
}

variable "invoker_members" {
  type    = list(string)
  default = []
}

variable "env" {
  type    = map(string)
  default = {}
}

variable "max_instances" {
  type    = number
  default = 4
}

variable "labels" {
  type    = map(string)
  default = {}
}
