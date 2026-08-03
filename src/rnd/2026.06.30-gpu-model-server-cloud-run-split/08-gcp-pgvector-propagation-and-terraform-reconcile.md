# 08 — GCP leg of v0.2.0 pgvector migration: terraform reconcile + pgvector propagation assessment

| Field | Value |
|---|---|
| **Date** | 2026-07-07 |
| **Author** | Cheech 🌿 (session `73b97cc6`, SWE-Implementer) under Mr. Radio 🦉 (mgr `17e81460`) |
| **Store task** | `c845346a` (P2) — GCP leg, Rick voice GO ~11:10 EDT ("credentials are fresh and ready to be run") |
| **Mode** | READ-ONLY reconcile + assessment. `terraform apply` / image build+push / deploy are **Manager-gated** (GCP spend = real money). NO apply performed. |
| **Creds** | ADC fresh (`application_default_credentials.json` mtime 2026-07-07 10:05 EDT), account `admin@rickruiz.altostrat.com`, project `hello-world-foo-423219`. |

---

## Part 1 — TERRAFORM RECONCILE

### Sibling task c3fafac5 state — VERIFIED CLOSED (not deferred)

The task briefing said "apply was deferred 2026-06-30, sibling task c3fafac5 — verify its state first." **It was NOT deferred — it was executed and closed 2026-07-01.** Primary artifact: `06-apply-verification-green-bar.md`:
- `lupin-model-server` **live on Cloud Run** (scale-to-zero L4, INTERNAL_ONLY), URL `https://lupin-model-server-um6r4fv7nq-uc.a.run.app`, image `lupin-model-server:0.1.0` (digest `d9b61e81…`).
- Apply outcome `2 added, 0 changed, 1 destroyed`; `Ready=True`; full with-creds green-bar passed (health 200 / embeddings dim=768 / transcribe 200 / bogus-key 401 / public 404).
- The data plane (Secret Manager, Cloud SQL `lupin-pg16-test`, Artifact Registry, IAM, GCS) was already in state from a prior apply.

So the environment is **already converged** — this reconcile is a drift check, not a first apply.

### validate + plan (ran 2026-07-07, fresh ADC, remote GCS state)

```
terraform init -reconfigure -backend-config="bucket=hello-world-foo-423219-tf-state"   → success
terraform validate                                                                     → Success! configuration is valid.
terraform plan -var-file=terraform.tfvars                                              → Plan: 0 to add, 1 to change, 0 to destroy.
```

**The single change is benign provider-noise drift** on the Cloud Run service-level `scaling` block:

```
~ module.cloud_run_model_server.google_cloud_run_v2_service.lupin_model_server
  - scaling {
      - manual_instance_count = 0 -> null
      - min_instance_count    = 0 -> null
    }
```

**Why it is safe:**
- This is the **service-level** `scaling` block (the manual-scaling GA feature), which the GCP API populated with `0/0`. The config never declares it, so terraform wants to null it out.
- The module's `lifecycle { ignore_changes = [template[0].scaling[0].min_instance_count] }` covers the **template-level** scaling (the one the 9am/11pm scheduler owns) — NOT this service-level block, which is why it surfaces.
- Applying it changes **nothing about running behavior**: the service stays scale-to-zero (template scaling min=0 unchanged). **Cost delta = $0.**
- Nothing else drifts: **0 add / 0 destroy**, no Cloud SQL diff, no recreation, no pgvector-related resource.

**Recommendation → RULED (Mr. Radio 2026-07-07): LEAVE IT — no apply.** A functional no-op isn't worth touching prod state. Recorded as **known plan-noise**: `terraform plan` will show this same `0 add / 1 change / 0 destroy` on every run until (if ever) someone applies it; expected, unrelated to the pgvector leg.

**F-T1 regression check (Rio's criterion):** scheduler auth is OAuth-not-OIDC in-tree (`modules/cloud-run-model-server/variables.tf:318`). The fresh plan touches **nothing** in the scheduler resources (they are `count=0` under the default-paused vars) — no OIDC regression introduced. Confirmed clean.

### Monthly cost posture (unchanged by this plan)

Per `04-cost-all-paused-floor.md` / `05-default-paused-terraform-plan.md`: default-paused floor **≈ $10–20/mo** (Cloud SQL retained storage + backups ~$3–5, AR ~$2.80, GCS/Secrets/Scheduler ~$2, VM boot disk ~$1–10; all compute at $0 while paused). This plan adds no resources → **no cost delta**. The DB line is priced explicitly in **§2e** below (Rick's rigor ask 2026-07-07).

---

## Part 2 — PGVECTOR PROPAGATION ASSESSMENT

What the GCP environment needs to mirror the local cutover (backend=postgres, exact-scan keystone), broken into the four surfaces.

### 2a. Database engine — ✅ NO CHANGE NEEDED (Cloud SQL pgvector is native)

The project already ruled this. `docker-compose.yml` lines 5–10 (verbatim):
> *v0.2.0: image swapped stock postgres:16.3-alpine → pgvector/pgvector:pg16 so `CREATE EXTENSION vector` succeeds (LanceDB → pgvector migration). … Cloud-SQL supports pgvector natively → cloud-test/prod compose need no change.*

The local Docker image swap was **only** because `postgres:16.3-alpine` lacks the extension. **Cloud SQL for PostgreSQL 16 ships pgvector as an available extension** — no instance/image change; the terraform `cloud-sql-pg16` module (`google_sql_database_instance … database_version = "POSTGRES_16"`) is already correct.
- **Action needed:** one-time `CREATE EXTENSION IF NOT EXISTS vector;` against `lupin_db_test` (part of the pre-deploy schema step, below).
- **Version caveat (low risk):** Cloud SQL's bundled pgvector may lag local `0.8.4`. Irrelevant here — the exact-scan ruling (migration `e1f2a3b4c5d6`) **dropped the HNSW index** on the keystone, so only the base `vector` type + exact scan is exercised (any pgvector ≥0.1). HNSW-revisit is a post-purge tail (`df51e19a`), not on the GCP critical path.

### 2b. App image — ❌ GAP: registry image predates the pgvector dep-set

| Image | Built | pgvector deps? |
|---|---|---|
| AR `lupin:1.2.0` (newest in registry) | **2026-06-23** | **NO** |
| AR `lupin:1.1.0` | 2026-06-11 | NO |
| local `lupin:1.1.1-pgvector-candidate` (dev+test today) | 2026-07-07 | YES |

The pgvector Python deps — `pgvector==0.4.2` (SQLAlchemy `Vector` type) + `psycopg2-binary==2.9.11` — were declared in the **image-build manifest `pyproject.toml` + `uv.lock`** via commit **`2a2cc63c` on 2026-07-01 19:22 EDT** (commit message: *"declare pgvector==0.4.2 in pyproject.toml + uv.lock (make it durable in the app image)"*), **8 days after** `lupin:1.2.0` was built. (`src/cosa/requirements.txt` also carries `pgvector==0.4.2`, but the app image builds from `pyproject.toml`/`uv.lock`, so `2a2cc63c` is the decisive commit for image contents.) → **No registry app image contains the pgvector dep-set.**

**⚠️ Landmine:** `vector store backend = postgres` is set in `[Lupin: Baseline]` (`lupin-app.ini:543`), which the GCP `[Lupin: Testing]` / `[Lupin: Testing-GCS]` / `[Lupin: Production]` blocks all **inherit**. So the moment the GCP app runs against Cloud SQL, it selects the postgres vector store — and an **old 1.2.0 image would crash** (no `pgvector` lib, no `Vector` type). No live breakage *today* only because the VM/app is paused. **The image MUST be rebuilt+pushed before the GCP app is next brought up.**

**Action taken (2026-07-07) — FRESH BUILD from HEAD, pushed. ✅ EXECUTED.** The image must be a **`docker build` from current HEAD that bakes BOTH the pgvector deps AND the cutover code** (`is_postgres_backend`, the `backend=postgres` INI key, migration `e1f2a3b4c5d6`) — a self-consistent artifact. DEPLOYED artifact = `us-central1-docker.pkg.dev/hello-world-foo-423219/lupin-images/lupin:**1.2.1-pgvector-r3**` @ `sha256:4748ab2a…` (`-r2`/`04316fe6…` was SUPERSEDED by `-r3` for a config_path boot-crash; see Receipts for all three digests + the tag-immutability note).

> **⚠️ CORRECTION (2026-07-07) — a re-tag is NOT sufficient; the image must be a fresh build.** An earlier attempt **re-tagged** the 5-days-old local candidate `a87d3219` (`lupin:1.1.1-pgvector-candidate`) as the AR image, on the reasoning that "the VM runs a bind-mount so only the DEPS need baking; the code rides the on-VM checkout." **That was wrong.** Clayton's post-build probe caught it RED: `a87d3219` was built ~07-02, **before** the cutover commit `0901984d` (07-07), so it carries the pgvector deps ✅ but NOT the cutover code (no `is_postgres_backend`, no `backend=postgres` INI, no `e1f2a3b4c5d6`). The local `294/0` integration was green only because `docker-compose` bind-mounts host `./src` over the baked image — **it validated host code, not the artifact** (host-code-green ≠ artifact-green). **Rulings that stand (Mr. Radio):** (1) the deploy path is a **self-consistent image or nothing** — the VM-bind-mount "code rides the checkout" path is REJECTED; the image must bake the code. (2) A **baked-image probe pre-push is now MANDATORY doctrine** (pull-by-digest + verify baked code/INI/migration, not just deps). The corrected `1.2.1-pgvector-r2` build bakes the code + deps and passed the structural probe (built-today · `is_postgres_backend` · INI=postgres:543 · `e1f2a3b4c5d6`).

### 2c. Config / INI — ✅ NO CHANGE NEEDED (inheritance already carries it)

`vector store backend = postgres` in `[Lupin: Baseline]` is inherited by every GCP block. No per-env INI edit required. (This is the same fact that makes 2b a landmine — inheritance is doing the right thing, so the image just has to be able to honor it.) Confirm the GCP app's `LUPIN_CONFIG_MGR_CLI_ARGS` selects a block that inherits Baseline (it does: `Testing` / `Testing-GCS`).

### 2d. Schema + data — the GCP `lupin_db_test` store

- **Schema:** the `cloud-sql-pg16` module comment states schema is created by "the pre-deploy Alembic step (NOT auto-on-startup)". Running `alembic upgrade head` against `lupin_db_test` produces the identical 25-table schema **including** the `e1f2a3b4c5d6` DROP-INDEX migration → vector-store tables **without** the keystone HNSW index, matching local exactly. Must also run `CREATE EXTENSION vector` first (2a).
- **Data — RULED (Mr. Radio 2026-07-07, Rick's frame): option (i) empty / fixture-managed** for the TEST env. Local `lupin_db_test` is fixture-managed (`clean_test_db` truncates per run); the GCP test DB mirrors that — tests seed their own rows, no backfill. The 202k-row corpus backfill (the offline utility `2026.07.02-lane-d-p4-offline-backfill-utility.md`) is a **PROD-cutover** concern for a future prod leg ("memory is the product" applies to prod, not test fixtures) — explicitly OUT of this test-env scope.

### 2e. DB placement + explicit monthly cost (Rio's criterion + Rick's rigor ask)

**The ratified $527/mo model (`03-cost-reprice.md`) prices ONLY the Cloud-Run split + e2 app VM — it has NO Postgres line.** Rio held this plan to naming the DB placement explicitly and re-stating the delta vs $527; Rick (voice 2026-07-07) wants the DB line priced with a **stated number + cited SKU** "for the sake of being rigorous," even though he expects it nominal.

**Placement = Cloud SQL (ratified, ALREADY provisioned & wired).** Ground-truth receipt: the terraform plan refresh reported `module.cloud_sql.google_sql_database_instance.pg16[0]: Refreshing state... [id=lupin-pg16-test]` — a live existing resource, **not a create**. Live probe: `gcloud sql instances list` → `lupin-pg16-test · POSTGRES_16 · db-custom-2-7680 · ALWAYS · RUNNABLE`. The cloud-test app reaches it via the `lupin-cloudsql-proxy` sidecar (runbook §0). So Cloud SQL is not a hypothetical new line — it exists, is priced below, and **pgvector adds $0 to it** (a free in-engine extension; tier unchanged).

**Cited SKU + numbers** (Cloud SQL Enterprise PostgreSQL, us-central1, ZONAL; rates sourced in `04-cost-all-paused-floor.md`: **$0.0413/vCPU-h + $0.007/GB-h**; tier `db-custom-2-7680` = 2 vCPU + 7.5 GB):

| DB line state | Monthly $ | Note |
|---|---|---|
| **Cloud SQL RUNNING 24/7** (compute) | **$98.63** | 2 × $0.0413 × 730 + 7.5 × $0.007 × 730. **This is what it costs RIGHT NOW** — the instance is `ALWAYS`/RUNNABLE as probed. |
| + storage (SSD ~10 GB) | ~$1.70 | $0.17/GB-mo |
| + backups (7 auto + PITR) | ~$1–3 | small DB |
| **Cloud SQL weekday-warm** (~304 runnable-h/mo) | **~$41** compute (+~$4 storage/backup = **~$45**) | Derived: hourly compute rate = 2×$0.0413 + 7.5×$0.007 = **$0.1351/h**; VM weekday window 09:00–23:00 EDT Mon–Fri = 14h×5 = 70h/wk ≈ **304 h/mo** → $0.1351 × 304 = **$41.07**. If the DB mirrors the ratified VM-warm schedule (03-cost-reprice's operative model), this is the expected DB compute. |
| **Cloud SQL STOPPED** (`activation_policy=NEVER`) | **~$4** | compute → $0; only storage + backups retained. The Option-A paused-default steady state. |
| **pgvector propagation delta** | **$0.00** | free extension, no tier change, instance already in state |

**Derived monthly number (Rick's rigor ask, stated not hand-waved):** the module provisions tier **`db-custom-2-7680` (2 vCPU / 7.5 GiB, ENTERPRISE, ZONAL)** at **$0.1351/compute-hour**. At 24×7 that is **$98.63/mo** (≈$100 list, confirming Rio's estimate); under the ratified weekday-warm schedule (~304 runnable-h/mo) it is **~$41/mo** compute + ~$4 storage/backup = **~$45/mo**; fully stopped it is **~$4/mo**.

**Delta vs the $527 model:** the DB line is **additive** to the $527 (which omitted Postgres). Expected add under the ratified weekday-warm schedule = **+~$45/mo** (→ total ≈ **$572/mo**); **+~$4/mo** if kept stopped-when-idle; **+$98.63/mo** worst-case 24×7. → **pgvector-attributable delta = $0.00; the DB line itself is ~$4 (paused) → ~$45 (weekday-warm) → ~$102 (24×7 full month).**

**Operator note (not my action):** the instance is currently **RUNNABLE** — if it is not actively being used, `gcloud sql instances patch lupin-pg16-test --activation-policy=NEVER` drops it from ~$98.63 → ~$4/mo (lifecycle `ignore_changes` keeps it stopped across future applies).

**Co-locate alternative (priced honestly, per Rio's steer to evaluate cost-conservative first):** run pgvector Postgres as a **container on the e2 app VM** (like local `pgvector/pgvector:pg16`) instead of Cloud SQL. Cost: **~$0 additional compute** (rides the VM already priced in $527; DB suspends WITH the VM on the weekday schedule — matches the suspend-preserves-state design), trivial disk (option (i) = empty/fixtures, so the "202k rows + HNSW disk" concern does **not** apply to a test env). **Savings ≈ the full DB line (~$4–$98/mo).** **BUT** it is a real architecture change, not free engineering: drop the `cloud-sql-pg16` module + the `lupin-cloudsql-proxy` sidecar, add a pg container to `docker-compose.cloud-test.yml`, and rework `database.py`'s Cloud SQL unix-socket contract. Cloud SQL is already built, wired, and in state.

**Recommendation:** for the near-term test-env propagation, **stay on Cloud SQL** (zero rework, already wired via the proxy sidecar) and reach the nominal cost by **stopping it when idle (~$4/mo)**. Revisit co-locate only if the DB line proves to matter — it is a cost-optimization, not a correctness need. Rio/Rick to rule if they want the co-locate path instead.

---

## Part 3 — PROPOSED IMPLEMENTATION PLAN (execution gated on Manager + Rick)

Ordered; every outward-facing step (★) requires the Manager's word before execution.

1. **Terraform reconcile** — ★ RULED **LEAVE IT** (no apply; §1 known plan-noise). No action.
2. ★ **Build app image** from current HEAD → tag **`lupin:1.2.1-pgvector`** (ruled; no `:latest`) → `docker push` to AR `lupin-images`. **GATE-WORD GIVEN (Rio PASS + Mr. Radio 2026-07-07): push-and-stop** — no deploy, no VM bring-up. (ADC-token `docker login`; deps-layer rebuild — see §2b.) Ping Clayton for the post-build import probe on push.
3. Bring Cloud SQL `lupin-pg16-test` RUNNABLE — **already RUNNABLE** as probed (`ALWAYS`); no action unless it has since been stopped.
4. **Pre-deploy schema step** against `lupin_db_test`: `CREATE EXTENSION IF NOT EXISTS vector;` then `alembic upgrade head`. **Verify `alembic current` == `e1f2a3b4c5d6`** (the DROP-HNSW head — NOT the prior head `d0e1f2a3b4c5`; stopping at that prior head would leave the keystone HNSW index in place and BREAK exact-scan parity). Also verify `SELECT extversion FROM pg_extension WHERE extname='vector';`. Run via the cloudsql-proxy sidecar / IAP from the VM.
5. **Data** — RULED option (i) empty/fixture (§2d). No backfill; nothing to do.
6. ★ **Deploy to the VM surface (RESOLVED — see below):** update the on-VM checkout to the migrated code (via `lupin-wip.bundle`), move the `docker-compose.cloud-test.yml` app tag → `1.2.1-pgvector`, recreate `lupin-rest-cloud-test`. `LUPIN_CLOUD_BACKED=true` + cloudsql-proxy already wired; config inherits `backend=postgres`.
7. **Green-bar verify** on GCP (via IAP tunnel `:6999`): app `/health`, a live calculator pipeline (exercises the exact-scan keystone read path), `backend==postgres` in-container. Mirror the local cutover's §5 verify tiers.

**RESOLVED — the live GCP app surface is the VM `lupin-host-test`, NOT Cloud Run.** Ground-truth probes (2026-07-07, fresh ADC):
- `gcloud run services list` → a Cloud Run service named **`lupin` exists but is `Ready=False`** — a **dead 2025-11-12 stub**: image `gcr.io/hello-world-foo-423219/lupin:latest` (the OLD gcr.io registry, not Artifact Registry), revision `lupin-00001-mmd`, `HealthCheckContainerError` (never listened on PORT 8080). It is **abandoned cruft**, not the current surface. `src/scripts/cloud-run-deploy.sh` (`gcloud run deploy`) is the stale script that produced it.
- The authoritative current surface is the **VM `lupin-host-test`** running `docker-compose.cloud-test.yml` (`lupin-rest-cloud-test` app + `lupin-model-server-cloud-test` + `lupin-cloudsql-proxy`), per runbook `2026.06.15-new-deployer-runbook-gcp-cloud-test.md`. Currently **TERMINATED** (paused; still `g2-standard-8` — the VM-downgrade handoff `02-vm-downgrade-handoff.md` is not yet applied). No live app breakage from the pgvector landmine while it is down.
- **Cleanup candidate (flag, not action):** the dead Cloud Run `lupin` service + the stale `cloud-run-deploy.sh` could be deleted to remove the surface ambiguity — Manager/Rick's call, out of this task's scope.

---

## Part 4 — BRING-UP EXECUTION PLAN (post-push, 2026-07-07)

**Authority (Rick voice ruling 2026-07-07, relayed by Mr. Radio):** GCP bring-up is **no longer Rick-gated** — "do not gate me on this, simply inform me." Operative chain: **Mr. Radio's gate-word executes each ★ step**; Rick receives **inform-only** milestone cards (never an ask); María's tripwire flags any GCP mutation lacking Mr. Radio's word. **Rick's cost-rigor standard is retained** (stated numbers + cited SKUs, even though the gate moved).

**Preconditions:** ✅ image pushed — `lupin:1.2.1-pgvector` @ `sha256:ec9957dc635f279be5a07ddca04b97451b5fac0f8b969b3bb896157e96ffaeab`; ✅ Cloud SQL `lupin-pg16-test` RUNNABLE (Rick ruled **LEAVE-RUNNABLE**, bring-up expected this week); ✅ data plane in state. **Gate on Clayton's post-build import probe (GREEN) before step 2.**

| # | Step | Mutation? | Detail |
|---|---|---|---|
| 1 | **Terraform apply** | — | **NONE required** (aligns with standing ruling A = LEAVE IT). The ONLY resource a `terraform apply` would touch is `module.cloud_run_model_server.google_cloud_run_v2_service.lupin_model_server` — the **service-level `scaling` block** (`min_instance_count 0→null`, `manual_instance_count 0→null`), a functional no-op (stays scale-to-zero). **Nothing else drifts**: Cloud SQL, secrets, AR, IAM, GCS all `0 change` (already in state). The VM lifecycle lives in the standalone `terraforming-vms` stack, not here. So bring-up needs **no `terraform apply` on this stack.** |
| 2 | **Start the VM** | ★ | `gcloud compute instances start lupin-host-test --zone=us-central1-a`. ⚠️ VM is still **g2-standard-8 + 1×L4** (un-downgraded) — see cost line + the downgrade decision. |
| 3 | **Pre-deploy schema** (Cloud SQL `lupin_db_test`, via cloudsql-proxy / IAP) | — (DDL on already-running DB) | `CREATE EXTENSION IF NOT EXISTS vector;` then `alembic upgrade head`. **Verify** `alembic current` == `e1f2a3b4c5d6` (drop-HNSW head, NOT prior `d0e1f2a3b4c5`) + `SELECT extversion FROM pg_extension WHERE extname='vector';`. |
| 4 | **Deploy the app** | ★ | Set `docker-compose.cloud-test.yml` app to **`1.2.1-pgvector-r3`** @ digest `sha256:4748ab2a…` (fresh build from committed HEAD `c2b02065`; code + deps + `/src`-relative config baked, boots on its own env — §2b + d57f38bd); recreate `lupin-rest-cloud-test`. `LUPIN_CLOUD_BACKED=true` + cloudsql-proxy already wired; config inherits `backend=postgres`. ⚠️ **CORRECTED-AT-EXECUTION (2026-07-07)** — the compose STILL bind-mounts `- ./src:/var/lupin/src` (verified live), which SHADOWS the baked `-r3` code with the on-VM checkout (found at pre-cutover `8f4a36f`). So "bump the tag + `up -d`" alone is INSUFFICIENT — it would run stale pre-cutover code (no `backend=postgres`, no auto-migrate). **Opt-1 executed (Mr. Radio ruling):** REMOVE the `- ./src:/var/lupin/src` mount so the self-consistent baked `-r3` IS the runtime; pin `LUPIN_IMAGE` to the `-r3` DIGEST; `docker compose up -d` recreate. **Decision-3 mount model SUPERSEDED for this leg.** Post-deploy `docker inspect` Mounts MUST show `/var/lupin/src` is NOT a bind (rides the image). See **Part-4 Execution Receipts** below. |
| 5 | **Green-bar verify** (IAP tunnel `:6999`) | — | `/health`; a live calculator pipeline (exercises the exact-scan keystone read path); `backend==postgres` in-container. Mirror the local cutover §5 tiers. |

> **⚠️ DEPLOY-TARGET LOCK.** Deploy ONLY **`lupin:1.2.1-pgvector-r3`** @ `sha256:4748ab2a789fd3558e801ccfb01e1032c08b9737936f9d393aebf9d754416207` (fresh build from committed HEAD `c2b02065`; boots self-consistently on its baked env — `BACKEND=postgres`). **NEVER deploy the two superseded predecessors:** `1.2.1-pgvector` (`ec9957dc`, stale pre-cutover code) and `1.2.1-pgvector-r2` (`04316fe6`, absolute-config_path boot crash) — both SUPERSEDED-NEVER-DEPLOYED (§2b + Receipts). Pin the **`-r3` digest** in `docker-compose.cloud-test.yml`, not just the tag.

### Cost line (Rick's rigor standard — stated numbers + cited SKUs)

Live-probed 2026-07-07: `lupin-host-test` = **g2-standard-8 · nvidia-l4 ×1 · TERMINATED**.

| Item | Rate (SKU) | Weekday-warm (~304 h/mo) | 24×7 | Note |
|---|---|---|---|---|
| **Cloud SQL** `db-custom-2-7680` | $0.1351/compute-h (§2e) | ~$45/mo | **~$98.63/mo** | Rick ruled LEAVE-RUNNABLE → 24×7 this week |
| **VM — e2-standard-8** (downgrade target) | **$0.2680/h** (03-cost-reprice, sourced) | **~$81/mo** | ~$196/mo | CPU-only; no GPU needed for pgvector |
| **VM — g2-standard-8 + L4** (current, un-downgraded) | ≈ **$0.71/h** (bundled-L4 family; est. — confirm exact at apply) | **≈ $215/mo** | ≈ $518/mo | The L4 is **pure waste** for a pgvector bring-up (inference is on Cloud Run) |
| Cloud Run model-server | scale-to-zero | ~$0 | ~$0 | idle |
| **pgvector-attributable delta** | — | **$0.00** | **$0.00** | free in-engine extension; same image tier |

**VM-downgrade DECISION (for Mr. Radio's gate-word):**
- **(A) Bring up on g2 now** — fastest; but burns ≈ **+$134/mo weekday-warm** (~$215 vs ~$81) on an idle L4. Acceptable IF bring-up is genuinely this-week + short-lived.
- **(B) Do the e2 VM-downgrade first** (`02-vm-downgrade-handoff.md`, in the standalone `terraforming-vms` stack) — saves ≈ $134/mo, but adds a cross-repo prerequisite before bring-up.
- **Recommendation:** if the week-long bring-up is a smoke/validation window → **(A)** (speed over ~$134/mo for a few days ≈ a few dollars). If it becomes sustained → **(B)** first. Flagging for your gate-word; I do not execute either without it.

### Rollback stanza

Bring-up starts from a **fully-paused** state (VM `lupin-host-test` TERMINATED, no live app, Cloud SQL running but only fixture data), so rollback is **state-not-image** and near-zero-risk:

- **Primary rollback = stop the VM.** `gcloud compute instances stop lupin-host-test --zone=us-central1-a` returns the environment to its exact pre-bring-up state (TERMINATED, no live app). Nothing was serving, so there is no traffic to drain and no data to lose.
- **⚠️ Do NOT roll the app image back to `1.2.0`.** The config inherits `vector store backend = postgres` (`[Lupin: Baseline]`, §2c), and `1.2.0` predates the pgvector deps — an old image + `backend=postgres` is exactly the crash-landmine (§2b). The only safe app image on GCP is **`1.2.1-pgvector-r3`** (@ `sha256:4748ab2a…`) — the DEPLOYED, self-consistent build; **NEVER `-r2`/`04316fe6`** (the config_path boot-crash build, SUPERSEDED-NEVER-DEPLOYED — see Deploy-Target Lock + Receipts). App-level rollback is therefore "stop the VM," not "downgrade the tag."
- **Schema rollback (low-stakes, test DB is empty/fixture).** `alembic downgrade -1` reverses `e1f2a3b4c5d6` (a reversible DROP-INDEX migration — the downgrade re-creates the keystone HNSW index). `CREATE EXTENSION vector` is additive/harmless — leave it. Since the GCP `lupin_db_test` carries no real corpus (option (i)), schema state is not load-bearing; a full reset is `DROP`/recreate the fixture tables.
- **Cloud SQL:** untouched by rollback (Rick ruled LEAVE-RUNNABLE); stopping it is a separate operator cost lever (`--activation-policy=NEVER`), not a bring-up rollback step.
- **Terraform:** nothing applied → nothing to revert.

**Status:** ✅ **COMPLETE** — Part-4 bring-up EXECUTED 2026-07-07 (Cheech-successor, under Mr. Radio's D1/D2/D3 rulings). All 5 steps green; deploy `-r3` @ `sha256:4748ab2a…`; VM `lupin-host-test` **TERMINATED** (default-paused). Superseded artifacts `ec9957dc` + `04316fe6` never deployed. See **Part-4 Execution Receipts** below.

---

## Part 4 — EXECUTION RECEIPTS (2026-07-07, VERBATIM per Mr. Radio's D1 condition)

**Evidence-holder:** Clayton 😎 (designated). Gate D1 met by Cheech-successor's firsthand in-container pass + Clayton's LOCAL 7/7 double-green on the exact deployed digest `4748ab2a`. Clayton's live-VM re-derive was classifier-blocked (his session lacked Rick's 4-rule set), so the gate = artifact-proof (Clayton local 7/7) + deploy-wiring-proof (Cheech Mounts-inspect + in-container head/ext/backend) — Mr. Radio ruling D1=(b).

**Finding ① (VERIFIED, sanctioned):** the sanctioned compose deploy AUTO-MIGRATES at boot — `src/lupin_app/main.py:444` calls `run_migrations_to_head()` in the app lifespan → `cosa/rest/db/auto_migrate.py:198` `alembic upgrade head`; migration `d0e1f2a3b4c5:70` runs `CREATE EXTENSION IF NOT EXISTS vector` FIRST then builds the vector tables. So step 4 covers ALL of step 3 (extension + schema + head), fail-loud, no hand-SQL → **GOTCHA #6 mooted** for this leg (no standalone DB-write command). **The runbook `2026.06.15-new-deployer-runbook-gcp-cloud-test.md` "Known Issue #2 (no auto-migrate on startup)" is STALE** — auto-migrate was wired in-process (not the shell CMD).

**Deploy (step 4, Opt-1):**
```
pull  us-central1-docker.pkg.dev/hello-world-foo-423219/lupin-images/lupin@sha256:4748ab2a789fd3558e801ccfb01e1032c08b9737936f9d393aebf9d754416207  → Downloaded
compose edit: removed `- ./src:/var/lupin/src`  (backup docker-compose.cloud-test.yml.bak-r3deploy)
env edit:     LUPIN_IMAGE = <AR>/lupin@sha256:4748ab2a…  (backup cloud-test.env.bak-r3deploy)
docker compose up -d → Recreated lupin-rest-cloud-test (proxy + model-server untouched, healthy)
```

**Boot auto-migrate log (verbatim):**
```
Running database auto-migration (alembic upgrade head)...
[auto-migrate] Running 'alembic upgrade head'...
[auto-migrate] Database is at migration head.
✓ Database schema is at migration head.
✓ LanceDBSolutionManager initialized (postgres backend, cache bypass)
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:7999
```
(Pre-deploy DB head was `b2c3d4e5f6a7`; walked forward → `d0e1f2a3b4c5` → `e1f2a3b4c5d6`.)

**Green-bar verification (verbatim, D2 channel = docker-exec-local per runbook §6):**
```
HEALTH_HTTP=200 BODY={"status":"ok","timestamp":"2026-07-07T18:59:03..."}
ALEMBIC_HEAD=['e1f2a3b4c5d6']
VECTOR_EXT=['0.8.1']
VS_TABLE_input_and_output=['input_and_output']
BACKEND=postgres is_postgres=True         # config block resolved LIVE: Testing-GCS → Development → Baseline, INI from /var/lupin/src (baked)
# keystone exact-scan read path:
KNN_EXACT_SCAN_EXECUTED_OK rows=0          # get_knn_by_input() → dot_topk `<#>`; empty-by-design fixture (Ruling C)
INPUT_AND_OUTPUT_ROWCOUNT=0
INPUT_AND_OUTPUT_INDEXES=['input_and_output_pkey']   # NO HNSW → e1f2a3b4c5d6 drop-index landed semantically
# Mounts proof (rider-4): /var/lupin/src is NOT a bind — rides the -r3 image:
bind   /mnt/lupin-data/lupin/io            -> /var/lupin/io
bind   /mnt/lupin-data/lupin/src/conf/keys -> /var/lupin/src/conf/keys
volume lupin_cloudsql-socket               -> /cloudsql
running image digest = sha256:4748ab2a789fd3558e801ccfb01e1032c08b9737936f9d393aebf9d754416207
```

**VM stop (default-paused rider):** `gcloud compute instances stop lupin-host-test` → `describe --format='value(status)'` → **TERMINATED** (Mr. Radio verified independently from his session).

**Ephemeral-snapshot note (Mr. Radio flag):** boot shows a `[Local Backend] Using local path: .../lupin.lancedb` line beside `LanceDBSolutionManager initialized (postgres backend, cache bypass)` — the legacy-named manager runs postgres with cache bypass; the lancedb handle is an ephemeral solution-snapshot path (writes into the container layer, lost on recreate). **Acceptable-by-design for the empty fixture test DB.** A future PROD compose decision must handle snapshot persistence deliberately; Tiffany's teardown lane renames `LanceDBSolutionManager → SolutionSnapshotManager`, which will stop the boot line mis-stating its backend.

### Deferred follow-ups (non-blocking, → Rick's return, ~2026-07-07 20:30)
1. **IAP `:7999` firewall rule** — the browser tunnel (`gcloud compute start-iap-tunnel … 7999 :6999`) fails `4003: failed to connect to backend`: the IAP ingress firewall opens only `:22` to IAP's range (35.235.240.0/20), not `:7999`. The app IS host-published (`docker-proxy 0.0.0.0:7999`, host-local `/health` 200) — this is purely a **human-browser-access** gap; the automated §6 validation (docker-exec-local) is green. Adding the rule is a gated GCP mutation (Rick's word).
2. **Authenticated write-path calc E2E** — the local cutover §5 "calculator live-pipeline smoke" needs a seeded user + job-submit (GOTCHA #6 classifier-gated cloud-DB writes) on the empty fixture DB, where a calc can only prove fresh-generation (the retrieval/keystone read path is already proven non-gated, returning 0 by construction). Rick's call on seeding a test user; marginal signal on empty data.

---

## Receipts (primary artifacts)

- **AR push (2026-07-07) — THREE digests, ONE LIVE (two structural probe catches):**
  - ❌ `sha256:ec9957dc…` on `lupin:1.2.1-pgvector` — **SUPERSEDED-NEVER-DEPLOYED.** Re-tag of 5-days-old `a87d3219`; had deps but NOT the cutover code (Clayton probe RED — bind-mount-shadowed integration, §2b).
  - ❌ `sha256:04316fe60070e2d4963cf26d74423528a7154bb126a96417abbecb6b00b92f09` on `lupin:1.2.1-pgvector-r2` — **SUPERSEDED-NEVER-DEPLOYED.** Fresh build (id `93e1d549`) that fixed the staleness, but Clayton's Layer-2e probe caught the pre-existing `Dockerfile:304` absolute-config_path boot crash on the baked env (bug `d57f38bd`).
  - ✅ `sha256:4748ab2a789fd3558e801ccfb01e1032c08b9737936f9d393aebf9d754416207` on `lupin:1.2.1-pgvector-r3` (size 11011) — **LIVE / CORRECT / DEPLOY THIS.** Fresh build (id `e9104463`) from committed HEAD `c2b02065` (the `d57f38bd` `/src`-relative fix). **Clayton 7/7 DOUBLE-GREEN** (local + pulled-by-digest, incl. Layer-2e baked-env boot → `BACKEND=postgres`, no path doubling).
  - **AR tag immutability is ENABLED** on `lupin-images` — a push to an existing tag fails. Every corrected image needs a fresh tag (`-r2`/`-r3`); superseded digests stay orphaned → flag for AR cleanup later (zero urgency). **Operational rule: every future image push needs a fresh unique tag.**
  - All pushes ran under Rick's repo-level `Bash(docker push us-central1-docker.pkg.dev:*)` allow-rule + his explicit execute word. Fix commit `c2b02065` reviewed+APPROVE by Mr. Radio.
- Live VM probe: `lupin-host-test` = g2-standard-8 · nvidia-l4×1 · TERMINATED (un-downgraded).
- `terraform validate` → Success; `terraform plan` → `0 add / 1 change / 0 destroy` (service-scaling null-drift), ran 2026-07-07 from `src/terraform/envs/test/` with fresh ADC + remote GCS state.
- Registry listing: `gcloud artifacts docker images list …/lupin-images` → `lupin:1.2.0` (2026-06-23), `1.1.0` (2026-06-11), `lupin-model-server:0.1.0` (2026-07-01).
- pgvector dep add to the image-build manifest: commit `2a2cc63c` 2026-07-01 19:22 EDT (`pyproject.toml` + `uv.lock`; `src/cosa/requirements.txt` also carries it).
- App-surface ground truth (2026-07-07): `gcloud run services list` → `lupin` service `Ready=False` (dead 2025-11-12 `gcr.io/…/lupin:latest` stub, `HealthCheckContainerError`); `gcloud compute instances list` → `lupin-host-test` TERMINATED (g2-standard-8); `gcloud sql instances list` → `lupin-pg16-test` POSTGRES_16 `db-custom-2-7680` ALWAYS RUNNABLE.
- Cloud SQL already in state (not a create): plan refresh `module.cloud_sql.google_sql_database_instance.pg16[0]: id=lupin-pg16-test`.
- INI: `vector store backend = postgres` at `lupin-app.ini:543` (`[Lupin: Baseline]`, inherited by GCP blocks).
- docker-compose.yml:5–10 — "Cloud-SQL supports pgvector natively → cloud-test/prod compose need no change."
- Sibling apply closure: `06-apply-verification-green-bar.md` (c3fafac5 executed 2026-07-01, service live).
