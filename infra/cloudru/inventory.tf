# READ-ONLY inventory. All queries scoped to the approved project ID.
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
data "cloudru_evolution_vpc_vpc_collection" "existing" {
  project_id = var.project_id
  page_size  = 100
}
data "cloudru_evolution_compute_nat_gateway_collection" "existing" {
  project_id = var.project_id
  page_size  = 100
}

locals {
  expected_project_id = "20853297-65b7-42a8-af40-25c8d2df4e11"
  vms     = data.cloudru_evolution_compute_vm_collection.existing.vms == null ? [] : data.cloudru_evolution_compute_vm_collection.existing.vms
  disks   = data.cloudru_evolution_compute_disk_collection.existing.disks == null ? [] : data.cloudru_evolution_compute_disk_collection.existing.disks
  ips     = data.cloudru_evolution_compute_external_ip_collection.existing.external_ips == null ? [] : data.cloudru_evolution_compute_external_ip_collection.existing.external_ips
  subnets = data.cloudru_evolution_compute_subnet_collection.existing.subnets == null ? [] : data.cloudru_evolution_compute_subnet_collection.existing.subnets
  vpcs    = data.cloudru_evolution_vpc_vpc_collection.existing.vpcs == null ? [] : data.cloudru_evolution_vpc_vpc_collection.existing.vpcs
  nats    = data.cloudru_evolution_compute_nat_gateway_collection.existing.nat_gateways == null ? [] : data.cloudru_evolution_compute_nat_gateway_collection.existing.nat_gateways
}

check "approved_project_only" {
  assert {
    condition = var.project_id == local.expected_project_id
    error_message = "Project ID does not match approved project. No other project may be queried."
  }
}

output "scoped_inventory" {
  description = "Read-only resource inventory for approved Cloud.ru project"
  value = {
    project_id = var.project_id
    vms = [for x in local.vms : { id = x.id, name = x.name, status = x.status }]
    disks = [for x in local.disks : { id = x.id, name = x.name, size = x.size, status = x.status }]
    ips = [for x in local.ips : { id = x.id, name = x.name, address = x.ip_address, status = x.status }]
    subnets = [for x in local.subnets : { id = x.id, name = x.name, cidr = x.subnet_address, vpc_id = x.vpc_id }]
    vpcs = [for x in local.vpcs : { id = x.id, name = x.name, project_id = x.project_id }]
    nat_gateways = [for x in local.nats : { id = x.id, name = x.name, status = x.status }]
  }
}
