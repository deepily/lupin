# gcs-buckets module — inputs
# Two buckets per environment (LanceDB + Deep-Research). Names compose to match
# the gs:// URIs hardcoded in lupin-app.ini so flipping storage_backend=gcs needs
# zero code change.

variable "project_id" {
  type        = string
  description = "GCP project ID. No default — must be supplied by the caller (never the sandbox literal)."
}

variable "region" {
  type        = string
  description = "Bucket location (single-region, co-located with the VM to avoid egress)."
  default     = "us-central1"
}

variable "environment" {
  type        = string
  description = "Environment suffix used to compose bucket names: lupin-lancedb-<env>, lupin-deep-research-<env>."
}

variable "create_buckets" {
  type        = bool
  description = "True provisions the buckets; false reuses pre-existing ones (Phase-0 V4 confirmed the -test buckets already exist in us-central1). The composed names are output either way."
  default     = true
}

variable "lancedb_keep_noncurrent_versions" {
  type        = number
  description = "Noncurrent object versions to retain on the LanceDB bucket (append-only store; versioning gives point-in-time recovery)."
  default     = 3
}

variable "deep_research_nearline_age_days" {
  type        = number
  description = "Age (days) after which Deep-Research objects transition to NEARLINE."
  default     = 90
}
