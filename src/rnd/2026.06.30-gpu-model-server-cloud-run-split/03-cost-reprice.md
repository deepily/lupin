# Cost re-price — ruled Cloud-Run-split config vs status-quo VM (finding #5 / Decision #5)

| Field | Value |
|---|---|
| **Date** | 2026-07-01 |
| **Author** | Rachel 🕊️ (session `c5173c48`, GCP-remediation builder) under Tiberius 👑 |
| **Trigger** | Ratified Decision #5 ("re-price DRIVE NOW") + Arnold 🪨 finding #5 |
| **Status** | ANALYSIS for manager → Rick. Deciding number for whether Rick buys the split. |
| **Rick's framing (2026-07-01)** | **VM is PAUSED (suspended), not stopped.** **Compare MONTHLY costs only — 1-yr CUD commitments are OUT of scope.** |
| **Rates dated** | Published GCP us-central1 rates, retrieved 2026-07-01 (sources below) |

> ⚠️ **Itemized estimate from published list rates, not an official Cloud-billing
> figure.** Authoritative number still needs a with-creds pricing-calculator run.
> The verdict is robust across the rate range.

## PRIMARY profile — weekday-only, VM suspended off-hours

**Both services utilized ONLY Mon–Fri 09:00–23:00 EDT** (14h × 5 = 70h/week ≈
**303.3 h/mo**, 52/12 weeks). ALL other hours (weeknights 23:00–09:00 + all
weekend): **Cloud Run → min=0 scale-to-zero ($0)** AND **the e2-standard-8 VM
SUSPENDED (paused)**.

**Suspend vs stop (Rick's correction):** a *suspended* VM writes its RAM to disk
and incurs **no compute (cores/RAM) charge** — only the saved memory-state at
**Persistent-Disk rates** (prorated per second) plus the boot disk. Upside over
stop: **state is preserved → near-instant resume** (no cold boot / no
docker-compose-up cycle), which fits an app VM hosting lupin-rest + CC + FIFO.
Cost delta vs stop is only ~$1–2/mo (the 32 GB RAM-state storage).

### Published rates used

| Resource | Rate | Source |
|---|---|---|
| Cloud Run L4 GPU (no zonal redundancy, Tier 1) | **$0.0001867 / GPU-s** (≈ $0.672/GPU-h) | Cloud Run pricing / GPU docs |
| Cloud Run vCPU, instance-based (Tier 1) | **$0.000018 / vCPU-s** (primary); request-based upper bound $0.000024 | Cloud Run pricing |
| Cloud Run memory, instance-based (Tier 1) | **$0.000002 / GiB-s** (primary); request-based upper bound $0.0000025 | Cloud Run pricing |
| e2-standard-8, on-demand (per-hour, running only) | **$0.2680 / h** | Compute Engine pricing |
| Persistent Disk (pd-balanced) — boot disk + suspended RAM-state | **~$0.10 / GB-mo** | Compute Engine disk pricing |

> GPU **requires instance-based billing** → instance-based vCPU/memory rates are
> the primary figures. A suspended VM's saved memory + the boot disk bill at PD
> rates whether the VM is running or paused.

### Itemized monthly cost — weekday-only + suspend profile

| Line item | Calculation | $/mo (primary) | $/mo (upper) |
|---|---|---|---|
| Cloud Run L4 GPU | 303.3 h × $0.672/h | **$204** | $204 |
| Cloud Run vCPU (8) | 8 × 303.3 h × 3600 × rate | **$157** | $210 |
| Cloud Run memory (32 GiB) | 32 × 303.3 h × 3600 × rate | **$70** | $87 |
| — Cloud Run subtotal (weekday warm) | | **$431** | $501 |
| e2-standard-8 VM compute (running ~303 h) | 303.3 h × $0.2680/h | **$81** | $81 |
| VM boot/data disk (~100 GB pd-balanced, 24×7) | ~100 × $0.10 | **~$10** | ~$10 |
| Suspended RAM-state (32 GB @ PD, ~58% of month paused) | 32 × $0.10 × 0.58 | **~$2** | ~$2 |
| Scheduler / internal egress / Secret Mgr / AR image (~20 GB) | negligible–minor | **~$3** | ~$3 |
| **TOTAL — weekday-only + suspend** | | **≈ $527 / mo** | ≈ $597 / mo |

Confirm with creds: boot-disk **size + type** (dominant disk cost — 100 GB
pd-balanced assumed; scales linearly). Suspend requires the memory-state written to
PD; e2-standard-8 (CPU-only) supports suspend.

## Comparison — MONTHLY only (Rick: CUD out of scope)

| Baseline (always-on, monthly, no commitment) | $/mo | Split Δ (primary ≈ $527) | Beats it? |
|---|---|---|---|
| g2-standard-8 + L4, **on-demand** | **$623** | **−$96 / mo (~15% cheaper)** | ✅ **YES** |

> The 1-yr-CUD figure ($393) is **excluded per Rick — he does not want year-long
> commitments; monthly cost is the only axis.** On that axis there is no fork.

## Verdict — **CLEAN WIN (de-inverts vs on-demand)** ✅

At **≈ $527/mo**, the weekday-only + suspend split costs **~$96/mo less (~15%)** than
the current always-on on-demand VM ($623). Robust across the rate range: even at the
request-based upper bound ($597) it still beats $623.

The v1 over-provisioned inversion is gone — it was an artifact of a 24×7 VM + 7-day
warm that Rick never wanted. With weekday-only usage + suspend off-hours, the split
is **cheaper monthly AND** brings the non-cost wins: no on-VM GPU-driver upkeep,
clean stateless/stateful separation, elastic 0→1, near-instant resume on suspend.

**Recommendation: the economics work on a monthly basis — buy the split.**

### ⚠️ Operational implication

Suspending the e2-standard-8 nights + weekends takes **lupin-rest + CC + the FIFO
queues offline** during those windows (the VM hosts the whole app). This is the
**cloud-TEST** env (off-hours-dispensable), so it is acceptable — but stated so Rick
sees the implication: **no test-env availability weeknights 23:00–09:00 EDT or any
weekend.** Suspend (vs stop) makes the return quick — resume restores RAM state.

## Design sub-tasks — BUILT (dry-verified 2026-07-01; apply stays Rick-gated)

1. **Cloud Run weekday min-toggle (in-repo):** module `scale_up_cron`/`scale_down_cron`
   defaults → weekday-only (`0 9 * * 1-5` / `0 23 * * 1-5`). ✅ built.
2. **VM suspend/resume pair (in-repo `vm-power-schedule` module):** Cloud Run's
   min-toggle cannot pause a VM, so a new module provisions two Cloud Scheduler jobs
   POSTing to the Compute Engine API **`instances.suspend`** (`0 23 * * 1-5`) +
   **`instances.resume`** (`0 9 * * 1-5`) with an OAuth token (cloud-platform scope);
   weekends stay suspended (no weekday resume). ✅ built + wired into `envs/test`.
   `terraform plan` = 6 add / 0 change / 0 destroy. What remains is IAM only (grant
   the scheduler SA `compute.instances.suspend`/`resume` on the VM) + confirm the VM
   zone — see 02-vm-downgrade-handoff.md.

## REJECTED variant — 24×7 VM + 7-day warm (over-provisioned; superseded)

Earlier estimate assumed a 24×7 VM + 7-day (14h/day) warm — Rick never wanted that.
Retained for the audit trail: Cloud Run 7-day warm $605 + e2-standard-8 24×7 $196 +
misc ≈ **$803/mo** (would exceed on-demand $623). REJECTED; the weekday-only +
suspend profile above is operative.

## Sources

- [Cloud Run pricing | Google Cloud](https://cloud.google.com/run/pricing)
- [GPU support for services | Cloud Run docs](https://docs.cloud.google.com/run/docs/configuring/services/gpu)
- [e2-standard-8 pricing | economize.cloud](https://www.economize.cloud/resources/gcp/pricing/compute-engine/e2-standard-8/)
- [Suspend/stop/reset instances | Compute Engine docs](https://docs.cloud.google.com/compute/docs/instances/suspend-stop-reset-instances-overview)
- [Disk and image pricing | Google Cloud](https://cloud.google.com/compute/disks-image-pricing)
