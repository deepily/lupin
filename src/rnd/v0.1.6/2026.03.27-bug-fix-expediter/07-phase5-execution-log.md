# Plan: Bug Fix Expediter Phase 5 — Trust Proxy + Git Strategy

## Context

BFE Phases 2-4 (Diagnose → Propose → Fix) landed in Session 384 (2,602 tests passing). Phase 5 closes the loop: after a successful fix, the orchestrator commits changes to git and — when trust level permits — pushes a branch + opens a PR. **Current state**: `run_fix()` completes, writes the fix to disk, and then nothing happens. No commit, no branch, no PR. Meanwhile the Phase 5 plan doc is finalized (`06-phase5-trust-proxy-git-strategy-plan.md`) and marks this as "Execute first thing next session."

**Outcome**: A completed BFE fix ends with either (a) a commit on the current branch, or (b) a new `fix/YYYY-MM-DD-{slug}` branch + PR via `gh`, determined by the trust proxy's read of the engineering trust level. The plan doc footer gains a populated **Git References** section. Zero behavior change when `trust_mode = shadow` (default).

**Outcome boundary**: This plan implements Phase 5 ONLY. End-to-end live-fire BFE testing (diagnose → propose → fix → **commit/PR**) is unlocked by this work but is a separate follow-up.

---

## Critical Files

### New files (3)

| File | Purpose |
|---|---|
| `src/cosa/agents/bug_fix_expediter/git_ops.py` | Async git operations module — commit/branch/push/PR. Never raises; returns dicts. |
| `src/tests/unit/test_bfe_git_ops.py` | ~8 tests with mocked `asyncio.create_subprocess_exec` |
| `src/tests/unit/test_bfe_phase5.py` | ~10 tests covering proxy init, run_git_strategy, plan writer update |

### Modified files (6)

| File | Change |
|---|---|
| `src/cosa/agents/bug_fix_expediter/state.py` | Add `COMMITTING = "committing"` to `BFEPhase`; extend `FixResult` with `git_strategy`, `commit_hash`, `branch_name`, `pr_url` (all `Optional[str]=None`); bump smoke-test assertion `len(BFEPhase) == 9 → 10` |
| `src/cosa/agents/bug_fix_expediter/config.py` | Add `trust_mode: str = "shadow"` field + `"trust_mode": "bug fix expediter trust mode"` mapping |
| `src/conf/lupin-app.ini` | Add `bug fix expediter trust mode = shadow` under `[Lupin: Baseline]` |
| `src/conf/lupin-app-splainer.ini` | Matching splainer entry |
| `src/cosa/agents/bug_fix_expediter/plan_writer.py` | Add `Git References` placeholder to `_render_footer()`; add `update_git_references(plan_path, fix_result)` method |
| `src/cosa/agents/bug_fix_expediter/orchestrator.py` | Constructor: init `self.proxy` + `self.last_files_changed=[]`; `run_fix()`: store `files_changed` on self at end; NEW `run_git_strategy()` method; extend `_voice_gate_proposal()` with shadow-mode proxy auto-select (active-mode only) |
| `src/cosa/agents/bug_fix_expediter/job.py` | After `run_fix()` completes (~line 244), call `orchestrator.run_git_strategy(fix_result, orchestrator.last_files_changed, plan_path)` and re-dump artifacts |

---

## Reusable Components (DO NOT REIMPLEMENT)

- **Async subprocess pattern** — copy from `src/cosa/agents/test_suite/test_runner.py:124-128` and `src/cosa/agents/swe_team/dispatcher.py:281-287`. Use `asyncio.create_subprocess_exec(*args, ...)` wrapped in `wait_for(timeout=30)`.
- **SWE trust proxy** — `src/cosa/agents/swe_team/proxy/engineering_strategy.py` (EngineeringStrategy class). Constructed with `trust_mode`, `accepted_senders`, auto-creates `TrustTracker` + `CircuitBreaker`. `gate()` returns `"shadow" | "suggest" | "act" | "defer"`.
- **Trust-proxy config factory** — `src/cosa/agents/swe_team/proxy/config.py::swe_proxy_config_from_config_mgr()` reads INI keys. BFE can either reuse this or define its own analogous helper; reusing is simpler.
- **TrustTracker** — `src/cosa/agents/decision_proxy/trust_tracker.py`. `.level` property returns 1-5.
- **Sync git reference** (do NOT reuse directly; convert to async pattern) — `src/cosa/agents/.../git_diff_parser.py:86-155`.

---

## Trust-to-Git Mapping

| Trust Level | Mode | Git Strategy | Rationale |
|---|---|---|---|
| L1 (shadow) | passive | `commit_only` on current branch | Baseline trust — single-author safe commit |
| L2 (suggest) | passive | `commit_only` on current branch | Reviewing mode — still don't branch unprompted |
| L3+ (active) | active | `branch_and_pr` via `gh` | Trusted — create `fix/YYYY-MM-DD-{slug}` branch + PR |
| Proxy unavailable | — | `commit_only` | Conservative fallback |
| `gh` CLI missing | — | Degrade L3+ → `branch_only` | Branch + commit + push succeed; PR step skipped with a notification |

---

## git_ops.py API (new module)

```python
class GitOps:
    def __init__( self, cwd=None, timeout_secs=30, debug=False )

    async def _run_git( self, *args ) -> dict:
        # {"success": bool, "stdout": str, "stderr": str, "returncode": int}
    async def get_current_branch( self ) -> str
    async def commit_on_branch( self, files_changed, commit_message ) -> dict:
        # {"success": bool, "commit_hash": str|None, "error": str|None}
    async def create_fix_branch( self, slug ) -> dict:
        # {"success": bool, "branch_name": str|None, "error": str|None}
    async def commit_and_push( self, branch, files_changed, commit_message ) -> dict:
        # {"success": bool, "commit_hash": str|None, "error": str|None}
    async def create_pr( self, branch, title, body ) -> dict:
        # {"success": bool, "pr_url": str|None, "error": str|None}
    async def checkout_branch( self, branch ) -> dict
```

All methods return dicts. Never raise. On failure populate `error`. On `create_pr` gracefully degrade if `gh` missing (detect via `which gh` first call, cache result).

---

## Execution Phases

### Phase 5.0 — Serialize plan next to design doc
Per CLAUDE.md plan-serialization rule: copy this plan to `src/rnd/v0.1.6/2026.03.27-bug-fix-expediter/07-phase5-execution-log.md` (next to the existing `06-phase5-trust-proxy-git-strategy-plan.md` design doc — keeps all Phase 5 docs together). The `06-*` doc is the DESIGN; `07-*` is the EXECUTION log with status per phase.

### Phase 5.1 — Data model changes (state.py + config.py + INI) — INDEPENDENT
- Add `COMMITTING` phase, git fields on `FixResult`, bump assertion.
- Add `trust_mode` config field + key_map entry + INI pair + splainer entry.
- Post-edit: `py_compile` on each, run their `quick_smoke_test()` via `python -m cosa.agents.bug_fix_expediter.state` and `python -m cosa.agents.bug_fix_expediter.config`.

### Phase 5.2 — git_ops.py — INDEPENDENT
- Write the module per the API above + an inline `quick_smoke_test()` that mocks subprocess.
- Compile + smoke: `python -m cosa.agents.bug_fix_expediter.git_ops`.

### Phase 5.3 — plan_writer.py — INDEPENDENT
- Extend footer template with `## Git References` placeholder.
- Add `update_git_references(plan_path, fix_result)` — reads file, replaces placeholder with 4-line block (Strategy/Commit/Branch/PR), writes back. Silently no-op if plan file missing or placeholder already replaced.
- Compile + smoke.

### Phase 5.4 — test_bfe_git_ops.py (~8 tests) — INDEPENDENT
Mock `asyncio.create_subprocess_exec`. Cover:
- `_run_git` success + failure
- `commit_on_branch` success + empty-files guard
- `create_fix_branch` slug formatting
- `commit_and_push` sequence (add → commit → push)
- `create_pr` success + `gh` unavailable degrades to `branch_only`

### Phase 5.5 — orchestrator.py — DEPENDS ON 5.1-5.4
- Constructor: try-except import trust proxy; set `self.proxy` (or `None`) + `self.last_files_changed = []`.
- `run_fix()`: store `self.last_files_changed = files_changed` right before return.
- NEW `run_git_strategy(fix_result, files_changed, plan_path)` — orchestrates the commit/branch/PR flow with voice notifications, state transitions FIXING → COMMITTING → COMPLETED, and plan-writer call at end.
- `_voice_gate_proposal()`: add shadow-safe proxy auto-select block — ONLY fires when `proxy.trust_mode == "active"` AND `trust_level >= 3` AND single-fix with confidence >= 0.8. Default shadow mode = no behavior change.
- `_generate_slug(text)` static helper: lowercase, strip non-alphanumeric, first 3 words, prefix with `fix/YYYY-MM-DD-`.
- Compile + smoke.

### Phase 5.6 — job.py wiring — DEPENDS ON 5.5
- After line 244 (`self.artifacts["fix_result"] = fix_result.model_dump()`), add the Phase 5 block that calls `run_git_strategy()` and re-dumps artifacts.
- Compile + smoke.

### Phase 5.7 — test_bfe_phase5.py (~10 tests) — DEPENDS ON 5.5-5.6
Cover:
- Proxy init in shadow mode (default config)
- Proxy init ImportError falls back to `None` gracefully
- `run_git_strategy` skips when `fix_result.success == False`
- `run_git_strategy` skips when `files_changed` is empty
- L1 trust → `commit_only` strategy
- L3 trust → `branch_and_pr` strategy
- `_voice_gate_proposal` shadow mode falls through (no auto-select)
- `_voice_gate_proposal` active + L3 + single high-confidence → auto-selects
- `FixResult` git fields populated after success
- `plan_writer.update_git_references` rewrites placeholder correctly

### Phase 5.8 — Verification
- Full regression: `pytest src/tests/unit/ -q` — expect existing 2,602 + ~18 new = ~2,620 passing.
- Targeted: `pytest src/tests/unit/test_bfe_*.py -v`.
- Smoke chain: each BFE module's `quick_smoke_test()` via `python -m cosa.agents.bug_fix_expediter.{state,config,git_ops,plan_writer,orchestrator,job}`.
- Shadow-mode safety: verify `trust_mode=shadow` (default) results in `commit_only` strategy across tests — no branches created in test env.

---

## Parallelism Map

```
5.0 (serialize plan)
  ↓
5.1 ┐
5.2 ├─ parallel (all independent)
5.3 │
5.4 ┘
  ↓
5.5 (orchestrator — needs 5.1-5.4)
  ↓
5.6 (job.py — needs 5.5)
  ↓
5.7 (phase5 tests — needs 5.5-5.6)
  ↓
5.8 (verification)
```

---

## Verification Steps (final gate)

1. `python -c "import py_compile; [py_compile.compile(p, doraise=True) for p in ['src/cosa/agents/bug_fix_expediter/git_ops.py','src/cosa/agents/bug_fix_expediter/state.py','src/cosa/agents/bug_fix_expediter/config.py','src/cosa/agents/bug_fix_expediter/plan_writer.py','src/cosa/agents/bug_fix_expediter/orchestrator.py','src/cosa/agents/bug_fix_expediter/job.py']]; print('OK')"`
2. `python -m cosa.agents.bug_fix_expediter.git_ops` → PASS
3. `python -m cosa.agents.bug_fix_expediter.state` → PASS (new assertion count 10)
4. `python -m cosa.agents.bug_fix_expediter.orchestrator` → PASS (trust proxy init logs)
5. `pytest src/tests/unit/test_bfe_git_ops.py -v` → 8/8
6. `pytest src/tests/unit/test_bfe_phase5.py -v` → 10/10
7. `pytest src/tests/unit/test_bfe_*.py -v` → full BFE suite green (no existing-test regressions)
8. Grep plan file: any newly-written plan should show `## Git References` with 4 populated lines after a successful dry-run fix.

---

## Defaults Applied (override at execution if needed)

1. **Plan serialization** → `src/rnd/v0.1.6/2026.03.27-bug-fix-expediter/07-phase5-execution-log.md` (next to design doc, parent Lupin repo).
2. **Unit tests INCLUDED in this session** (Phases 5.4 + 5.7) — user asked whether BFE is "finished and awaiting testing", so shipping without tests would leave it un-finished.
3. **Full regression run** via `pytest src/tests/unit/ -q` as the final gate (Phase 5.8).

---

## Non-Goals / Out of Scope

- **Live-fire BFE end-to-end run** (real bug → real fix → real PR) — separate follow-up
- **CoSA nested-repo commit strategy** — Phase 5 commits land in the parent Lupin repo by default; if `cwd` happens to be inside `src/cosa/`, git operations will apply to COSA repo as-is (user responsibility to cd into the right repo before BFE triggers)
- **Theme/workflow changes to `_voice_gate_proposal`** beyond the small shadow-safe auto-select block
- **New trust categories** — BFE uses `"engineering"` category (shared with SWE team)
- **Circuit-breaker integration beyond init** — just wire it up per the existing pattern; actual tripping/recovery logic lives in the proxy

---

## Risk Notes

1. **Trust proxy import failure** — wrapped in try/except; falls back to `self.proxy = None` → always L1 → `commit_only`. Safe default.
2. **`gh` CLI missing in user env** — `create_pr` detects and degrades; branch + push still succeed.
3. **Committing wrong files** — `files_changed` is sourced from `orchestrator.run_fix()` which has the authoritative list. git_ops does `git add <files>` explicitly (no `git add .`).
4. **Wrong current-branch baseline** — `get_current_branch()` captures original before checkout; we checkout back at end.
5. **Plan doc placeholder drift** — `update_git_references()` silently no-ops if placeholder not found (backward-compatible with older plan docs that predate this phase).
