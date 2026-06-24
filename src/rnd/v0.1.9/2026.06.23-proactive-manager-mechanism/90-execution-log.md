# Lane A — Execution Log: Proactive-Manager Mechanism

**Owner**: Krishna 🦚 (cc-author-mr-radio-3) for Mr. Radio 🦉 · **Store task**: `fcb5dbc0` (P1)
**Branch**: `wip-v0.1.9-2026.06.21-bug-fix-implementation` · **Build plan**: [`01-build-plan.md`](01-build-plan.md) §1
**Design-of-record**: `planning-is-prompting/src/rnd/2026.06.23-proactive-manager-doctrine-and-mechanism.md` (5/5 + rename)

> All commits are **HELD** (`--no-ff`-equivalent direct commits on the working branch, **NO push** — push is Rick's
> word alone). Built in the SHARED tree (Mr. Radio's call), every commit **selective-staged** by explicit path /
> `git apply --cached`; **zero destructive git** (Sam's uncommitted Lane B work lives in the same tree).

---

## Commit ledger

| Phase | Commit | Summary | Tests |
|---|---|---|---|
| **A0** | `f187f0a2` | `gate_class` value `ricks_court` → `operator` everywhere (one-name, no shim) + alembic `b8c9d0e1f2a3` back-catalogue heal | task_store_rules 100% L/B; arbiter_routing 100%; migration 5-test suite |
| **A1a** | `08be880d` | Pure core: `manager_needs_spinup_check` (Face A) + `manager_needs_question_surface` (Face B) + 2 hold-artifact debounce clocks + 3 INI keys/splainer | heartbeat_work_owed + heartbeat_hold BOTH 100% L/B (131 local) |
| **A1b** | `52ad564b` | Wire Face A/B into `_run_heartbeat` (additive) + `query_owed(owner_field=...)` + **FLAG-2 class fix** | task_store_client 100% L/B; 558 heartbeat/stop + 534 arbiter GREEN |
| **A2-store** | `2c8ed5ac` | `urgency` {urgent\|normal\|low} dimension full vertical slice + alembic `c9d0e1f2a3b4` add-col | task_store_rules + routers/tasks 100% L/B; migration 5-test suite; 546 GREEN |

Head of held stack: `2c8ed5ac`. Alembic head: `c9d0e1f2a3b4`.

---

## Phase notes

### A0 — operator rename
- `gate_class` is a free VARCHAR (house style, no PG ENUM) → the rename is app-side enum + an idempotent data
  migration (`UPDATE task_items … ricks_court→operator`; 2 live terminal rows healed). Faithful downgrade.
- **AC-A0.1** met: `grep -rn ricks_court` over lupin code returns ZERO hits **except** the deliberate AC-A0.2
  rejection regression test (a guard that proves the retired value is now rejected MUST name it — the one
  called-out exception).
- **Bonus heal**: `test_alembic_baseline_chain.py` `_HEAD_REVISION` was already STALE (`f6a7b8c9d0e1`; `a7b8c9d0e1f2`
  had landed unrecorded) → that test was RED on the branch before me; updated the head + both missing chain links.

### A1 — Stop-hook debounced self-check (Face A nudge DOWN + Face B surface UP)
- Both predicates GENERALIZE the shipped `6929f4ac` `manager_needs_verification` debounce shape (reuse, not
  reinvent). Routed through `evaluate_work_owed` as two new optional bools → signals `spinup_nudge` /
  `surface_operator_gates`; strongest-first order preserved, existing callers unaffected.
- The two per-manager timestamps (`last_spinup_check_ts`, `last_surfaced_questions_ts`) persist in the **hold
  artifact** → SURVIVE `/clear` (same mechanism as `last_looked_in_on_workers_ts`).
- Face A backlog source = `query_owed(owner_field="accountable_manager")` — **inherently manager-scoped** (a plain
  worker has ~zero rows accountable to itself, so Face A never nudges a non-manager). Store read **fails safe**
  (not-ok ⇒ no nudge). Idle capacity = live delegated workers < `cc session spawn max reviewers` (8).
- **Design note (flagged, not changed)**: the build plan put the thresholds in `lupin-app.ini` (stop.py already
  reads `ConfigurationManager`); I followed it. The sibling `6929f4ac` `verification_threshold_seconds` lives in
  `~/.claude/settings.json` — a minor config-home inconsistency surfaced to Mr. Radio for awareness only.
- **FLAG-2** (Mr. Radio-confirmed): `count_inbound_questions_as_owed` KeyError — a test-mock + live-bridge-inbound
  env-flake class. Found it was BIGGER than the one named test: the same defect hit **42** tests in
  `test_heartbeat_integration.py` once fleet DMs accumulated mid-session. Fixed at the HARNESS level (added the key
  + stubbed the 3 live-IO gatherers → hermetic). `test_pc1_full_chain` + all 42 GREEN.

### A2 — operator-gate minting + urgency tiering
- **Store substrate (DONE)**: `urgency` is a dedicated TIME-SENSITIVITY field (NOT `priority` importance), default
  `normal`, threaded through model → rules → repository → router (create/patch/serialize/filter) → MCP
  (`task_create`/`task_query`). The per-tier filter supports the arbiter's eventual
  `task_query(gate_class=operator, urgency=urgent)`.
- **Arbiter tier-PUSH routing (DEFERRED)**: urgent→interrupt / normal→digest / low→queue lives in `arbiter_job.py`
  + only takes effect after a `:8001` bounce — the SAME Lane-B collision + gated-infra reason that parked A3. It
  rides A3 as one arbiter pass once Lane B (`bc1bc373`) is committed. **Awaiting Mr. Radio's ratify + Lane-B-in
  confirm.**
- gate-clear → halt-re-surface is **already satisfied** by A1 Face B (keys on OPEN operator gates; an answered
  gate drops out) — no extra work owed.

---

## Deferred / parked (NOT in the held stack)

| Item | Why parked | Unblocks when |
|---|---|---|
| **A3** — thin arbiter dark-session backstop | re-touches `arbiter_job.py` (Sam's uncommitted Lane B) + needs `:8001` bounce | Mr. Radio confirms Lane B `bc1bc373` committed |
| **A2 arbiter tier-push routing** | same `arbiter_job.py` + `:8001` gate | rides A3 (one arbiter pass) |
| **A4** — doctrine (`manager-autonomy.md` / `task-store-discipline.md`) | María's planning-is-prompting lane | handoff (not this lane) |

**`:8001` bounce protocol**: STOP + flag Mr. Radio BEFORE any bounce (he sequences it behind in-flight arbiter
work + loops Tiberius). Do NOT restart `:8001` autonomously.

---

## Standing-rule compliance
- Commit + merge are STANDING after green; **PUSH is Rick's alone** — the held stack stays local, surfaced as status.
- Every phase: 100% L/B on changed modules (migrations sit outside the `cosa` coverage denominator but each got a
  dedicated unit suite anyway); unit + integration green; selective-staged; flagged forks to Mr. Radio.
