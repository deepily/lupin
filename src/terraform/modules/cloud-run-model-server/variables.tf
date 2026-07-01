# cloud-run-model-server module — inputs
#
# Set B of the GPU model-server → Cloud Run split (design:
# src/rnd/2026.06.30-gpu-model-server-cloud-run-split/01-design.md).
# Every Rick-pending decision (#2 scale mechanism, #4 ingress, cold-start
# tolerance) is a parameter here with the design's RECOMMENDED DEFAULT — so a
# later decision just flips a var, no module surgery. The defaults encode:
# min_instances=0 (scale-to-zero), internal ingress, nvidia-l4, scheduler OFF.

variable "project_id" {
  type        = string
  description = "GCP project ID. No default — must be supplied by the caller (never the sandbox literal)."
}

variable "region" {
  type        = string
  description = "Cloud Run region (regional service)."
  default     = "us-central1"
}

variable "service_name" {
  type        = string
  description = "Cloud Run v2 service name for the model server."
  default     = "lupin-model-server"
}

# --- Image (reuse the artifact-registry module's image_path_prefix output) ---
variable "image" {
  type        = string
  description = "Full Artifact Registry image reference, e.g. <region>-docker.pkg.dev/<project>/<repo>/lupin-model-server:<tag-or-digest>. No default — caller wires it from the artifact-registry module output."
}

# --- Scaling (Decision #2: min=0 scale-to-zero [rec] vs scheduled warm) -------
variable "min_instances" {
  type        = number
  description = "Minimum Cloud Run instances. DEFAULT 0 → scale-to-zero (overnight zero-cost). Set 1 (or use the scheduler) iff cold-start gaps are unacceptable."
  default     = 0

  validation {
    condition     = var.min_instances >= 0 && var.min_instances <= 1
    error_message = "min_instances must be 0 or 1 (max_instance_count is pinned at 1 for the single-GPU model server)."
  }
}

variable "max_instances" {
  type        = number
  description = "Maximum Cloud Run instances. Pinned to 1 — the model server is a single-GPU singleton (per design Set B)."
  default     = 1
}

# --- Container / GPU resources -------------------------------------------------
variable "container_port" {
  type        = number
  description = "Port the model server listens on (LUPIN_MODEL_SERVER_PORT). Cloud Run routes ingress to this port."
  default     = 7998
}

variable "cpu_limit" {
  type        = string
  description = "vCPU limit. 8 is the minimum Cloud Run requires alongside an L4 GPU."
  default     = "8"
}

variable "memory_limit" {
  type        = string
  description = "Memory limit. 32Gi headroom for Whisper + 2 encoders (~2.9 GB VRAM but host RAM for model load/decode)."
  default     = "32Gi"
}

variable "gpu_count" {
  type        = string
  description = "nvidia.com/gpu limit. 1 L4 per the carve-out model server."
  default     = "1"
}

variable "accelerator_type" {
  type        = string
  description = "Cloud Run GPU node-selector accelerator type."
  default     = "nvidia-l4"
}

variable "gpu_zonal_redundancy_disabled" {
  type        = bool
  description = "Disable GPU zonal redundancy (cheaper, single-zone). True per design — the model server is stateless and a cold-start re-spin is acceptable."
  default     = true
}

variable "launch_stage" {
  type        = string
  description = "Cloud Run launch stage. GA now that Cloud Run GPU is generally available; set BETA only if a preview-gated field is needed."
  default     = "GA"
}

# --- Startup probe (finding #10: guard a slow first cold start) ----------------
# The ~20 GB GPU image pull + model load (.to(cuda)) can exceed a default
# startup budget; without a probe Cloud Run may mark the revision unhealthy
# before the server is ready. The probe polls /health (no-auth) until ready.
# Startup budget ≈ period_seconds × failure_threshold.
variable "health_check_path" {
  type        = string
  description = "HTTP path for the startup probe (the model server's no-auth /health endpoint)."
  default     = "/health"
}

variable "startup_probe_period_seconds" {
  type        = number
  description = "Seconds between startup-probe attempts. Startup budget ≈ this × failure_threshold."
  default     = 10
}

variable "startup_probe_failure_threshold" {
  type        = number
  description = "Consecutive startup-probe failures tolerated before the revision is marked failed. Default 24 → a 240s startup budget covering the GPU image pull + model load."
  default     = 24
}

variable "startup_probe_timeout_seconds" {
  type        = number
  description = "Per-attempt startup-probe timeout. Must be ≤ startup_probe_period_seconds."
  default     = 5
}

variable "startup_probe_initial_delay_seconds" {
  type        = number
  description = "Delay before the first startup-probe attempt."
  default     = 10
}

# --- Security (Decision #4: internal+VPC [rec] vs public+key quick-start) ------
variable "ingress" {
  type        = string
  description = "Cloud Run ingress. INGRESS_TRAFFIC_INTERNAL_ONLY [rec] (defense-in-depth behind the X-API-Key); INGRESS_TRAFFIC_ALL for the public quick-start."
  default     = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  validation {
    condition = contains(
      ["INGRESS_TRAFFIC_ALL", "INGRESS_TRAFFIC_INTERNAL_ONLY", "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"],
      var.ingress
    )
    error_message = "ingress must be one of INGRESS_TRAFFIC_ALL, INGRESS_TRAFFIC_INTERNAL_ONLY, INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER."
  }
}

variable "allow_unauthenticated" {
  type        = bool
  description = <<-EOT
    Bind allUsers → roles/run.invoker on the service. DEFAULT true.

    Ingress and IAM invoker are ORTHOGONAL layers, not substitutes:
      - ingress (network layer) decides WHO can reach the service —
        INTERNAL_ONLY restricts reachability to VPC-internal callers.
      - the invoker IAM binding (identity layer) decides whether a reachable
        caller must present a valid Google OIDC identity token.

    Ratified Decision #3 is "X-API-Key is the gate; NO OIDC / app-auth rework."
    The app client sends ONLY X-API-Key (no OIDC bearer), so WITHOUT this
    binding Cloud Run rejects every call with 403 at the platform IAM layer
    before the app's X-API-Key is ever checked. With INTERNAL_ONLY ingress
    the allUsers grant is scoped to VPC-internal callers, and X-API-Key is the
    real auth — the standard internal+unauthenticated pattern. Hence default
    true so the binding materializes and Decision #3 actually serves traffic.

    Set false ONLY if the client is reworked to fetch + attach an OIDC id-token
    (which contradicts Decision #3).
  EOT
  default     = true
}

variable "service_account_email" {
  type        = string
  description = "Runtime service account for the Cloud Run revision (needs secretmanager.secretAccessor on the api-key secret + artifactregistry.reader). Empty → Cloud Run uses the project default compute SA."
  default     = ""
}

# --- Secret file-mount (the ck_live_ X-API-Key the server reads at boot) -------
# main.py reads the plaintext key from {KEYS_DIR}/{API_KEY_NAME}. We mount the
# Secret Manager secret as a FILE at exactly that path → zero app change.
variable "api_key_secret_id" {
  type        = string
  description = "Secret Manager secret ID holding the model-server X-API-Key (ck_live_*). Matches the secret-manager module inventory."
  default     = "lupin-notification-api-key"
}

variable "api_key_name" {
  type        = string
  description = "Key FILE name within KEYS_DIR (LUPIN_MODEL_SERVER_API_KEY_NAME). The secret is mounted at {keys_dir}/{api_key_name}."
  default     = "notification-api-claude-code-dev"
}

variable "api_key_secret_version" {
  type        = string
  description = "Secret Manager version to mount. 'latest' for the sandbox; pin a numeric version in prod."
  default     = "latest"
}

variable "keys_dir" {
  type        = string
  description = "Mount directory for the api-key secret file (LUPIN_MODEL_SERVER_KEYS_DIR). The server joins this with api_key_name."
  default     = "/secrets/keys"
}

# --- Model / device env (mirror src/lupin_model_server/main.py defaults) -------
variable "device" {
  type        = string
  description = "Torch device (LUPIN_MODEL_SERVER_DEVICE). cuda:0 per the Lupin GPU-0 rule."
  default     = "cuda:0"
}

variable "whisper_model_id" {
  type        = string
  description = "Whisper model id (LUPIN_MODEL_SERVER_WHISPER_ID)."
  default     = "distil-whisper/distil-large-v3"
}

variable "code_embed_model_id" {
  type        = string
  description = "Code-embedding model id (LUPIN_MODEL_SERVER_CODE_EMBED)."
  default     = "nomic-ai/CodeRankEmbed"
}

variable "prose_embed_model_id" {
  type        = string
  description = "Prose-embedding model id (LUPIN_MODEL_SERVER_PROSE_EMBED)."
  default     = "nomic-ai/nomic-embed-text-v1.5"
}

variable "extra_env" {
  type        = map(string)
  description = "Extra environment variables merged over the base model-server env (escape hatch; overrides on key collision)."
  default     = {}
}

# --- Direct VPC egress (gated; needed for INTERNAL_ONLY ingress to be reachable
#     from the VM on the app VPC). Empty network → block omitted so validate
#     passes before the terraforming-vms VPC/subnet exist. ----------------------
variable "vpc_network" {
  type        = string
  description = "VPC network (name or self-link) for Direct VPC egress. Empty → no VPC access block (validate-clean before the app VPC exists)."
  default     = ""
}

variable "vpc_subnetwork" {
  type        = string
  description = "Subnetwork (name or self-link) for Direct VPC egress. REQUIRED whenever vpc_network is set — the vpc_access block emits BOTH fields, and Cloud Run treats an empty subnetwork as 'use the subnet NAMED LIKE THE NETWORK' (e.g. network dev-vpc → nonexistent subnet dev-vpc), an APPLY-TIME code-9 error invisible to `terraform plan`. Empty is valid ONLY when vpc_network is also empty (VPC access block omitted; validate-clean before the app VPC exists). Enforced by the validation below."
  default     = ""

  # FAIL-LOUD (Lupin doctrine: no silent fallbacks). Reject the network-set +
  # subnetwork-empty combination at PLAN time so the operator gets a clear
  # variable error instead of the opaque Cloud Run code-9 subnet-not-found on
  # apply. The silent-skip alternative (omit the block when subnetwork is empty)
  # was rejected: it would deploy an INTERNAL_ONLY service with NO VPC egress —
  # unreachable from the app VM — as a silent misconfiguration. See task cb0e145a
  # + src/rnd/2026.06.30-gpu-model-server-cloud-run-split/06-apply-verification-green-bar.md §2.
  validation {
    condition     = var.vpc_network == "" || var.vpc_subnetwork != ""
    error_message = "vpc_subnetwork is REQUIRED when vpc_network is set. Cloud Run treats an empty subnetwork as the subnet named like the network (e.g. 'dev-vpc'), producing a plan-invisible apply-time code-9 subnet-not-found. Set vpc_subnetwork to the target subnet (projects/<project>/regions/<region>/subnetworks/<name>) — or clear vpc_network to omit the VPC access block entirely."
  }
}

variable "vpc_egress" {
  type        = string
  description = "Direct VPC egress setting. PRIVATE_RANGES_ONLY (only RFC1918 over the VPC) or ALL_TRAFFIC."
  default     = "PRIVATE_RANGES_ONLY"

  validation {
    condition     = contains(["PRIVATE_RANGES_ONLY", "ALL_TRAFFIC"], var.vpc_egress)
    error_message = "vpc_egress must be PRIVATE_RANGES_ONLY or ALL_TRAFFIC."
  }
}

variable "deletion_protection" {
  type        = bool
  description = "Cloud Run deletion protection. False for the sandbox (easy teardown); true in prod."
  default     = false
}

variable "labels" {
  type        = map(string)
  description = "Resource labels applied to the service template."
  default     = {}
}

# --- Optional scheduled scale toggle (Decision #2 alt: scheduled warm window).
#     Scaffold only — default OFF. Two Cloud Scheduler jobs PATCH the service's
#     minInstanceCount 1↔0 via the Cloud Run Admin API. -----------------------
variable "enable_scale_schedule" {
  type        = bool
  description = "Provision the 2 Cloud Scheduler jobs that toggle min_instances 1↔0 (warm daytime / zero overnight). DEFAULT false — scale-to-zero handles the common case; flip only if cold-start gaps hurt."
  default     = false
}

variable "scale_up_cron" {
  type        = string
  description = "Cron for the warm-up job (min_instances → 1). WEEKDAY-ONLY per Rick's 2026-07-01 correction (Mon–Fri 09:00) — the model server is only utilized Mon–Fri 09:00–23:00 EDT."
  default     = "0 9 * * 1-5"
}

variable "scale_down_cron" {
  type        = string
  description = "Cron for the cool-down job (min_instances → 0). WEEKDAY-ONLY (Mon–Fri 23:00); weekends stay at min=0 because there is no weekday warm-up until Monday 09:00."
  default     = "0 23 * * 1-5"
}

variable "scheduler_time_zone" {
  type        = string
  description = "IANA time zone for the scheduler crons."
  default     = "America/New_York"
}

variable "scheduler_region" {
  type        = string
  description = "Region for the Cloud Scheduler jobs. Empty → falls back to var.region."
  default     = ""
}

variable "scheduler_service_account_email" {
  type        = string
  description = "Service account the scheduler uses to mint the OAuth access token (cloud-platform scope) for the Cloud Run Admin API PATCH (needs run.services.update). Required only when enable_scale_schedule = true. NB: OAuth access token, NOT an OIDC id-token — the run.googleapis.com management API is a Google API; OIDC/audience is for invoking a Cloud Run service."
  default     = ""
}
