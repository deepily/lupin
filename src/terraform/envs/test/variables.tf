variable "project_id" {
  type        = string
  description = "GCP project ID. NO default — must be supplied (never the sandbox literal). Unset fails the plan loudly."
}

variable "region" {
  type        = string
  description = "GCP region for all regional resources."
  default     = "us-central1"
}

variable "app_vpc_self_link" {
  type        = string
  description = "Self-link of the VPC created by the terraforming-vms app (the VM lives there). Supplied after the app provisions the VM; Cloud SQL private IP + the on-prem VPN attach to it. Empty default keeps `terraform validate` runnable before the app exists."
  default     = ""
}

variable "environment" {
  type        = string
  description = "Environment name; composes resource names (e.g. lupin-lancedb-<env>)."
  default     = "test"

  validation {
    condition     = contains(["test", "prod"], var.environment)
    error_message = "environment must be 'test' or 'prod'."
  }
}

variable "create_buckets" {
  type        = bool
  description = "False reuses the pre-existing GCS buckets (Phase-0 V4 found the -test buckets already present in us-central1). Set true to provision fresh."
  default     = false
}

variable "vm_sa_account_id" {
  type        = string
  description = "Account-id (local part) of the terraforming-vms VM's attached service account. The full email is constructed as <id>@<project_id>.iam.gserviceaccount.com, so the project literal never appears in source (Phase B IAM repoint — bind data-plane roles to the VM vm_sa)."
  default     = "lupin-host-test-sa"
}
