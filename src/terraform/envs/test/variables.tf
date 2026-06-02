variable "project_id" {
  type        = string
  description = "GCP project ID. NO default — must be supplied (never the sandbox literal). Unset fails the plan loudly."
}

variable "region" {
  type        = string
  description = "GCP region for all regional resources."
  default     = "us-central1"
}

variable "zone" {
  type        = string
  description = "GCP zone for the GCE VM (L4 quota confirmed in us-central1-a, Phase-0 V3)."
  default     = "us-central1-a"
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
