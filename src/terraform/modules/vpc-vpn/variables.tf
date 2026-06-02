# vpc-vpn module — inputs

variable "project_id" {
  type        = string
  description = "GCP project ID. No default — must be supplied by the caller."
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "subnet_cidr" {
  type        = string
  description = "Primary subnet CIDR (must NOT overlap the on-prem range)."
  default     = "10.10.0.0/24"
}

variable "ssh_source_ranges" {
  type        = list(string)
  description = "Source ranges allowed to SSH the VM on tcp/22. Default is the IAP range."
  default     = ["35.235.240.0/20"]
}

variable "onprem_cidr" {
  type        = string
  description = "On-prem network reachable over the VPN (the vLLM farm)."
  default     = "192.168.1.0/24"
}

variable "enable_vpn" {
  type        = bool
  description = "Provision the Cloud VPN tunnel to on-prem. Default false — the VPC/subnet/peering/firewall always provision; the VPN waits until the on-prem peer is coordinated (Phase-0 did not stand up the on-prem side)."
  default     = false
}

variable "onprem_peer_ip" {
  type        = string
  description = "On-prem VPN peer public IP (required only when enable_vpn=true)."
  default     = ""
}

variable "vpn_shared_secret" {
  type        = string
  description = "VPN IKE pre-shared key (required only when enable_vpn=true; pass via TF_VAR from Secret Manager, never tfvars)."
  default     = ""
  sensitive   = true
}
