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

# --- GPU model-server → Cloud Run (Set B, 2026-06-30). Knobs Rick flips post-
#     decision; recommended defaults wired (min=0, internal ingress, L4). -------
variable "model_server_image_tag" {
  type        = string
  description = "Image tag (or :digest) of the lupin-model-server image in Artifact Registry to deploy to Cloud Run."
  default     = "latest"
}

variable "model_server_min_instances" {
  type        = number
  description = "Cloud Run model-server min instances. 0 → scale-to-zero (rec). Decision #2."
  default     = 0
}

variable "model_server_ingress" {
  type        = string
  description = "Cloud Run model-server ingress. INGRESS_TRAFFIC_INTERNAL_ONLY (rec) vs INGRESS_TRAFFIC_ALL (public quick-start). Decision #4."
  default     = "INGRESS_TRAFFIC_INTERNAL_ONLY"
}

variable "model_server_allow_unauthenticated" {
  type        = bool
  description = "Bind allUsers → run.invoker on the model server (public quick-start; X-API-Key still enforced). Default false."
  default     = false
}

variable "model_server_vpc_subnetwork" {
  type        = string
  description = "Subnetwork (name/self-link) for the model server's Direct VPC egress. Empty → no VPC access block (validate-clean before the terraforming-vms subnet exists). Pair with app_vpc_self_link as the network."
  default     = ""
}

variable "model_server_enable_scale_schedule" {
  type        = bool
  description = "Provision the 2 Cloud Scheduler jobs toggling model-server min_instances 1↔0. Default false (scale-to-zero handles the common case)."
  default     = false
}

variable "model_server_scheduler_sa_email" {
  type        = string
  description = "Service account email for the scheduler OIDC token (Cloud Run Admin API PATCH). Required only when model_server_enable_scale_schedule = true."
  default     = ""
}
