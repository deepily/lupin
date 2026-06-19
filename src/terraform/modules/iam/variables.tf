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

variable "external_vm_sa_email" {
  type        = string
  default     = ""
  description = <<-EOT
    Optional: bind the data-plane runtime roles (per-bucket objectUser, per-secret
    accessor, AR reader, cloudsql.client + log/metric writer) to an EXTERNAL service
    account — the standalone terraforming-vms VM's attached `vm_sa` — instead of the
    module-created runtime_sa. When "" (default) the module falls back to runtime_sa.
    build-sa is ALWAYS module-owned regardless. See:
    src/rnd/v0.1.8/2026.05.30-gcp-deployment/2026.06.10-m2-arbiter-ride-along-and-vm-cutover.md §Phase B.
  EOT
}
