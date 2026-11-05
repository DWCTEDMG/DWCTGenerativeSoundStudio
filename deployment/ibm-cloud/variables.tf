variable "region" {
  type        = string
  description = "IBM Cloud region; defaults to the A100-enabled us-east deployment."
  default     = "us-east"
}
variable "zone" {
  type        = string
  description = "A100-enabled IBM VPC zone. The default is us-east-1; confirm account availability before applying."
  default     = "us-east-1"
}
variable "resource_group_id" {
  type        = string
  description = "Existing customer resource group ID."
}
variable "prefix" {
  type        = string
  description = "prefix"
  default     = "edmg"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,19}$", var.prefix))
    error_message = "Use 1-20 lowercase letters, digits or hyphens, starting with a letter."
  }
}
variable "environment" {
  type        = string
  description = "environment"
  default     = "production"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,19}$", var.environment))
    error_message = "Use 1-20 lowercase letters, digits or hyphens, starting with a letter."
  }
}
variable "profile" {
  type        = string
  description = "IBM VPC profile; defaults to one A100 80 GB GPU."
  default     = "gx3d-24x120x1a100p"
}
variable "accelerator_profile" {
  type        = string
  description = "Backend compute mode; defaults to IBM A100 with NVIDIA Virtual Compute Server licensing."
  default     = "nvidia-compute"
  validation {
    condition = contains(["cpu", "cuda", "nvidia-compute"], var.accelerator_profile) && (
      var.accelerator_profile == "cpu" ||
      can(regex("^gx[23].*(a100p|h100|h200|l40s|l4|v100)$", var.profile))
    )
    error_message = "Choose cpu, cuda, or nvidia-compute; GPU modes require a compatible NVIDIA GPU profile."
  }
}
variable "image_id" {
  type        = string
  description = "Customer-selected IBM Ubuntu 24.04 amd64 VPC image ID in the target region."
}
variable "ssh_key_id" {
  type        = string
  description = "Existing regional IBM VPC SSH public key ID."
}
variable "admin_cidr" {
  type        = string
  description = "Single administrator public IPv4 address in /32 notation."
  validation {
    condition     = can(cidrhost(var.admin_cidr, 0)) && endswith(var.admin_cidr, "/32")
    error_message = "Supply a single administrator IPv4 /32 CIDR."
  }
}
variable "backend_image" {
  type        = string
  description = "Public customer-built backend image pinned by sha256 digest."
  default     = "ghcr.io/dwctedmg/edmg-studio-backend@sha256:bd2f64cedefb0a21faa29a399fed3226ec59bdc58dda1ec96a84184e1c721d1d"
  validation {
    condition     = can(regex("^[a-zA-Z0-9./:_-]+@sha256:[a-f0-9]{64}$", var.backend_image))
    error_message = "Use a public OCI image pinned by sha256 digest."
  }
}
variable "boot_capacity" {
  type        = number
  description = "boot capacity"
  default     = 100
}
