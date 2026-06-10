# Milestone-1 GCP TEST environment — DATA PLANE + on-prem VPN.
#
# The VM + VPC + subnet + Cloud NAT + IAP-SSH are owned by the standalone
# `terraforming-vms` app (separate repo/state). This stack provisions the data
# plane (secrets, SQL, GCS, Artifact Registry, IAM) and the on-prem vLLM VPN,
# attaching to the app's VPC via `var.app_vpc_self_link`.
# See: 2026.06.02-terraforming-vms-reuse-and-integration.md

module "secret_manager" {
  source     = "../../modules/secret-manager"
  project_id = var.project_id
}

module "gcs_buckets" {
  source         = "../../modules/gcs-buckets"
  project_id     = var.project_id
  region         = var.region
  environment    = var.environment
  create_buckets = var.create_buckets # false → reuse the existing -test buckets (Phase-0 V4)
}

module "artifact_registry" {
  source     = "../../modules/artifact-registry"
  project_id = var.project_id
  region     = var.region
}

module "iam" {
  source           = "../../modules/iam"
  project_id       = var.project_id
  bucket_names     = module.gcs_buckets.bucket_names
  secret_names     = module.secret_manager.secret_ids
  ar_repository_id = module.artifact_registry.repository_id
  ar_location      = var.region
  # Phase B (2026-06-10): bind the data-plane runtime roles to the standalone
  # terraforming-vms VM's attached vm_sa. Email constructed from project_id so the
  # project literal stays out of source (the "no hardcoded sandbox project" lock).
  external_vm_sa_email = "${var.vm_sa_account_id}@${var.project_id}.iam.gserviceaccount.com"
}

# --- Bridge: private-services peering on the APP's VPC, so Cloud SQL gets a
#     private IP. Created here (not in a module) because the VPC is the app's.
#     Gated on app_vpc_self_link being supplied (after the app provisions the VM).
resource "google_compute_global_address" "private_services" {
  count         = var.app_vpc_self_link == "" ? 0 : 1
  project       = var.project_id
  name          = "lupin-private-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = var.app_vpc_self_link
}

resource "google_service_networking_connection" "private_services" {
  count                   = var.app_vpc_self_link == "" ? 0 : 1
  network                 = var.app_vpc_self_link
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services[0].name]
}

module "cloud_sql" {
  source            = "../../modules/cloud-sql-pg16"
  project_id        = var.project_id
  region            = var.region
  environment       = var.environment
  network_self_link = var.app_vpc_self_link

  # Private IP needs the peering first; the db-password version needs the secret container.
  depends_on = [
    google_service_networking_connection.private_services,
    module.secret_manager,
  ]
}

module "onprem_vpn" {
  source     = "../../modules/onprem-vpn"
  project_id = var.project_id
  region     = var.region
  network    = var.app_vpc_self_link
  # enable_vpn defaults false — provisions the tunnel once the on-prem peer is coordinated.
}
