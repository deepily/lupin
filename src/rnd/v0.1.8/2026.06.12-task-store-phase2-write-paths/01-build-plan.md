# Unified Task Store — Phase-2 Build Plan: Write-Path Hooks (Lupin side)

**Date**: 2026.06.12 (EDT)
**Author**: Tiffany 💍 (Phase-2 write-path builder) — session `d03e6219`
**Manager**: Tiberius 👑 (`f557aab9`)
**Status**: CONTRACT RULED (Tiberius qid `b312b0f1`: all 5 contract calls APPROVED) — building
**Canonical design (LAW)**: planning-is-prompting → `src/rnd/2026.06.11-unified-task-store-design.md` (v0.4.1)
**Practice doc**: planning-is-prompting → `workflow/task-store-discipline.md` (v0.1, María — drift flags DM'd pre-freeze, qid `bb452ab5`)
**Phase-1 record**: `src/rnd/v0.1.8/2026.06.11-task-store-phase1/01-build-plan.md` (landed `3be8008e`; migration `f0a1b2c3d4e5`; alembic head `a1b2c3d4e5f6`)
**Branch**: `wip-task-store-phase2` (worktree `/tmp/wt-task-store-phase2`, off `wip-v0.1.8-…-gcp-deployment` @ `926c6925`)

---

## 0. Scope & Rulings That Bind

Phase 2 per design §4: **write paths — sessions recording task state (create /
transition / block events) through the Phase-1 store.** This lane = the
harness-task mirror hook + its server-side contract additions.

Fixed inputs:

- **D3** — Phase-2 write-path hooks GO (Rick post-game ruling 2026-06-12).
- **D2 / arbiter-oracle contract** — `blocked_by` `{kind:user}` ⇒ NOT-owed
  (design §2.1) must survive EXACTLY. This lane **never writes `blocked`**
  (the harness has no blocked status); the semantic rides only explicit
  MCP/REST transitions and is untouched. (Tiberius emphasis, qid `e7f0fa5e`.)
- **D1** — `task_events` shape is the fleet-allocation convergence target.
  The one schema change here (§3.2 `reason`) is ADDITIVE (nullable column).
- **F4** — managers-first writes: the hook gates on the manager-figure
  predicate (`workflow/manager-autonomy.md` §2.1).
- **Out of my lane** (Tiberius ruling, qid `b312b0f1` call 5): T4 DM
  review-request auto-create + the C10 scope call — filed as a separate work
  item. Clayton's acked-ledger fold (C-lane) is also separate.

### 0.1 Empirical correction to the design letter: this harness is Task*, not TodoWrite

`stop.py` §0.3 already corrected TodoWrite→Task* for the work-owed oracle. The
`PostToolUse` payload for `TaskCreate` carries **`tool_response.task.id`** — the
stable harness task id — so C1's correlation-key derivation takes precedence
path **(a)** (harness task id) universally here. The (b) normalized-content-hash
path and the subject-change supersede mechanics are **dormant on this harness**
(TaskUpdate updates by id; there is no whole-list rewrite). Documented to María
for the practice-doc freeze (qid `bb452ab5`).

### 0.2 The 5 ruled contract calls (Tiberius qid `b312b0f1`)

| # | Call | Ruling |
|---|---|---|
| 1 | Harness `completed` → store **`review`** (hook cannot fabricate receipts; receipted `→done` stays an explicit act — no receipt-theater) | APPROVED |
| 2 | **C12 pulled forward**: `task_events.reason` column (additive migration on head `a1b2c3d4e5f6`) + rule `→dropped` REQUIRES non-empty reason | APPROVED — C-ledger note: this is cold-review **C12's** "`→dropped` requires a reason" item, built in Phase 2 because the hook's `deleted`→`dropped` mapping needs the field NOW; the REST of C12 (chase consumer, cross-item events query, legal transition graph, I4 detection) stays backlog |
| 3 | `correlation_key` filter param on `GET /api/tasks` (column was indexed Phase-1 but unreachable via REST; needed for spool-replay idempotency + map-loss recovery) | APPROVED |
| 4 | Respawn adoption: `TaskCreate` carrying `metadata.task_store_id=<uuid>` → hook ADOPTS via new **`POST /api/tasks/{id}/correlate`** (re-stamps `correlation_key`, audited event) instead of creating a fork | APPROVED w/ rider: DM Sam (`01b3bf59`, MCP-wrapper builder) the endpoint shape when pinned — wrapper exposure (now vs Phase-2.1) is Sam+Tiberius's call; no silent drift |
| 5 | T4 DM auto-create NOT in this lane | APPROVED |

## 1. Deliverables

### Hook side (`src/lupin_cli/claude_code/hooks/lib/`)

1. **`task_store_settings.py`** — settings loader, `~/.claude/settings.json`
   `["task_store"]` block, mirrors `heartbeat_settings` exactly:
   `enabled` (**default False** — merging is a NO-OP until opted in; the
   kill-switch IS the rollout gate), `api_base_url` (default
   `http://localhost:7999`), `timeout_seconds` (default 3.0, fail-loud
   ValueError on non-positive), `spool_ttl_seconds` (default 86400, mirrors
   `notify outbox ttl seconds`).
2. **`manager_figure.py`** — the F4 write gate (§2.1 predicate, both sources):
   EXPLICIT — bridge `role == "manager"`; IMPLICIT — session
   `voice_persona.name` ∈ the NAMED entries (wildcard excluded) of
   `COSA_VOICE_PREFERRED_PERSONA__<PROJECT>` (resolved via the existing
   `cosa.rest.voice_persona_helpers.pick_persona_chain_from_env` +
   `parse_persona_chain` — no duplicated parser). Degrade-safe → False
   (fail-CLOSED for writes: a doubt-case session does not write; F4).
3. **`task_store_map.py`** — per-session correlation map artifact
   `.task-store-map-<sid>.json` (same family/base-dir resolver as
   `heartbeat_hold`/`heartbeat_acked_ledger`; atomic tmp+rename writes;
   degrade-safe reads): `{ harness_id: { "item_id": uuid, "last_status":
   harness_status } }` + `flagged_at` (the I4 flag-once marker).
4. **`task_store_spool.py`** — C8 write-side failure spool: per-session JSONL
   `.task-store-spool-<sid>.jsonl`; append on transport failure; FIFO drain;
   TTL-expired entries dropped at drain (counted, flagged); atomic rewrite.
5. **`task_store_client.py`** — stdlib-urllib REST client (no requests dep in
   hook lane): `create_task`, `transition_task`, `correlate_task`,
   `query_by_correlation_key`; auth `X-API-Key` read from
   `src/conf/keys/notification-api-claude-code-dev` (AC2 lane, same key file
   as `cascade_heartbeat_scheduler.DEFAULT_KEY_PATH`); short timeout; returns
   `( ok, status_code, body_dict )`, NEVER raises.
6. **`task_store_mirror.py`** — the orchestrator `mirror_task_tool_event(
   payload )`: gate → drain spool → map event → execute → update map → spool
   on transport failure → drop+flag-once on 4xx. NEVER raises; NEVER blocks
   the hook beyond the bounded client timeout.
7. **`post_tool_use.py` integration** — minimal: `tool_name` ∈
   {`TaskCreate`, `TaskUpdate`} → call the mirror (its own never-raise belt).
   All other tools: ZERO added work (the existing cheap-stamp invariant holds).

### Server side (Lupin `src/cosa/rest/`)

8. **Migration** `src/migrations/versions/<rev>_add_task_event_reason.py` —
   `task_events.reason` Text NULL; `down_revision = "a1b2c3d4e5f6"`;
   symmetric downgrade.
9. **`postgres_models.py`** — `TaskEvent.reason` column (+ model comment:
   required-by-rule for `→dropped`, optional elsewhere).
10. **`task_store_rules.py`** — `validate_transition` gains `reason` param:
    `→dropped` with missing/blank reason → error (every other transition:
    optional, no shape rule — free text ≤ a sane length cap, 4000 chars).
11. **`routers/tasks.py`** —
    - `TaskTransitionIn.reason : Optional[str]` (max_length=4000), threaded to
      rules + repository; serialized in `_serialize_event`.
    - `GET /api/tasks` gains `correlation_key : Optional[str]` exact-match
      filter (threaded to repository; indexed column).
    - **`POST /api/tasks/{id}/correlate`** — body `{ correlation_key (req,
      ≤255), actor (req, ≤255), authority (default "standing") }`; 404 on
      missing item; 422 on terminal item (no re-keying closed history) or bad
      authority; updates `item.correlation_key`; appends audit event
      `transition="re-correlated"`, `receipt_refs=None`, `reason` carries
      `"correlation_key: <old> -> <new>"` (R3: the adoption is auditable);
      returns `{ item, event }`. Sync `def` (C4 debt-clean), row-locked read
      (N3 parity).
12. **`task_repository.py`** — `query_tasks` correlation_key filter;
    `apply_transition` reason threading; `apply_correlation` primitive.

### Docs & tests

13. This plan doc + `src/rnd/README.md` link.
14. Full pyramid, **100% lines/branches/functions on all new/changed
    surface**; integration additions ride the Phase-1 integration file's
    pattern (held for :8000 scheduling via `pytest_direct`).

## 2. Status mapping (the hook's contract)

| Harness event | Store write | Notes |
|---|---|---|
| `TaskCreate` (no `metadata.task_store_id`) | `POST /api/tasks` — `item_class="task"`, `title=subject`, `body=description`, `project=<derived>`, `owner_persona=<my persona>`, `accountable_manager=<my persona>`, `correlation_key="cc-task:<stable_sid>:<harness_id>"`, `authority="standing"` | map records `harness_id → item_id`, `last_status="pending"` |
| `TaskCreate` with `metadata.task_store_id=<uuid>` | `POST /api/tasks/{uuid}/correlate` to the NEW key | the cross-session respawn residual fix: successor ADOPTS the inherited item; no fork |
| `TaskUpdate status=in_progress` | transition `→in_progress` | |
| `TaskUpdate status=pending` | transition `→queued` | re-queue |
| `TaskUpdate status=completed` | transition `→review` | ruling #1 — `→done` is NEVER hook-written; receipted closes stay explicit |
| `TaskUpdate status=deleted` | transition `→dropped`, `reason="harness-deleted (TaskUpdate)"` | ruling #2 |
| `TaskUpdate` without status change (subject/description/metadata-only) | no-op | item field drift (title edits) = known accepted gap, Phase-2.1 candidate (no item-PATCH endpoint exists) |
| same mapped status as `last_status` | no-op (skip, no 422 noise) | idempotence via map |
| any event for a harness id whose item is terminal (`dropped`) | no-op + log | terminal lockout is by design |
| **never** | `→blocked`, `→done`, `→claimed` | blocked/done semantics ride explicit transitions only; `blocked_by {kind:user}` oracle contract untouched |

Identity stamping: `created_by` / `actor` = `"<persona_lower> <sid8>"` (e.g.
`"tiffany d03e6219"`) from the session bridge — same convention as the MCP
wrapper spec §2.1; a session cannot impersonate. Project derivation: basename
of `LUPIN_ROOT` (fallback cwd), lowercased — same rule as `hook_credentials`.

## 3. C8 spool semantics (write-side failure)

- Transport failure (connect/timeout/5xx) → spool the op (JSONL append) +
  flag-once. A spooled `create` forces all subsequent ops for the SAME harness
  id to spool too (order preserved; a transition cannot precede its create).
- Drain runs at the START of every mirror invocation (opportunistic replay on
  next Task* fire — hook-cadence analog of the notify-outbox flusher; one
  bounded pass, first still-failing entry stops the drain, never blocks).
- Replay idempotency for `create`: query `GET /api/tasks?correlation_key=…`
  first — if the item exists (lost-response case), record the mapping and skip
  the duplicate POST (the ruled #3 filter is what makes this possible).
- 4xx (422/404) → NOT spooled (will never succeed): drop + flag-once + log.
- TTL: entries older than `spool_ttl_seconds` dropped at drain (counted in the
  flag) — mirrors `notify outbox ttl seconds` = 24h.
- I4: a session that cannot write FLAGS ONCE (log_to_stream + `flagged_at`
  marker; cleared on first success), never fakes, never breaks the hook.

## 4. Verification plan (100% L/B/F on changed surface)

| Tier | Venue | What |
|---|---|---|
| compile | local | `py_compile` + import chain after EVERY edit |
| unit | local pytest (:7999-class) | settings (defaults/malformed/fail-loud), manager_figure (both predicate sources × degrade), map (round-trip/atomic/degrade), spool (append/drain/TTL/order), client (mocked urllib: ok/4xx/5xx/timeout/never-raises), mirror (full mapping table + gate + spool interplay + idempotence), rules (reason on dropped ± , unchanged paths), router (correlate endpoint + correlation_key filter + reason threading, TestClient + dependency_overrides), repository, migration model parity |
| migration | scratch DB | stamp `a1b2c3d4e5f6` → `upgrade +1` → column present → live reason write → `downgrade -1` symmetric |
| integration | :8000 via `POST /api/test-suite/submit` (`pytest_direct`, UNDERSCORE) | live create→correlate→transition(reason)→query-by-correlation_key against real Postgres; file rides the repo, held |
| harness gotchas | — | worktree conftest path-poisoning controls from worktree; `coverage run` not pytest-cov (sqlalchemy double-registration); plain unittest for expected-failure control receipts |

## 4.1 Verification results (2026-06-12, ~13:45 EDT)

| Tier | Venue | Result |
|---|---|---|
| py_compile + import chain | worktree | ✅ every file, every edit (server chain + hook chain) |
| smoke (`task_store_rules` inline) | worktree | ✅ incl. new dropped-reason assertions |
| unit — hook modules (settings/map/spool/manager_figure/client/mirror) | local pytest | ✅ 140 tests; **100% lines + branches** on all six modules (397 stmts / 108 branches, 0 missed) |
| unit — server (rules/repository/router/models) | local pytest | ✅ 180 tests; **100% lines + branches** on task_store_rules (105/64), task_repository (45/2), routers/tasks (106/20) |
| unit — post_tool_use seam | local pytest | ✅ 22 tests (6 new: Task* routes to mirror; TaskGet/TaskList/Read/Bash never touch it) |
| migration up | scratch DB `lupin_db_taskstore_p2_scratch` (stamped e9f0a1b2c3d4 → upgrade +3) | ✅ chain f0a1b2c3d4e5 → a1b2c3d4e5f6 → **b2c3d4e5f6a7**; reason column TEXT NULL; live INSERT carrying a reason round-trips |
| migration down | `downgrade -1` | ✅ symmetric — column gone; scratch dropped after |
| full unit regression | worktree, whole `src/tests/unit/` | ✅ **6925 passed, 1 xfailed, 0 failed** (3m05s; was 6633 at Phase-1 tip — +292 incl. this lane's 161 new/extended) |
| integration | :8000 scheduled (`pytest_direct`) | ⏸ HELD — `TestTaskStorePhase2WritePaths` (3 tests: dropped-reason wire, correlation_key filter, correlate+terminal-lockout) rides the Phase-1 integration file; scheduling still gated on the C2-pin deploy sequence |

Coverage harness note (worktree): `coverage run --source=<module.name>` imports
the named modules BEFORE pytest's conftest → sqlalchemy double-registration
("Type <class 'object'> is already registered"). The working recipe is the
pyproject default source + `coverage report --include=<files>` for server
modules, and `--source=<module>` only for modules that never import sqlalchemy
(the hook six). Adds a data point to the §8.4 gotcha block.

## 5. Gates

| Gate | State |
|---|---|
| Contract calls (5) | ✅ RULED (qid `b312b0f1`) |
| Sam DM — `/correlate` shape coordination (ruling #4 rider) | owed the moment §1.11 freezes — sent at plan-doc commit |
| Fresh-critical review before merge | MANDATORY (Tiberius spawns) |
| Commit | HELD in worktree |
| Push | NEVER (Rick only) |
