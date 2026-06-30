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

# --- GPU inference plane (Set B): the carve-out model server on Cloud Run GPU,
#     scale-to-zero. Image pulled from the artifact-registry module's repo; the
#     X-API-Key is mounted from the secret-manager module's inventory. Direct VPC
#     egress attaches to the app VPC only once both the VPC self-link and a
#     subnetwork are supplied (else the block is omitted → validate stays clean).
#     See: src/rnd/2026.06.30-gpu-model-server-cloud-run-split/01-design.md
module "cloud_run_model_server" {
  source     = "../../modules/cloud-run-model-server"
  project_id = var.project_id
  region     = var.region

  image = "${module.artifact_registry.image_path_prefix}/lupin-model-server:${var.model_server_image_tag}"

  min_instances         = var.model_server_min_instances
  ingress               = var.model_server_ingress
  allow_unauthenticated = var.model_server_allow_unauthenticated

  # The api-key secret lives in the secret-manager inventory (lupin-notification-api-key default).
  api_key_secret_id = "lupin-notification-api-key"

  # Direct VPC egress: network = app VPC, subnetwork supplied separately. Both
  # empty by default → no VPC access block until the terraforming-vms net exists.
  vpc_network    = var.app_vpc_self_link
  vpc_subnetwork = var.model_server_vpc_subnetwork

  # Optional scheduled warm/cool toggle (default OFF).
  enable_scale_schedule           = var.model_server_enable_scale_schedule
  scheduler_service_account_email = var.model_server_scheduler_sa_email

  # The secret container must exist before the service mounts it.
  depends_on = [module.secret_manager]
}
