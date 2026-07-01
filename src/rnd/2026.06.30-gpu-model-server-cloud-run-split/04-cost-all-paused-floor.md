# Cost — CONTRAST "all-paused floor" (Cloud Run scale-to-zero + GPU VM STOPPED 24/7/30d)

| Field | Value |
|---|---|
| **Date** | 2026-07-01 |
| **Author** | Clayton 😎 (session `bb7e4f56`, GCP author/worker) under Tiberius 👑 |
| **Deliverable** | D1 (`task 5cb954b2`) — Rick asked by name for the all-paused contrast baseline |
| **Scenario** | Cloud Run `min_instances=0` (scale-to-zero) 24/7 **AND** the app VM `lupin-host-test` **STOPPED** 24 h/day for a full 30-day month. Nothing runs; nothing serves. |
| **Companion** | Contrast baseline for `03-cost-reprice.md` (the operative weekday-warm + suspend plan ≈ $527/mo) |
| **Month convention** | 730 h (GCP's standard billing month). A strict 30-day month is 720 h — a <1.4% difference; ignored. |

> ⚠️ **Itemized estimate from published us-central1 list rates (retrieved 2026-07-01), not an official Cloud-billing figure.** Terraform-confirmed items are marked ✅; items owned by the external `terraforming-vms` repo or needing a creds pricing-calc run are marked ⚠️.

---

## Headline

**The all-paused floor is ≈ $125 / month — and it is dominated by the always-on Cloud SQL Postgres instance (~$103/mo, ~82%), NOT by any GPU reservation.**

**There is NO L4 GPU reservation in the split.** The GPU moved onto Cloud Run (serverless), so at `min=0` with zero requests the GPU cost is **$0** — the feared "reservation billed even while stopped" floor **does not exist** in this architecture. Verified: zero `google_compute_reservation` and zero `reservation_affinity` anywhere in `src/terraform/` (`grep` clean).

---

## Line-item breakdown — all-paused floor

| # | Line item | Status | Calculation | $/mo |
|---|---|---|---|---|
| 1 | **L4 GPU reservation** | ✅ none exists | GPU is Cloud Run serverless; no reservation resource | **$0.00** |
| 2 | **Cloud Run compute** (min=0, 0 requests) | ✅ | scale-to-zero → no instances → no GPU/vCPU/mem seconds | **$0.00** |
| 3 | **Cloud SQL PG16 compute** | ✅ `db-custom-2-7680`, ENTERPRISE, ZONAL, `create_instance=true` — runs 24/7, cannot scale to zero | 2 vCPU × $0.0413 × 730 + 7.5 GB × $0.007 × 730 | **$98.63** |
| 4 | Cloud SQL storage (SSD) | ⚠️ default ~10 GB, autoresize | ~10 × $0.17 | **~$1.70** |
| 5 | Cloud SQL backups (7 automated + PITR) | ✅ configured | small DB, backup storage $0.08/GB-mo | **~$1–3** |
| 6 | **VM boot/data disk** (STOPPED VM still bills disk) | ⚠️ `terraforming-vms` repo; ~100 GB pd-balanced assumed | ~100 × $0.10 | **~$10.00** |
| 7 | Reserved static external IP | ⚠️ `terraforming-vms` repo — bills only if a *static* IP is reserved (a stopped VM's *ephemeral* IP is released → $0) | $0.01/h × 730 | **~$7.30** or $0 |
| 8 | **Artifact Registry** image storage | ✅ 2 immutable images (rest + ~20 GB model-server) | ~28 GB × $0.10 | **~$2.80** |
| 9 | GCS buckets (reused `-test`) | ⚠️ `create_buckets=false`; pre-existing, storage-only | est. small | **~$1–2** |
| 10 | Secret Manager | ✅ ~5 active secret versions | 5 × $0.06 | **~$0.30** |
| 11 | Cloud Scheduler | ✅ 4 jobs (first 3 free) | 1 × $0.10 | **~$0.10** |
| | **FLOOR TOTAL** | | | **≈ $125 / mo** (range ~$115–135) |

**~82% of the floor is Cloud SQL** (compute + storage + backups ≈ $103). Everything else combined is ~$22.

---

## ⚠️ Two caveats that can move the floor materially

1. **Cloud NAT (external repo).** If a Cloud NAT gateway in `terraforming-vms` stays up while the VM is stopped, add **~$32/mo** (~$0.044/gateway-hour, traffic-independent). This is the single largest *unconfirmed* risk to the floor — verify in that repo.
2. **Cloud SQL is stoppable.** The ~$99/mo compute is only spent while the instance is ACTIVE. Setting the instance `activation_policy = NEVER` (stop it) drops compute to $0, leaving only storage + backups (~$4/mo). **If Rick wants a true minimum, stopping Cloud SQL too takes the floor from ~$125 → ~$30/mo.** As currently built (`create_instance=true`, always active), Cloud SQL runs.

---

## Contrast — floor vs running

| Scenario | $/mo | Notes |
|---|---|---|
| **All-paused floor** (this doc) | **≈ $125** | Cloud Run 0 + VM STOPPED; ~$103 is Cloud SQL |
| **Operative running plan** (weekday-warm + VM suspend, `03-cost-reprice.md`) | **≈ $527** | Mon–Fri 09:00–23:00 warm; off-hours paused |
| Δ (activity cost above the floor) | **~+$400/mo** | what you pay for the weekday warm window |
| Always-on 24/7 warm (min=1 + VM on) — rejected v1 | ≈ $803 | over-provisioned; superseded |
| Status-quo always-on on-demand VM (g2-standard-8 + L4) | ≈ $623 | today's baseline; on-demand, no reservation → a *stopped* status-quo VM also bills no GPU |

**Takeaway:** the floor you cannot escape without deleting/stopping the database is **~$125/mo**, essentially the price of keeping Postgres alive. The GPU contributes **$0** to the floor in the split — its cost is fully elastic (pay only when warm). If Rick also stops Cloud SQL, the floor collapses to **~$30/mo** (disk + IP + AR + misc).

---

## Sources (rates retrieved 2026-07-01)

- Cloud SQL Enterprise PostgreSQL us-central1: $0.0413/vCPU-h, $0.007/GB-h — [Cloud SQL pricing | Google Cloud](https://cloud.google.com/sql/pricing); [Usage.ai Cloud SQL Pricing 2026](https://www.usage.ai/blogs/gcp/cloud-sql/pricing/)
- Static external IP $0.01/h (assigned-but-idle / unattached) — [Network pricing | Google Cloud](https://cloud.google.com/vpc/network-pricing)
- Persistent Disk pd-balanced ~$0.10/GB-mo — [Disk and image pricing | Google Cloud](https://cloud.google.com/compute/disks-image-pricing)
- Artifact Registry $0.10/GB-mo (first 0.5 GB free) — [Artifact Registry pricing | Google Cloud](https://cloud.google.com/artifact-registry/pricing)
- Cloud Run GPU / scale-to-zero — [Cloud Run pricing | Google Cloud](https://cloud.google.com/run/pricing)
- Terraform confirmations — `src/terraform/envs/test/main.tf`, `modules/cloud-sql-pg16/{main,variables}.tf`, `modules/cloud-run-model-server/{main,variables}.tf`, `modules/artifact-registry/main.tf`
