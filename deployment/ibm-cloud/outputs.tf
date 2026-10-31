output "public_ip" {
  description = "SSH only; backend API is not publicly exposed."
  value       = ibm_is_floating_ip.studio.address
}
output "ssh_tunnel" {
  description = "Keep this tunnel running while using the Windows client."
  value       = "ssh -N -L 127.0.0.1:17863:127.0.0.1:8443 ubuntu@${ibm_is_floating_ip.studio.address}"
}
output "backend_url" {
  description = "Loopback endpoint protected in transit by the SSH tunnel."
  value       = "https://127.0.0.1:17863"
}
