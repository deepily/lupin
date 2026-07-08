# Memento — Rachel 🕊️ (GCP-remediation builder), 2026-07-01

| Field | Value |
|---|---|
| **Persona / session** | Rachel 🕊️ / `c5173c48` (BUILD worker, role=author) |
| **Manager** | Tiberius 👑 / `eb4b105f` |
| **Reviewer-of-record** | Arnold 🪨 / `af7d4492` · Observer: María 🌸 / `f1cb1e70` |
| **Task** | `dab6cdfa` — GCP GPU-model-server → Cloud Run split remediation |
| **Spec thread** | dm-tiberius `a0f48b0d-661c-471d-b620-8379e140aec7` (Arnold's 10-finding REVISE + María verification) |
| **State** | ✅ REMEDIATION + FINALIZATION COMPLETE, self-verified green (dry). Rick greenlit the buy; Tiberius un-held → weekday-cron + VM suspend/resume TF BUILT (`vm-power-schedule` module), plan = 6 add / 0 change / 0 destroy. Tiberius **APPROVED** (F-T1 oauth fix verified). Awaiting María #1-#4 source re-verify → commit-held. NOT committed, NOT pushed. **🟢 REAP-READY at equilibrium** — nothing in mid-stride, memento self-contained; commit is Tiberius's, not mine. A re-spawn (if any) needs only this file + 01/02/03. |

## What is DONE (all 10 findings; Arnold's order #4→#1→#3)

9 files (8 mod + 1 new), verified via `terraform validate`+`plan` (dry), shellcheck (docker koalaman, exit 0), 63 resolver unit tests:

1. `src/scripts/cloud-run-model-server-deploy.sh` — **#4**: build+push ONLY (dropped `gcloud run deploy`); prints pushed digest (**#9**).
2. `src/scripts/cloud-run-model-server.env.example` — reconciled (service-config moved to TF).
3. `src/terraform/modules/cloud-run-model-server/main.tf` — invoker comment (**#1**) + `startup_probe` on /health (**#10**).
4. `src/terraform/modules/cloud-run-model-server/variables.tf` — `allow_unauthenticated` default→**true** (**#1**) + 5 probe vars.
5. `src/terraform/envs/test/variables.tf` — `model_server_allow_unauthenticated` default→**true** (**#1**, the operative ruled-config flip).
6. `docker-compose.cloud-gpu.yml` — removed dead `LUPIN_MODEL_SERVER_API_KEY_FILE` (**#7**).
7. `src/rnd/…/01-design.md` — Local→cloud step 2 reworded (**#4**) + Apply-runbook (**#6/#8/#9**).
8. `src/rnd/…/02-vm-downgrade-handoff.md` — **#2**: PGA + `*.run.app`→`199.36.153.4/30` DNS section, OWNER=terraforming-vms repo owner, seed TODOs, sequencing diagram updated.
9. NEW `src/rnd/…/03-cost-reprice.md` — **#5** analysis.

**Plan-confirmed (dry, 4-add/0-change/0-destroy):** `public_invoker[0]` member=allUsers role=roles/run.invoker PRESENT · KEYS_DIR=/secrets/keys + mount_path=/secrets/keys + item notification-api-claude-code-dev BYTE-IDENTICAL · INTERNAL_ONLY ingress · scale_up+scale_down scheduler pair · startup_probe /health.

**#3 subsumed by #4** (script no longer deploys; TF path already correct). **#6** = with-creds embedding+STT smoke DOCUMENTED not run. Image build UNAFFECTED (touched nothing under `docker/lupin-model-server/` or `src/lupin_model_server/`). NO Python changed → 100% new/changed-Python gate vacuously satisfied.

## #5 RE-PRICE — v2 weekday-only = PARTIAL DE-INVERSION (current)

**v1 (rejected):** 24×7 VM + 7-day warm ≈ **$803/mo** → INVERTED (+$180 OD, +$410 CUD). Triangulated Arnold ~$793 + María ~$635–793. Rick said he never wanted 24×7 VM / 7-day warm.

**v3 (PRIMARY, Rick-corrected 2026-07-01 — supersedes v2):** BOTH services weekday-only Mon–Fri 09:00–23:00 EDT (~303 h/mo); else Cloud Run min=0 + **VM SUSPENDED/PAUSED** (Rick: suspend, NOT stop — no compute charge, only saved RAM-state + boot disk at PD rates; preserves state for near-instant resume). Rick framing: **MONTHLY cost ONLY — 1-yr CUD OUT of scope.** Total ≈ **$527/mo** (range $527–597): Cloud Run warm $431 (GPU $204 + 8vCPU $157 + 32Gi $70, instance-based) + e2-standard-8 running-303h $81 + ~100GB disk $10 + suspended 32GB RAM-state ~$2 + misc $3.
- vs $623 OD: **−$96/mo → CLEAN WIN (~15% cheaper)** ✅
- CUD excluded per Rick (no year commitments). No fork — just buy the split.
**Verdict: CLEAN WIN vs on-demand. Recommend buy the split.** (v2's partial-de-inversion/CUD-fork framing is DEAD — Rick killed the CUD axis; v1 $803 24×7 remains the rejected over-provisioned variant.)

**NEW design sub-tasks (held pending Rick buy-in, NOT yet in TF):** (1) module scale_up/down crons → weekday-only `0 9/23 * * 1-5`; (2) cross-repo VM **suspend/resume** pair (Cloud Scheduler→Compute Engine API `instances.suspend`/`resume` — min-toggle can't pause a VM), owned by terraforming-vms (in 02-handoff). Operational: VM suspend = lupin-rest+CC+FIFO OFFLINE off-hours (acceptable for cloud-TEST; suspend = fast resume).

## FINALIZATION build (2026-07-01, un-held by Tiberius after Rick's greenlight)

NEW/changed for the weekday + suspend finalization (dry-verified, plan 6-add/0-change/0-destroy):
- `modules/cloud-run-model-server/variables.tf` — scale_up/down_cron defaults → weekday `0 9/23 * * 1-5`.
- **NEW** `modules/vm-power-schedule/{main,variables,outputs}.tf` — 2 Cloud Scheduler jobs → Compute Engine API `instances.suspend`(`0 23 * * 1-5`)/`resume`(`0 9 * * 1-5`), OAuth token (cloud-platform scope), gated on `enable`.
- `envs/test/variables.tf` + `envs/test/main.tf` — wired `vm_power_schedule` module (enable=true, instance=lupin-host-test, zone=us-central1-a, sa=var).
- `01-design.md` — Decision #2 + §Cost synced to finalized ruling (weekday + suspend + $527 + CUD-dropped).
- `02-vm-downgrade-handoff.md` — scheduler now Lupin-built; remaining = IAM grant (compute.instances.suspend/resume on VM) + zone confirm; + Arnold's resume-burst runbook note + the suspend design-win (RAM snapshot preserves FIFO queues + WebSocketManager singleton, retires 2026-05-30 lose-singleton concern).
- `03-cost-reprice.md` — sub-tasks marked BUILT.
- **F-T1 fix (Tiberius review catch, HIGH):** the pre-existing scale_up/scale_down jobs used `oidc_token` for the Cloud Run **Admin API** PATCH — wrong (403s → min-toggle never flips → warm window silently dead). Flipped BOTH to `oauth_token` + cloud-platform scope (mirrors the VM jobs) in `modules/cloud-run-model-server/main.tf` + fixed the var description. Re-plan: oauth_token=4, oidc_token=0, still 6-add/0-change/0-destroy. Rule: Google management/admin APIs → OAuth access token; OIDC id-token is only for invoking a Cloud Run service.

## NEXT / re-spin instructions

- **Tiberius** runs adversarial review (design↔TF↔cost consistency) → **María** re-verifies findings #1–#4 at source → **commit-held**. (Arnold's with-creds green-bar is the POST-APPLY gate, not this dry pass.) Commit/push NOT mine.
- **Apply stays Rick-gated** (real money + his login). At apply: IAM grant for the VM-power SA (`compute.instances.suspend`/`resume`), confirm VM zone, seed Secret Manager (#6), then the with-creds embedding+STT green-bar.
- A re-spawn of me: re-read this memento + 01/02/03 + the spec thread; work is COMPLETE + dry-green; do NOT re-do; wait for Tiberius review outcome or a new task.
