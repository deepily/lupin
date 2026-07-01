# cloud-run-model-server — Set B of the GPU model-server → Cloud Run split.
#
# A google_cloud_run_v2_service hosting the FROZEN, env-driven stateless model
# server (src/lupin_model_server/main.py: Whisper distil-large-v3 + CodeRankEmbed
# + nomic-embed-text-v1.5, ~2.9 GB VRAM, cuda:0) on an L4 GPU that scales to zero.
#
# Module defaults remain the generic recommended set (min_instances=0, internal
# ingress, nvidia-l4, scheduler OFF) — every one is a var. The envs/test caller
# now LOCKS them to Rick's ruled decisions (2026-07-01): SCHEDULED-WARM (min=1
# seed + the ×2 Cloud Scheduler jobs, min=1 09:00–23:00 / min=0 23:00–09:00
# America/New_York), INTERNAL-ONLY ingress + Direct VPC egress. Because the
# schedule is the LIVE authority over min_instance_count, the service ignores
# drift on that field (lifecycle below) so re-applies never revert the
# scheduler's runtime PATCH. See 01-design.md § "Ratified Decisions (2026-07-01)".
#
# The X-API-Key (ck_live_*) is NEVER a tfvar: it lives in Secret Manager and is
# mounted as a FILE at {keys_dir}/{api_key_name} — exactly the path main.py reads
# (KEYS_DIR/API_KEY_NAME) — so the app needs zero change to run in Cloud Run.

locals {
  # Base env mirrors src/lupin_model_server/main.py's os.environ.get defaults.
  # extra_env overrides on key collision (escape hatch for the deploy script).
  base_env = {
    LUPIN_MODEL_SERVER_DEVICE       = var.device
    LUPIN_MODEL_SERVER_WHISPER_ID   = var.whisper_model_id
    LUPIN_MODEL_SERVER_CODE_EMBED   = var.code_embed_model_id
    LUPIN_MODEL_SERVER_PROSE_EMBED  = var.prose_embed_model_id
    LUPIN_MODEL_SERVER_PORT         = tostring(var.container_port)
    LUPIN_MODEL_SERVER_KEYS_DIR     = var.keys_dir
    LUPIN_MODEL_SERVER_API_KEY_NAME = var.api_key_name
  }
  effective_env = merge(local.base_env, var.extra_env)

  # Stable volume name shared by the secret volume + its mount.
  api_key_volume = "model-server-api-key"

  # Cloud Scheduler region falls back to the service region when unset.
  scheduler_region = var.scheduler_region != "" ? var.scheduler_region : var.region

  # Admin-API PATCH endpoint the optional scheduler jobs hit to toggle min count.
  service_patch_uri = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/services/${var.service_name}?updateMask=template.scaling.minInstanceCount"
}

resource "google_cloud_run_v2_service" "lupin_model_server" {
  project             = var.project_id
  name                = var.service_name
  location            = var.region
  ingress             = var.ingress
  launch_stage        = var.launch_stage
  deletion_protection = var.deletion_protection

  # Cloud Scheduler is the LIVE authority over min_instance_count (Decision #2
  # SCHEDULED-WARM): the two google_cloud_scheduler_job resources PATCH it 1↔0
  # on the 9am/11pm crons. Terraform seeds it once from var.min_instances at
  # create, then must NOT revert the scheduler's runtime value on later applies
  # — otherwise an off-hours apply would re-warm the L4 until the next 11pm cron
  # (a real overnight cost leak). ignore_changes hands the field to the scheduler.
  lifecycle {
    ignore_changes = [template[0].scaling[0].min_instance_count]
  }

  template {
    # Stateless + single-GPU singleton: scale 0..1 (min is the dial-to-zero knob).
    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    # L4 GPU node selection.
    node_selector {
      accelerator = var.accelerator_type
    }

    # Cheaper single-zone GPU (stateless → cold re-spin acceptable).
    gpu_zonal_redundancy_disabled = var.gpu_zonal_redundancy_disabled

    # Empty service_account_email → Cloud Run default compute SA.
    service_account = var.service_account_email != "" ? var.service_account_email : null

    labels = var.labels

    containers {
      image = var.image

      ports {
        container_port = var.container_port
      }

      resources {
        limits = {
          "cpu"            = var.cpu_limit
          "memory"         = var.memory_limit
          "nvidia.com/gpu" = var.gpu_count
        }
        # GPU instances bill instance-based: CPU stays allocated (no throttling).
        cpu_idle          = false
        startup_cpu_boost = true
      }

      dynamic "env" {
        for_each = local.effective_env
        content {
          name  = env.key
          value = env.value
        }
      }

      # Mount the Secret Manager api-key as a file at KEYS_DIR.
      volume_mounts {
        name       = local.api_key_volume
        mount_path = var.keys_dir
      }

      # Startup probe (finding #10): the ~20GB GPU image pull + model load can
      # be slow; poll /health (no-auth) so the revision isn't failed before the
      # server is ready. Startup budget ≈ period_seconds × failure_threshold.
      startup_probe {
        http_get {
          path = var.health_check_path
          port = var.container_port
        }
        initial_delay_seconds = var.startup_probe_initial_delay_seconds
        timeout_seconds       = var.startup_probe_timeout_seconds
        period_seconds        = var.startup_probe_period_seconds
        failure_threshold     = var.startup_probe_failure_threshold
      }
    }

    # Secret volume: one item → the file named {api_key_name} under the mount.
    volumes {
      name = local.api_key_volume
      secret {
        secret = var.api_key_secret_id
        items {
          path    = var.api_key_name
          version = var.api_key_secret_version
        }
      }
    }

    # Direct VPC egress — only when a network is supplied (so validate stays
    # clean before the terraforming-vms VPC/subnet exist). Required for an
    # INTERNAL_ONLY service to be reachable from the app VM.
    dynamic "vpc_access" {
      for_each = var.vpc_network != "" ? [1] : []
      content {
        egress = var.vpc_egress
        network_interfaces {
          # Cloud Run v2 network_interface wants the SHORT `projects/*/global/networks/*`
          # (and `projects/*/regions/*/subnetworks/*`) form — NOT the compute self-link
          # (`https://www.googleapis.com/compute/v1/...`) that app_vpc_self_link + the
          # subnetwork self-link carry (and that the VPC-peering + Cloud SQL resources
          # correctly consume as-is). Strip the API prefix so either form works; replace()
          # is a no-op on an already-short or empty value. This is an APPLY-TIME API
          # validation `terraform plan` cannot catch — it slipped the plan-only review
          # (c89c31ea) and surfaced on the first real apply (2026-07-01).
          network    = replace(var.vpc_network, "https://www.googleapis.com/compute/v1/", "")
          subnetwork = replace(var.vpc_subnetwork, "https://www.googleapis.com/compute/v1/", "")
        }
      }
    }
  }
}

# --- allUsers invoker binding (X-API-Key remains the app-layer gate). ----------
# Default ON (allow_unauthenticated=true). Ingress and IAM invoker are
# orthogonal: with ingress=INTERNAL_ONLY this grant is scoped to VPC-internal
# callers, and it is REQUIRED so the X-API-Key-only client isn't 403'd at the
# platform IAM layer before app auth runs (Ratified Decision #3 — no OIDC/app-
# auth rework). count 0 (allow_unauthenticated=false) makes the service OIDC-
# gated → the current client, which sends no OIDC token, gets 403 on every call.
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  count    = var.allow_unauthenticated ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.lupin_model_server.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- Optional scheduled scale toggle (scaffold; default OFF via count 0). ------
# Warm-up: min_instances → 1 at scale_up_cron (e.g. 9am).
resource "google_cloud_scheduler_job" "scale_up" {
  count       = var.enable_scale_schedule ? 1 : 0
  project     = var.project_id
  region      = local.scheduler_region
  name        = "${var.service_name}-scale-up"
  description = "Warm the model server: patch min_instances → 1."
  schedule    = var.scale_up_cron
  time_zone   = var.scheduler_time_zone

  http_target {
    http_method = "PATCH"
    uri         = local.service_patch_uri
    headers = {
      "Content-Type" = "application/json"
    }
    body = base64encode(jsonencode({
      template = {
        scaling = {
          minInstanceCount = 1
        }
      }
    }))
    # Cloud Run ADMIN API (run.googleapis.com management endpoint) is a Google
    # API → authenticate with an OAuth access token (cloud-platform scope), NOT
    # an OIDC id-token (OIDC/audience is for INVOKING a Cloud Run service, not
    # for calling the services-management API). Mirrors the vm-power-schedule
    # jobs. With OIDC here the PATCH 403s → min_instances never flips → the
    # weekday-warm window silently never activates.
    oauth_token {
      service_account_email = var.scheduler_service_account_email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }
}

# Cool-down: min_instances → 0 at scale_down_cron (e.g. 11pm).
resource "google_cloud_scheduler_job" "scale_down" {
  count       = var.enable_scale_schedule ? 1 : 0
  project     = var.project_id
  region      = local.scheduler_region
  name        = "${var.service_name}-scale-down"
  description = "Dial the model server to zero: patch min_instances → 0."
  schedule    = var.scale_down_cron
  time_zone   = var.scheduler_time_zone

  http_target {
    http_method = "PATCH"
    uri         = local.service_patch_uri
    headers = {
      "Content-Type" = "application/json"
    }
    body = base64encode(jsonencode({
      template = {
        scaling = {
          minInstanceCount = 0
        }
      }
    }))
    # Cloud Run ADMIN API (run.googleapis.com management endpoint) is a Google
    # API → authenticate with an OAuth access token (cloud-platform scope), NOT
    # an OIDC id-token (OIDC/audience is for INVOKING a Cloud Run service, not
    # for calling the services-management API). Mirrors the vm-power-schedule
    # jobs. With OIDC here the PATCH 403s → min_instances never flips → the
    # weekday-warm window silently never activates.
    oauth_token {
      service_account_email = var.scheduler_service_account_email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }
}
