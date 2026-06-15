# Unified Task Store — Phase-2.1 Build Plan (Lupin side)

**Date**: 2026.06.15 (EDT)
**Author**: Krishna 🦚 — session `a38ee857`
**Status**: PLAN — Phase-0 documentation gate (no code until this lands). Rick GO 2026-06-15 (voice): "implement the Phase 2.1 backlog" + ask_yes_no APPROVE (schedule integration + begin backlog build, plan-first).
**Canonical design (LAW)**: planning-is-prompting → `src/rnd/2026.06.11-unified-task-store-design.md` (v0.4.1) — §"Phase-2+ backlog (cold-review C8–C15)"
**Phase-1 record**: `src/rnd/v0.1.8/2026.06.11-task-store-phase1/01-build-plan.md` (migration `f0a1b2c3d4e5`)
**Phase-2 record**: `src/rnd/v0.1.8/2026.06.12-task-store-phase2-write-paths/01-build-plan.md` (migration `b2c3d4e5f6a7`)
**Activation state**: `~/.claude/settings.json` `task_store.enabled = true` (flipped 2026-06-15) — the harness Task*→store mirror is now LIVE on `:7999`.

---

## 0. Scope & Binding Rulings

Phase 2.1 closes the deferred follow-ups from the Phase-1/Phase-2 merges plus the
remaining cold-review **C12** items. Everything here is ADDITIVE — no Phase-1/2
contract is changed; the `blocked_by {kind:user}` ⇒ NOT-owed arbiter-oracle
invariant (design §2.1) survives untouched.

Fixed inputs carried forward:
- **F3** store-canonical · **F2** `:7999` `/api/tasks/*` · **F4** managers-first writes.
- **I3** `→blocked` requires `next_chase_ts` + ≥1 typed `blocked_by` ref (already enforced).
- **I4** fail-open + flag-once on non-compliance (hook-side; partially built Phase 2).
- **One-name rule** — `item_class`, `_ts` suffixes, no per-layer aliasing.
- **Push** = NEVER (Rick only). **Merge** = green + fresh-critical reviewer.

## 1. Deliverables — five work items (recommended build order)

Ordered lowest-risk / highest-isolation → highest-blast-radius. Each item is
independently mergeable behind its own fresh-critical review.

### Item A — `task_correlate` MCP tool (transport-only; deferred from wrapper merge `8f4a36f2`)
- **Where**: `src/lupin_mcp/task_store_tools.py` (+ registration in `cosa_voice_mcp.py`).
- **What**: `task_correlate_impl( api_base_url, api_key, actor, task_id, correlation_key, authority="standing" )`
  → `POST /api/tasks/{task_id}/correlate` (endpoint already exists, Phase 2).
  Mirrors the existing three impls exactly: transport-only, never pre-validates,
  server words verbatim on 4xx, never raises. `actor` caller-stamped (no impersonation).
- **Risk**: LOW — endpoint live + tested; this is a thin wrapper + tool registration.
- **Open call**: tool name — `task_correlate` vs the `taskstore_*`-collision review
  (design backlog). Resolve before registering (no rename later — one-name rule).

### Item B — `PATCH /api/tasks/{id}` item-field edit endpoint (closes the title/description drift gap)
- **Where**: `routers/tasks.py` (+ `task_repository.apply_patch`, + `task_store_rules` field whitelist).
- **What**: edit `title` / `body` / `priority` / `owner_persona` / `accountable_manager`
  / `gate_class` on a non-terminal item; append an audit event `transition="patched"`
  with `reason` carrying the field delta (R3 auditability). Terminal items (`done`/`dropped`)
  rejected 422. Field whitelist enforced server-side (no arbitrary column write).
  Sync `def` (C4 debt-clean), row-locked read (N3 parity).
- **No schema change** — all columns exist.
- **Hook follow-on**: the Phase-2 "TaskUpdate without status change → no-op (known gap)"
  row can now mirror title/description edits via PATCH. In-scope iff trivial; else 2.2.
- **Risk**: LOW-MED — new write path; field whitelist is the security-critical surface.

### Item C — Cross-item events query (Rick's fleet-wide audit, design backlog)
- **Where**: `routers/tasks.py` `GET /api/tasks/events` (new, distinct from the existing
  per-item `GET /api/tasks/{id}/events`) + `task_repository.query_events`.
- **What**: filtered event stream across items — filters `actor`, `transition`,
  `since`/`until` (ts range), `project`, `limit`/`offset` (bounded `Query(ge=0,le=500)`
  per N4). Read-only. Powers the fleet-wide "who did what when" audit.
- **No schema change**.
- **Risk**: LOW — read-only query.

### Item D — Legal-transition graph (design backlog; tightens Phase-1's minimal rules)
- **Where**: `task_store_rules.py` — replace the Phase-1 "any→any except terminal/same"
  with an explicit adjacency map.
- **What**: pin the legal graph, e.g.
  `queued→{claimed,in_progress,blocked,dropped}`, `claimed→{in_progress,blocked,dropped}`,
  `in_progress→{blocked,review,done,dropped}`, `blocked→{in_progress,claimed,dropped}`,
  `review→{in_progress,done,dropped}`; `done`/`dropped` terminal. Illegal edge → 422
  with the offending edge named verbatim. EXACT graph is **gate call #1** (ratify before build).
- **Compat risk**: MED — the hook mirror writes `→review`, `→in_progress`, `→queued`,
  `→dropped`; every hook-emitted edge MUST be legal or the live mirror starts 422-ing.
  Cross-check the Phase-2 status-mapping table before finalizing the graph.
- **Risk**: MED — behavior change on an ACTIVE (now-enabled) write path; needs the
  hook-edge cross-check + a regression test asserting every mirror edge stays legal.

### Item E — `next_chase_ts` chase consumer + I4 non-compliance detection (design backlog)
- **Where**: new `src/cosa/rest/task_chase_consumer.py` (daemon, mirrors the
  ghost-job-sweeper pattern on `RunningFifoQueue`) + I4 detector.
- **What**:
  - **Chase consumer** — periodic scan (INI `task store chase interval seconds`,
    default 300) for `blocked` items whose `next_chase_ts` is past; emits a chase
    signal (notify to `accountable_manager` / commons post) + stamps a `chased` audit
    event; re-arms `next_chase_ts` (backoff). Idempotent; never auto-transitions.
  - **I4 detection** — surface sessions that should-write-but-don't (the flag-once
    marker already written hook-side Phase 2); a read endpoint/report, NOT an enforcement.
- **New INI keys** (lockstep `lupin-app.ini` `[Lupin: Baseline]` + `-splainer.ini`):
  `task store chase interval seconds`, `task store chase backoff seconds`,
  `task store chase enabled` (default **False** — same opt-in posture as the mirror flag).
- **Risk**: HIGH — background daemon + active outbound notifications; build LAST,
  flag-gated OFF by default, never auto-acts on a blocked item beyond chasing.

### Item F (deferred-candidate) — T4 DM auto-create-on-review-request
- **Where**: hook DM path / commons review-request lane.
- **What**: a review-request DM auto-creates a `review`-class task in the store.
- **Status**: design backlog flags an **acked-ledger-scope vs T4-auto-create-class**
  ambiguity that is UNRESOLVED. **Recommend deferring to Phase 2.2** pending that ruling
  — do NOT build on an unresolved class boundary. Listed here for completeness.

## 1.5 Reviewer verdict (2026-06-15) — APPROVE-WITH-DELTAS · BUILD UNBLOCKED

`cc-reviewer-tiberius-1` (fresh-critical, manager-owned) → **APPROVE-WITH-DELTAS**, relayed by Tiberius (thread `0985a96d`). Build A–E; **F held for 2.2**. Commit HELD on `wip-v0.1.8`; push NEVER. Each item gets its OWN fresh-critical review before merge — coordinate per-item with Tiberius at each green+held checkpoint.

**GATE #1 (Item D legal graph) — my §1-Item-D DRAFT IS REJECTED & SUPERSEDED.** The draft would have 422'd 3 edges the LIVE mirror genuinely emits (`queued→review`, `in_progress→queued`, `review→queued`, verified against `task_store_mirror.py` STATUS_TRANSITIONS). **RATIFIED graph: every NON-terminal status → every OTHER status; `done`/`dropped` terminal (no out-edges); no-op/same-status rejected.** = Phase-1 semantics made EXPLICIT, behavior-preserving.
- **D-DELTA-1**: the adjacency check **PREPENDS** to `validate_transition`'s existing rules, does NOT replace them — receipt-on-`done`, `→blocked` (next_chase_ts + typed refs), `→dropped` reason MUST survive untouched.
- **D-DELTA-2**: the mirror-edge regression must derive edges **PROGRAMMATICALLY** by importing the hook's `STATUS_TRANSITIONS` (+ the `queued` create-seed + the backward `in_progress→queued` / `review→queued`) and assert each ∈ LEGAL; also assert terminal-source still 422s + no-op still 422s. **No hand-copied edge list** (it rots).

**GATE #2 (Item A name) — RULED: `task_correlate`.** `taskstore_*` REJECTED (snake_case `task_*` family from `8f4a36f2`; PascalCase harness `Task*` disambiguated by case + namespace).

**ITEM B delta**: the PATCH field whitelist MUST EXCLUDE `status` / `blocked_by` / `next_chase_ts` / `receipt_refs` / `correlation_key` (HARD invariant — PATCH can NEVER bypass the transition oracle); `apply_patch` must NOT route through `validate_transition` (`patched` is an EVENT label, not a `to_status` — would 422).

**BUILD ORDER (adopted): A → C → B → D → E** (reviewer's suggestion; C read-only is lower blast-radius than B's new write path).

### Item status
- **Item A — `task_correlate` MCP tool — ✅ BUILT, green+held** (2026-06-15). `task_correlate_impl` in `task_store_tools.py` + `@mcp.tool task_correlate` in `cosa_voice_mcp.py` (actor bridge-stamped, never a param). Tests: 33/33 pass; `task_store_tools.py` **100% lines (34) + branches (6)**; wrapper-registration + default-authority pinned. Review ASSIGNED (Tiberius, same reviewer owns A→E; verdict relays through him). NOT committed.
- **Item C — `GET /api/tasks/events` cross-item event stream — ✅ BUILT, green+held** (2026-06-15). `TaskRepository.query_events` (filters actor/transition/project[join to TaskItem]/since/until, ts-desc newest-first, bounded limit/offset) + router endpoint declared BEFORE `/tasks/{task_id}` (static path wins over the UUID converter — pinned by a regression test). Read-only; no schema change. Tests: 85/85 pass (repo + router suites); `task_repository.py` **100% (54 stmts / 4 br)** + `routers/tasks.py` **100% (113 stmts / 20 br)**. Awaiting its fresh-critical review. NOT committed.
- **Item B — `PATCH /api/tasks/{id}` item-field edit — ✅ BUILT, green+held** (2026-06-15). `TaskPatchIn` (Pydantic `extra='forbid'` → naming any oracle field = 422 at the wire), `task_store_rules.validate_patch` (editable whitelist title/body/priority/owner_persona/accountable_manager/gate_class; enum + non-empty-title checks; empty-patch reject), `TaskRepository.apply_patch` (writes only changed editable fields, appends `patched` event with field delta, **never** touches status/blocked_by/next_chase_ts/receipt_refs/correlation_key), router `patch_task` (row-locked N3, terminal-lockout 422, authority validation). NO schema change. Tests: 202/202 pass (rules + repo + router suites); **100% L/B** on `task_store_rules.py` (117/72), `task_repository.py` (63/8), `routers/tasks.py` (139/26). Awaiting its fresh-critical review. NOT committed at build time → folded into the 2026-06-15 held checkpoint commit.
- Items D, E — pending (in adopted order).

### Checkpoint — 2026-06-15 (held commit on `wip-v0.1.8`)
Items **A + C + B** committed as ONE held checkpoint (Rick directive "document and checkpoint"). **NOT pushed** (Rick's gate). Review status at checkpoint: A = reviewer-CLEARED (APPROVE no-deltas); C + B = in the reviewer's queue (verdicts relay through Tiberius). Any review deltas land as follow-up held commits. Notification-direction `:8000` integration re-run still HELD pending Mr Radio's `c3d4e5f6a7b8` apply.

## 2. Verification plan (100% lines/branches/functions on all new/changed surface)

| Tier | Venue | What |
|---|---|---|
| compile | local | `py_compile` + import chain after EVERY edit |
| unit | local pytest (:7999-class) | Item A: wrapper impl (ok/404/422/timeout/never-raises) + tool registration. Item B: PATCH (each whitelisted field, terminal-lockout, non-whitelist reject, audit-event shape, bounds). Item C: events query (each filter, ts range, bounds). Item D: legal graph (every legal edge accepts, representative illegal edges reject, **every hook-mirror edge asserted legal**). Item E: consumer (past-due scan, backoff re-arm, idempotence, flag-gate off=no-op), I4 detector. |
| migration | scratch DB | N/A for A–D (no schema change); E adds INI only. Confirm no Alembic revision needed. |
| integration | :8000 via `POST /api/test-suite/submit` (held) | live PATCH→events-query→correlate against real Postgres; rides the Phase-1/2 integration file pattern. |
| regression | local, whole `src/tests/unit/` | full suite green; mirror-edge-legality regression is the load-bearing one (Item D). |

## 3. Gates

| Gate | State |
|---|---|
| Phase-0 plan doc (this) + `src/rnd/README.md` link | building now |
| Gate call #1 — exact legal-transition graph (Item D) | ✅ RULED (see §1.5) — draft rejected, ratified graph = non-terminal→any-other, terminal no-out, no-op reject |
| Gate call #2 — `task_correlate` tool name vs `taskstore_*` collision review (Item A) | ✅ RULED (see §1.5) — `task_correlate` |
| Item F (T4 auto-create) acked-ledger-scope ruling | BLOCKED → defer to 2.2 |
| Fresh-critical review before each item merges | MANDATORY |
| Commit | HELD on `wip-v0.1.8` |
| Push | NEVER (Rick only) |

## 4. Milestones

- **M-A** Item A (correlate tool) green + held.
- **M-B** Item B (PATCH) green + held.
- **M-C** Item C (events query) green + held.
- **M-D** Item D (legal graph) — gate call #1 ratified → green + mirror-edge regression + held.
- **M-E** Item E (chase consumer + I4) — flag OFF by default → green + held.
- **M-int** integration additions written + scheduled on idle :8000.
- Tabular full-pyramid report at each milestone.
