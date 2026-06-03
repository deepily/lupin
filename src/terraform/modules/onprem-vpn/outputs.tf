# onprem-vpn module — outputs

output "vpn_gateway_ip" {
  value       = var.enable_vpn ? google_compute_address.vpn_ip[0].address : ""
  description = "GCP VPN gateway public IP (empty unless enable_vpn). Hand this to the on-prem peer config."
}
