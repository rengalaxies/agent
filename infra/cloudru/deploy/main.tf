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
  description = "Must be selected from scoped catalog; approximately 8 vCPU / 32 GiB."
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
  description = "Single approved management address CIDR for SSH."
  validation {
    condition = can(cidrhost(var.admin_cidr, 0)) && var.admin_cidr != "0.0.0.0/0" && !startswith(var.admin_cidr, "192.0.2.")
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
  vm = {}
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
}
resource "cloudru_evolution_compute_vm" "vm" {
  for_each = local.vm
  project_id = var.project_id
  name = "dm-p1-${each.key}"
  zone = { name = var.zone_name }
  flavor = { name = each.value.flavor }
  disks = [{ id = cloudru_evolution_compute_disk.boot[each.key].id }]
  network_interfaces = [{ id = cloudru_evolution_compute_interface.nic[each.key].id }]
  cloud_init_userdata = base64encode(templatefile("${path.module}/../bootstrap/${each.key == "ui" ? "ui" : "core"}-cloud-init.yaml", {
    git_ref = var.git_ref
    core_ip = cloudru_evolution_compute_interface.nic["core"].ip_address
    ui_ip_dashed = replace(cloudru_evolution_compute_external_ip.ui.ip_address, ".", "-")
    ui_basic_auth_hash = var.ui_basic_auth_hash
  }))
  image_metadata = {
    public_key = { string_value = var.ssh_public_key }
  }
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
