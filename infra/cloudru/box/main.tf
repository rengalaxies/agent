# One Linux VM for the agent-service box (batch 5B). Apply only through
# .github/workflows/cloudru-box.yml: protected environment, reviewed plan digest,
# encrypted remote state with use_lockfile. Never apply with local state.
#
# The model is the external Cloud.ru Foundation Models API: no GPU, no Kubernetes.
# Secrets never enter this configuration; the owner delivers them over SSH (see
# docs/implementation/autonomous-mvp/batch-5b.md).

terraform {
  required_version = ">= 1.10.0"
  required_providers {
    cloudru = {
      source  = "cloudru/cloud"
      version = "2.1.3"
    }
  }
  # Partial configuration; boxctl.py init supplies bucket, key terraform/box/<box_id>.tfstate,
  # use_lockfile=true and encrypt=true. The SSE-C key comes from AWS_SSE_CUSTOMER_KEY.
  backend "s3" {}
}

variable "project_id" {
  type    = string
  default = "20853297-65b7-42a8-af40-25c8d2df4e11"
  validation {
    condition     = var.project_id == "20853297-65b7-42a8-af40-25c8d2df4e11"
    error_message = "STOP: only project 20853297-65b7-42a8-af40-25c8d2df4e11 is authorized."
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

variable "box_id" {
  type        = string
  description = "Short id of this installation; every resource is named amvp-box-<box_id>-<kind>."
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{2,15}$", var.box_id))
    error_message = "box_id: 3-16 lowercase letters and digits, starting with a letter."
  }
}

variable "expires_on" {
  type        = string
  description = "TTL of the box (YYYY-MM-DD). Recorded in the ownership output and ledger; nothing deletes it automatically."
  validation {
    condition     = can(regex("^20[0-9]{2}-[01][0-9]-[0-3][0-9]$", var.expires_on))
    error_message = "expires_on must be YYYY-MM-DD."
  }
}

variable "commit" {
  type        = string
  description = "Git commit of this configuration, recorded in the ownership output."
  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.commit))
    error_message = "commit must be a full git SHA."
  }
}

variable "zone_name" {
  type    = string
  default = "ru.AZ-2"
  validation {
    condition     = var.zone_name == "ru.AZ-2"
    error_message = "Only ru.AZ-2, the zone of the approved subnet."
  }
}

variable "subnet_id" {
  type        = string
  default     = "d58e80ef-fff1-43eb-b601-96fb358224b7"
  description = "Existing project subnet 10.0.0.0/24, verified by the live API on 2026-10-18. Read, never managed here."
  validation {
    condition     = var.subnet_id == "d58e80ef-fff1-43eb-b601-96fb358224b7"
    error_message = "Only the verified project subnet."
  }
}

variable "flavor" {
  type        = string
  default     = "gen-2-4"
  description = "2 vCPU / 4 GiB: the smallest full-share flavor in the project catalog (run 38599890963)."
  validation {
    condition     = contains(["gen-2-4", "gen-2-8"], var.flavor)
    error_message = "flavor: gen-2-4 (default) or gen-2-8."
  }
}

variable "image_id" {
  type        = string
  default     = "fe51a6e6-a5ad-410e-b441-1a195208a8cf"
  description = "Ubuntu-24.04 (min_disk 10) from the project catalog: python3.12 and git, as the 5A release needs."
}

variable "disk_gib" {
  type    = number
  default = 20
  validation {
    condition     = var.disk_gib >= 10 && var.disk_gib <= 60
    error_message = "disk_gib between 10 and 60."
  }
}

variable "ssh_public_key" {
  type        = string
  description = "Owner SSH public key for user boxadmin. Public key only."
  validation {
    condition     = startswith(var.ssh_public_key, "ssh-ed25519 ") || startswith(var.ssh_public_key, "ssh-rsa ")
    error_message = "A real SSH public key is required."
  }
}

variable "admin_cidr" {
  type        = string
  default     = ""
  description = "Owner IPv4 /32 allowed to SSH. Empty: no inbound rule at all."
  validation {
    condition     = var.admin_cidr == "" || (can(cidrhost(var.admin_cidr, 0)) && endswith(var.admin_cidr, "/32") && !startswith(var.admin_cidr, "10.") && !startswith(var.admin_cidr, "192.0.2."))
    error_message = "admin_cidr must be empty or one public IPv4 /32."
  }
}

variable "release_url" {
  type = string
  validation {
    condition     = startswith(var.release_url, "https://github.com/rengalaxies/agent/releases/download/")
    error_message = "Release must be a GitHub release asset of rengalaxies/agent."
  }
}

variable "release_sha256" {
  type = string
  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.release_sha256))
    error_message = "release_sha256 must be a sha256 hex digest."
  }
}

variable "release_name" {
  type = string
  validation {
    condition     = can(regex("^agent-service-[0-9A-Za-z.]+-g[0-9a-f]{12}-linux-x86_64-cp312$", var.release_name))
    error_message = "release_name must be a linux-x86_64-cp312 release built by tools/agent_service/box/release.py."
  }
}

locals {
  name   = "amvp-box-${var.box_id}"
  marker = "amvp-box:${var.box_id}"
  # Polling needs outbound HTTPS only (GitHub, Jira, Foundation Models, release download).
  # 80 is for apt and the instance metadata service, 53 and 123 for DNS and NTP.
  egress = {
    https   = { protocol = "IP_PROTOCOL_TCP", ports = "443:443" }
    http    = { protocol = "IP_PROTOCOL_TCP", ports = "80:80" }
    dns_udp = { protocol = "IP_PROTOCOL_UDP", ports = "53:53" }
    dns_tcp = { protocol = "IP_PROTOCOL_TCP", ports = "53:53" }
    ntp     = { protocol = "IP_PROTOCOL_UDP", ports = "123:123" }
  }
  release_env = join("", [
    "RELEASE_URL=${var.release_url}\n",
    "RELEASE_SHA256=${var.release_sha256}\n",
    "RELEASE_NAME=${var.release_name}\n",
  ])
  cloud_init = join("\n", ["#cloud-config", yamlencode({
    package_update = true
    packages       = ["ca-certificates", "curl", "git", "python3"]
    write_files = [
      { path = "/etc/agent-service-box-provision/release.env", permissions = "0644", encoding = "b64", content = base64encode(local.release_env) },
      { path = "/usr/local/sbin/agent-service-box-provision", permissions = "0755", encoding = "b64", content = filebase64("${path.module}/provision.sh") },
      { path = "/etc/systemd/system/agent-service-box-provision.service", permissions = "0644", encoding = "b64", content = filebase64("${path.module}/agent-service-box-provision.service") },
      { path = "/etc/systemd/system/agent-service-box-provision.path", permissions = "0644", encoding = "b64", content = filebase64("${path.module}/agent-service-box-provision.path") },
    ]
    runcmd = [
      ["install", "-d", "-m", "0755", "/etc/agent-service"],
      ["systemctl", "daemon-reload"],
      ["systemctl", "enable", "--now", "agent-service-box-provision.path"],
      ["systemctl", "start", "--no-block", "agent-service-box-provision.service"],
    ]
  })])
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

resource "cloudru_evolution_compute_security_group" "box" {
  project_id  = var.project_id
  name        = "${local.name}-sg"
  zone        = { name = var.zone_name }
  description = "${local.marker} managed by infra/cloudru/box; inbound SSH only from admin_cidr"
}

resource "cloudru_evolution_compute_security_group_rule" "egress" {
  for_each          = local.egress
  security_group_id = cloudru_evolution_compute_security_group.box.id
  direction         = "TRAFFIC_DIRECTION_EGRESS"
  ether_type        = "ETHER_TYPE_IPV4"
  ip_protocol       = each.value.protocol
  port_range        = each.value.ports
  remote_ip_prefix  = "0.0.0.0/0"
}

resource "cloudru_evolution_compute_security_group_rule" "ssh" {
  count             = var.admin_cidr == "" ? 0 : 1
  security_group_id = cloudru_evolution_compute_security_group.box.id
  direction         = "TRAFFIC_DIRECTION_INGRESS"
  ether_type        = "ETHER_TYPE_IPV4"
  ip_protocol       = "IP_PROTOCOL_TCP"
  port_range        = "22:22"
  remote_ip_prefix  = var.admin_cidr
}

resource "cloudru_evolution_compute_disk" "boot" {
  project_id = var.project_id
  name       = "${local.name}-boot"
  zone       = { name = var.zone_name }
  size       = var.disk_gib
  disk_type  = { name = "SSD" }
  image      = { id = var.image_id }
  bootable   = true
  encrypted  = true
  readonly   = false
  shared     = false
}

resource "cloudru_evolution_compute_interface" "nic" {
  project_id                 = var.project_id
  name                       = "${local.name}-nic"
  zone                       = { name = var.zone_name }
  subnet                     = { id = var.subnet_id }
  interface_security_enabled = true
  security_groups            = [{ id = cloudru_evolution_compute_security_group.box.id }]
  type                       = "INTERFACE_TYPE_REGULAR"
}

# One public IPv4 serves egress and the optional owner SSH. It costs the same per hour as
# an sNAT gateway and, unlike sNAT, needs no bastion for SSH.
resource "cloudru_evolution_compute_external_ip" "public" {
  project_id        = var.project_id
  name              = "${local.name}-ip"
  zone              = { name = var.zone_name }
  network_interface = { id = cloudru_evolution_compute_interface.nic.id }
}

resource "cloudru_evolution_compute_vm" "box" {
  project_id         = var.project_id
  name               = "${local.name}-vm"
  zone               = { name = var.zone_name }
  flavor             = { name = var.flavor }
  disks              = [{ id = cloudru_evolution_compute_disk.boot.id }]
  network_interfaces = [{ id = cloudru_evolution_compute_interface.nic.id }]
  image_metadata = {
    hostname          = { string_value = "${local.name}-vm" }
    name              = { string_value = "boxadmin" }
    public_key        = { string_value = trimspace(var.ssh_public_key) }
    guest_agent_ready = { bool_value = true }
  }
  cloud_init_userdata = base64encode(local.cloud_init)
  lifecycle {
    # Release updates go through `box update` on the VM, not through a new VM.
    ignore_changes = [cloud_init_userdata]
  }
  depends_on = [cloudru_evolution_compute_external_ip.public, cloudru_evolution_compute_security_group_rule.egress]
}

output "ownership" {
  description = "Ownership record of this box; boxctl.py status and cleanup read it from the remote state."
  value = {
    box_id      = var.box_id
    project_id  = var.project_id
    expires_on  = var.expires_on
    commit      = var.commit
    marker      = local.marker
    names       = { for k in ["sg", "boot", "nic", "ip", "vm"] : k => "${local.name}-${k}" }
    vm_id       = cloudru_evolution_compute_vm.box.id
    disk_id     = cloudru_evolution_compute_disk.boot.id
    ip_id       = cloudru_evolution_compute_external_ip.public.id
    sg_id       = cloudru_evolution_compute_security_group.box.id
    nic_id      = cloudru_evolution_compute_interface.nic.id
    ssh_ingress = var.admin_cidr != ""
  }
}

output "public_ip" {
  description = "Owner-only: the address for SSH. Sensitive so that workflow logs of the public repo do not print it."
  sensitive   = true
  value       = cloudru_evolution_compute_external_ip.public.ip_address
}

output "cloud_init_sha256" {
  description = "sha256 of the rendered cloud-config, to compare with a local render."
  value       = sha256(local.cloud_init)
}
