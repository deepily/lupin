# Centralized Persona-Name Normalization

**Date**: 2026-06-19
**Branch**: `wip-v0.1.9-2026.06.19-bug-fixing`
**Status**: PLAN APPROVED → in implementation
**Severity**: Rick P0 follow-up — kills the persona-normalizer drift bug-class permanently
**Supersedes the follow-up scoped in**: `src/rnd/v0.1.8/2026.06.04-heartbeat-hook/2026.06.18-owed-oracle-persona-normalizer-drift-and-store-unknown-false-idle.md` §Follow-up
**Antecedents**: `src/rnd/v0.1.8/2026.06.04-heartbeat-hook/2026.06.18-...false-idle.md` (READ-seam fix) · `src/rnd/v0.1.8/2026.06.11-arbiter-lineage-persistence-and-persona-matching.md` (arbiter role-match)

---

## Context

Persona/voice names that carry accents or punctuation — **`María`** (🌸) and **`Mr. Radio`** (🦉) — have repeatedly broken cross-subsystem agreement because **each subsystem slugs the name with its own ad-hoc algorithm**. The same persona ends up keyed as `"maría"`, `"maria"`, `"mr. radio"`, `"mr radio"`, or `"mrradio"` depending on which code touched it. Clean ASCII names (Tiberius, Clayton) normalize to themselves under any algorithm, so they work *by luck* — which is exactly why the bug was intermittent and persona-specific.

**Concrete damage already recorded:**
- **2026-06-18 false-idle P0** (`src/rnd/v0.1.8/2026.06.04-heartbeat-hook/2026.06.18-owed-oracle-persona-normalizer-drift-and-store-unknown-false-idle.md`): the heartbeat Stop-hook owed-oracle queried `owner_persona` with a bare `.lower()` (`"maría"`, `"mr. radio"`) and matched **zero** store rows (which hold `"maria"` / `"mr radio"`) → managers beaconed *"idle — nothing owed"* while genuinely owing work. Tiberius's store probe: `"maria"`→22 rows, `"maría"`→0; `"mr radio"`→54, `"mr. radio"`→0.
- **2026-06-11 arbiter role misclassification** (`src/rnd/v0.1.8/2026.06.11-arbiter-lineage-persistence-and-persona-matching.md`): Mr. Radio badged `role=worker` instead of `manager` because the declared-roster check used `.lower()` against an event-sourced normalized persona.

The 2026-06-18 fix introduced `canonical_persona_key()` and wired it into the **READ** seam only, explicitly deferring the rest: *"adopt `canonical_persona_key` at the WRITE seam … and retire `follow_through_escalation_watcher._norm_persona` … so READ and WRITE can never drift again. Strategic, Rick-flagged."* **This plan is that ratified follow-up, widened to a true codebase-wide single source of truth.**

**Intended outcome:** exactly **one** normalization root, in one importable module, with two thin documented derivations. Every site that keys, stores, queries, or compares a persona calls the same function; no subsystem carries a private copy. María and Mr. Radio behave identically to Tiberius everywhere.

---

## Current state (what exploration found)

**Five+ divergent normalizers coexist today:**

| # | Location | Transform | `María` → | `Mr. Radio` → | Used for |
|---|---|---|---|---|---|
| 1 | `lupin_cli/.../session_bridge.py:61` `canonical_persona_key` ✅ | NFKD accent-strip, lower, `[a-z0-9 ]`, **keep spaces** | `maria` | `mr radio` | store READ seam (stop.py) |
| 2 | hooks `_identity()` — `task_store_mirror.py:143`, `task_store_drain.py:166` | bare `.lower()` | `maría` | `mr. radio` | store **WRITE** seam ⚠️ |
| 3 | `lupin_mcp/commons_persona_matcher.py:38` `_normalize_for_match` | `[^\w]`→"", lower, **drop spaces, KEEP accents** | `maría` ⚠️ | `mrradio` | arbiter role-match, manager_figure, voice helpers, free-text match |
| 4 | `cosa/rest/follow_through_escalation_watcher.py:97` `_norm_persona` | NFKD accent-strip, lower, **drop spaces** | `maria` | `mrradio` | hold-file persona match |
| 5 | `stop.py:1071` `_dm_topic_for`, `cosa_voice_mcp.py:2799` `_dm_topic`, `session_spawner.py:777` `_slug` | `re.sub` keep `\w`/`-`, spaces→`_` or `-` (**keep accents**) | `maría` ⚠️ | `mr_radio` / `mr-radio` | DM-topic + session names |

Plus ad-hoc `.lower()` compares: `voice_persona.py:287`, `voice_persona_helpers.py:211/614/821`, `heartbeat_poker_commons_gateway.py:174`.

**Settled facts (no longer open questions):**
- **The store is already canonical** (keep-spaces `"mr radio"`, `"maria"`). So the canonical root is **keep-spaces** `canonical_persona_key`; the fix is making *producers and comparators* agree with what the store already holds → **no bulk DB migration** for the core path (only a guarded backfill probe for stragglers).
- **`lupin_mcp` is the one universally-importable package**: `cosa` (arbiter `fleet_render`/`manager_resolver`, `voice_persona_helpers`) and `lupin_cli` (`manager_figure`) already import `lupin_mcp.commons_persona_matcher`; `lupin_mcp` imports neither. New home there reaches all three.
- **Hold files key persona by a JSON field, normalized at read-time on both sides** (filename uses `session_id`) → swapping the comparator is migration-free.
- **All hook writes funnel through the `/api/tasks` router** (HTTP from CLI subprocess) → the router is a single enforceable choke point; `routers/tasks.py`/`task_repository.py` are pass-throughs that store `owner_persona` verbatim.
- **This machine has no registered Claude-Code hooks** (`~/.claude/settings.json` + project settings carry no `hooks` block), so editing the hook libs here does **not** run uncommitted code on this session's events — the live fleet's hooks run on the server. Main-tree editing is safe on this clone.

---

## Design — one root, two derivations

New module **`src/lupin_mcp/persona_normalization.py`** (stdlib-only: `re`, `unicodedata`, `typing` — safe to import in hook subprocesses, no MCP-server deps, no project imports → zero cycle risk):

```python
def canonical_persona_key( name ) -> str:
    """IDENTITY / STORE KEY. NFKD accent-strip → lower → reduce to [a-z0-9 ]
    (keep internal spaces) → collapse whitespace → trim. Idempotent.
    'María'->'maria', 'Mr. Radio'->'mr radio'. (moved verbatim from session_bridge)"""

def normalize_for_match( name ) -> str:
    """LENIENT FREE-TEXT MATCH KEY = canonical_persona_key(name) with spaces removed.
    'Mr. Radio'/'mr radio'/'mrradio'/'MR.RADIO' -> 'mrradio'; 'María' -> 'maria'.
    Use ONLY for resolving noisy human input to a pool name — NEVER as a store key."""
    return canonical_persona_key( name ).replace( " ", "" )

def persona_slug( name, sep="-" ) -> str:
    """FILESYSTEM / TOPIC NAME = canonical_persona_key(name) with spaces -> sep.
    'Mr. Radio' -> 'mr-radio' (or 'mr_radio'); 'María' -> 'maria'."""
    key = canonical_persona_key( name )
    return key.replace( " ", sep ) if key else ""
```

**Decision rule applied at every site (the heart of the plan):**
- **Structured persona identity** — store write/query, comparing two persona values, dict keys, role-roster membership → **`canonical_persona_key`** (keep-spaces; its output *equals* the store key, so it doubles as a query param).
- **Noisy free-text human input** → a pool name → **`normalize_for_match`** (its space-dropping leniency is deliberate; never persisted).
- **Building a filename / DM-topic / session name** → **`persona_slug`**.

This **fixes two latent bugs as a side effect**: derivation #3's accent-blindness (`normalize_for_match("María")` now `"maria"`, was `"maría"`) and derivation #5's accent-leaky slugs.

---

## Implementation phases

### Phase 0 — persist this plan ✅ (this document)

### Phase 1 — Foundation (no behavior change except the accent fix)
1. Create `src/lupin_mcp/persona_normalization.py` (3 functions above) + `src/tests/unit/test_persona_normalization.py` at 100% (María, Mr. Radio, idempotency, empty/None, accent-strip, slug separators).
2. **Back-compat re-exports** so nothing breaks mid-migration:
   - `session_bridge.py`: replace the body with `from lupin_mcp.persona_normalization import canonical_persona_key` (stop.py + existing tests keep importing it).
   - `commons_persona_matcher.py`: `from lupin_mcp.persona_normalization import normalize_for_match`; keep `_normalize_for_match = normalize_for_match` alias; `match_persona` now rides the shared root.
3. Update `test_commons_persona_matcher.py` assertion `"María" → "maría"` to `"maria"` (intended correctness change — document it).

### Phase 2 — Identity-key centralization (the bug fix)
Route every **structured-identity** site through `canonical_persona_key`:
- **Write seam:** hooks `_identity()` in `task_store_mirror.py:143` + `task_store_drain.py:166` (`.lower()` → `canonical_persona_key`).
- **API choke point:** `routers/tasks.py` — canonicalize `owner_persona`, `accountable_manager`, and persona-typed `blocked_by` refs on **create**, and the `owner_persona` query param on **read**. Belt-and-suspenders that guarantees the store invariant for *any* caller.
- **Arbiter:** `fleet_render.py:304/340`, `manager_resolver.py:205/229` (swap `_normalize_for_match` → `canonical_persona_key`; both sides normalize symmetrically, and the value now equals the store key), `arbiter_job.py:204` query.
- **Escalation watcher:** retire `_norm_persona` (`follow_through_escalation_watcher.py:97`) → `canonical_persona_key` at both compare sites (306, 326). Update `test_follow_through_escalation_watcher.py` (`"Mr. Radio 🦉"` now `"mr radio"`, not `"mrradio"`).
- **Voice persona dedup/lookup:** `voice_persona.py:287`, `voice_persona_helpers.py:211/614/821`, and `heartbeat_poker_commons_gateway.py:174` — route per the decision rule (structured → `canonical_persona_key`; if the compared value is genuine spoken free-text recipient → `normalize_for_match`).
- **manager_figure.py:95** (declared-manager membership) → `canonical_persona_key`.
- **Backfill probe (guarded):** query the store for any `owner_persona`/`accountable_manager` that isn't already canonical (uppercase/accent/punct/double-space); UPDATE the stragglers. Expected near-empty given the 2026-06-18 probe.
- **Flip tests** at each seam: neutralize the fix (revert to `.lower()`/`_norm_persona`) → the María/Mr. Radio assertion must fail.

### Phase 3 — Slug unification (carries persisted-name risk — land after Ph1–2 bake)
- `stop.py:_dm_topic_for` + `cosa_voice_mcp.py:_dm_topic` → `f"dm-{persona_slug(name, sep='_')}"` (both already agree with each other; now also accent-proof).
- Audit `session_spawner._slug` callers: persona-derived names → `persona_slug(sep='-')`; leave general-text slugging on `_slug`.
- **Migration sweep (likely no-op):** live bridges hold pool form, so existing topics are almost certainly already `dm-maria`/`dm-mr_radio` → new slug identical. Run a one-time sweep that lists `dm-*` topic files + persona-named tmux sessions, compares each to `persona_slug(owner)`, and renames any mismatch. Do the cutover in a quiet window; confirm DM-topic TTL so residual mismatches self-heal.

### Phase 4 — Collapse to one name (honor the "one-name rule")
Migrate remaining imports to `lupin_mcp.persona_normalization`; reduce the old `session_bridge`/`commons_persona_matcher` symbols to thin re-export shims (or delete once no caller remains). No second normalizer survives.

---

## Critical files

**New:** `src/lupin_mcp/persona_normalization.py`, `src/tests/unit/test_persona_normalization.py`
**Identity seam:** `task_store_mirror.py`, `task_store_drain.py`, `routers/tasks.py`, `db/repositories/task_repository.py` (verify pass-through), `follow_through_escalation_watcher.py`, `heartbeat_arbiter/{fleet_render,manager_resolver,arbiter_job}.py`, `voice_persona.py`, `voice_persona_helpers.py`, `manager_figure.py`, `heartbeat_poker_commons_gateway.py`
**Re-export shims:** `session_bridge.py`, `commons_persona_matcher.py`
**Slugs (Ph3):** `stop.py`, `cosa_voice_mcp.py`, `session_spawner.py`
**Docs to touch:** `src/docs/fleet-liveness-and-task-store-architecture.md` (persona-key invariant), the 2026-06-18 R&D doc (mark follow-up done), 2026-06-11 arbiter-matching doc.

---

## Verification

> **Execution venue (2026-06-21 amendment):** this work was authored on Rick's
> **laptop**, which has no pytest / `.venv` / Docker. Per Rick's direction, all
> pytest **execution and result validation is deferred to the development server**
> and owned by the **SWE team** after this branch lands there. On the laptop the AI
> validates every changed pure-function via `py_compile` + standalone smoke/parity
> scripts run through the runtime venv (regex/fastapi present); the pytest suites
> below are authored and committed, ready for the SWE team to run. This does NOT
> make Rick the tester — the SWE team + server automation are the testers.

- **Unit (:7999, SWE team runs on server):** `pytest src/tests/unit/test_persona_normalization.py` + every touched suite (`test_session_bridge_persona_key`, `test_commons_persona_matcher`, `test_follow_through_escalation_watcher`, `test_stop_hook_heartbeat`, arbiter unit). `py_compile` on each edited file. **100% lines/branches/functions** (Lupin mandate) with flip tests.
- **Smoke (:7999):** stop-hook heartbeat + `test_heartbeat_arbiter_integration`.
- **Protocol E2E (:7999 API):** submit owed work as `María`/`Mr. Radio` via `/api/push`, drive a Stop event, assert the owed-oracle finds the rows and the beacon does **not** false-idle; `GET /api/queue/pool-status` + arbiter fleet render shows correct `role`.
- **Integration + E2E UI (:8000, scheduled, self-authorized on verified-idle):** `run-integration-tests.sh --bg` (FINAL gate) + `run-e2e-ui-tests.sh --bg` after Phase 2, and again after Phase 3's slug cutover. Submit via `POST /api/test-suite/submit`.
- **Store backfill audit:** before/after row counts per `owner_persona` to prove no rows orphaned.

---

## Risks & mitigations
- **`normalize_for_match` accent-fix changes one assertion** → intended; update the test, call it out in the commit.
- **Arbiter role-match swap to keep-spaces** → symmetric on both compare sides, so equivalence is preserved while the value gains store-key parity; covered by flip tests.
- **Slug migration could orphan in-flight DM topics/sessions** → why Phase 3 is decoupled and gated behind a (likely no-op) rename sweep + quiet-window cutover; common case is byte-identical because bridges hold pool form.
- **`stop.py` is the live Stop hook on the server** — per the 2026-06-18 constraint, hook-file edits on the live fleet machine must be made in a worktree; on this hook-less dev clone the main tree is safe.

---

## Implementation status & handoff (2026-06-21)

Authored on Rick's laptop; pytest execution delegated to the SWE team on the dev server.

### ✅ Done & locally parity-validated
- **Phase 0** — this plan doc, relocated to its own home `src/rnd/v0.1.9/2026.06.19-persona-name-normalization/` (with a `README.md` index) and committed on `wip-v0.1.9-2026.06.19-bug-fixing`.
- **Phase 1 — Foundation:**
  - `src/lupin_mcp/persona_normalization.py` — new home: `canonical_persona_key` (moved verbatim), `normalize_for_match` (= root minus spaces), `persona_slug` (= root, spaces→sep) + `quick_smoke_test`.
  - `src/tests/unit/test_persona_normalization.py` — full unit coverage (identity/match/slug, idempotency, edge cases, cross-primitive consistency).
  - `session_bridge.canonical_persona_key` → delegates to the new home (dropped now-unused `import unicodedata`).
  - `commons_persona_matcher._normalize_for_match` → pure alias of the new `normalize_for_match` (dropped now-unused `import re`); `match_persona` rides the shared root.
  - `test_commons_persona_matcher.py` accent assertion updated (`"María"`→`"maria"`, the intended fix).
  - Local validation: `py_compile` clean on all edited files; a 10-check parity script confirms delegation, the accent-fix alias identity, `match_persona` resolution, and slug forms.

### ⬜ Remaining (not yet implemented)
- **Phase 2 — Identity-key centralization (the actual bug fix):** write seam (`task_store_mirror`/`task_store_drain` `_identity()`), `/api/tasks` router boundary, arbiter (`fleet_render`/`manager_resolver`/`arbiter_job`), escalation watcher (retire `_norm_persona`), voice-persona dedup/helpers, `manager_figure`, commons gateway; store backfill probe; flip tests at each seam.
- **Phase 3 — Slug unification:** `_dm_topic_for` / `_dm_topic` / `session_spawner` persona path → `persona_slug`; persisted-name migration sweep.
- **Phase 4 — Collapse + docs:** migrate remaining imports to the new home, reduce shims; update `fleet-liveness-and-task-store-architecture.md` + the 2026-06-18 / 2026-06-11 R&D docs.

### SWE-team test checklist (run on server, in PR-merge order)
1. Unit (`:7999`): the suites listed in §Verification, `--cov-fail-under=100` on touched `cosa` surface.
2. WebSocket smoke (`:7999`).
3. Protocol E2E (`:7999` API): submit owed work as `María` / `Mr. Radio`, drive a Stop event, assert owed-oracle finds rows and no false-idle.
4. Integration + E2E UI (`:8000`, scheduled): final merge gate.
