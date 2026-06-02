# iam module — inputs
# Two service accounts (build-sa, runtime-sa) with per-RESOURCE least-privilege
# bindings. Replaces the over-privileged default Compute SA (Phase-0 V7).

variable "project_id" {
  type        = string
  description = "GCP project ID. No default — must be supplied by the caller."
}

variable "bucket_names" {
  type        = list(string)
  description = "GCS buckets to grant runtime-sa storage.objectUser on, PER-BUCKET (never project-wide, never objectAdmin)."
}

variable "secret_names" {
  type        = list(string)
  description = "Secret Manager secret IDs to grant runtime-sa secretAccessor on, PER-SECRET."
}

variable "ar_repository_id" {
  type        = string
  description = "Artifact Registry repo ID: runtime-sa gets reader, build-sa gets writer."
}

variable "ar_location" {
  type        = string
  description = "Artifact Registry repo location."
}
