# READ-ONLY inventory of the approved project before any box plan. Data sources only;
# `terraform plan` here creates nothing and needs no backend. Same collections as
# infra/cloudru/inventory.tf (verified in this project) plus the quota read of
# cloudru-discovery.yml. Output carries ids, names and statuses, never IP addresses.

terraform {
  required_version = ">= 1.10.0"
  required_providers {
    cloudru = {
      source  = "cloudru/cloud"
      version = "2.1.3"
    }
  }
}

variable "project_id" {
  type    = string
  default = "20853297-65b7-42a8-af40-25c8d2df4e11"
  validation {
    condition     = var.project_id == "20853297-65b7-42a8-af40-25c8d2df4e11"
    error_message = "STOP: only the approved project may be read."
  }
}

variable "auth_key_id" {
  type      = string
  sensitive = true
}

variable "auth_secret" {
  type      = string
  sensitive = true
}

provider "cloudru" {
  project_id  = var.project_id
  auth_key_id = var.auth_key_id
  auth_secret = var.auth_secret
  endpoints = {
    iam_endpoint     = "iam.api.cloud.ru:443"
    compute_endpoint = "compute.api.cloud.ru:443"
  }
}

provider "cloudru" {
  alias       = "organization"
  project_id  = var.project_id
  auth_key_id = var.auth_key_id
  auth_secret = var.auth_secret
  endpoints = {
    iam_endpoint            = "iam.api.cloud.ru:443"
    cloud_platform_endpoint = "organization.api.cloud.ru:443"
  }
}

data "cloudru_evolution_compute_vm_collection" "existing" {
  project_id = var.project_id
  page_size  = 100
}

data "cloudru_evolution_compute_disk_collection" "existing" {
  project_id = var.project_id
  page_size  = 100
}

data "cloudru_evolution_compute_external_ip_collection" "existing" {
  project_id = var.project_id
  page_size  = 100
}

data "cloudru_evolution_compute_subnet_collection" "existing" {
  project_id = var.project_id
  page_size  = 100
}

data "cloudru_evolution_organization_project_collection" "approved" {
  provider    = cloudru.organization
  project_ids = [var.project_id]
  page_size   = 1
}

data "cloudru_evolution_organization_quota_usage_collection" "organization" {
  provider           = cloudru.organization
  subject_type_codes = ["QUOTA_SUBJECT_TYPE_CUSTOMER"]
  subject_ids        = [data.cloudru_evolution_organization_project_collection.approved.projects[0].customer_id]
  page_size          = 100
}

data "cloudru_evolution_organization_quota_usage_collection" "project" {
  provider           = cloudru.organization
  subject_type_codes = ["QUOTA_SUBJECT_TYPE_PROJECT"]
  subject_ids        = [var.project_id]
  page_size          = 100
}

locals {
  vms     = coalesce(data.cloudru_evolution_compute_vm_collection.existing.vms, [])
  disks   = coalesce(data.cloudru_evolution_compute_disk_collection.existing.disks, [])
  ips     = coalesce(data.cloudru_evolution_compute_external_ip_collection.existing.external_ips, [])
  subnets = coalesce(data.cloudru_evolution_compute_subnet_collection.existing.subnets, [])
  codes   = ["network.ip.quantity", "compute.vcpu", "compute.ram"]
}

output "scoped_inventory" {
  description = "Read-only inventory of the approved project for boxctl.py classify"
  value = {
    project_id = var.project_id
    vms        = [for x in local.vms : { id = x.id, name = x.name, status = x.status }]
    disks      = [for x in local.disks : { id = x.id, name = x.name, status = x.status }]
    ips        = [for x in local.ips : { id = x.id, name = x.name, status = x.status }]
    subnets    = [for x in local.subnets : { id = x.id, name = x.name }]
    quotas = {
      organization = [for r in coalesce(data.cloudru_evolution_organization_quota_usage_collection.organization.usages, []) : {
        resource_type_code = r.resource_type_code
        individual_limit   = r.individual_limit
        individual_usage   = r.individual_usage
        aggregated_usage   = r.aggregated_usage
      } if contains(local.codes, lower(r.resource_type_code))]
      project = [for r in coalesce(data.cloudru_evolution_organization_quota_usage_collection.project.usages, []) : {
        resource_type_code = r.resource_type_code
        individual_limit   = r.individual_limit
        individual_usage   = r.individual_usage
        aggregated_usage   = r.aggregated_usage
      } if contains(local.codes, lower(r.resource_type_code))]
    }
  }
}
