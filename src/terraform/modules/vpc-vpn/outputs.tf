# vpc-vpn module — outputs

output "network_self_link" {
  value       = google_compute_network.vpc.self_link
  description = "VPC self_link (for Cloud SQL private IP + VM NIC)."
}

output "network_id" {
  value       = google_compute_network.vpc.id
  description = "VPC id."
}

output "subnet_self_link" {
  value       = google_compute_subnetwork.subnet.self_link
  description = "Subnet self_link (for the VM network interface)."
}

output "private_services_connection" {
  value       = google_service_networking_connection.private_services.id
  description = "Service Networking connection id — Cloud SQL depends on this for private IP."
}

output "vpn_gateway_ip" {
  value       = var.enable_vpn ? google_compute_address.vpn_ip[0].address : ""
  description = "GCP VPN gateway public IP (empty unless enable_vpn). Hand this to the on-prem peer config."
}
