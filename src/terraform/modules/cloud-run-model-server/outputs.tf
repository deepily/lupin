# cloud-run-model-server module — outputs

output "service_url" {
  value       = google_cloud_run_v2_service.lupin_model_server.uri
  description = "HTTPS URL of the Cloud Run model server → LUPIN_MODEL_SERVER_URL on the app VM (the local→cloud switch)."
}

output "service_name" {
  value       = google_cloud_run_v2_service.lupin_model_server.name
  description = "Cloud Run service name (for the deploy script + scheduler PATCH target)."
}

output "service_location" {
  value       = google_cloud_run_v2_service.lupin_model_server.location
  description = "Cloud Run service region."
}

output "latest_ready_revision" {
  value       = google_cloud_run_v2_service.lupin_model_server.latest_ready_revision
  description = "Latest ready revision name (deploy-verification handle)."
}
