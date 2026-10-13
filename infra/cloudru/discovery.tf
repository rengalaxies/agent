terraform {
  required_version = ">= 1.7.0"
  required_providers {
    cloudru = {
      source = "cloudru/cloud"
    }
  }
}
variable "project_id" { type = string }
variable "auth_key_id" { type = string; sensitive = true }
variable "auth_secret" { type = string; sensitive = true }
provider "cloudru" {
  project_id  = var.project_id
  auth_key_id = var.auth_key_id
  auth_secret = var.auth_secret
  endpoints = {
    iam_endpoint     = "iam.api.cloud.ru:443"
    compute_endpoint = "compute.api.cloud.ru:443"
  }
}
data "cloudru_evolution_compute_vm_collection" "existing" {
  project_id = var.project_id
  page_size = 100
}
output "existing_vms" {
  description = "Read-only inventory to prevent duplicating resources already deployed by Codex."
  value = [for vm in data.cloudru_evolution_compute_vm_collection.existing.vms : { name = vm.name, id = vm.id, status = vm.status }]
}
