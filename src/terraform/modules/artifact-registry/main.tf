# artifact-registry — Docker repo for the lupin + lupin-model-server images.
# Replaces the deprecated gcr.io path the build scripts used. Immutable tags
# honor the no-auto-promote-tags practice (promotion = deliberate digest re-tag,
# never an overwrite). Phase-0 V8 confirmed no repo exists yet → provision-new.

resource "google_artifact_registry_repository" "lupin" {
  project       = var.project_id
  location      = var.region
  repository_id = var.repository_id
  format        = "DOCKER"
  description   = "Lupin container images (rest + model-server)."

  docker_config {
    immutable_tags = true
  }

  cleanup_policies {
    id     = "keep-most-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = var.keep_versions
    }
  }
}
