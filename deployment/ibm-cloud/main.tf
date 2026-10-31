locals {
  name                = "${var.prefix}-${var.environment}"
  tags                = ["application:edmg-studio", "environment:${var.environment}"]
  gpu_enabled         = var.accelerator_profile != "cpu"
  cuda_driver_enabled = var.accelerator_profile == "cuda"
  nvidia_compute_enabled = var.accelerator_profile == "nvidia-compute"
}
resource "ibm_is_vpc" "studio" {
  name           = local.name
  resource_group = var.resource_group_id
  tags           = local.tags
}
resource "ibm_is_subnet" "studio" {
  name                     = "${local.name}-subnet"
  vpc                      = ibm_is_vpc.studio.id
  zone                     = var.zone
  total_ipv4_address_count = 256
  resource_group           = var.resource_group_id
}
resource "ibm_is_security_group" "studio" {
  name           = "${local.name}-sg"
  vpc            = ibm_is_vpc.studio.id
  resource_group = var.resource_group_id
}
resource "ibm_is_security_group_rule" "ssh" {
  group     = ibm_is_security_group.studio.id
  direction = "inbound"
  remote    = var.admin_cidr
  protocol  = "tcp"
  port_min  = 22
  port_max  = 22
}
resource "ibm_is_security_group_rule" "web" {
  for_each  = toset(["80", "443"])
  group     = ibm_is_security_group.studio.id
  direction = "outbound"
  remote    = "0.0.0.0/0"
  protocol  = "tcp"
  port_min  = tonumber(each.value)
  port_max  = tonumber(each.value)
}
resource "ibm_is_security_group_rule" "dns" {
  for_each  = toset(["161.26.0.10", "161.26.0.11"])
  group     = ibm_is_security_group.studio.id
  direction = "outbound"
  remote    = each.value
  protocol  = "udp"
  port_min  = 53
  port_max  = 53
}
resource "ibm_is_instance" "studio" {
  name           = local.name
  vpc            = ibm_is_vpc.studio.id
  zone           = var.zone
  profile        = var.profile
  image          = var.image_id
  keys           = [var.ssh_key_id]
  resource_group = var.resource_group_id
  tags           = local.tags
  metadata_service {
    enabled = false
  }
  boot_volume {
    size = var.boot_capacity
  }
  primary_network_interface {
    subnet          = ibm_is_subnet.studio.id
    security_groups = [ibm_is_security_group.studio.id]
  }
  user_data = templatefile("${path.module}/scripts/cloud-init.yaml.tftpl", {
    backend_image       = var.backend_image
    accelerator_profile = var.accelerator_profile
    gpu_enabled         = local.gpu_enabled
    cuda_driver_enabled = local.cuda_driver_enabled
    nvidia_compute_enabled = local.nvidia_compute_enabled
  })
  depends_on = [ibm_is_security_group_rule.web, ibm_is_security_group_rule.dns]
}
resource "ibm_is_floating_ip" "studio" {
  name           = "${local.name}-ip"
  target         = ibm_is_instance.studio.primary_network_interface[0].id
  resource_group = var.resource_group_id
  tags           = local.tags
}
