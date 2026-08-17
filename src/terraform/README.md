# Lupin GCP Infrastructure (Terraform)

Declarative provisioning for Milestone 1 (single always-on GCE GPU VM running
`docker-compose` ~verbatim, with Cloud SQL + GCS + Secret Manager). Build/deploy
stays in the `src/scripts/cloud-run-*.sh` wrappers; **Terraform owns the
resources** those wrappers assume already exist.

Plan of record: `src/rnd/v0.1.8/2026.05.30-gcp-deployment/2026.05.30-gcp-deployment-provisioning-plan.md` §6.
Execution log: `src/rnd/v0.1.8/2026.05.30-gcp-deployment/2026.06.02-phase2-terraform-execution.md`.

## Layout

```
src/terraform/
├── modules/
│   ├── gcs-buckets/        ✅ LanceDB + Deep-Research buckets (reuse-aware)
│   ├── artifact-registry/  ✅ Docker repo (immutable tags, cleanup policy)
│   ├── iam/                ⬜ split build-sa / runtime-sa, per-resource least-priv
│   ├── secret-manager/     ⬜ secret inventory + per-secret accessor bindings
│   ├── cloud-sql-pg16/     ⬜ private-IP PG16 + PITR
│   ├── vpc-vpn/            ⬜ VPC + Cloud VPN tunnel to on-prem vLLM
│   ├── gce-gpu-vm/         ⬜ L4 VM + startup-script (driver + compose up)
│   └── cloud-run-model-server/ ✅ L4 GPU model server on Cloud Run, scale-to-zero (Set B)
└── envs/
    └── test/               Milestone-1 GCP TEST environment
```

## Hard rules

- **No hardcoded project ID or region.** Everything threads `var.project_id` /
  `var.region`. A grep for any hardcoded sandbox project ID across `src/terraform/`
  must return nothing.
- **No secrets in `.tf` / `.tfvars`.** Secret *values* are populated into Secret
  Manager out-of-band; Terraform references them, never stores them.
- `terraform.tfvars` is git-ignored; copy `terraform.tfvars.example` and fill in.

## Usage

```bash
cd src/terraform/envs/test

# Validate syntax/providers without a remote state bucket:
terraform init -backend=false && terraform validate

# Real run (remote state bucket must exist first — see backend.tf):
gcloud storage buckets create gs://<proj>-tfstate --location=us-central1 --uniform-bucket-level-access
gcloud storage buckets update gs://<proj>-tfstate --versioning
terraform init -backend-config="bucket=<proj>-tfstate"
cp terraform.tfvars.example terraform.tfvars   # then edit
terraform plan
```

## Status (2026-06-02)

Foundation + `gcs-buckets` + `artifact-registry` authored and `terraform validate`
green. The buckets module defaults to **reuse** for the test env (Phase-0 V4 found
`lupin-deep-research-test` already present); the registry module provisions
`lupin-images` fresh (Phase-0 V8 found none). Remaining five modules are sequenced
in the execution log.

**2026-08-17**: the LanceDB bucket left this module with the LanceDB teardown
(row `281e52e6`). Phase-0 V4 had also found `lupin-lancedb-test` present, which is
why it appeared here — but `create_buckets` was false in every environment, so
terraform never created either LanceDB bucket and held no state for them.
`gs://lupin-lancedb-prod` did not exist at all; `gs://lupin-lancedb-test` was empty
and was deleted by hand.
