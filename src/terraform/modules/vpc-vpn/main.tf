# vpc-vpn — VPC + subnet + private-services peering (for Cloud SQL private IP) +
# firewall, plus an OPTIONAL classic Cloud VPN tunnel to the on-prem vLLM farm.
#
# The VPN is gated on enable_vpn (default false): the network substrate the VM and
# Cloud SQL need is always created; the tunnel waits until the on-prem peer is
# coordinated. Static-route classic VPN matches the straw-man (BGP is a future flip).

resource "google_compute_network" "vpc" {
  project                 = var.project_id
  name                    = "lupin-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "subnet" {
  project       = var.project_id
  name          = "lupin-subnet"
  region        = var.region
  network       = google_compute_network.vpc.id
  ip_cidr_range = var.subnet_cidr
}

# --- Private Services Access: reserved range + peering so Cloud SQL gets a private IP ---
resource "google_compute_global_address" "private_services" {
  project       = var.project_id
  name          = "lupin-private-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "private_services" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]
}

# --- Firewall: operator SSH (IAP range by default) ---
resource "google_compute_firewall" "allow_ssh" {
  project       = var.project_id
  name          = "lupin-allow-ssh"
  network       = google_compute_network.vpc.id
  direction     = "INGRESS"
  source_ranges = var.ssh_source_ranges

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

# --- Firewall: egress to the on-prem vLLM ports only (tight allowlist) ---
resource "google_compute_firewall" "egress_vllm" {
  project            = var.project_id
  name               = "lupin-egress-vllm"
  network            = google_compute_network.vpc.id
  direction          = "EGRESS"
  destination_ranges = [var.onprem_cidr]

  allow {
    protocol = "tcp"
    ports    = ["3000", "3001"]
  }
}

# ----------------------------------------------------------------------------
# OPTIONAL classic Cloud VPN (enable_vpn=true). Static route to the on-prem CIDR.
# ----------------------------------------------------------------------------
resource "google_compute_address" "vpn_ip" {
  count   = var.enable_vpn ? 1 : 0
  project = var.project_id
  name    = "lupin-vpn-ip"
  region  = var.region
}

resource "google_compute_vpn_gateway" "gw" {
  count   = var.enable_vpn ? 1 : 0
  project = var.project_id
  name    = "lupin-vpn-gw"
  network = google_compute_network.vpc.id
  region  = var.region
}

resource "google_compute_forwarding_rule" "esp" {
  count       = var.enable_vpn ? 1 : 0
  project     = var.project_id
  name        = "lupin-vpn-esp"
  region      = var.region
  ip_protocol = "ESP"
  ip_address  = google_compute_address.vpn_ip[0].address
  target      = google_compute_vpn_gateway.gw[0].id
}

resource "google_compute_forwarding_rule" "udp500" {
  count       = var.enable_vpn ? 1 : 0
  project     = var.project_id
  name        = "lupin-vpn-udp500"
  region      = var.region
  ip_protocol = "UDP"
  port_range  = "500"
  ip_address  = google_compute_address.vpn_ip[0].address
  target      = google_compute_vpn_gateway.gw[0].id
}

resource "google_compute_forwarding_rule" "udp4500" {
  count       = var.enable_vpn ? 1 : 0
  project     = var.project_id
  name        = "lupin-vpn-udp4500"
  region      = var.region
  ip_protocol = "UDP"
  port_range  = "4500"
  ip_address  = google_compute_address.vpn_ip[0].address
  target      = google_compute_vpn_gateway.gw[0].id
}

resource "google_compute_vpn_tunnel" "tunnel" {
  count              = var.enable_vpn ? 1 : 0
  project            = var.project_id
  name               = "lupin-vpn-tunnel"
  region             = var.region
  peer_ip            = var.onprem_peer_ip
  shared_secret      = var.vpn_shared_secret
  target_vpn_gateway = google_compute_vpn_gateway.gw[0].id

  local_traffic_selector  = [var.subnet_cidr]
  remote_traffic_selector = [var.onprem_cidr]

  depends_on = [
    google_compute_forwarding_rule.esp,
    google_compute_forwarding_rule.udp500,
    google_compute_forwarding_rule.udp4500,
  ]
}

resource "google_compute_route" "to_onprem" {
  count               = var.enable_vpn ? 1 : 0
  project             = var.project_id
  name                = "lupin-route-onprem"
  network             = google_compute_network.vpc.id
  dest_range          = var.onprem_cidr
  next_hop_vpn_tunnel = google_compute_vpn_tunnel.tunnel[0].id
  priority            = 1000
}
