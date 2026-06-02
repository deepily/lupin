# Milestone-1 GCP TEST environment — full module wiring (provisioning DAG per plan §6.5).
#
# Order of dependency (Terraform resolves automatically via references):
#   secret-manager, gcs-buckets, artifact-registry, vpc-vpn  (no deps)
#     → iam            (binds runtime-sa to buckets/secrets/AR)
#     → cloud-sql-pg16 (private IP needs the VPC + service-networking peering)
#     → gce-gpu-vm     (needs subnet + runtime-sa)

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
  # Phase-0 V8 confirmed no repo exists → provision-new "lupin-images".
}

module "vpc_vpn" {
  source     = "../../modules/vpc-vpn"
  project_id = var.project_id
  region     = var.region
  # enable_vpn defaults false — VPC/subnet/peering/firewall now; tunnel when on-prem is coordinated.
}

module "iam" {
  source           = "../../modules/iam"
  project_id       = var.project_id
  bucket_names     = module.gcs_buckets.bucket_names
  secret_names     = module.secret_manager.secret_ids
  ar_repository_id = module.artifact_registry.repository_id
  ar_location      = var.region
}

module "cloud_sql" {
  source            = "../../modules/cloud-sql-pg16"
  project_id        = var.project_id
  region            = var.region
  environment       = var.environment
  network_self_link = module.vpc_vpn.network_self_link

  # Private IP requires the service-networking peering to exist first.
  depends_on = [module.vpc_vpn]
}

module "gce_vm" {
  source           = "../../modules/gce-gpu-vm"
  project_id       = var.project_id
  region           = var.region
  zone             = var.zone
  environment      = var.environment
  subnet_self_link = module.vpc_vpn.subnet_self_link
  runtime_sa_email = module.iam.runtime_sa_email
}
