# onprem-vpn — classic Cloud VPN tunnel from the app's VPC to the on-prem vLLM
# farm, plus a tight egress firewall to the vLLM ports. Static route (BGP is a
# future flip). Entirely gated on enable_vpn: when false this module creates
# nothing, so the app's VPC stands alone until the on-prem peer is coordinated.

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
  network = var.network
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
  network             = var.network
  dest_range          = var.onprem_cidr
  next_hop_vpn_tunnel = google_compute_vpn_tunnel.tunnel[0].id
  priority            = 1000
}

# Tight egress allowlist: VM → on-prem vLLM ports only.
resource "google_compute_firewall" "egress_vllm" {
  count              = var.enable_vpn ? 1 : 0
  project            = var.project_id
  name               = "lupin-egress-vllm"
  network            = var.network
  direction          = "EGRESS"
  destination_ranges = [var.onprem_cidr]

  allow {
    protocol = "tcp"
    ports    = ["3000", "3001"]
  }
}
