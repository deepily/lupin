# onprem-vpn module — inputs
# The ONLY networking piece Lupin still owns after adopting the terraforming-vms
# app for the VPC/subnet/NAT/SSH: a Cloud VPN tunnel from the app's VPC to the
# on-prem vLLM farm. Everything else (VPC, subnet, NAT, IAP-SSH) is the app's.

variable "project_id" {
  type        = string
  description = "GCP project ID. No default — must be supplied by the caller."
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "network" {
  type        = string
  description = "Self-link/id of the VPC to attach the tunnel + firewall to (the terraforming-vms app's VPC)."
  default     = ""
}

variable "subnet_cidr" {
  type        = string
  description = "Local traffic selector — the app VPC's subnet CIDR (must not overlap on-prem)."
  default     = "10.10.0.0/24"
}

variable "onprem_cidr" {
  type        = string
  description = "On-prem network reachable over the tunnel (the vLLM farm)."
  default     = "192.168.1.0/24"
}

variable "enable_vpn" {
  type        = bool
  description = "Provision the tunnel. Default false — waits on the on-prem peer (IP + PSK) being coordinated."
  default     = false
}

variable "onprem_peer_ip" {
  type        = string
  description = "On-prem VPN peer public IP (required only when enable_vpn=true)."
  default     = ""
}

variable "vpn_shared_secret" {
  type        = string
  description = "IKE pre-shared key (required only when enable_vpn=true; pass via TF_VAR from Secret Manager, never tfvars)."
  default     = ""
  sensitive   = true
}
