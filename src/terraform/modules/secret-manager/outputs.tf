# secret-manager module — outputs

output "secret_ids" {
  value       = [for s in google_secret_manager_secret.secrets : s.secret_id]
  description = "Secret IDs created, for per-secret accessor binding in the iam module."
}
