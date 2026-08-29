# gcs-buckets module — inputs
# One bucket per environment (Deep-Research). The name composes to match the gs://
# URI hardcoded in lupin-app.ini so flipping storage_backend=gcs needs zero code
# change. The LanceDB bucket was removed with the teardown on 2026-08-17.

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
  description = "Environment suffix used to compose the bucket name: lupin-deep-research-<env>."
}

variable "create_buckets" {
  type        = bool
  description = "True provisions the bucket; false reuses a pre-existing one (Phase-0 V4 confirmed the -test bucket already exists in us-central1). The composed name is output either way."
  default     = true
}

variable "deep_research_nearline_age_days" {
  type        = number
  description = "Age (days) after which Deep-Research objects transition to NEARLINE."
  default     = 90
}
