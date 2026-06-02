# artifact-registry module — outputs

output "repository_id" {
  value       = google_artifact_registry_repository.lupin.repository_id
  description = "The Artifact Registry repository ID."
}

output "registry_host" {
  value       = "${var.region}-docker.pkg.dev"
  description = "Artifact Registry host (the LUPIN_GCP_REGISTRY value for cloud-run.env)."
}

output "image_path_prefix" {
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${var.repository_id}"
  description = "Full image path prefix: push as <prefix>/lupin:<tag>."
}
