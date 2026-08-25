# D2 — Default-paused terraform change (PLAN-ONLY) + caveat verification

| Field | Value |
|---|---|
| **Date** | 2026-07-01 |
| **Author** | Clayton 😎 (session `bb7e4f56`, GCP author/worker) under Tiberius 👑 |
| **Deliverable** | D2 (`task 942d3b9d`) — prepare (do NOT apply) the default-paused terraform |
| **Mode** | RED / plan-first. `terraform apply` is Rick-gated; this doc is the reviewable diff. Commit-HELD, not pushed. |
| **Goal (Rick 2026-07-01)** | A plain `terraform apply` leaves everything COLD: Cloud Run `min_instances=0` (scale-to-zero), VM STOPPED, Cloud SQL paused. Rick toggles each ON manually when he works. |

---

## The change — three `envs/test/variables.tf` default flips (DONE, validated)

All three currently encode the "ruled SCHEDULED-WARM + weekday-suspend" operative plan. Default-paused flips them cold:

| Variable | Was | Now | Effect of a plain apply |
|---|---|---|---|
| `model_server_min_instances` | `1` | **`0`** | Cloud Run service lands COLD (scale-to-zero; $0 GPU at rest) |
| `model_server_enable_scale_schedule` | `true` | **`false`** | NO auto-warm scheduler provisioned — nothing dials min→1 on a weekday morning |
| `vm_power_schedule_enable` | `true` | **`false`** | NO auto-resume scheduler — nothing brings the VM back up; it stays paused |

Module defaults (`modules/cloud-run-model-server/variables.tf`) were already cold (`min_instances=0`, `enable_scale_schedule=false`); only the `envs/test` caller overrode them warm. The fix is purely in the caller.

**This repo cannot set the VM's power state** — the VM (`lupin-host-test`) lives in the standalone `terraforming-vms` repo/state. This repo only controls the *auto-resume scheduler*; disabling it stops anything here from un-pausing the VM. The actual VM STOP is an operational step (`gcloud compute instances stop` / a `terraforming-vms` default).

### terraform plan (read-only, ran with ADC 2026-07-01)

```
Plan: 2 to add, 0 to change, 0 to destroy.
```

- **+ `google_cloud_run_v2_service.lupin_model_server`** — created with `scaling { min_instance_count = 0, max_instance_count = 1 }`
- **+ `google_cloud_run_v2_service_iam_member.public_invoker[0]`** — the allUsers→run.invoker binding (Decision #3)
- **NOT created** (vs Rachel's 6-add): the 2 scale scheduler jobs + the 2 vm-power scheduler jobs — all four suppressed by `count = 0`.
- **0 change**: the data plane (Secret Manager, Cloud SQL, Artifact Registry, IAM, GCS) is ALREADY in state — a prior apply provisioned it. `terraform validate` = Success.

---

## Caveat verification (both GATE Tiberius's final apply)

### Caveat 1 — does anything need the GCP Cloud SQL 24/7? ✅ NO BLOCKER

`src/cosa/rest/db/database.py` `is_cloud_backed()` returns True **only** when env `LUPIN_CLOUD_BACKED` is truthy. That flag is set in exactly one place: `src/scripts/cloud-run-deploy.sh` (the GCP-deployed lupin-rest app running on the cloud-test VM). The on-prem fleet — dev `:7999`, the arbiter `:8001`, cosa-voice, the unified task-store — runs against the **local** Postgres (`run-postgresql-dev.sh`) and never sets the flag. **Cloud SQL `lupin-pg16-test`'s only consumer is the GCP-deployed app, which is itself down when the VM is stopped.** Pausing Cloud SQL affects nothing always-on.

### Caveat 2 — Cloud NAT lifecycle + the ~$32/mo risk ✅ NO BLOCKER

`terraforming-vms/network.tf`: the NAT is `google_compute_router_nat.nat_gateway` on `google_compute_router.nat_router` + the VPC subnet — **independent of the VM lifecycle** (it persists when the VM stops; it is NOT torn down with the VM). BUT under **current 2026 Cloud NAT pricing** (per-VM: $0.0014/VM-hr, capped $0.044/hr; "once a VM ceases public internet access it is no longer counted"), a **stopped VM = 0 VMs using the gateway → $0**. `nat_ip_allocate_option = "AUTO_ONLY"` holds **no reserved external IP** when idle → no IP charge. The ~$32/mo fear was the OLD flat-gateway-hour model and **does not apply**. Teardown-with-VM is unnecessary for cost (it's $0 idle); it can be torn down separately in `terraforming-vms` if desired.

**Bonus finding:** `terraforming-vms/compute.tf` — the VM has **no `access_config` block = no external IP** (internal-only; egress via NAT, admin via IAP-SSH). So the "static external IP" floor line is also **$0**.

### Refined all-paused floor (with Cloud SQL stopped)

| Item | $/mo |
|---|---|
| L4 reservation / Cloud Run compute / Cloud SQL compute / static ext IP / Cloud NAT | **$0** each |
| Cloud SQL retained storage + backups | ~$3–5 |
| VM boot disk (STOPPED; default 20 GB pd-standard, actual TBD) + optional data disk (`enable_data_disk=false` → none) | ~$1–10 |
| Artifact Registry (~28 GB, 2 images) | ~$2.80 |
| GCS + Secret Manager + Cloud Scheduler | ~$2 |
| **FLOOR TOTAL** | **≈ $10–20/mo** (below the ~$30 ceiling) |

---

## Cloud SQL "paused by default" — Option A IMPLEMENTED (Tiberius approved 2026-07-01)

**Why not a literal `activation_policy = "NEVER"` default:** an instance created STOPPED rejects `google_sql_database` / `google_sql_user` creation and the pre-deploy Alembic schema step (all need a RUNNABLE instance) → a broken greenfield apply.

**Option A (implemented) — mirrors this repo's Cloud Run `min_instance_count` authority pattern + the VM-stop model:**
1. `modules/cloud-sql-pg16/variables.tf` — new `activation_policy` var (default `"ALWAYS"`, validated ALWAYS/NEVER) so greenfield provisions DB/user/schema.
2. `modules/cloud-sql-pg16/main.tf` — `activation_policy = var.activation_policy` in `settings` + `lifecycle { ignore_changes = [settings[0].activation_policy] }` on the instance — terraform hands the live power state to the operator; re-applies never re-start a stopped DB.
3. `envs/test/variables.tf` + `main.tf` — new `cloud_sql_activation_policy` var (default `"ALWAYS"`) wired into the module.
4. **Operator step (Rick, post-apply, one-time):** `gcloud sql instances patch lupin-pg16-test --activation-policy=NEVER` stops the DB → the ~$30 all-paused floor; `ignore_changes` keeps it stopped across every future apply.

This is identical in shape to how the VM is handled (this repo doesn't set VM power either; the stop is operational) and how Cloud Run's live min-count is operator-owned.

### Final plan (read-only, ADC, 2026-07-01 — after Option A)

```
Plan: 2 to add, 0 to change, 0 to destroy.
```

- **+** `google_cloud_run_v2_service.lupin_model_server` — `min_instance_count = 0`
- **+** `google_cloud_run_v2_service_iam_member.public_invoker[0]`
- **0 change** to Cloud SQL — `activation_policy=ALWAYS` matches the running instance + `ignore_changes` suppresses drift (no destructive diff).
- **0 destroy.** `terraform fmt` clean, `terraform validate` Success.

**Apply is Rick-gated.** A plain apply lands Cloud Run cold and seeds Cloud SQL running; the ~$30 floor is reached by the one-time operator stop (DB) + stopping the VM in `terraforming-vms`. Rick warms manually per-session: `min_instances=1` (Cloud Run) / resume DB + VM.

---

## Sources (rates retrieved 2026-07-01)

- Cloud NAT per-VM pricing / idle-VM billing — [Cloud NAT pricing | Google Cloud](https://cloud.google.com/nat/pricing); [Network pricing | Google Cloud](https://cloud.google.com/vpc/network-pricing)
- Terraform confirmations — `src/terraform/envs/test/variables.tf` (this change), `modules/cloud-sql-pg16/main.tf`; `terraforming-vms/{network,compute}.tf`; consumer gate `src/cosa/rest/db/database.py`, `src/scripts/cloud-run-deploy.sh`
