# Remote state in a dedicated, versioned GCS bucket with state locking.
#
# BOOTSTRAP PREREQUISITE: the state bucket must exist before `terraform init`.
# Create it once (versioned), then init with the backend config. The bucket
# name is supplied via -backend-config (NOT hardcoded here) so no project-
# specific literal lives in the tree:
#
#   gcloud storage buckets create gs://<proj>-tfstate --location=us-central1 \
#     --uniform-bucket-level-access && \
#   gcloud storage buckets update gs://<proj>-tfstate --versioning
#   terraform init -backend-config="bucket=<proj>-tfstate"
#
# For provider/syntax validation without a remote bucket, use:
#   terraform init -backend=false && terraform validate

terraform {
  backend "gcs" {
    # bucket = supplied via -backend-config (reuse hello-world-foo-423219-tf-state)
    prefix = "lupin/envs/test"
  }
}
