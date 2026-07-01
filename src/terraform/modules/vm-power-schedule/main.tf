# vm-power-schedule — weekday suspend/resume of the app VM via Cloud Scheduler.
#
# Two google_cloud_scheduler_job resources POST to the Compute Engine API's
# instances.suspend / instances.resume methods. Because the target is a Google
# API (compute.googleapis.com), the scheduler authenticates with an OAuth token
# (cloud-platform scope) — NOT an OIDC id-token (which is for Cloud Run / custom
# audiences). Both jobs are gated on var.enable (count 0 → validate-clean).
#
# See: src/rnd/2026.06.30-gpu-model-server-cloud-run-split/01-design.md
#      src/rnd/2026.06.30-gpu-model-server-cloud-run-split/02-vm-downgrade-handoff.md

locals {
  # Zonal Compute Engine instance resource base (v1 API).
  instance_uri = "https://compute.googleapis.com/compute/v1/projects/${var.project_id}/zones/${var.vm_zone}/instances/${var.vm_instance_name}"

  # OAuth scope for calling Google APIs from Cloud Scheduler.
  compute_scope = "https://www.googleapis.com/auth/cloud-platform"
}

# --- Suspend (pause) the VM: weekday 23:00. -----------------------------------
resource "google_cloud_scheduler_job" "suspend" {
  count       = var.enable ? 1 : 0
  project     = var.project_id
  region      = var.region
  name        = "${var.vm_instance_name}-suspend"
  description = "Weekday suspend (pause) of ${var.vm_instance_name} — off-hours cost save; RAM snapshot preserves in-memory state for fast resume."
  schedule    = var.suspend_cron
  time_zone   = var.time_zone

  http_target {
    http_method = "POST"
    uri         = "${local.instance_uri}/suspend"
    oauth_token {
      service_account_email = var.scheduler_service_account_email
      scope                 = local.compute_scope
    }
  }
}

# --- Resume the VM: weekday 09:00. --------------------------------------------
resource "google_cloud_scheduler_job" "resume" {
  count       = var.enable ? 1 : 0
  project     = var.project_id
  region      = var.region
  name        = "${var.vm_instance_name}-resume"
  description = "Weekday resume of ${var.vm_instance_name} — restores the suspended RAM state (near-instant vs a cold boot)."
  schedule    = var.resume_cron
  time_zone   = var.time_zone

  http_target {
    http_method = "POST"
    uri         = "${local.instance_uri}/resume"
    oauth_token {
      service_account_email = var.scheduler_service_account_email
      scope                 = local.compute_scope
    }
  }
}
