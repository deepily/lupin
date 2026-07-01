# vm-power-schedule module — inputs
#
# Weekday suspend/resume of a Compute Engine VM via two Cloud Scheduler jobs
# hitting the Compute Engine API. Part of the GPU model-server → Cloud Run split
# (Rick's 2026-07-01 correction): the app VM is utilized ONLY Mon–Fri 09:00–23:00
# EDT and PAUSED (suspended) all other hours. Cloud Run's min-instance toggle
# cannot pause a VM, so this is a separate mechanism.
#
# Suspend (not stop): the VM's RAM is snapshotted to disk → no compute charge
# while paused (only the saved memory-state + disks at PD rates), and RAM state
# is preserved for near-instant resume — which also keeps Lupin's in-memory FIFO
# queues + WebSocketManager singleton intact across the pause.
#
# The target VM lives in the standalone terraforming-vms repo/state, but these
# scheduler jobs reference it only by project/zone/name (strings) + need an SA
# with compute.instances.suspend/resume — NO cross-state data source, so
# `terraform validate`/`plan` stay clean independently.

variable "project_id" {
  type        = string
  description = "GCP project ID of the target VM (same data-plane project)."
}

variable "region" {
  type        = string
  description = "Region for the Cloud Scheduler jobs."
  default     = "us-central1"
}

variable "enable" {
  type        = bool
  description = "Provision the suspend/resume scheduler jobs. DEFAULT false (validate-clean scaffold); envs/test pins true per the ruled weekday-suspend profile."
  default     = false
}

variable "vm_instance_name" {
  type        = string
  description = "Name of the target Compute Engine VM to suspend/resume."
  default     = "lupin-host-test"
}

variable "vm_zone" {
  type        = string
  description = "Zone of the target VM — MUST match the terraforming-vms VM's actual zone (the Compute Engine API is zonal). Confirm at apply."
  default     = "us-central1-a"
}

variable "scheduler_service_account_email" {
  type        = string
  description = "Service account the scheduler uses to mint the OAuth token for the Compute Engine API calls. Needs compute.instances.suspend + compute.instances.resume on the VM. REQUIRED when enable=true (empty is validate-clean but fails apply)."
  default     = ""
}

variable "suspend_cron" {
  type        = string
  description = "Cron for the suspend (pause) job. WEEKDAY-ONLY (Mon–Fri 23:00); weekends stay suspended because there is no weekday resume until Monday."
  default     = "0 23 * * 1-5"
}

variable "resume_cron" {
  type        = string
  description = "Cron for the resume job. WEEKDAY-ONLY (Mon–Fri 09:00)."
  default     = "0 9 * * 1-5"
}

variable "time_zone" {
  type        = string
  description = "IANA time zone for the crons (matches the model-server scheduler)."
  default     = "America/New_York"
}
