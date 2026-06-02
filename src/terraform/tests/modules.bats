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

@test "gce-gpu-vm data disk is prevent_destroy" {
  grep -q 'prevent_destroy = true' "${MODULES}/gce-gpu-vm/main.tf"
}

@test "gce-gpu-vm terminates on host maintenance (GPU requirement)" {
  grep -q 'on_host_maintenance = "TERMINATE"' "${MODULES}/gce-gpu-vm/main.tf"
}

@test "gce-gpu-vm runs as runtime-sa, not default compute SA" {
  grep -q 'email  = var.runtime_sa_email' "${MODULES}/gce-gpu-vm/main.tf"
}

@test "secret-manager creates no secret VERSIONS (values stay out-of-band)" {
  run grep 'resource "google_secret_manager_secret_version"' "${MODULES}/secret-manager/main.tf"
  [ "$status" -ne 0 ]
}
