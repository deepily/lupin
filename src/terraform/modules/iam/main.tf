# iam — split build-sa (CI/image push) vs runtime-sa (VM), least-privilege.
#
# runtime-sa: per-bucket objectUser (NOT objectAdmin — cannot delete buckets),
# per-secret accessor, AR reader, cloudsql.client + log/metric writer (project).
# build-sa: AR writer only. Neither holds owner/editor/objectAdmin.

resource "google_service_account" "build_sa" {
  project      = var.project_id
  account_id   = "lupin-build-sa"
  display_name = "Lupin CI / image-build SA (Artifact Registry writer)"
}

resource "google_service_account" "runtime_sa" {
  project      = var.project_id
  account_id   = "lupin-runtime-sa"
  display_name = "Lupin VM runtime SA (least-privilege app identity)"
}

locals {
  # The IAM member that carries the data-plane runtime roles. When an external VM
  # SA is supplied (the standalone terraforming-vms vm_sa attached to lupin-host-test),
  # bind the roles to IT; otherwise fall back to the module-created runtime_sa.
  # coalesce returns the first non-empty string → external wins when set.
  # build-sa is ALWAYS module-owned (image push), independent of this.
  runtime_sa_member = "serviceAccount:${coalesce(var.external_vm_sa_email, google_service_account.runtime_sa.email)}"
}

# --- runtime-sa: per-bucket storage.objectUser (create/read/update/delete OBJECTS,
#     but NOT delete-bucket / admin) ---
resource "google_storage_bucket_iam_member" "runtime_objectuser" {
  for_each = toset(var.bucket_names)

  bucket = each.value
  role   = "roles/storage.objectUser"
  member = local.runtime_sa_member
}

# --- runtime-sa: per-secret accessor ---
resource "google_secret_manager_secret_iam_member" "runtime_secret_accessor" {
  for_each = toset(var.secret_names)

  project   = var.project_id
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = local.runtime_sa_member
}

# --- Artifact Registry: runtime reads, build writes ---
resource "google_artifact_registry_repository_iam_member" "runtime_ar_reader" {
  project    = var.project_id
  location   = var.ar_location
  repository = var.ar_repository_id
  role       = "roles/artifactregistry.reader"
  member     = local.runtime_sa_member
}

resource "google_artifact_registry_repository_iam_member" "build_ar_writer" {
  project    = var.project_id
  location   = var.ar_location
  repository = var.ar_repository_id
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.build_sa.email}"
}

# --- runtime-sa: project-level roles that are not resource-scopable ---
resource "google_project_iam_member" "runtime_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = local.runtime_sa_member
}

resource "google_project_iam_member" "runtime_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = local.runtime_sa_member
}

resource "google_project_iam_member" "runtime_metric_writer" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = local.runtime_sa_member
}
