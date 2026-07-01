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

# --- GPU inference plane (Set B): the carve-out model server on Cloud Run GPU.
#     LOCKED to Rick's ruled decisions (2026-07-01): SCHEDULED-WARM (min=1 seed +
#     the ×2 Cloud Scheduler jobs dial 1↔0 on 9am/11pm America/New_York), and
#     INTERNAL-ONLY ingress + Direct VPC egress. Image pulled from the
#     artifact-registry module's repo; the X-API-Key is mounted from the
#     secret-manager module's inventory. Direct VPC egress attaches to the app
#     VPC only once both the VPC self-link and a subnetwork are supplied (else
#     the block is omitted → validate stays clean before the terraforming-vms
#     net exists). See: src/rnd/2026.06.30-gpu-model-server-cloud-run-split/01-design.md
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

# --- VM power schedule (Set B companion): weekday suspend/resume of the app VM.
#     Rick 2026-07-01 — the app VM (lupin-host-test) is utilized Mon–Fri
#     09:00–23:00 EDT and PAUSED (suspended) off-hours. Cloud Run's min-toggle
#     cannot pause a VM, so this provisions two Cloud Scheduler jobs hitting the
#     Compute Engine API (instances.suspend at 23:00 / instances.resume at 09:00,
#     weekdays; weekends stay suspended). The VM lives in the standalone
#     terraforming-vms repo/state — referenced here by name + zone only (no
#     cross-state data source), so validate/plan stay clean. Suspend snapshots
#     RAM → preserves the in-memory FIFO queues + WebSocketManager singleton
#     across the pause. See 01-design.md + 02-vm-downgrade-handoff.md.
module "vm_power_schedule" {
  source     = "../../modules/vm-power-schedule"
  project_id = var.project_id
  region     = var.region

  enable                          = var.vm_power_schedule_enable
  vm_instance_name                = var.vm_power_instance_name
  vm_zone                         = var.vm_power_vm_zone
  scheduler_service_account_email = var.vm_power_scheduler_sa_email
  # suspend_cron / resume_cron / time_zone use the module's weekday defaults
  # (0 23 * * 1-5 / 0 9 * * 1-5, America/New_York).
}
