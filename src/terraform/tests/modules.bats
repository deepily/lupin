#!/usr/bin/env bats
#
# Terraform module assertions (Decision 1/2, 2026-06-02: bats wrappers).
#
# Structural + security-attribute regression locks over the IaC. Runnable offline:
# `terraform validate` (schema) + source-attribute greps for the things most likely
# to regress (no objectAdmin, private-IP SQL, immutable tags, prevent_destroy, etc.).
# Plan-level (`terraform plan -json`) assertions are added once ADC + the
# db-password secret version exist (they need credentials + a populated secret).
#
# Run:  bats src/terraform/tests/modules.bats
# (Install bats: `apt-get install bats` or `npm i -g bats`.)

TF_ROOT="${BATS_TEST_DIRNAME}/.."
ENV_TEST="${TF_ROOT}/envs/test"
MODULES="${TF_ROOT}/modules"

setup() {
  cd "${ENV_TEST}"
}

@test "envs/test passes terraform validate" {
  terraform init -backend=false -no-color >/dev/null
  run terraform validate -no-color
  [ "$status" -eq 0 ]
  [[ "$output" == *"valid"* ]]
}

@test "no hardcoded sandbox project id anywhere in src/terraform" {
  run grep -rn "hello-world-foo-423219" "${TF_ROOT}" --include="*.tf"
  [ "$status" -ne 0 ]
}

@test "env project_id variable has NO default argument (fails loud if unset)" {
  # Extract the project_id variable block; it must not contain a `default =` ARGUMENT
  # (the description mentioning the word "default" must not trip this).
  run bash -c "awk '/variable \"project_id\"/{f=1} f{print} /^}/{if(f)exit}' '${ENV_TEST}/variables.tf' | grep -cE 'default[[:space:]]*='"
  [ "$output" -eq 0 ]
}

@test "iam grants storage.objectUser to runtime, never objectAdmin/storage.admin" {
  grep -q 'roles/storage.objectUser' "${MODULES}/iam/main.tf"
  run grep -E 'storage.objectAdmin|roles/storage.admin' "${MODULES}/iam/main.tf"
  [ "$status" -ne 0 ]
}

@test "iam binds secrets/buckets per-resource, not project-wide" {
  grep -q 'google_secret_manager_secret_iam_member' "${MODULES}/iam/main.tf"
  grep -q 'google_storage_bucket_iam_member' "${MODULES}/iam/main.tf"
  # The project-level grants must carry ONLY cloudsql.client / logging / monitoring —
  # never objectUser or secretAccessor (those are bound per-resource above).
  run bash -c "grep -A2 'google_project_iam_member' '${MODULES}/iam/main.tf' | grep 'role' | grep -Ev 'cloudsql.client|logging.logWriter|monitoring.metricWriter'"
  [ -z "$output" ]
}

@test "iam creates no owner/editor grants" {
  run grep -E 'roles/owner|roles/editor' "${MODULES}/iam/main.tf"
  [ "$status" -ne 0 ]
}

@test "iam exposes an optional external_vm_sa_email (Phase B repoint)" {
  grep -q 'variable "external_vm_sa_email"' "${MODULES}/iam/variables.tf"
  # Optional → must carry an empty-string default so validate runs without it.
  run bash -c "awk '/variable \"external_vm_sa_email\"/{f=1} f{print} /^}/{if(f)exit}' '${MODULES}/iam/variables.tf' | grep -cE 'default[[:space:]]*=[[:space:]]*\"\"'"
  [ "$output" -eq 1 ]
}

@test "iam binds runtime roles via coalesce(external_vm_sa_email, runtime_sa) local" {
  # The repoint local must coalesce external over the module SA…
  grep -q 'coalesce(var.external_vm_sa_email, google_service_account.runtime_sa.email)' "${MODULES}/iam/main.tf"
  # …and the runtime role bindings must reference that local, not the SA directly.
  grep -q 'member = local.runtime_sa_member' "${MODULES}/iam/main.tf"
  # No runtime binding may still pin the module SA email directly (build-sa is separate).
  run grep -E 'member[[:space:]]*=[[:space:]]*"serviceAccount:\$\{google_service_account.runtime_sa.email\}"' "${MODULES}/iam/main.tf"
  [ "$status" -ne 0 ]
}

@test "envs/test repoints iam to the VM vm_sa without a hardcoded project literal" {
  # Email is constructed from var.project_id (the project literal stays out of source).
  grep -q 'external_vm_sa_email = "${var.vm_sa_account_id}@${var.project_id}.iam.gserviceaccount.com"' "${ENV_TEST}/main.tf"
  grep -q 'variable "vm_sa_account_id"' "${ENV_TEST}/variables.tf"
}

@test "artifact-registry uses immutable tags" {
  grep -q 'immutable_tags = true' "${MODULES}/artifact-registry/main.tf"
}

@test "cloud-sql is private IP only" {
  grep -q 'ipv4_enabled    = false' "${MODULES}/cloud-sql-pg16/main.tf"
}

@test "cloud-sql has PITR enabled" {
  grep -q 'point_in_time_recovery_enabled = true' "${MODULES}/cloud-sql-pg16/main.tf"
}

@test "cloud-sql password comes from a secret data source (no plaintext)" {
  grep -q 'data.google_secret_manager_secret_version.db_password' "${MODULES}/cloud-sql-pg16/main.tf"
}

# NOTE: the GCE VM + VPC/subnet/NAT/SSH are now owned by the standalone
# terraforming-vms app (its own repo + tests). Lupin keeps only the on-prem VPN.

@test "onprem-vpn is fully gated on enable_vpn (creates nothing when false)" {
  # Every resource in the module carries the enable_vpn count guard.
  run bash -c "grep -cE '^resource' '${MODULES}/onprem-vpn/main.tf'"
  res_count="$output"
  run bash -c "grep -c 'var.enable_vpn ? 1 : 0' '${MODULES}/onprem-vpn/main.tf'"
  [ "$output" -eq "$res_count" ]
}

@test "secret-manager creates no secret VERSIONS (values stay out-of-band)" {
  run grep 'resource "google_secret_manager_secret_version"' "${MODULES}/secret-manager/main.tf"
  [ "$status" -ne 0 ]
}
