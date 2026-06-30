# Milestone-1 TEST environment — key outputs (for the bash deploy wrapper + app env).

output "cloud_sql_connection_name" {
  value       = module.cloud_sql.connection_name
  description = "→ CLOUD_SQL_CONNECTION_NAME on the VM (with LUPIN_CLOUD_BACKED=true)."
}

output "artifact_registry_image_prefix" {
  value       = module.artifact_registry.image_path_prefix
  description = "Push images as <prefix>/lupin:<tag> (→ LUPIN_GCP_REGISTRY/AR_REPO in cloud-run.env)."
}

output "runtime_sa_email" {
  value       = module.iam.runtime_sa_email
  description = "Data-plane service account (integration follow-up: bind to the app's vm_sa instead)."
}

output "lancedb_bucket" {
  value       = module.gcs_buckets.lancedb_bucket_name
  description = "LanceDB GCS bucket name."
}

output "vpn_gateway_ip" {
  value       = module.onprem_vpn.vpn_gateway_ip
  description = "GCP VPN gateway IP for on-prem peer config (empty unless enable_vpn)."
}

output "model_server_url" {
  value       = module.cloud_run_model_server.service_url
  description = "→ LUPIN_MODEL_SERVER_URL on the app VM (the local→cloud switch for STT + embeddings + router)."
}

output "model_server_name" {
  value       = module.cloud_run_model_server.service_name
  description = "Cloud Run model-server service name (deploy script + scheduler PATCH target)."
}
