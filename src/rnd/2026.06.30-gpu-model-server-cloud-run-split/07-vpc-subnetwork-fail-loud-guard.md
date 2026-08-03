# 07 — vpc_subnetwork FAIL-LOUD Guard + Doc Alignment (2026-07-01)

**Author**: Cheech 🌿 (session a60ceb36, author for Tiberius 👑 b75d199b) · **Task**: `cb0e145a`
**Fixes**: the doc/behavior mismatch flagged in [06 §2](06-apply-verification-green-bar.md) — the subnetwork-not-found apply-time trap.

## Problem

`modules/cloud-run-model-server/main.tf` gates the `dynamic "vpc_access"` block ONLY on
`var.vpc_network != ""` (main.tf:145). With **network set + subnetwork empty**, the block
emits `subnetwork = ""`, and the Cloud Run API interprets an empty subnetwork as *"use the
subnet NAMED LIKE THE NETWORK"* (network `dev-vpc` → nonexistent subnet `dev-vpc`) → **apply-time
error code 9**, invisible to `terraform plan`. Meanwhile the env-level
`model_server_vpc_subnetwork` description claimed *"Empty → no VPC access block"* — a
doc/behavior mismatch that turned a missing var into an opaque apply crash instead of a clean signal.

## Decision — FAIL-LOUD, not silent-skip

Two candidate fixes:

- **(a) Silent-skip** — gate the block on BOTH vars, omitting `vpc_access` when subnetwork is empty.
  **REJECTED**: this deploys an `INTERNAL_ONLY` service with **no VPC egress** — unreachable from
  the app VM — as a *silent misconfiguration*. It trades a loud apply error for a quiet runtime
  outage, which violates Lupin's no-silent-fallbacks doctrine.
- **(b) FAIL-LOUD precondition** — reject the network-set-with-subnetwork-empty combination at
  **plan time** with a clear, actionable variable error. **CHOSEN** (Tiberius-approved). The
  operator learns the exact fix before any apply; the valid "both empty → block omitted"
  path (validate-clean before the app VPC exists) is preserved.

## The change (2 files)

1. **`modules/cloud-run-model-server/variables.tf`** — added a cross-variable `validation` block to
   `vpc_subnetwork`: `condition = var.vpc_network == "" || var.vpc_subnetwork != ""`, with an error
   message naming the code-9 trap and the fix. Sharpened the variable description to match.
2. **`envs/test/variables.tf`** — aligned the stale `model_server_vpc_subnetwork` description
   (the module's own `vpc_subnetwork` description already said *"Required when vpc_network is set"* —
   the env-level one was the straggler).

No change to `main.tf` — the `dynamic "vpc_access"` gate is left as-is; the validation is the guard.

## Mechanism note (why `plan`, not `validate`, for the proof)

`terraform validate` treats input-variable values as **unknown** and does **not** evaluate variable
`validation` blocks (confirmed empirically: a violating default and a violating literal module-arg
both report `Success`). `terraform plan` **does** evaluate them during variable evaluation — before
provider configuration — so the RED proof uses `plan`. Cross-variable validation requires Terraform
≥ 1.9 (env runs 1.12.2).

## RED-first verification (terraform 1.12.2, offline harness calling the REAL module)

Harness in scratchpad instantiates `modules/cloud-run-model-server` directly with a dummy offline
provider credential (no GCP calls, **no apply**, **tfvars untouched**):

| Case | network / subnetwork | Guard | `vpc_access` block | `terraform plan` |
|---|---|---|---|---|
| **BAD (RED)** | set / **empty** | **FIRES** — `Error: Invalid value for variable ... vpc_subnetwork is REQUIRED when vpc_network is set` | — | planning aborts |
| **GOOD (GREEN)** | set / `dev-internal-subnet` (pinned) | passes | emitted, `subnetwork = projects/hello-world-foo-423219/regions/us-central1/subnetworks/dev-internal-subnet` | **2 to add** |
| **EMPTY (compat)** | empty / empty (defaults) | passes | **omitted** | **2 to add** |

Additional gates:
- `terraform fmt -check -recursive src/terraform` → clean (exit 0).
- `terraform validate` → `Success` on both `modules/cloud-run-model-server` and `envs/test`.

## Review finding (Tiberius) + fix — Terraform version floor

Pre-commit review surfaced a real gap the 1.12.2 run could not expose: the cross-variable
validation condition (`var.vpc_subnetwork` referencing `var.vpc_network`) is legal **only since
Terraform 1.9**. On 1.5–1.8, `terraform init` errors with *"condition ... can only refer to the
variable itself"*. But `envs/test/versions.tf` pinned `required_version = ">= 1.5"`, and the
module had **no** `versions.tf` at all — so the pin under-stated the real floor and a <1.9 caller
would hit an opaque init error.

**Fix** (2 more files):
- **NEW `modules/cloud-run-model-server/versions.tf`** — `required_version = ">= 1.9"`, declared at
  the SOURCE of the 1.9-gated feature so ANY caller of the module is protected (mirrors the reason
  the validation itself lives in the module, not the env).
- **`envs/test/versions.tf`** — bumped `>= 1.5` → `>= 1.9` with a comment citing the cross-var
  validation.

Post-fix: `terraform fmt -check -recursive` clean; `terraform validate` Success on module + env;
RED/GREEN/compat harness re-run unchanged (guard fires on BAD, `2 to add` on GOOD).

## Discipline

No `terraform apply`; git-ignored `terraform.tfvars` untouched; deployed service unmodified.
CODE change → standing pre-commit review gate: reviewed by Tiberius (one required change — the
version floor above — then APPROVED). Commit HELD until the fix landed; never pushed.
