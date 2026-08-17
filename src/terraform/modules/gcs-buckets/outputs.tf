# gcs-buckets module — outputs
# Composed names are exported whether the buckets were created or reused, so
# dependents (IAM bindings, app config) resolve identically in both paths.

output "deep_research_bucket_name" {
  value       = local.deep_research_bucket
  description = "Deep-Research bucket name (composed; matches lupin-app.ini)."
}

output "bucket_names" {
  value       = [local.deep_research_bucket]
  description = "All bucket names this module manages, for per-bucket IAM binding."
}
