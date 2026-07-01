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

# --- GPU model-server → Cloud Run (Set B, 2026-06-30). LOCKED to Rick's ruled
#     decisions (2026-07-01): SCHEDULED-WARM (Decision #2), INTERNAL-ONLY + VPC
#     (Decision #3), e2-standard-8 is a terraforming-vms concern (Decision #4).
#     These defaults now encode the RULED values, not the earlier recommended
#     defaults. See 01-design.md § "Ratified Decisions (2026-07-01)". ----------
variable "model_server_image_tag" {
  type        = string
  description = "Image tag (or :digest) of the lupin-model-server image in Artifact Registry to deploy to Cloud Run."
  default     = "latest"
}

variable "model_server_min_instances" {
  type        = number
  description = "Cloud Run model-server min instances — the SEED value Terraform sets at create. Decision #2 RULED SCHEDULED-WARM, so 1 = warm baseline (a daytime apply lands warm; the 11pm Cloud Scheduler job dials it to 0). Cloud Scheduler is the LIVE authority thereafter — the service ignores drift on min_instance_count (see module lifecycle block), so re-applies never fight the scheduler."
  default     = 1
}

variable "model_server_ingress" {
  type        = string
  description = "Cloud Run model-server ingress. Decision #3 RULED INTERNAL-ONLY + VPC: INGRESS_TRAFFIC_INTERNAL_ONLY (keeps the warm-9-to-11 L4 off the public internet). INGRESS_TRAFFIC_ALL is the public quick-start only."
  default     = "INGRESS_TRAFFIC_INTERNAL_ONLY"
}

variable "model_server_allow_unauthenticated" {
  type        = bool
  description = "Bind allUsers → run.invoker on the model server. Decision #3 RULED INTERNAL-ONLY ingress + X-API-Key as the gate with NO OIDC/app-auth rework — the client sends only X-API-Key (no OIDC bearer), so this binding MUST be present or Cloud Run 403s every call at the IAM layer before app auth. With INTERNAL_ONLY ingress the allUsers grant is scoped to VPC-internal callers (the standard internal+unauthenticated pattern). Default true — flipping this false without reworking the client to attach an OIDC id-token would break Decision #3. See module variables.tf allow_unauthenticated for the ingress/IAM orthogonality."
  default     = true
}

variable "model_server_vpc_subnetwork" {
  type        = string
  description = "Subnetwork (name/self-link) for the model server's Direct VPC egress. Empty → no VPC access block (validate-clean before the terraforming-vms subnet exists). Pair with app_vpc_self_link as the network."
  default     = ""
}

variable "model_server_enable_scale_schedule" {
  type        = bool
  description = "Provision the 2 Cloud Scheduler jobs toggling model-server min_instances 1↔0. Decision #2 RULED SCHEDULED-WARM → default TRUE (min=1 09:00–23:00, min=0 23:00–09:00, America/New_York — the module's scale_up_cron/scale_down_cron/scheduler_time_zone defaults match). The service treats the scheduler as the live authority over min_instance_count."
  default     = true
}

variable "model_server_scheduler_sa_email" {
  type        = string
  description = "Service account email for the scheduler OIDC token (Cloud Run Admin API PATCH; needs run.services.update). REQUIRED AT APPLY now that model_server_enable_scale_schedule defaults true — Rick supplies this alongside project_id at apply time. Empty is validate-clean but will fail apply."
  default     = ""
}

# --- VM power schedule (Rick 2026-07-01): the app VM (lupin-host-test) is
#     utilized ONLY Mon–Fri 09:00–23:00 EDT and PAUSED (suspended) off-hours.
#     Cloud Run's min-toggle cannot pause a VM → a separate Cloud Scheduler →
#     Compute Engine API (instances.suspend/resume) mechanism. ------------------
variable "vm_power_schedule_enable" {
  type        = bool
  description = "Provision the weekday VM suspend/resume scheduler jobs. Default TRUE per the ruled weekday-suspend profile (Mon–Fri resume 09:00 / suspend 23:00, weekends stay suspended)."
  default     = true
}

variable "vm_power_scheduler_sa_email" {
  type        = string
  description = "SA email for the VM suspend/resume OAuth token (needs compute.instances.suspend + compute.instances.resume on lupin-host-test). REQUIRED at apply when vm_power_schedule_enable=true — Rick supplies alongside project_id. Empty is validate-clean but fails apply."
  default     = ""
}

variable "vm_power_instance_name" {
  type        = string
  description = "Target VM name for suspend/resume (matches the terraforming-vms VM)."
  default     = "lupin-host-test"
}

variable "vm_power_vm_zone" {
  type        = string
  description = "Zone of the target VM — MUST match the terraforming-vms VM's actual zone (Compute Engine API is zonal). Confirm at apply."
  default     = "us-central1-a"
}
