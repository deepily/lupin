# iam module — outputs

output "runtime_sa_email" {
  value       = google_service_account.runtime_sa.email
  description = "Runtime service account email (attached to the GCE VM)."
}

output "build_sa_email" {
  value       = google_service_account.build_sa.email
  description = "Build service account email (CI / image push)."
}
