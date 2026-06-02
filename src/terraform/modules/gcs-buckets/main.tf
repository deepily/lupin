# gcs-buckets — LanceDB + Deep-Research storage.
#
# Names are composed (NOT hardcoded) to match the URIs in lupin-app.ini:
#   lupin-lancedb-<env>        ← gs://lupin-lancedb-{prod,test}/...
#   lupin-deep-research-<env>  ← gs://lupin-deep-research-{prod,test}/
# so flipping storage_backend=gcs resolves unchanged (zero code change).
#
# create_buckets=false is the reuse path (Phase-0 found the -test buckets present);
# the composed names are still exported via outputs for dependents.

locals {
  lancedb_bucket       = "lupin-lancedb-${var.environment}"
  deep_research_bucket = "lupin-deep-research-${var.environment}"
}

resource "google_storage_bucket" "lancedb" {
  count = var.create_buckets ? 1 : 0

  name                        = local.lancedb_bucket
  project                     = var.project_id
  location                    = upper(var.region)
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  # Append-only store — cap noncurrent-version cost while keeping PITR.
  lifecycle_rule {
    condition {
      num_newer_versions = var.lancedb_keep_noncurrent_versions
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_storage_bucket" "deep_research" {
  count = var.create_buckets ? 1 : 0

  name                        = local.deep_research_bucket
  project                     = var.project_id
  location                    = upper(var.region)
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = var.deep_research_nearline_age_days
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }
}
