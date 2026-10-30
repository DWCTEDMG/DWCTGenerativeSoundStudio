variable "region" {
  type        = string
  description = "region"
  default     = "us-south"
}
variable "zone" {
  type        = string
  description = "zone"
  default     = "us-south-1"
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
  description = "profile"
  default     = "bx2-2x8"
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
