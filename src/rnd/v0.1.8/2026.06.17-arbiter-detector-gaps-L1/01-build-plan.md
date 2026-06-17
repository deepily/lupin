# L1 — Arbiter Detector Gaps: blocked-on-user / done awareness (Build Plan)

**Date**: 2026-06-17 · **Author**: Tiberius 👑 · **Status**: PLAN (investigate-first complete; for builder)
**Lane**: L1 of the unified-task-store follow-up build (Mr. Radio's plan
`src/rnd/v0.1.8/2026.06.17-unified-task-store-followups-plan.md` §B + lane table). Rick-ratified
2026-06-17 (Decision #1: **full 3-part fix**). Task `e02e22b9` (P1, owner tiberius).
**Coordination**: Mr. Radio owns L2/L3/L4 (no file overlap — L1 is `heartbeat_arbiter/*` only).
**HELD, never push; deploy = bounce `:8001` after merge.**

---

## 1. Problem (observed live overnight 2026-06-17)

The arbiter's two escalation detectors fire repeating false alarms at Rick whenever a manager is
**finished** or **legitimately blocked on Rick**, because neither detector knows the difference
between "present-but-not-acting" and "correctly waiting":

- **D4 MANAGER-DOWN** (`_check_manager_acks`, `manager_ack_window_seconds=600`): a manager is TAPPED
  when its *crew* needs attention (`_tap_managers` → `_last_tap_at[mgr]=now`). The tap is ACK'd by
  liveness = commons-activity ∪ bridge-mtime. A manager **idle-waiting on Rick** makes no tool calls
  (no bridge bump) and posts nothing to commons → no liveness since tap → at 600s it false-escalates
  **MANAGER-DOWN** to Rick, even though it is correctly blocked.
- **D3 WHOLE-FLEET-STALL** (`_check_fleet_stall`, `fleet_stall_window_seconds=1800`): gated by
  `_has_live_owed_work`, which counts any session that is `alive` AND `state ∈ {working,stuck,holding}`.
  A manager in **`holding`** (legitimately blocked) is alive+holding → counts as live owed work →
  no progress for 1800s → false **WHOLE-FLEET-STALL** to Rick.

Relates to dropped bug `332af094`. The detectors have **zero notion of done or blocked-on-user**.

## 2. Investigation findings (current predicates — grounded)

- `fleet_data_model.build_fleet_view` builds the per-session view from **heartbeat events ∪
  commons_who ∪ bridges** — it carries `state`, `holding_on`, `alive`, `stuck`, etc. but **NO store
  fields** (`gate_class`, `blocked_by`, owed-count). `holding_on` = the hook's hold `awaiting` value
  (e.g. `"user:rick"`, `"peer:X"`, `"none"`); `last_task_transition_ts` arrives via the
  `task_transition` heartbeat beacon, NOT a live store query.
- `_has_live_owed_work( fleet_view )` (arbiter_job ~1632): `any(alive AND state ∈
  {working,stuck,holding})`. ← stall gate.
- `_check_fleet_stall` (~1661): escalates once/episode when the progress signature is unchanged ≥1800s
  AND `_has_live_owed_work`.
- `_check_manager_acks` (~1474): per `_last_tap_at` manager, ACK on `max(commons, bridge_mtime)`;
  escalate MANAGER-DOWN once per un-acked tap after 600s of no liveness.
- `_tap_managers` (~1363): taps on crew attention-need, not the manager's own owed state.

**The arbiter does not query the store per-manager today.** Adding that read is the crux of the fix
and is architecturally correct — the arbiter is reader #2 of the "one store, three readers" design.

## 3. Design — the full 3-part fix

### 3.0 New seam: a swallow-safe per-poll store read (injected)
- Add an **injected** `owed_work_fn` (default → the task-store client `query_owed`-style read) that,
  given a persona, returns its **non-terminal** owed items (id, status, gate_class, blocked_by).
- **Observer invariant**: any store hiccup is swallowed → returns `None`; a `None` result means
  "store unknown" and must **fail SAFE** (fall back to today's behavior / corroborate with
  `holding_on`), never crash the poll and never silently suppress a real escalation.
- **One read per poll** for the set of managers under evaluation (batch/cache), not per-manager-per-detector.
- Classify each manager once per poll into: `BLOCKED_ON_USER` · `DONE` (owed-count 0) · `ACTIVE`.
  - `BLOCKED_ON_USER` ⇔ every non-terminal owed item is `gate_class=ricks_court` OR
    (`status=blocked` AND `blocked_by` contains `{kind:"user"}`).
  - `DONE` ⇔ no non-terminal owed items.
  - Degrade-safe corroboration when the store read is `None`: treat `holding_on` starting `"user:"`
    as a blocked-on-user hint (best-effort only; never the sole basis for suppressing).

### 3.1 Part 1 — blocked-on-user exclusion
- **Stall**: `_has_live_owed_work` (or a wrapper) excludes managers classified `BLOCKED_ON_USER`
  from the "live owed work" set — a fleet whose only live owed work is Rick-gated is NOT a stall.
- **Tap-ACK / MANAGER-DOWN**: in `_check_manager_acks`, a `BLOCKED_ON_USER` manager is **not**
  escalated MANAGER-DOWN; instead emit at most **ONE** "awaiting Rick" advisory (not a repeating
  MANAGER-DOWN loop). Reuse the existing escalate-once flag pattern.

### 3.2 Part 2 — done-aware suppression
- A manager classified `DONE` (owed-count 0) is not tap-ACK'd as if it owes work; if genuinely
  idle-done, emit **ONE** "consider reaping" advisory, not a repeating escalation. (The stall path is
  already partly done-safe because an idle manager's `state` is `"idle"` ∉ {working,stuck,holding};
  make the tap-ACK path match.)

### 3.3 Part 3 — tap-ACK window vs loop cadence
- Reconcile the 600s `manager_ack_window_seconds` so it cannot out-pace a sane management loop:
  either (a) honor the same `BLOCKED_ON_USER`/`DONE` exclusions on the tap-ACK path (preferred — makes
  the window irrelevant for correctly-waiting managers), and/or (b) widen/parameterize + DOCUMENT the
  window. Cross-ref memory `reference_arbiter_staleness_threshold_loop_cadence` (mgr loop must stay
  < the staleness floor). Document the final cadence contract in the doc.

### 3.4 Reconcile held `9694fb11` (bridge-mtime implicit tap-ACK)
- Mr. Radio handed over held branch `fix-9694fb11-arbiter-false-manager-down @255a90e2`
  ("bridge-mtime is an implicit tap-ACK"). **The working-tree `_check_manager_acks` ALREADY contains
  the bridge-mtime union + cites "bug 9694fb11" (~lines 1511-1520).** FIRST STEP for the builder:
  **verify the merge/commit state** — is the bridge-mtime tap-ACK already on HEAD, uncommitted on the
  working tree, or only on the `9694fb11` branch? Do NOT destructive-git the shared tree (peers' held
  work). Reconcile so L1 SUPERSEDES `9694fb11` as **one coherent arbiter change** — no double-apply,
  no shim. Reproduce-not-trust on the branch before adopting.

## 4. Scope / files
- `src/cosa/agents/heartbeat_arbiter/arbiter_job.py` — `_check_manager_acks`, `_check_fleet_stall`,
  `_has_live_owed_work` (+ a small classifier helper + the injected `owed_work_fn` seam).
- `src/cosa/agents/heartbeat_arbiter/fleet_data_model.py` — only if the classifier needs a view field;
  prefer keeping the store classification in `arbiter_job` so `fleet_data_model` stays a pure
  liveness/state transform.
- No edits to L2/L3/L4 files.

## 5. Acceptance criteria
- 100% L/B/F on the **changed surface**, including every new exclusion branch: `BLOCKED_ON_USER`
  suppresses stall + MANAGER-DOWN (advisory-once instead); `DONE` suppresses tap-ACK (reap-advisory-once);
  store-read `None` fails SAFE (preserves today's escalation, never silently suppresses); the
  degrade-safe `holding_on` corroboration path.
- Unit tests with a mocked `owed_work_fn` covering: all-ricks_court owed → suppressed; mixed
  (one normal owed item) → NOT suppressed (still escalates); owed-count 0 → done-advisory-once;
  store raises → swallowed + safe fallback.
- `quick_smoke_test()` updated; observer invariant (never-raises) preserved + structurally tested.

## 6. Execution
1. Builder in a **git worktree** (live arbiter code; never the live tree).
2. Reconcile `9694fb11` (§3.4) FIRST.
3. Build §3.0–3.3 → 100% L/B/F → `quick_smoke_test` green.
4. **Fresh-critical reproduce-not-trust review** (independent reviewer).
5. `git merge --no-ff` **HELD** on `wip-v0.1.8` (coordinate merge timing with Mr. Radio's L2/L3/L4).
6. Deploy: **bounce `:8001`** (`systemctl --user restart lupin-arbiter-app.service`, standing manager
   authority) so the arbiter loads the fix. Push = Rick's gate.
7. Report held hash + review verdict + bounce confirmation to `dm-tiberius`.
