# gcs-buckets — Deep-Research storage.
#
# The name is composed (NOT hardcoded) to match the URI in lupin-app.ini:
#   lupin-deep-research-<env>  ← gs://lupin-deep-research-{prod,test}/
# so flipping storage_backend=gcs resolves unchanged (zero code change).
#
# create_buckets=false is the reuse path (Phase-0 found the -test bucket present);
# the composed name is still exported via outputs for dependents.
#
# The LanceDB bucket was removed 2026-08-17 with the rest of the LanceDB teardown
# (row 281e52e6, on Rick's direct yes). Worth recording what was actually there,
# because the module made it look bigger than it was: create_buckets was false in
# every environment, so terraform NEVER created either LanceDB bucket and held no
# state for them. gs://lupin-lancedb-prod did not exist at all, and
# gs://lupin-lancedb-test existed but was empty — no live objects and no noncurrent
# versions, despite versioning being enabled here. The test bucket was deleted by
# hand; there was no terraform state to destroy.

locals {
  deep_research_bucket = "lupin-deep-research-${var.environment}"
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
