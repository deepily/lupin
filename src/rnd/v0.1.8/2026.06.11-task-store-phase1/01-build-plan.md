# Unified Task Store — Phase-1 Build Plan (Lupin side)

**Date**: 2026.06.11 (EDT)
**Author**: Krishna 🦚 (Lane 2, task-store crew) — session `38d15e3b`
**Manager**: Tiberius 👑 (`f557aab9`)
**Status**: BUILT + VERIFIED — design-gate APPROVED (Tiberius, qid `c8c73fde`: all 5 open
calls ruled in favor + 2 build notes folded: `updated_ts` `onupdate=func.now()`, symmetric
downgrade). See §9 Verification Results.
**Canonical design (LAW)**: planning-is-prompting → `src/rnd/2026.06.11-unified-task-store-design.md` (v0.4, PIP commit `e4f3d92`)
**Branch**: `wip-task-store-phase1` (worktree `/tmp/wt-task-store-phase1`, off `wip-v0.1.8-2026.05.29-preparing-for-gcp-deployment`)

---

## 0. Scope & Gates

Phase 1 per design §4: store + REST + receipts-on-done enforcement + MCP wrapper SPEC.
Rick's ratified rulings (design §3.1) are fixed inputs: **F1** PostgreSQL now · **F2**
extend `:7999` with `/api/tasks/*` · **F3** store-canonical · **F4** managers-first writes.

| Gate | State |
|---|---|
| Design-gate (Tiberius reviews this plan + DDL before code) | **submitted** (qid `c8c73fde`) |
| Lane-1 async-handlers fix LANDED before `/api/tasks/*` deploys (C2 pin) | held — coordinate via Tiberius |
| MCP wrapper implementation (cosa-voice repo touch) | spec-only until Rick's GO relayed |
| Merge | green + fresh-critical reviewer |
| Push | NEVER (Rick only) |

## 1. Deliverables

1. **Models** — `TaskItem` + `TaskEvent` in `src/cosa/rest/postgres_models.py` (§2.1 of design,
   incl. `correlation_key` indexed per C1, typed `blocked_by` refs, `gate_class`,
   `next_chase_ts`-required-when-blocked CHECK).
2. **Migration** — Alembic revision in `src/migrations/versions/`, `down_revision = e9f0a1b2c3d4`
   (current head, verified 2026-06-11).
3. **Repository** — `TaskRepository( BaseRepository[TaskItem] )` in
   `src/cosa/rest/db/repositories/task_repository.py`: `create_item`, `transition`
   (event + item update, atomic in one `get_db()` session), `query_tasks`, `get_events`.
4. **Receipt validation** — pure module `src/cosa/rest/task_receipts.py` (§4.1 AC1):
   key whitelist + per-key shape rules; designed as a dependency-free function so 100%
   L/B/F is mechanical.
5. **REST router** — `src/cosa/rest/routers/tasks.py`, registered in `main.py`:
   - `POST /api/tasks` — create (stamps `→queued` creation event)
   - `POST /api/tasks/{id}/transition` — `→done` rejects without valid `receipt_refs`;
     `→blocked` requires `next_chase_ts` + typed `blocked_by`
   - `GET /api/tasks` — filters: `owner_persona`, `status`, `gate_class`,
     `accountable_manager`, `project`, `item_class`
   - `GET /api/tasks/{id}` · `GET /api/tasks/{id}/events`
   - ALL endpoints: `Depends( require_api_key_or_jwt )` (AC2) and **sync `def`**
     handlers → FastAPI threadpool (C4 debt-clean: DB layer is sync SQLAlchemy via
     `get_db()`; the sync-inside-`async def` grep gate passes by construction).
6. **Hook-side auth lane** (AC2) — documented here: hook writers authenticate via
   `X-API-Key` read from `src/conf/keys/notification-api-claude-code-dev` (same key-file
   lane as `src/scripts/cascade_heartbeat_scheduler.py` `DEFAULT_KEY_PATH`). No new auth scheme.
7. **MCP wrapper SPEC** — `02-mcp-wrapper-spec.md` (sibling doc). Implementation is a
   cosa-voice-repo deliverable (design C5) — NOT touched from this lane until GO.
8. **Tests** — full pyramid (§4.1 AC5), 100% lines/branches/functions on all new code.

## 2. Schema (DDL sketch as submitted for gate)

### `task_items` (model `TaskItem`)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | `gen_random_uuid()` |
| `item_class` | String(32), idx | design's `class` — Python reserved word → `item_class` at EVERY layer (one-name rule). **Gate call #1** |
| `title` | Text NOT NULL | |
| `body` | Text NULL | decision framing payload lives here (v0.4, no separate payload column) |
| `project` | String(255), idx | repo scope |
| `owner_persona` | String(255) NULL, idx | |
| `accountable_manager` | String(255) NULL, idx | |
| `created_by` | String(255) NOT NULL | persona + session id |
| `status` | String(32), idx | `queued\|claimed\|in_progress\|blocked\|review\|done\|dropped` — house style String + app validation, not PG ENUM |
| `created_ts`, `updated_ts` | TIMESTAMPTZ | `server_default func.now()`; design names (`_ts`, not `_at`) |
| `blocked_by` | JSONB default `[]` | typed refs `[{kind: item\|persona\|user, id}]`, app-validated |
| `next_chase_ts` | TIMESTAMPTZ NULL | + CHECK `(status != 'blocked' OR next_chase_ts IS NOT NULL)` (I3) |
| `gate_class` | String(32) default `'none'`, idx | `none\|manager\|ricks_court` |
| `priority` | String(2) default `'P2'` | P0–P3 |
| `source_qid` | String(64) NULL | T4 |
| `correlation_key` | String(255) NULL, **idx** | C1 — poured Phase 1, writer arrives Phase 2 |

Composite index `(owner_persona, status)` — the oracle query shape.

### `task_events` (model `TaskEvent`, append-only)

| Column | Type | Notes |
|---|---|---|
| `id` | BigInteger autoincrement PK | |
| `item_id` | UUID FK → `task_items.id` CASCADE, idx | |
| `ts` | TIMESTAMPTZ | `func.now()` |
| `actor` | String(255) NOT NULL | persona + session id |
| `transition` | String(64) | `"queued→claimed"`; creation stamps `"→queued"` |
| `receipt_refs` | JSONB NULL | non-empty REQUIRED for `→done` (T3) |
| `authority` | String(32) | `standing\|user_direct\|manager_relay` |

## 3. Receipt validation rules (§4.1 AC1)

Whitelist `{commit, test_run, qid, doc_path, log_line}`; unknown key ⇒ reject (422).

| Key | Shape |
|---|---|
| `commit` | `^[0-9a-f]{7,40}$` |
| `test_run` | `^ts-[0-9a-f]{8}$` (confirmed: `test_suite.py:46` `ts-{uuid8}`) |
| `qid` | strict UUID regex |
| `doc_path` | `<scope>/<rel>` — scope resolved via `_scope_registry` roots (`lupin` → `LUPIN_ROOT`); `os.path.isfile` must pass. Reuses doc-viewer addressing — no new path grammar |
| `log_line` | **proposal (gate call #3)**: `<path>:<lineno>` with path-exists check — design doesn't pin a shape |

`→done` REQUIRES ≥1 valid ref; non-empty-but-junk (`{doc_path: "trust me"}`) rejected.

## 4. Transition rules (Phase 1)

The full legal-transition graph is Phase-2+ backlog (design C-item). Phase 1 enforces:

- `to_status` ∈ enum; same→same rejected
- transitions FROM `done`/`dropped` rejected (terminal-state sanity — **gate call #4**,
  a minimal addition beyond the design letter)
- `→done` requires valid receipts
- `→blocked` requires `next_chase_ts` AND ≥1 typed `blocked_by` ref (**gate call #5** —
  design mandates only `next_chase_ts`)
- every transition = 1 event row + item update, atomic in one session

## 5. Config

ZERO new INI keys anticipated for Phase 1. If a tunable emerges, key lands in
`lupin-app.ini` `[Lupin: Baseline]` + `lupin-app-splainer.ini` in lockstep.

## 6. Verification plan (100% L/B/F on all new code)

| Tier | Venue | What |
|---|---|---|
| compile | local | `py_compile` + import chain after EVERY edit |
| unit | :7999-class (local pytest) | models (constraints, repr), repository (CRUD, transition atomicity, filters), `task_receipts` (every shape rule, every reject branch), router (TestClient + `dependency_overrides` on auth + session) |
| integration | :8000 via `POST /api/test-suite/submit` ONLY | live create→transition→query→events against real Postgres; **scheduled only after Lane-1 lands + deploy** (ship gate); file written now, held |

Tabular per-tier report at each milestone DM.

## 7. Open gate calls (submitted to Tiberius, qid `c8c73fde`)

1. `item_class` rename (Python reserved word `class`) — one name at every layer.
2. Table names `task_items`/`task_events` vs design's bare `items`/`events`
   (shared `lupin_auth` namespace argues for the prefix).
3. `log_line` receipt shape proposal.
4. Terminal-state rule (no transitions FROM `done`/`dropped`).
5. `→blocked` requires ≥1 `blocked_by` ref.

## 8. Milestones

- **M1** — models + migration green (py_compile, import chain, migration up/down on dev DB)
- **M2** — repository + receipt validation green (unit, 100%)
- **M3** — router green (unit via TestClient, 100%; debt-clean grep gate)
- **M4** — integration file written + held; tabular full-pyramid report; fresh-critical
  reviewer requested via Tiberius

## 9. Verification Results (2026-06-12 ~00:30 EDT)

| Tier | Venue | Result |
|---|---|---|
| py_compile + import chain | local | ✅ every file, every edit |
| smoke (`task_store_rules` inline) | local | ✅ all validators |
| unit — rules | local pytest | ✅ 77 tests; **100% lines (103) + branches (62)** |
| unit — models | local pytest | ✅ 15 tests (incl. onupdate + CHECK + index parity) |
| unit — repository | local pytest | ✅ 16 tests; **100% lines (38) + branches (2)** |
| unit — router | local pytest | ✅ 22 tests; **100% lines (86) + branches (14)** |
| `postgres_models.py` changed surface | coverage | ✅ 13 missed lines are PRE-EXISTING reprs of the other 13 models — TaskItem/TaskEvent surface 100% |
| migration up | scratch DB (`lupin_db_taskstore_scratch`, stamped at prior head `e9f0a1b2c3d4` → `upgrade +1`) | ✅ both tables + CHECK + all indexes (11 incl. PKs) |
| live semantics | scratch DB | ✅ server defaults fire · CHECK rejects blocked-without-chase · `updated_ts` onupdate bumps · FK CASCADE deletes events |
| migration down | scratch DB `downgrade -1` | ✅ both tables gone; scratch DB dropped after |
| C4 debt-clean grep gate | static | ✅ ZERO `async def` in `routers/tasks.py` (one grep hit = docstring prose); all 5 `get_db()` sites inside sync `def` |
| full unit regression | local pytest, whole `src/tests/unit/` | ✅ **6633 passed, 1 xfailed, 0 failed** (3m04s) |
| integration | :8000 scheduled | ⏸ HELD — file `src/tests/integration/test_task_store_integration.py` rides the repo; scheduling gated on Lane-1 async-fix LANDED + `/api/tasks/*` deploy (C2 pin) |

Pre-existing finding (not mine, surfaced): `alembic upgrade head` from an EMPTY
database fails at `275fb8d9c75c_add_notifications_table` — the initial schema
(`users` etc.) was created out-of-band via `schema.sql`, so the migration chain
is not zero-bootstrappable. Filed upward to Tiberius.

Note: one micro-deviation from §1 — receipt validation lives in
`task_store_rules.py` (widened from the planned `task_receipts.py`) because the
transition/create/blocked_by rules belong in the SAME one-rules-home module.
