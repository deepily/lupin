# cloud-run-model-server — Set B of the GPU model-server → Cloud Run split.
#
# A google_cloud_run_v2_service hosting the FROZEN, env-driven stateless model
# server (src/lupin_model_server/main.py: Whisper distil-large-v3 + CodeRankEmbed
# + nomic-embed-text-v1.5, ~2.9 GB VRAM, cuda:0) on an L4 GPU that scales to zero.
#
# Recommended defaults (per design 2026.06.30): min_instances=0 (overnight
# zero-cost), INGRESS_TRAFFIC_INTERNAL_ONLY, nvidia-l4, scheduler OFF. Every one
# is a var → Rick's pending decisions flip a value, not this file.
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
          network    = var.vpc_network
          subnetwork = var.vpc_subnetwork
        }
      }
    }
  }
}

# --- Quick-start: public invoker (X-API-Key still enforced by the app). --------
# Default OFF (count 0) → service stays IAM-gated.
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
    oidc_token {
      service_account_email = var.scheduler_service_account_email
      audience              = "https://run.googleapis.com/"
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
    oidc_token {
      service_account_email = var.scheduler_service_account_email
      audience              = "https://run.googleapis.com/"
    }
  }
}
