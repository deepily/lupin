# Row 011f1f90 — arbiter repo-root hold visibility: source interface (FROZEN)

**Author:** Clayton (Implementer) · **Reviewer gate:** Rachel · **Tests:** Tiffany · 2026-08-06

The correctness bug: the arbiter's honored-hold **veto** read holds from `fleet_data_root` only, so a
hold leaked to a repo root was invisible → the parked session got poked forever. Fix: the veto now reads
via the session's **own bridge cwd**, so a repo-root hold in *any* project is found. Paired with a
first-class **location** signal so the fix can't silence the leak (a now-functioning misplaced hold is
still flagged).

## Source touched (4 files — all landed, compile-clean, branch-smoked)

### 1. `src/lupin_cli/claude_code/hooks/lib/heartbeat_hold.py`
- **NEW `read_hold_via_bridge( session_id, log_fn=None )`** — resolves the session's cwd from its bridge
  (`find_session_by_id`, guarded `( … or {} )`), then `read_hold_resilient( sid, cwd )`.
  - Whenever cwd resolves to **None**, and `log_fn` is provided, emits **one** journal event
    `arbiter_hold_reader_cwd_fallback` with `session_id` + `reason ∈ {no_bridge, bridge_without_cwd, bridge_error}`.
  - cwd-**present** path never logs (no per-tick noise). Never raises. `log_fn=None` → no crash.
- **NEW `hold_correct_zone( swept_roots=None )`** → `fleet_data_root().parent` resolved, or `None` on
  failure or when the zone is unsafe. TWO fail-closed guards (Rachel/Mr Radio 2026-08-06):
  - **floor** — `len(zone.parts) < 2` (a filesystem root `/` is an ancestor of every path). Cheap; catches `/` only.
  - **structural** (Mr Radio's ruling — structural over magic number) — when `swept_roots` is provided,
    the zone is too broad if ANY swept repo root sits under it (e.g. `DEEPILY_DATA_DIR=/mnt` → `/mnt` is an
    ancestor of `/mnt/DATA01/.../<repo>`, which the parts-count can't catch), **EXCLUDING** `fleet_data_root`'s
    own subtree (which legitimately lives under the zone). `report_hold_files` passes `roots_swept` in.
  A `None` return means "cannot judge" → the caller surfaces it loudly (see the unjudged event).
- **NEW `hold_is_misplaced( path, correct_zone )`** → `True` iff `path` is outside `correct_zone`;
  fail-safe `False` on `None` zone or unresolvable path (never over-flags).
- **`report_hold_files()` return CHANGED**: each `files` row gains `"misplaced": bool`; the return gains
  top-level `"misplaced_paths": [...]`, `"location_zone": str|None`, and `counts["misplaced"]: int`.
  `location_zone is None` means the zone was UNJUDGEABLE (unresolved/shallow) — the caller must treat that
  distinctly from a real `misplaced == 0`. Location is **not** folded into `cargo_bearing`.

### 2. `src/lupin_arbiter_app/fleet_arbiter_loop.py` (the LIVE :8001 path)
- Import changed to `read_hold_via_bridge` (was `read_hold as _default_hold_reader`).
- Factory default: `hold_reader_fn = hold_reader_fn if not None else ( lambda sid: read_hold_via_bridge( sid, log_fn=log_fn ) )`.
- `_sweep_hold_files` now logs `location_zone` + `misplaced=counts["misplaced"]` +
  `misplaced_paths=report["misplaced_paths"]` in the `fleet_arbiter_hold_report` line, AND emits a
  **distinct** `fleet_arbiter_hold_location_unjudged` event when `report["location_zone"] is None` (so a
  fail-closed zone never masquerades as "no leaks" — mirrors the existing no_roots distinct-event pattern).

### 3. `src/cosa/rest/arbiter_bootstrap.py` (gated-OFF rollback path) — parity
- `hold_reader_fn = read_hold_via_bridge` (log_fn omitted — no journal wiring on this dead path).

### 4. `src/scripts/run-heartbeat-arbiter.py` (manual dev runner) — parity
- `hold_reader_fn = read_hold_via_bridge` (log_fn omitted).

## Failing tests → Tiffany updates (5, all expected)

| Test | Why it breaks | Update |
|---|---|---|
| `test_lupin_arbiter_app_fleet_arbiter_loop.py` — `_report()` helper (lines ~39–51) | fake report lacks `counts["misplaced"]`, `misplaced_paths`, AND `location_zone` → `_sweep` KeyErrors → the report event never fires | add `"misplaced": misplaced` to `counts`, top-level `"misplaced_paths"`, and top-level `"location_zone"` (default a deep str; parameterize for the shallow test) — one helper edit fixes the 3 sweep tests |
| `test_sweep_emits_UNCONDITIONALLY…` / `test_sweep_SWEPT_ZERO_ROOTS…` / `test_sweep_report_carries…` | (same helper) | covered by the helper edit; add assertions on the new `misplaced` fields |
| `test_build_factory_wires_real_hold_reader_by_default` (line ~479) | default is now a lambda, not `read_hold` | replace `is read_hold` identity with a **behavioral** assertion (call it; assert it delegates / fallback logs). The `is fake` override test (line ~490) still passes — keep it |
| `test_arbiter_bootstrap.py::test_build_arbiter_job_wires_real_hold_reader` (line ~185) | now `read_hold_via_bridge` | update the identity assertion |

## New tests Rachel REQUIRES (2 controls + branch coverage)

- **Control A — bridge-present**: parked live session self-declaring `work_owed=false` + repo-root hold +
  bridge carrying that repo's cwd → veto **FIRES** (session subtracted, no poke). Then repoint the reader
  at the old fleet-only `read_hold` → assert it **DOES** poke (proves teeth). Predicted failure under the
  old reader, **inline as the assert message**: `assert 'clayton' not in {'clayton'}`.
- **Control B — bridge-less**: parked session + LUPIN_ROOT hold + **no resolvable bridge** → veto **STILL
  FIRES**. Same predicted failure text inline.
- **Control C — unjudgeable zone fails LOUD (Rachel/Mr Radio MUST-FIX)**: monkeypatch `fleet_data_root` so
  the zone is unsafe, TWO ways — (i) shallow: `/lupin` → parent `/`; (ii) structural: `/mnt/lupin` with a
  swept repo root `/mnt/DATA01/.../<repo>` under the `/mnt` zone. In each, assert `hold_correct_zone(...)`
  returns `None` (refuses to judge), the report's `location_zone` is `None`, and `_sweep_hold_files` emits
  the distinct `fleet_arbiter_hold_location_unjudged` event — proving an unjudgeable zone fails LOUD, not
  silently False-for-all.
- **Branch coverage** (100% lines+branches+functions on touched files):
  - `read_hold_via_bridge`: bridge+cwd (no log) · `no_bridge` · `bridge_without_cwd` · `bridge_error` · `log_fn=None` (no crash).
  - `hold_is_misplaced`: misplaced `True` · not-misplaced `False` · `None` zone · unresolvable path.
  - `hold_correct_zone`: deep-zone success (`swept_roots=None`, floor only) · shallow zone (`< 2` parts) → `None`
    · resolution exception → `None` · **structural: a swept repo root under the zone → `None` (unsafe)** ·
    **clean zone (repos in the sibling tree) → zone (safe)** · **`fleet_data_root`-subtree exclusion (only fdr
    under the zone → safe)** · an unresolvable entry in `swept_roots` is skipped (no crash).
  - `report_hold_files`: `misplaced` field + `location_zone` populated (deep) and `None` (shallow).
  - `_sweep_hold_files`: misplaced logging AND the `location_zone is None` → distinct-event branch.

## Known gap (named, NOT scoped away) — for the row
Option B (bridge cwd) closes planning-is-prompting + worktree repo-root holds. The residual: a session with
**no resolvable bridge** (dead-PID prune, id-form mismatch) falls to cwd=None → catches LUPIN_ROOT +
fleet_data_root only. That fallback is now **logged** (`arbiter_hold_reader_cwd_fallback`), so it's visible,
not silent. The mtime liveness signal (`arbiter_job.py:461`, `hold_path` fleet-only) stays fleet-only — it's
additive, not the veto — flagged, not fixed here.
