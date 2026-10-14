terraform {
  required_version = ">= 1.7.0"
  required_providers {
    cloudru = {
      source  = "cloudru/cloud"
      version = "2.1.3"
    }
  }
}
variable "project_id" {
  type = string
  default = "20853297-65b7-42a8-af40-25c8d2df4e11"
  validation {
    condition = var.project_id == "20853297-65b7-42a8-af40-25c8d2df4e11"
    error_message = "STOP: only the Daniil Smirnov project is authorized."
  }
}
variable "auth_key_id" {
  type = string
  sensitive = true
}
variable "auth_secret" {
  type = string
  sensitive = true
}
variable "ui_flavor" {
  type = string
  description = "Must be selected from scoped catalog; approximately 2 vCPU / 4 GiB."
}
variable "core_flavor" {
  type = string
  description = "Must be selected from scoped catalog; current iteration 2 vCPU / 8 GiB."
}
variable "ubuntu_image_id" {
  type = string
  description = "Choose supported Ubuntu image ID in project and ru.AZ-2."
}
variable "git_ref" {
  type = string
  validation {
    condition = can(regex("^[0-9a-f]{40}$", var.git_ref))
    error_message = "git_ref must be an immutable git SHA."
  }
}
variable "ui_basic_auth_hash" {
  type        = string
  sensitive   = true
  description = "Caddy bcrypt password hash generated outside the repository."
  validation {
    condition = startswith(var.ui_basic_auth_hash, "$2a$") || startswith(var.ui_basic_auth_hash, "$2b$") || startswith(var.ui_basic_auth_hash, "$2y$")
    error_message = "Supply a bcrypt hash for HTTPS UI authentication."
  }
}
variable "ssh_public_key" {
  type = string
  validation {
    condition = startswith(var.ssh_public_key, "ssh-ed25519 ") || startswith(var.ssh_public_key, "ssh-rsa ")
    error_message = "A real SSH public key is required."
  }
  description = "SSH public key only; no private key and no plaintext password."
}
variable "admin_cidr" {
  type = string
  default = ""
  description = "Optional trusted SSH CIDR; empty disables public SSH."
  validation {
    condition = var.admin_cidr == "" || (can(cidrhost(var.admin_cidr, 0)) && var.admin_cidr != "0.0.0.0/0" && !startswith(var.admin_cidr, "192.0.2."))
    error_message = "SSH admin_cidr must be a restricted valid CIDR, not 0.0.0.0/0."
  }
}
variable "zone_name" {
  type = string
  default = "ru.AZ-2"
  validation {
    condition = var.zone_name == "ru.AZ-2"
    error_message = "Deployment only supports the verified subnet zone ru.AZ-2."
  }
}
locals {
  approved_subnet_id = "d58e80ef-fff1-43eb-b601-96fb358224b7"
  vm = {
    ui   = { flavor = var.ui_flavor, disk = 30 }
    core = { flavor = var.core_flavor, disk = 80 }
  }
}
provider "cloudru" {
  project_id = var.project_id
  auth_key_id = var.auth_key_id
  auth_secret = var.auth_secret
  endpoints = {
    iam_endpoint = "iam.api.cloud.ru:443"
    compute_endpoint = "compute.api.cloud.ru:443"
  }
}

resource "cloudru_evolution_compute_security_group" "ui" {
  project_id = var.project_id
  name = "dm-p1-ui"
  zone = { name = var.zone_name }
  description = "Public HTTPS edge only"
}
resource "cloudru_evolution_compute_security_group" "core" {
  project_id = var.project_id
  name = "dm-p1-core"
  zone = { name = var.zone_name }
  description = "Private domain core; no inbound public endpoints"
}
resource "cloudru_evolution_compute_security_group_rule" "ui_https" {
  security_group_id = cloudru_evolution_compute_security_group.ui.id
  direction = "TRAFFIC_DIRECTION_INGRESS"
  ether_type = "ETHER_TYPE_IPV4"
  ip_protocol = "IP_PROTOCOL_TCP"
  port_range = "443:443"
  remote_ip_prefix = "0.0.0.0/0"
}
resource "cloudru_evolution_compute_security_group_rule" "ui_http" {
  security_group_id = cloudru_evolution_compute_security_group.ui.id
  direction = "TRAFFIC_DIRECTION_INGRESS"
  ether_type = "ETHER_TYPE_IPV4"
  ip_protocol = "IP_PROTOCOL_TCP"
  port_range = "80:80"
  remote_ip_prefix = "0.0.0.0/0"
}
resource "cloudru_evolution_compute_security_group_rule" "ui_admin" {
  count = var.admin_cidr == "" ? 0 : 1
  security_group_id = cloudru_evolution_compute_security_group.ui.id
  direction = "TRAFFIC_DIRECTION_INGRESS"
  ether_type = "ETHER_TYPE_IPV4"
  ip_protocol = "IP_PROTOCOL_TCP"
  port_range = "22:22"
  remote_ip_prefix = var.admin_cidr
}
resource "cloudru_evolution_compute_security_group_rule" "core_api" {
  security_group_id = cloudru_evolution_compute_security_group.core.id
  direction = "TRAFFIC_DIRECTION_INGRESS"
  ether_type = "ETHER_TYPE_IPV4"
  ip_protocol = "IP_PROTOCOL_TCP"
  port_range = "8000:8000"
  remote_security_group = { id = cloudru_evolution_compute_security_group.ui.id }
}
resource "cloudru_evolution_compute_security_group_rule" "ui_outbound" {
  security_group_id = cloudru_evolution_compute_security_group.ui.id
  direction = "TRAFFIC_DIRECTION_EGRESS"
  ether_type = "ETHER_TYPE_IPV4"
  ip_protocol = "IP_PROTOCOL_ANY"
  port_range = "any"
  remote_ip_prefix = "0.0.0.0/0"
}
resource "cloudru_evolution_compute_security_group_rule" "core_outbound" {
  security_group_id = cloudru_evolution_compute_security_group.core.id
  direction = "TRAFFIC_DIRECTION_EGRESS"
  ether_type = "ETHER_TYPE_IPV4"
  ip_protocol = "IP_PROTOCOL_ANY"
  port_range = "any"
  remote_ip_prefix = "0.0.0.0/0"
}

resource "cloudru_evolution_compute_disk" "boot" {
  for_each = local.vm
  project_id = var.project_id
  name = "dm-p1-${each.key}-boot"
  zone = { name = var.zone_name }
  size = each.value.disk
  disk_type = { name = "SSD" }
  image = { id = var.ubuntu_image_id }
  bootable = true
  encrypted = true
  readonly = false
  shared = false
}
resource "cloudru_evolution_compute_interface" "nic" {
  for_each = local.vm
  project_id = var.project_id
  name = "dm-p1-${each.key}-nic"
  zone = { name = var.zone_name }
  subnet = { id = local.approved_subnet_id }
  interface_security_enabled = true
  security_groups = [{ id = each.key == "ui" ? cloudru_evolution_compute_security_group.ui.id : cloudru_evolution_compute_security_group.core.id }]
  type = "INTERFACE_TYPE_REGULAR"
}
resource "cloudru_evolution_compute_nat_gateway" "core_egress" {
  project_id = var.project_id
  name       = "dm-p1-core-snat"
  zone       = { name = var.zone_name }
  vpc_id     = "6a7f399a-277d-40f6-98fb-1ab8fe8531e1"
  description = "Approved-project-only private core outbound for package and artifact delivery"
  lifecycle {
    prevent_destroy = true
  }
}

resource "cloudru_evolution_compute_external_ip" "ui" {
  project_id = var.project_id
  name = "dm-p1-ui-public-ip"
  zone = { name = var.zone_name }
  network_interface = { id = cloudru_evolution_compute_interface.nic["ui"].id }
  lifecycle {
    prevent_destroy = true
    precondition {
      condition = var.original_ui_ip != ""
      error_message = "STOP: original approved UI IP allocation must exist before rebinding."
    }
    postcondition {
      condition = self.id == "33a27f64-e474-49ed-a17b-15f67dd16400" && self.ip_address == var.original_ui_ip && self.network_interface.id == cloudru_evolution_compute_interface.nic["ui"].id
      error_message = "STOP: original UI IP or approved interface binding was not retained."
    }
  }
}
variable "original_ui_ip" {
  type = string
  sensitive = true
  description = "Original UI public IPv4 read from encrypted production state before planning; immutable recovery boundary."
  validation {
    condition = can(cidrhost("${var.original_ui_ip}/32", 0))
    error_message = "Original UI IPv4 must be read from the existing encrypted deployment state."
  }
}
resource "cloudru_evolution_compute_vm" "vm" {
  depends_on = [cloudru_evolution_compute_nat_gateway.core_egress]
  for_each = { core = local.vm.core }
  project_id = var.project_id
  name = "dm-p1-${each.key}"
  zone = { name = var.zone_name }
  flavor = { name = each.value.flavor }
  disks = [{ id = cloudru_evolution_compute_disk.boot[each.key].id }]
  network_interfaces = [{ id = cloudru_evolution_compute_interface.nic[each.key].id }]
  cloud_init_userdata = base64encode(templatefile("${path.module}/../bootstrap/core-cloud-init.yaml", {
    git_ref = var.git_ref
    ssh_public_key = jsonencode(trimspace(var.ssh_public_key))
    core_ip = cloudru_evolution_compute_interface.nic["core"].ip_address
  }))
  lifecycle {
    prevent_destroy = true
  }
}
output "planned_scope" {
  value = {
    project_id = var.project_id
    zone = var.zone_name
    subnet_id = local.approved_subnet_id
    vm_names = [for name, vm in local.vm : "dm-p1-${name}"]
    public_ip_count = 1
    core_public_ip_count = 0
  }
}

output "ui_https_url" {
  description = "Temporary demo hostname with managed TLS and restricted HTTP authentication"
  value       = "https://${replace(cloudru_evolution_compute_external_ip.ui.ip_address, ".", "-")}.sslip.io"
}

# Move only the UI VM state address; the private core retains its lifecycle guard.
moved {
  from = cloudru_evolution_compute_vm.vm["ui"]
  to = cloudru_evolution_compute_vm.ui_vm
}
variable "deployment_public_key" {
  type = string
  default = ""
  description = "Temporary installation public key; private key never enters Terraform."
}
variable "deployment_cidr" {
  type = string
  default = ""
  description = "Temporary installation runner single IPv4 /32."
  validation {
    condition = var.deployment_cidr == "" || (can(cidrhost(var.deployment_cidr, 0)) && endswith(var.deployment_cidr, "/32"))
    error_message = "Installation source must be a single IPv4 /32."
  }
}
resource "cloudru_evolution_compute_vm" "ui_vm" {
  depends_on = [cloudru_evolution_compute_nat_gateway.core_egress]
  project_id = var.project_id
  name = "dm-p1-ui"
  zone = { name = var.zone_name }
  flavor = { name = var.ui_flavor }
  disks = [{ id = cloudru_evolution_compute_disk.boot["ui"].id }]
  network_interfaces = [{ id = cloudru_evolution_compute_interface.nic["ui"].id }]
  image_metadata = {
    hostname = { string_value = "dm-p1-ui" }
    name = { string_value = "dmadmin" }
    public_key = { string_value = var.deployment_public_key == "" ? trimspace(var.ssh_public_key) : trimspace(var.deployment_public_key) }
    guest_agent_ready = { bool_value = true }
  }
  # Only the recovery workflow may replace this exact VM. Boot disk is retained.
  lifecycle {
    precondition {
      condition = cloudru_evolution_compute_disk.boot["ui"].id == "9af43326-a6e1-45f1-8235-b82937a1f664"
      error_message = "STOP: approved UI recovery must retain its existing boot disk."
    }
  }
}
resource "cloudru_evolution_compute_security_group_rule" "deployment_ui" {
  count = var.deployment_cidr == "" ? 0 : 1
  security_group_id = cloudru_evolution_compute_security_group.ui.id
  direction = "TRAFFIC_DIRECTION_INGRESS"
  ether_type = "ETHER_TYPE_IPV4"
  ip_protocol = "IP_PROTOCOL_TCP"
  port_range = "22:22"
  remote_ip_prefix = var.deployment_cidr
}
