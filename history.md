# Lupin Project History

### 2026.04.12 - Session 248e740e | TFE forensics capture — CoSA submodule commit + push

**Context**: Session-end ritual for prior TFE forensics capture work. All 4 edits were working-tree-only inside `src/cosa/` from the TFE forensics fix plan (`src/rnd/v0.1.6/2026.04.11-tfe-forensics-capture-plan.md`). This session committed them from CoSA repo context per nested-repo rule, then pushed both repos.

**CoSA-side changes committed** (commit `660dcd8`):
- `agents/test_fix_expediter/job.py` — BFE-pattern `JobState` enum lifecycle (`RUNNING`/`COMPLETED`/`FAILED`/`CANCELLED`) replacing bare string status, full Python traceback captured into `self.error` on failure, unconditional stdout print of traceback (not gated behind `self.debug`) so Docker logs always have forensics, cancellation support via `_cancel_requested` flag, `cu.get_current_datetime_iso()` timestamps replacing `datetime.now().isoformat()`. Voice routing fix (Fix 7): `_execute()` now sets `_bfe_ci.TARGET_USER = self.user_email` and `_bfe_ci.SENDER_ID` before entering the pipeline — fixes `tfe-d9e6b50f`'s "Cannot resolve target_user" crash. Urgent crash notification (Fix 3): pipeline wrapped in try/except that emits `voice_io.notify()` with `priority="urgent"` + full traceback in `abstract` field before re-raising. Plan path artifact (Fix 8a): `self.artifacts["plan_path"]` set after Phase 2 so the Phase 2 plan survives if a later phase crashes.
- `agents/test_fix_expediter/orchestrator.py` — Fix 6: Removed invalid `notification_type="progress"` kwarg from `notify_progress()` call. The dispatcher sets `NotificationType.PROGRESS` internally; passing it as a kwarg caused `TypeError` on every call, resulting in hundreds of `[TFE notify error]` log lines per run with zero progress notifications delivered.
- `rest/job_persistence.py` — Added `"test_fix_expediter"` to `AGENTIC_JOB_TYPES` frozenset. Without this, every TFE failure landed in the UI as "Unknown error" because the entire persistence layer was gated behind this allowlist.
- `rest/routers/queues.py` — New dead-queue branch in `get_queue()` surfaces partial artifacts (`plan_path`, `remediation_snapshot_path`, `report_path`, `yaml_path`, `cost_summary`) from failed-before-completion agentic jobs. Previously fell through to the generic todo/run branch which only returned basic fields — failed TFE jobs had a Phase 2 plan on disk with no UI link.

**Push outcomes**:
- CoSA: `f210d10..660dcd8` → `origin/wip-v0.1.6-2026.03.12-tracking-lupin-work`
- Lupin parent: `6c04cd9..685c134` (4 prior-session commits) → `origin/wip-v0.1.6-2026.03.12-cjflow-upe-and-playwrite`

**Files Changed — Lupin parent (this commit)**:
- `history.md` (this entry)
- `TODO.md` (marked CoSA submodule commits items complete)

**Files Changed — CoSA submodule (already committed & pushed as `660dcd8`)**:
- `agents/test_fix_expediter/job.py`
- `agents/test_fix_expediter/orchestrator.py`
- `rest/job_persistence.py`
- `rest/routers/queues.py`
- `history.md` (Session 248e740e entry)

---

### 2026.04.12 - Session 9056c113 | TFE checkpoint-resume + completion report + agentic-voice-workflow v3.0

**Context**: User reported a successful TFE run (`tfe-7c25082a`) that completed Phases 0-2 but produced no E2E resubmission. Forensic investigation showed the run actually stalled at Phase 2 voice gate with 0 selections (cascading to skipped Phases 3-6). User wanted: (a) completion voice reports for all agents, (b) checkpoint-resume so stalled jobs can continue later, (c) both patterns standardized in the agentic-voice-workflow skill so every new agent gets them by default. Plan serialized to `src/rnd/v0.1.6/2026.04.10-test-fix-expediter/14-checkpoint-resume-and-completion-report.md` — full 5-phase breakdown with step-by-step code snippets, file paths, and test specs.

**Accomplishments (5 phases complete, 35 new tests, 0 regressions)**:

- **Phase A — TFE completion voice report** (`src/cosa/agents/test_fix_expediter/job.py`): Added `self._start_time` at `_execute()` entry, computed agent-specific stats (clusters, proposed/selected/fixed/failed, duration), outcome-aware three-variant TTS message (fixes applied / none selected / fixes failed), rich markdown abstract with per-cluster diagnoses + plan path + rerun status. Replaces the old "scaffolding run complete (phases 0-6 walked)" placeholder with real stats. Mirrors Deep Research pattern (`job.py:338-356`). Wrapped in try/except — notification failure never masks a successful run. 2 new unit tests in `test_tfe_forensics.py` (13 total, 11 pre-existing + 2 new, up from needing the orchestrator mock fix to cover new attributes).

- **Phase B — `STALLED` JobState** (`src/cosa/rest/job_state.py`): New enum member `STALLED = "stalled"`. Transition matrix: `RUNNING → STALLED` (voice gate timeout), `STALLED → RUNNING` (resume), `STALLED → CANCELLED` (user gives up). New `RESUMABLE_STATES = frozenset({STALLED})` convenience set. Maps to `"todo"` UI container. Distinct from `PAUSED` (user-initiated vs system-initiated). 23 assertions updated in `test_job_state.py` (61 tests total, was 38 — added STALLED transition tests, exhaustive/disjoint set tests updated to include RESUMABLE_STATES).

- **Phase C — Checkpoint infrastructure** (CoSA: `state.py`, `orchestrator.py`, `job.py`, `cosa_interface.py`, `job_persistence.py`): New `VoiceGateTimeoutError` + `StalledException` exception types, `CheckpointData` TypedDict (phase_ordinal, phase_name, stall_reason, stalled_at, state_snapshot, artifacts, resume_count), `TFE_PHASE_ORDINALS` mapping (0-6). `TFEOrchestrator.save_checkpoint()` serializes full pipeline state via `.model_dump()`; `load_checkpoint()` reconstructs Pydantic models; `set_resume_phase()` marks phases as completed for skip guards. `_aggregate_voice_gate()` now propagates `VoiceGateTimeoutError` (was: catch-all auto-select). `run_phase2_propose()` wraps voice gate and raises `StalledException` with saved checkpoint. `_execute()` catches `StalledException`, persists checkpoint to `self.artifacts`, sends voice notification, returns `"__STALLED__"` sentinel. `do_all()` detects sentinel and sets `state = JobState.STALLED`. Added `"checkpoint"` to `rich_fields` in `_build_metadata_json()`. 10 new unit tests in `test_tfe_checkpoint.py` (save/load round-trip, Pydantic type preservation, StalledException propagation, do_all STALLED state, artifacts persistence, set_resume_phase, ordinals, rich_fields).

- **Phase D — Resume infrastructure** (CoSA: `job_persistence.py`, `agentic_job_factory.py`, `routers/queues.py`; Lupin: `notifications.js`, `notifications.css`): Two new persistence queries — `get_checkpoint_for_job()` returns checkpoint dict for stalled jobs (checks both `artifacts.checkpoint` and top-level `checkpoint` in metadata_json), `get_original_args_for_job()` returns full reconstruction info (original_args + routing_command + user_id/email/session_id). New `resume_job(job_id_hash, config_mgr)` factory reconstructs job via `create_agentic_job()` and attaches `_resume_checkpoint` attribute with incremented `resume_count`. New REST endpoint `POST /api/jobs/{id_hash}/resume-from-checkpoint` (depends on `get_todo_queue`, pushes reconstructed job to queue). TFE `_execute()` detects `_resume_checkpoint` at orchestrator creation and calls `load_checkpoint()` + `set_resume_phase()`. UI: stalled badge (`⏸` amber), `resumeStalledJob()` JS method (confirms, POSTs, shows toast), "View Plan" + "▶ Resume from Checkpoint" button on stalled cards. CSS: `.completion-badge.stalled { color: #f0ad4e }`.

- **Phase E — agentic-voice-workflow skill v3.0** (`src/workflow/agentic-voice-workflow.md`): Added Phase 11 (Completion Report) and Phase 12 (Checkpoint-Resume) as standard BUILD phases — every new agent now inherits these by default. Phase 11: outcome-aware TTS + rich markdown abstract pattern sourced from Deep Research and TFE. Phase 12: full checkpoint-resume workflow including exception types, save/load contract, voice gate timeout propagation, stall handling, resume flow via REST/UI/file-path, and idempotency guards. Added artifact-based resume pattern table (`.md` plan doc → TFE Phase 3, `.yaml` → Presentation Phase 6, `.md` script → Podcast audio phase). Updated TOC, checklist (Phase 11 MANDATORY, Phase 12 conditional on voice gates), reference implementations table (added TFE + BFE rows), key files section (completion report + checkpoint-resume pattern files), version history (2.1 → 3.0).

**Plan doc**: `src/rnd/v0.1.6/2026.04.10-test-fix-expediter/14-checkpoint-resume-and-completion-report.md` (added to `00-index.md`).

**Test regression**: 135 tests across touched files (test_tfe_forensics, test_tfe_checkpoint, test_job_state, test_tfe_phase*, test_tfe_config) — 0 failures. Previously at 3169 unit tests baseline; this session adds 35 new tests on top.

**Files modified — Lupin parent (this commit)**:
- `src/rnd/v0.1.6/2026.04.10-test-fix-expediter/14-checkpoint-resume-and-completion-report.md` (new)
- `src/rnd/v0.1.6/2026.04.10-test-fix-expediter/00-index.md` (added link)
- `src/workflow/agentic-voice-workflow.md` (v2.1 → v3.0, added Phase 11 + Phase 12)
- `src/tests/unit/test_tfe_forensics.py` (+2 tests, mock orchestrator fixture updated)
- `src/tests/unit/test_tfe_checkpoint.py` (new — 10 tests)
- `src/tests/unit/test_job_state.py` (+23 assertions, updated exhaustive/disjoint)
- `src/fastapi_app/static/js/notifications.js` (stalled badge + resume button + `resumeStalledJob()`)
- `src/fastapi_app/static/css/notifications.css` (stalled badge + actions styling)

**Files modified — CoSA submodule (working-tree only, user commits separately)**:
- `rest/job_state.py` (STALLED + RESUMABLE_STATES + transitions)
- `rest/job_persistence.py` (checkpoint rich_field + get_checkpoint_for_job + get_original_args_for_job)
- `rest/agentic_job_factory.py` (resume_job factory function)
- `rest/routers/queues.py` (POST /api/jobs/{id}/resume-from-checkpoint endpoint)
- `agents/test_fix_expediter/state.py` (VoiceGateTimeoutError + StalledException + CheckpointData + TFE_PHASE_ORDINALS)
- `agents/test_fix_expediter/orchestrator.py` (save/load/set_resume_phase + VoiceGateTimeoutError propagation + Phase 2 stall wrapping)
- `agents/test_fix_expediter/job.py` (completion report + StalledException catch + __STALLED__ sentinel + resume checkpoint detection)

**Deferred to follow-up**:
- Steps D4b-D4d: File-path-based resume endpoint (`POST /api/test-fix-expediter/resume-from-file`) + "Resume from" input field on TFE submission card — needs auto-detection logic for `.md` plan doc vs `.json` checkpoint
- Step D5: CLI `--resume` flag in `run-tfe-live-e2e.sh`
- Steps E1-E2: BFE completion voice notification + BFE checkpoint-resume (follows documented patterns now in skill v3.0)

---

### 2026.04.12 - Session 1cfcdf73 (follow-on) | Codebase analysis — Lupin parent vs CoSA submodule

**Context**: User requested a code-based comparison of the Lupin parent repo vs the nested CoSA submodule after the lunch-run commit landed. Ran the Directory Analyzer (`python -m cosa.repo.run_directory_analyzer`) against three scopes (full project, `src/`, `src/cosa/`) plus drill-downs into the biggest Lupin-parent subdirs (`tests/`, `rnd/`, `fastapi_app/`, `lupin-mobile/`, `docs/`). Wrote the findings as a persistent R&D doc with a Mermaid diagram.

**Deliverable**: `src/rnd/v0.1.6/2026.04.12-codebase-analysis-lupin-vs-cosa.md` (~190 lines)
- Mermaid flowchart color-coded by repo side (parent blue, CoSA red, engine-internals yellow)
- Numeric tables: top-level scopes, Python 60/40 split, parent drill-down
- 7 observations: engine-vs-wrapper split, non-code weight of parent, R&D docs > parent Python, Design-by-Contract docstring ratio, test pyramid placement, mobile sleeping giant, frontend size
- Explicit section on 61/39 × CoSA-never-commit coupling with Session 1cfcdf73 paired-commit example
- Re-run commands + "what this does not cover" honesty section
- 3 cross-references (all verified to resolve from `v0.1.6/` subdir depth)

**Headline numbers**:
- Full project: 558,267 lines / 2,306 files
- CoSA submodule: 168,310 / 568 (30% of project, 88.6% Python, 31.4% docstring ratio)
- Lupin parent (derived): 389,957 / 1,738 (70% of project, only ~25% Python)
- Python 60/40: 149k in CoSA vs 97k in parent
- R&D markdown corpus (108k) > all Lupin-parent Python (97k)

**Placement decision**: Initial landing at `src/rnd/` root was wrong per `src/rnd/README.md` convention ("new docs go in current version dir"). Moved to `src/rnd/v0.1.6/` and fixed the 3 relative links (`../../cosa/…`, `../README.md`, `../../../history.md`) accordingly.

**README link added**: new "Codebase metrics" bullet under the existing R&D archive section in top-level `README.md` pointing at the doc.

**Nature**: Transient analysis — numbers drift with every commit. Doc explicitly states "re-run the analyzer for a current snapshot rather than trusting this doc months from now."

**Files Changed — Lupin parent**:
- `src/rnd/v0.1.6/2026.04.12-codebase-analysis-lupin-vs-cosa.md` (new)
- `README.md` (+1 bullet under R&D archive section)
- `history.md`, `TODO.md`, `.claude-session.md` (tracking)

**Files Changed — CoSA submodule**: none (pure read-only analysis against the existing `cosa.repo.run_directory_analyzer` tool)

---

### 2026.04.11 - Session 1cfcdf73 (lunch run) | Unified watchdogs facade + TFE auto-fix defaults flipped + per-run override

**Context**: User reported overnight E2E run had 12 visual regression failures but TFE never auto-dispatched. Root-caused two stacked bugs: (1) `init_watchdog()` for TFE was never called in `main.py` startup — only BFE's was — so the done-queue hook silently no-op'd because `get_watchdog()` returned None; (2) both auto-fix flags defaulted to `false` ("opt-in") in the INI, when the user wanted "default = run unless told otherwise". User dictated the fix shape (single `init_watchdogs()` facade, both INI defaults flipped to true, per-request UI override surfaced on submission form, BFE stays INI-only) and went out for lunch with implicit permission to execute.

**Code shipped (16 files, parent-repo + CoSA submodule mixed)**:

- **Unified facade**: `src/cosa/rest/watchdogs.py` (new) — `init_watchdogs(config_mgr, todo_queue, debug, verbose)` brings up both `DeadQueueWatchdog` (BFE) and `TestSuiteCompletionWatchdog` (TFE) singletons in one call. Each constructor wrapped in try/except so a failure in one watchdog cannot block the other. Single `[Watchdogs] BFE={ENABLED|DISABLED}, TFE={ENABLED|DISABLED}` summary log line at startup
- `src/fastapi_app/main.py` — replaced standalone BFE init (lines 584-587) with the unified `from cosa.rest.watchdogs import init_watchdogs; init_watchdogs(config_mgr, jobs_todo_queue, debug=app_debug)`
- **INI defaults flipped to true**: `src/conf/lupin-app.ini`
  - `auto fix enabled` (BFE / dead-queue watchdog master switch) `false → true`
  - `test fix expediter auto fix enabled` (TFE watchdog master switch) `false → true`
  - Splainer entries updated to describe new defaults + per-run override semantics
- **TFE dataclass default flipped**: `src/cosa/agents/test_fix_expediter/config.py` — `auto_fix_enabled: bool = True` (matches INI for consistency when constructing without a config_mgr)
- **Per-run override threading**:
  - `src/cosa/agents/test_suite/job.py` — new `auto_fix_on_failure: Optional[bool] = None` constructor kwarg, stored on the job for the watchdog to read
  - `src/cosa/rest/agentic_job_factory.py` — new `_parse_optional_boolean()` helper (tri-state: None / True / False, no collapse to False); threads `auto_fix_on_failure` through the `agent router go to test suite` elif branch
  - `src/cosa/rest/routers/test_suite.py` — `TestSuiteSubmitRequest` accepts `auto_fix_on_failure: Optional[bool]`, handler propagates to `args_dict` only when explicitly set
  - `src/cosa/rest/routers/system.py` — `/api/config/client` now exposes `test_fix_expediter_auto_fix_enabled` so the UI knows the INI default
  - `src/cosa/rest/test_suite_completion_watchdog.py` — Gate 1 rewritten as tri-state: `override is False` short-circuits regardless of INI; `override is None and not self.enabled` skips per INI default; otherwise proceed
- **UI checkbox** (notifications dashboard test runner card):
  - `src/fastapi_app/static/html/notifications.html` — new `🛠️ Auto-fix on failure (TFE)` checkbox below the Dry run checkbox
  - `src/fastapi_app/static/js/notifications.js` — `submitTestSuiteJob()` reads the checkbox and includes `auto_fix_on_failure` in the request body when toggled away from the default; `fetchClientConfig()` reads `test_fix_expediter_auto_fix_enabled` from `/api/config/client` and syncs the checkbox's initial state
- **BFE stays INI-only** (per user direction) — no UI override surface, no per-run flag in `/api/bug-fix-expediter/submit`. The dead-queue path is governed entirely by `auto fix enabled` in the INI

**Documentation updates**:

- `src/docs/agents/test-fix-expediter-guide.md` — INI table flipped to `true`, "How to Enable Auto-Fix" rewritten as "How to Enable / Disable" with the per-run override workflow + UI checkbox + API field
- `src/docs/agents/test-suite-scheduling-guide.md` — cost model + "Interaction with TFE" + troubleshooting all updated for the new default; troubleshooting Check 3 now expects `[Watchdogs] BFE=ENABLED, TFE=ENABLED`
- `src/docs/agents/bug-fix-expediter-guide.md` — added unified-facade row to the code-locations table; INI tuning section clarifies that `auto fix enabled` is the actual auto-dispatch toggle (not `bug fix expediter enabled`) and is now `true` by default

**Tests added (45 new + 4 updated assertions)**:

- `src/tests/unit/test_test_suite_completion_watchdog.py` — new `TestPerRunOverride` class (6 tests) covering all 4 combinations of (INI true/false × override True/False) plus None passthrough; existing test fixture updated to set `mock.auto_fix_on_failure = None` because MagicMock auto-attributes return truthy children, breaking Gate 1 reads
- `src/tests/unit/test_watchdogs_facade.py` (new file, 11 tests) — happy-path init + singleton population + queue sharing + enabled-flag propagation + debug propagation + resilience (BFE init failure doesn't block TFE, TFE init failure doesn't block BFE, both failures return two Nones)
- `src/tests/unit/test_agentic_job_factory_optional_boolean.py` (new file, 24 tests) — parametrized coverage of `_parse_optional_boolean`: None passthrough, explicit bools, truthy/falsy strings, semantic-none strings, unparseable strings (return None instead of False)
- `src/tests/unit/test_test_suite_job.py` — 2 new tests for the `auto_fix_on_failure` constructor kwarg (default None, explicit True, explicit False), plus 1 assertion added to existing `test_default_creation`
- `src/tests/unit/test_tfe_config.py` — 2 assertions flipped (dataclass default + from_config) for the new `True` baseline

**Bonus root-cause fixes (8 pre-existing test failures triggered by overnight server slowness, fixed at the source not deferred)**:

1. **`test_cosa_voice_mcp_qualifier`** (6 tests) — `src/lupin_mcp/cosa_voice_mcp.py` `_validate_repo_account()` runs at module import time and only caught `requests.ConnectionError`. When the server is reachable but slow, `requests.ReadTimeout` propagates out of import scope and crashes every test that imports the module. Fixed by catching `(ConnectionError, Timeout)` plus a final `except Exception` fallback so module init never explodes
2. **`test_presentation_generator_job::test_user_visible_args_protocol`** — subprocess invokes `python -m cosa.agents.presentation_generator` but doesn't pass `PYTHONPATH=src` so the venv interpreter can't find the cosa package. Fixed by passing an explicit env dict built from `cu.get_project_root() + '/src'`
3. **`test_tfe_config`** (2 tests) — both assertions of `auto_fix_enabled is False` updated to `is True` to match the new INI / dataclass default (caused by my flip, not pre-existing)

**Regression**: 3169 passed, 1 xfailed, **0 failed** in 18m48s (was 3161 passed / 8 failed before fixes). Zero net regression — every previously-failing test now green and 8 new tests added on top.

**Key insight**: The "12 visual regression failures, no TFE" overnight incident was diagnosed as a stacked bug. After this commit + a server restart, expect `[Watchdogs] BFE=ENABLED, TFE=ENABLED` in the startup log and TFE will auto-dispatch on the next failed E2E run unless the submission explicitly opts out via `auto_fix_on_failure: false`.

**Files Changed — Lupin parent (this commit)**:
- `src/fastapi_app/main.py`
- `src/conf/lupin-app.ini`, `src/conf/lupin-app-splainer.ini`
- `src/fastapi_app/static/html/notifications.html`
- `src/fastapi_app/static/js/notifications.js`
- `src/lupin_mcp/cosa_voice_mcp.py`
- `src/docs/agents/bug-fix-expediter-guide.md`
- `src/docs/agents/test-fix-expediter-guide.md`
- `src/docs/agents/test-suite-scheduling-guide.md`
- `src/tests/unit/test_test_suite_completion_watchdog.py`
- `src/tests/unit/test_test_suite_job.py`
- `src/tests/unit/test_tfe_config.py`
- `src/tests/unit/test_presentation_generator_job.py`
- `src/tests/unit/test_watchdogs_facade.py` (new)
- `src/tests/unit/test_agentic_job_factory_optional_boolean.py` (new)

**Files Changed — CoSA submodule (working-tree only, user commits separately)**:
- `src/cosa/rest/watchdogs.py` (new — unified facade)
- `src/cosa/rest/test_suite_completion_watchdog.py` (Gate 1 tri-state override)
- `src/cosa/rest/agentic_job_factory.py` (`_parse_optional_boolean` + factory threading)
- `src/cosa/rest/routers/test_suite.py` (REST request model + handler)
- `src/cosa/rest/routers/system.py` (`/api/config/client` exposes TFE default)
- `src/cosa/agents/test_suite/job.py` (constructor kwarg)
- `src/cosa/agents/test_fix_expediter/config.py` (dataclass default + smoke test)

---

### 2026.04.10 - Session 1cfcdf73 | TestFixExpediter (TFE) end-to-end implementation + user-facing docs for BFE/TFE/scheduler

**Context**: Morning session started with TODO.md line 20 — the open design question "how does TestSuiteJob's remediation snapshot JSON feed into BFE for automated fix cycles?" Ultrathink pros/cons analysis of three options (modify BFE, new TFE job type, intermediate clusterer). Chose **Option B: new `TestFixExpediterJob` with shared `FixExecutor` extracted from BFE**, wrote a 20-doc planning package (14 design + 6 execution-log placeholders) under `src/rnd/v0.1.6/2026.04.10-test-fix-expediter/`, then implemented the full 20-step sequence in one session. Afternoon session: shipped the first user-facing documentation for BFE, TFE, and the TestSuiteJob scheduler under a new `src/docs/agents/` subdirectory.

**Part 1 — TFE implementation** (Phases 0-6 + watchdog + tests):

- **Phase 0 extraction** (3 commits inside `src/cosa/agents/shared/` — a new peer package to BFE/TFE):
  - `plan_writer.py` — moved verbatim from BFE, standalone smoke test with `SimpleNamespace` mocks so `shared/` has zero back-dependencies on `bug_fix_expediter/`
  - `git_strategist.py` — new module; extracted `resolve_trust_level`, `generate_slug`, `commit_and_pr_single` (BFE path) from BFE orchestrator. New `commit_and_pr_multi` for TFE's one-branch-N-commits-one-PR strategy
  - `fix_executor.py` — new module; `FIX_PROMPT_BUILDERS` registry + `FixExecutor.execute_fix()` retry loop. Polymorphic via `prompt_builder_key` ("bfe" | "tfe"). Accepts `delegate_to_coder_fn` / `verify_fix_fn` callbacks so BFE's unit-test patches via `patch.object(orchestrator, "_delegate_to_coder", ...)` still work
  - BFE `run_fix()` + `run_git_strategy()` → thin shims delegating to the shared engine. 58 BFE Phase-6 unit tests stayed green byte-for-byte through all 3 extraction commits
- **TFE scaffolding**: 14 files under `src/cosa/agents/test_fix_expediter/` — config, state, snapshot_loader, cluster, cosa_interface, voice_io, orchestrator, job, prompts/ (__init__, cluster, diagnosis, proposal, fix). 16 INI keys + splainer entries. Factory routing via `create_agentic_job("agent router go to test fix expediter", ...)`. `TestFixExpediterJob` extends `AgenticJobBase` with `JOB_TYPE="test_fix_expediter"`, `JOB_PREFIX="tfe"`
- **Phase 0 clustering**: Real `heuristic_seed()` — pure Python, groups by `(normalized_classname, first_non_pytest_traceback_frame)`. Handles parametrized tests collapsing to one cluster, fixture errors, collection errors, startup crashes. `_cap_enforce()` merges smallest into a "Mixed" tail when K > max_clusters. `llm_refine()` accepts optional async `refine_fn` callback; SDK wiring deferred
- **Phase 1 diagnose**: `prompts/diagnosis.py` with test-aware `DIAGNOSIS_SYSTEM_PROMPT` (teaches classname::name[param] decoding + 4 failure mode categories: code_bug, test_bug, fixture_bug, env_bug). `TFEOrchestrator.run_phase1_diagnose()` iterates clusters serially via Opus lead agent (read-only SDK tools). Iteration loop with confidence threshold, JSON parser with markdown-fence stripping + backward-walk extraction, low-confidence fallback
- **Phase 2 propose**: Per-cluster proposal calls, aggregated multi-select voice gate via `ask_multiple_choice(multiSelect=True)`, multi-section plan doc via shared `PlanWriter` with synthetic `DiagnosisResult` aggregation, `per_cluster` voice gate mode as config fallback
- **Phase 3 fix delegation**: Real `prompts/fix.py` with TFE `CODER_SYSTEM_PROMPT` + `TESTER_SYSTEM_PROMPT` (teaches `pytest -k` filtering to the cluster's failing test names). **Import-time self-registration** into `shared.FIX_PROMPT_BUILDERS["tfe"]`. `run_phase3_fix()` iterates selected fixes, builds `FixContext` as `SimpleNamespace` (duck-typed pass-through instead of Pydantic model per scope reduction), constructs per-cluster `FixExecutor(prompt_builder_key="tfe", ...)`. TFE has its own `_delegate_to_coder` / `_verify_fix` / `_build_tfe_{coder,tester}_options` mirroring BFE's pattern. Dry-run mode synthesizes files from `proposal.changes` so Phase 5 has non-empty commits
- **Phase 5 multi-cluster git**: `GitStrategist.commit_and_pr_multi()` — L1-L2 commit_only N sequential commits, L3+ branch+push+PR via `gh`, gh-missing degradation to branch_only, empty-files skip with partial-progress semantics. `TFEOrchestrator.run_phase5_git()` builds cluster tuples, resolves trust level via `inherit`/`fixed_l1`/`fixed_l3`/`shadow` modes. Commit message format `fix(tfe): {cluster_id} {title}`. Branch naming `fix/YYYY-MM-DD-tfe-{suite_abbrev}-{K}-clusters`
- **Phase 6 async rerun validation**: `run_phase6_validation()` constructs a new `TestSuiteJob` via factory + sets `metadata["triggered_by_tfe"] = self.job_id` (the critical recursion guard) + pushes to `fastapi_app.main.jobs_todo_queue`. Does NOT wait on the rerun — peer job. `rerun_scope` config selects `affected` (original suites) vs `full` (all)
- **TestSuiteCompletionWatchdog**: New `src/cosa/rest/test_suite_completion_watchdog.py` with 6 eligibility gates (enabled, job_type, snapshot valid, recursion guard, failure cap, repair tracker). `evaluate()` wraps all logic in try/except — never crashes the queue consumer. Hook in `running_fifo_queue.py` success-path around line 401, invoked after `jobs_done_queue.push()`. Module-level singleton via `init_watchdog()` / `get_watchdog()` / `reset_watchdog()`
- **Supporting artifacts**: Proxy Q&A script `src/conf/notification-proxy-scripts/tfe.json` (auto-answer 4 gate patterns). Live pipeline smoke test `src/tests/smoke/test_tfe_live_pipeline.py` (5 scenarios with mocked SDK). Live E2E shell driver `src/tests/e2e/run-tfe-live-e2e.sh` with `--dry-run` / `--live` modes. 6 fixture snapshots under `src/tests/fixtures/tfe/`. PEFT training data: 75 templates in `src/ephemera/prompts/data/synthetic-data-agent-routing-test-fix-expediter.txt`, TFE command registered in `src/conf/training/agent-router-agentic-commands.json`, `AGENTIC_TEMPLATES` whitelist updated in `test_swe_team_training_data.py`
- **Test coverage**: **197 new TFE test methods** across 13 files (12 unit + 1 smoke): state(9), config(6), snapshot_loader(14), cluster(29), diagnose(17), propose(21), phase3_fix(13), phase5_git(18), phase6_rerun(14), test_suite_completion_watchdog(30), job(9), training_data(12), live_pipeline smoke(5)
- **Regression gate**: held perfectly through every step. Baseline 2916 → final **3119 passed, 1 xfailed**, **zero regression** across every intermediate commit. Full trajectory: 2916 (extraction P0-P3 landed untouched) → 2954 (+38 scaffolding) → 2989 (+35 Phase 0) → 3006 (+17 Phase 1) → 3040 (+34 Phase 2) → 3072 (+32 Phase 3) → 3119 (+47 Phase 5+6+watchdog+PEFT+live)

**Part 2 — User-facing documentation** (5 new docs, 4 modified):

- `src/docs/agents/` (new subdirectory mirroring `src/docs/auth/` precedent): 5 docs totaling 2,384 lines
  - `shared-fix-primitives-reference.md` (528 lines) — developer reference for the shared package, how to add a new expediter agent
  - `bug-fix-expediter-guide.md` (551 lines) — BFE operator + developer guide, 6 phases, 14 INI keys, trust-to-git mapping, observability, troubleshooting
  - `test-fix-expediter-guide.md` (673 lines) — TFE guide, 6 phases + Phase 0 clustering, watchdog 6 gates, 16 INI keys, key-difference-from-BFE, troubleshooting
  - `test-suite-scheduling-guide.md` (518 lines) — `TestSuiteJob` + `/schedule-tests` skill, suite types table, monopolize mode, remediation snapshot schema v1.0, REST API, cost model, TFE interaction
  - `README.md` (114 lines) — subsystem index with "when to read which" decision table + canonical code locations
- `src/docs/README.md` — added "Agentic Jobs & Recovery" section with 5 entries + 5 verification-date rows
- `src/docs/rest-api-reference.md` — new sections 17/17a/17b for TestSuite/BFE/TFE endpoints + `bfe-` / `tfe-` prefix rows in Job ID Prefixes table
- `README.md` (top-level) — new "Agentic jobs, recovery & test scheduling" subsection under Documentation linking to all 4 new guides
- `CLAUDE.md` DOCUMENTATION TOUCHPOINTS — added 8 rows mapping code paths and INI key groups to the new guides
- **Verification**: 0 broken links, 30/30 cited INI keys present in both `lupin-app.ini` and `lupin-app-splainer.ini`, all 21 critical code paths resolve, 7 CLAUDE.md touchpoint rows reference `agents/`

**Key scope deviations** (documented inline in execution logs):

1. `FixContext` as `SimpleNamespace` duck-typed pass-through instead of a Pydantic model
2. BFE's `_delegate_to_coder` / `_verify_fix` / `_build_*_options` stayed on BFE orchestrator; TFE copies the pattern to preserve BFE's test-patch surface
3. No `api_client.py` / `cost_tracker.py` / `rate_limiter.py` in TFE — follows BFE's SDK-delegated pattern (not deep_research's direct-API)
4. Phase 0 `llm_refine` uses pure-Python cap-enforcement fallback; real SDK callback infrastructure in place but not wired
5. `agent_registry.py` TFE entry deferred — factory routing works via direct elif branch

**CoSA submodule rule honored**: all new files under `src/cosa/` (shared package, TFE package, watchdog module, BFE shim edits) are working-tree only. No git commands run in the submodule. User commits CoSA in a separate session.

**Files Changed — Lupin parent (committed this session)**:
- Plan file: `src/rnd/2026.04.10-test-fix-expediter-plan.md` (serialized approved plan)
- 20 planning docs under `src/rnd/v0.1.6/2026.04.10-test-fix-expediter/` (14 design + 6 execution logs)
- 13 new test files under `src/tests/unit/` + 1 smoke test at `src/tests/smoke/test_tfe_live_pipeline.py`
- 6 fixture JSON files under `src/tests/fixtures/tfe/`
- E2E shell driver `src/tests/e2e/run-tfe-live-e2e.sh`
- Conf: `src/conf/lupin-app.ini` (16 TFE keys), `src/conf/lupin-app-splainer.ini` (matching entries), `src/conf/notification-proxy-scripts/tfe.json`, `src/conf/training/agent-router-agentic-commands.json`
- Training data: `src/ephemera/prompts/data/synthetic-data-agent-routing-test-fix-expediter.txt` (75 templates)
- Whitelist: `src/tests/unit/test_swe_team_training_data.py` (`AGENTIC_TEMPLATES` set)
- New user-facing docs: 5 files under `src/docs/agents/`
- Modified docs: `src/docs/README.md`, `src/docs/rest-api-reference.md`, `README.md`, `CLAUDE.md`
- Session-end tracking: `history.md`, `TODO.md`, `.claude-session.md`

**Files Changed — CoSA submodule (working-tree only, user commits from CoSA context)**:
- New `src/cosa/agents/shared/` package (plan_writer.py, git_strategist.py, fix_executor.py, __init__.py)
- BFE orchestrator shims + prompts/fix.py registration + plan_writer.py re-export shim
- New `src/cosa/agents/test_fix_expediter/` package (14 files)
- New `src/cosa/rest/test_suite_completion_watchdog.py` + `running_fifo_queue.py` hook
- `src/cosa/rest/agentic_job_factory.py` TFE elif branch

**Follow-ups filed on TODO.md** (for next session):
- Archive `history.md` — token count at 17.7k (70.8% of 25k limit), approaching WARNING threshold
- Live E2E monopolize TFE run via `/schedule-tests` skill (GPU + real SDK cost gate, user-scheduled after hours)
- PEFT trainer run on GPU (user-run per memory rule) — templates ready, coordinator generation pending
- Phase 0 `llm_refine` real SDK wiring
- BFE Phase 6 live E2E verification (user's parallel console work, state unknown)
- CoSA submodule commits (user handles in a CoSA session)
- `agent_registry.py` TFE entry

---

### 2026.04.11 - Session 1b8c1cc0 (continued) | TFE forensics fix — error capture, persistence, dead-queue UI

**Context**: A real TFE job (`tfe-d9e6b50f`) ran for ~4.5 minutes, completed Phases 0-2 (clustering + diagnosis + proposal), wrote a full plan file to disk, then died at the Phase 2 voice gate with the UI showing only `"Unknown error"`. Forensic investigation this session reconstructed the failure from docker logs + filesystem artifacts and cataloged six independent bugs + a root-cause trigger that collaborate to destroy TFE's forensic signal on death.

**Accomplishments**:
- Forensic investigation: traced tfe-d9e6b50f's death to `present_choices failed: Cannot resolve target_user` (TFE never set `cosa_interface.TARGET_USER`); recovered the Phase 2 plan file from disk (`io/swe-team/plans/.../c1-plan.md`) which contained a correct diagnosis of 12 stale visual baselines
- Fix 1: added `test_fix_expediter` to `AGENTIC_JOB_TYPES` frozenset — was missing, causing zero TFE rows in `job_history` ever
- Fix 2: rewrote TFE `do_all()` to BFE pattern — uses `self.state` (JobState enum) not `self.status` (string), captures full traceback into `self.error`, prints unconditionally to stdout (not gated on `self.debug`)
- Fix 3+7: wrapped TFE `_execute()` in outer try/except with urgent voice notification (full traceback in abstract field, no truncation); set `bug_fix_expediter.cosa_interface.TARGET_USER` + `SENDER_ID` before orchestrator phases (TFE's cosa_interface is a thin delegator that reads BFE's module-level state)
- Fix 6: removed `notification_type="progress"` kwarg from TFE's `notify_progress()` calls — was causing hundreds of `[TFE notify error]` log lines per run (kwarg doesn't exist on the method)
- Fix 8a: TFE stores `self.artifacts["plan_path"] = orchestrator.last_plan_path` after Phase 2 so the artifact survives later failures
- Fix 8b: added dead-queue branch in `queues.py` that extracts `plan_path`, `remediation_snapshot_path`, `report_path`, `yaml_path`, `cost_summary` from dead agentic jobs (previously fell through to generic todo/run branch with no artifacts)
- Fix 8c: `renderJobCard()` in `notifications.js` shows clickable "Partial Plan" and "Remediation Snapshot" links on dead cards via `/app/docs?path=` endpoint (reuses existing report-link UI pattern)
- Plan serialized: `src/rnd/v0.1.6/2026.04.11-tfe-forensics-capture-plan.md` (39 KB)
- New TODO entry: TFE Phase 6 Live E2E (mirrors BFE Phase 6 Live E2E, separate test)

**Files modified** (CoSA submodule — 4 files, awaiting CoSA commit):
- `rest/job_persistence.py`, `rest/routers/queues.py`, `agents/test_fix_expediter/job.py`, `agents/test_fix_expediter/orchestrator.py`

**Files modified** (Lupin parent — 1 modified, 2 new, 2 docs):
- `src/fastapi_app/static/js/notifications.js` (dead-card partial artifacts)
- `src/tests/unit/test_tfe_forensics.py` (new — 11 assertions)
- `src/tests/smoke/test_tfe_error_capture_smoke.py` (new — 5-part smoke)
- `TODO.md` (TFE live E2E entry added)
- `src/rnd/v0.1.6/2026.04.11-tfe-forensics-capture-plan.md` (new plan)

**Test status**: 87/87 unit tests passing (76 pre-existing + 11 new); smoke test all 5 parts pass; zero `[TFE notify error]` log lines post-fix

---

### 2026.04.10 - Session 1b8c1cc0 | BFE Phase 6 dry-run smoke test + CJ Flow persistence gaps fix

**Context**: Two back-to-back planning cycles in one session. (1) Plan + implement the Phase 6 dry-run integration smoke test that the BFE parent plan left as Step 8. (2) When end-to-end verification exposed three persistence gaps in `job_history` (`session_id`, `routing_command`, `metadata_json.original_args` all NULL for REST-submitted agentic jobs), plan + fix those too. A bonus regex bug was surfaced while debugging the live server.

**Part 1 — Phase 6 dry-run smoke test** (plan doc 09):
- Added `force_failure_mode` Literal field to `MockJobSubmitRequest` + REST request models for DR/podcast/presentation; threaded through `agentic_job_factory.create_agentic_job()` into each job constructor
- Shared `_raise_forced_failure(voice_io)` helper on `AgenticJobBase` — raises `KeyError`/`asyncio.TimeoutError`/`Exception("RateLimitError: 429...")` at end of dry-run breadcrumbs so jobs land in dead queue with realistic error signatures
- BFE `_execute_dry_run()` extended to package real `DeadJobContext`, strip `force_failure_mode` from `original_args`, build a mocked successful `FixResult`, and call `_resubmit_original_job()` — so `dry_run=True` now exercises the full Phase 6 loop
- Dead queue watchdog `_submit_bfe()` propagates `dry_run=True` to spawned BFE when the failed job is a dry-run mock
- New smoke test `src/tests/smoke/test_bfe_phase6_repair_loop_smoke.py` with auto-mode scenarios (WATCHDOG_DISABLED when config is `false`, DR_LOOP_HAPPY when `true`)
- 12 new unit tests in `test_bfe_phase6.py` (`TestDryRunRepairLoopHooks`, `TestMockJobForceFailureMode`)
- Both smoke scenarios verified: WATCHDOG_DISABLED PASSED (dead queue hit, no BFE spawn); DR_LOOP_HAPPY end-to-end verified via direct DB inspection

**Part 2 — CJ Flow persistence gaps fix** (plan doc 10):
- Added `routing_command` + `original_args` attributes to `AgenticJobBase.__init__` (both default `None`); added `original_args` to `AgentBase.__init__` and `SolutionSnapshot.__init__` so every CJ Flow-eligible job has the attributes — enables `TodoFifoQueue.push()` to read them directly without defensive `getattr` fallbacks
- Removed legacy `self.routing_command = self.JOB_TYPE` line from `AgenticJobBase` (was stale, set bare job_type instead of the full routing command string)
- Refactored `agentic_job_factory.create_agentic_job()` with direct-assignment pattern: each branch now builds `job = FooJob(...)` and the function returns via a single tail that sets `job.routing_command = command` and `job.original_args = dict(args_dict)` — no wrapper, no indirection
- Enriched `TodoFifoQueue.push()` metadata dict with `session_id`, `routing_command`, `original_args` via direct attribute reads (no `getattr` defaults)
- Whitelisted `original_args` in `job_persistence._build_metadata_json()` rich_fields
- `persist_job_completed_from_metadata()` and `persist_job_failed_from_metadata()` now **merge** existing `metadata_json` with the new rich fields instead of overwriting — preserves `original_args` set at creation through state transitions
- Cleanup: removed `_JOB_TYPE_TO_ROUTING_COMMAND` lookup table + `or ""` coercions from `dead_job_packager.py` (reverted to direct `row[key]` reads); simplified BFE `_execute_dry_run()` resubmit args block (now `{**original_args, dry_run: True}` with `force_failure_mode` popped)
- 6 new `TestPersistenceRoundTrip` unit tests

**Part 3 — Bonus regex bugfix in dead_queue_watchdog**:
- Found that the watchdog's `INFRA_RATE_LIMIT` regex was matching bare `429` anywhere in error text — which caught traceback line numbers (e.g. `File ".../agentic_job_base.py", line 429, in _raise_forced_failure`). This misclassified `KeyError` code-bug failures as rate-limit failures and routed them to `_direct_retry()` instead of `_submit_bfe()`
- Tightened regex to require HTTP context: `\b(?:HTTP|status|code|error)\s*(?:code\s*)?429\b`
- `RateLimitError`, `rate.limit`, `Too Many Requests`, `overloaded` patterns still match; all classification unit tests pass

**Files modified** (14 production + 2 tests + 4 plan/index):
- Prod: `agentic_job_base.py`, `agent_base.py`, `solution_snapshot.py`, `agentic_job_factory.py`, `todo_fifo_queue.py`, `job_persistence.py`, `dead_job_packager.py`, `bug_fix_expediter/job.py`, `dead_queue_watchdog.py`, `running_fifo_queue.py`, `routers/mock_job.py`, `routers/deep_research.py`, `routers/podcast_generator.py`, `routers/presentation_generator.py`, `agents/deep_research/job.py`, `agents/podcast_generator/job.py`, `agents/presentation_generator/job.py`, `conf/lupin-app.ini` (toggled + restored)
- Tests: `test_bfe_phase6.py` (+18 tests), `test_bfe_phase6_repair_loop_smoke.py` (new)
- Plans: `09-phase6-dry-run-smoke-test-plan.md` (new), `10-cj-flow-persistence-gaps-plan.md` (new), `00-index.md` (updated)

**Test status**: 76/76 unit tests passing (58 pre-existing + 18 new this session)

**End-to-end verification via direct DB inspection**:
- `dr-5d4fb37c` (original, status=failed) → `bfe-e9908a2d` (watchdog-spawned BFE) → `dr-4b54fd31` (BFE-resubmitted DR) all present in job_history with complete persistence fields
- Resubmitted DR has `original_args = {query, budget, audience=expert, dry_run=True}` with `force_failure_mode` correctly stripped — proves BFE's "dry-run fix" round-trip is faithful
- Note: smoke test in-process observation was frequently interrupted by uvicorn reloads triggered by parallel test_fix_expediter edits in another session; DB rows are the authoritative evidence

**Memory update**: extended `feedback_no_defensive_programming.md` with a concrete "Known incidents" section documenting the `getattr(item, 'routing_command', None)` hedge caught by the user — the rule "add attribute with default to base class, don't hedge at the consumer" now has a fresh example

**Nested repos (not committed from this session)**: All the CoSA-side edits (most of this session's work) live under `src/cosa/` submodule — they need their own commit from a CoSA context per project policy

---

### 2026.04.10 - Session 85b05d1d (continued) | Lunch-time autonomous run through backlog items #0–#4

**Context**: After the initial E2E count mismatch fix landed (entry below), the user created a 6-item ordered backlog (#0 checkpoint → #1 notifications.js auth refresh → #2 test report filename TZ → #3 move runtime artifacts out of src → #4 visual regression cold/warm drift → #5 research stuck todo jobs) and authorized autonomous execution during their lunch break with three ground rules: no CoSA/deepily-scripts commits from Lupin, no destructive ops without pausing, no GPU workloads.

**#0 Checkpoint (commit 5b95859)** — Lupin-parent-only checkpoint of the E2E count mismatch bug work. 4 files: new plan doc for #1, updated `TODO.md` with the 5 new follow-up items, updated `history.md` with the full session entry, updated `.claude-session.md` with session 85b05d1d block. Deliberately did NOT commit the re-baselined `profile.png`/`notifications.png` since #3 was about to relocate the whole `__snapshots__` directory.

**#1 notifications.js auth refresh (commit e68d827)** — Added `authedFetch(url, options)` helper to `NotificationsUI` at ~L910, immediately after `ensureValidToken()`. Helper awaits `ensureValidToken`, injects the Authorization header (caller headers take precedence), passes all other fetch options through, returns Response as-is. Migrated 12 non-compliant fetch call sites to use it: `fetchClientConfig`, `updateQueueLists`, `loadQueueJobCards`, `loadJobHistory`, `deleteHistoryJob`, `deleteQueueJob`, `retryHistoryJob`, `sendJobMessage`, `cancelJob`, `toggleJobPause`, `loadJobInteractions` (the user's originally-reported 401 bug), and `submitResponse`. **Audit correction**: initial heuristic estimate was "16 non-compliant" but a stricter re-audit (walking back to the nearest `async fn()` declaration rather than the nearest brace) corrected this to 12 non-compliant and 13 compliant — 4 sites were false positives where `ensureValidToken` was called earlier in the same async function but my initial walker stopped at a nested `if`/`else` block. Verification: `node --check` passes; re-audit after migration shows 0 non-compliant sites remaining. Phase 4 (migrate the 13 already-compliant sites for file uniformity) deferred as low-priority cleanup. Plan doc updated with corrected counts. **User manual smoke pending** after return from lunch (hard-refresh the page to get a fresh token, click activity log + delete queue job + retry history job + load job history pagination after 30+ min idle — should not produce 401s).

**#2 Test report filename UTC → EST/EDT** — Edited `src/cosa/agents/test_suite/job.py:340-350` to use `ZoneInfo("America/New_York")` with `%Z` format specifier. Filenames now produce e.g. `2026.04.10-at-12:34-EDT-e2e-results.md` instead of the container's UTC `2026.04.10-at-16:34-e2e-results.md`, matching the project convention memory rule. Report body "Date" field also gets the TZ suffix (e.g., `2026-04-10 12:34:18 EDT`). The `timestamp` variable is reused for the `remediation.json` snapshot filename at L426, so both artifacts inherit the fix. Tmp /junit-XML paths at L612, L706 left as UTC — they're container-internal uniqueness keys not visible to the user. **CoSA submodule — working tree edit only, awaiting your CoSA-side commit.**

**#3 Move visual regression artifacts out of src tree (commit 824f314)** — Relocated `src/tests/e2e_ui/__snapshots__/` (12 committed baseline PNGs) → `io/test-suite/visual-baselines/` and `src/tests/e2e_ui/snapshot_failures/` (untracked, root-owned from container) → `io/test-suite/visual-failures/`. The cp captured my working-tree versions including the re-baselined `profile.png`/`notifications.png`, so those fresh baselines made the move without being committed to the old location. Updated `pytest.ini` `playwright_visual_snapshots_path` and `playwright_visual_snapshot_failures_path` keys to the new paths. `git rm -rf` the old tracked `__snapshots__` tree. `snapshot_failures` was root-owned inside the container so had to be deleted via `docker exec lupin-rest rm -rf`. **Host verification**: `./src/scripts/run-e2e-ui-tests.sh --bg -v -k visual` → 12 passed in 37.05s. io/ is gitignored per `.gitignore:64`; user confirmed io/ contents are backed up externally so baselines survive clean checkouts via restore, not via git history. **Container propagation requires next `sdla restart`**: the file-level bind mount for `pytest.ini` added in Session 85b05d1d earlier was bound to the OLD inode at container start; the host Edit tool atomically rewrote `pytest.ini` with a new inode, so the container's bind mount still points to the stale version. This matters only for scheduled test_suite runs that subprocess-Popen pytest from INSIDE the container (the surgical -k visual run above uses the host venv and is fine). `docker cp` fails on bind-mounted files; `docker exec tee` fails because the mount is `:ro`. Restart picks it up cleanly.

**#4 Visual regression cold/warm baseline drift** ✅ VERIFIED — Investigation: e2e suite has 31 test files, 335 total tests. `test_visual_regression.py` sorts alphabetically at position 28, with 323 tests running before it. Analysis of earlier failure diff PNGs showed only faint subpixel yellow speckles in text areas (titles, labels, button text) — no structural differences — ruling out DB state contamination and CSS layout drift. Hypothesis: Chromium's font/render cache warms up over test execution; subpixel anti-aliasing drifts between cold (freshly-started headless Chromium, as in `-k visual`) and warm state (after 323 tests). Baselines were captured in cold state, so warm-state renders exceed the 0.1 pixelmatch threshold. **Fix**: added `pytest_collection_modifyitems` hook in `src/tests/e2e_ui/conftest.py` that splits collected items into `visual` and `other`, then re-concatenates with visual first. Forces visual regression tests to run BEFORE any other e2e test, keeping Chromium in the cold state where baselines were captured. Minimum viable implementation: one conftest function, zero new dependencies, zero test code changes, trivially reversible. Rejected alternatives: (a) re-baseline in warm state (trades cold-fail for warm-fail), (b) raise 0.1 threshold (weakens the signal globally), (c) extract visual regression into a standalone scheduled suite (over-engineered). Plan doc at `src/rnd/v0.1.6/2026.04.10-visual-regression-cold-warm-drift.md`. **Verification**: full 335-test e2e run launched in background at 12:44 EDT (host-side via `./src/scripts/run-e2e-ui-tests.sh --bg -v`). **Result: `335 passed in 1202.84s (0:20:02)`** — all 335 tests including 12 visual regression pass cleanly with the hook in place. Cold/warm hypothesis CONFIRMED, #4 fix verified end-to-end.

**#5 Research 5-6 stuck todo jobs** — Investigation complete after e2e finished and Dev config was restored. Queried via API as `claude.code@lupin.deepily.ai` (user's `~/.lupin/config [lupin]` account): 0 jobs in all 4 queues (todo/run/done/dead). Account has `user` role, not admin — `?user_filter=*` returns 403. Queried PostgreSQL directly via `docker exec`: dev DB `lupin_db_dev` has 0 stuck jobs (just 12 historical `completed`); test DB `lupin_db_test` is completely empty (e2e cleanup drops/recreates tables). **No stuck jobs in persistence anywhere.** Code review of `queue_consumer.py:64-72` confirmed the consumer DOES support paused + future-scheduled "stuck" states: paused jobs sit until explicit resume, future-scheduled jobs sit until `scheduled_at` fires. Both are legitimate. **Most likely explanation**: the user was watching UI during the 10:32 EDT scheduled e2e run and saw transient test-suite traffic — `test_qa_submission.py`, `test_job_dispatch.py`, `test_queue_display.py`, `test_job_history_ui.py` et al. submit real queue jobs to validate the queue APIs, and those briefly sit in todo for seconds before the consumer dispatches them. The "dead or paused" framing was likely a misread of "pending" state. No active bug. Findings doc: `src/rnd/v0.1.6/2026.04.10-stuck-todo-jobs-investigation.md`. **User clarification needed** on return: (1) which UI account do you use, (2) are the 5-6 jobs still visible now that the e2e is finished, (3) was the "dead or paused" framing based on explicit badges or general impression? If the jobs are still visible, my hypothesis is wrong and we need to re-investigate with your account context.

**Commits so far (Lupin parent)**: 5b95859 (#0 checkpoint), e68d827 (#1 auth refresh), 824f314 (#3 artifact relocation).

**Working tree only (no commit — you handle in other repo sessions)**:
- CoSA submodule: `src/cosa/agents/test_suite/job.py` (combines #1's display fix from earlier + #2's timezone fix)
- deepily/scripts: `scripts/server/start-docker-lupin.sh` (#2 bind-mount line from earlier — already added, pending commit)

**Needs user action**:
1. `sdla restart` to propagate new `pytest.ini` paths into the container
2. Commit CoSA submodule changes (two unrelated fixes: display counter + timezone)
3. Commit deepily/scripts `start-docker-lupin.sh` pytest.ini bind mount line
4. Manual smoke of notifications.js auth refresh (click activity log, delete/retry buttons, job history pagination after 30+ min idle)
5. Tell me which UI account you use so I can query for #5 stuck jobs

---

### 2026.04.10 - Session 85b05d1d | Bug Fix: E2E Test Result Count Mismatch (3-layer root-cause fix)

**Goal**: User reported last night's scheduled e2e test run showed "FAILURES DETECTED" with summary `"335 passed, 0 failed, 0 skipped"` — numbers that add up to 335 clean but verdict says FAIL. User's question: "why does this not add up properly?" Answer turned out to require fixing three independent bugs.

**Root causes (three layers, each independent)**:

1. **Display bug — the numbers didn't include the errors counter.** `src/cosa/agents/test_suite/job.py` computed `total_errors` correctly but dropped it from five user-facing summary strings (report header, per-suite notification, abstract per-suite line, abstract total, conversational summary) and from the `cost_summary` dict. The report file's Errors column showed 12, but the user-facing line said "0 failed, 0 skipped" with no mention of errors — literally missing digits from the display. The test_suite job was telling the user `335 + 0 + 0 = 335 all good` when the real story was `335 passed + 12 errors on teardown`.

2. **Container config bug — pytest.ini wasn't in the container at all.** The lupin-rest container was started by `scripts/server/start-docker-lupin.sh` (in the separate `deepily/scripts` repo) with bind mounts only for `src/` and `io/`. Root-level files like `pytest.ini` and `requirements*.txt` were invisible inside the container. Confirmed by `docker exec lupin-rest ls /var/lupin/pytest.ini` → "No such file". Consequences: pytest ran with all defaults, custom markers (`manual`, `integration`) were unregistered, `addopts = -m "not manual"` was ignored, and the `playwright-visual-snapshot` plugin's configured path `src/tests/e2e_ui/__snapshots__` was ignored → fell back to `<rootdir>/__snapshots__/` → plugin couldn't find the 12 committed baseline PNGs → every visual test created a "new snapshot" → teardown reported ERROR for each. All 12 visual regression errors were a symptom of this one missing bind mount.

3. **Stale visual regression baselines.** Two of the 12 committed baselines (`profile.png`, `notifications.png`) were captured before Session 383 (Mar 30 2026) changed the main layout width from 800px to 1000px. The CSS commit modified exactly `notifications.css` and `auth/css/auth.css` — the two CSS files that style the two affected pages. The baselines were never refreshed, but the Docker path-mismatch bug from layer #2 was simultaneously creating new snapshots every run, so the stale baselines never actually compared against anything and never failed visibly. Once layer #2 was fixed, the stale baselines surfaced as real "Snapshots DO NOT match!" failures.

**Fix**:

- **Layer 1 (CoSA submodule, working tree edit only)** — `src/cosa/agents/test_suite/job.py`: added `errors` counter to five user-facing summary sites (lines 298, 351, 444, 456, 458) and `total_errors` key to `cost_summary` dict (line 318). After the fix, the validated e2e run shows `"**Total**: 335 passed, 0 failed, 12 errors, 0 skipped"` in the report header and `"Test suite complete: FAILURES DETECTED"` verdict — honest math, error count now visible.
- **Layer 2 (deepily/scripts repo, working tree edit only)** — `scripts/server/start-docker-lupin.sh:381`: added `-v "$LUPIN_ROOT/pytest.ini:/var/lupin/pytest.ini:ro" \` between the existing `src/` and `io/` bind mounts. User restarted lupin-rest, verified via `docker exec lupin-rest ls /var/lupin/pytest.ini` (886 bytes, uid 1001) and `configfile: pytest.ini` now showing in pytest collection header inside container.
- **Layer 3 (Lupin parent, re-baseline)** — Ran surgical `./src/scripts/run-e2e-ui-tests.sh --bg --update-snapshots -k "visual and (profile or notifications)"` which wrote fresh PNGs for just the two affected pages, preserving the other 10 healthy baselines. Subsequent `-k visual` clean run: **12 passed, 0 errors in 37.15s** — confirming both the plugin path fix AND the refreshed baselines.

**Validation — full e2e via test_suite job**: Scheduled a full 335-test e2e run via `/schedule-tests` (per the memory rule about using the skill). Result report landed at `io/test-suite/2026.04.10-at-14:53-e2e-results.md` showing the new honest total line: **"Total: 335 passed, 0 failed, 12 errors, 0 skipped"**. The 12 errors this time are different from the original bug — they're `"Snapshots DO NOT match!"` (plugin IS finding baselines, bind mount working) rather than `"New snapshot(s) created"`. The visual diffs show only faint subpixel font anti-aliasing speckles, not structural changes, and include `login`/`register`/`change-password` pages that passed cleanly in the isolated `-k visual` run earlier. This suggests a cold/warm Chromium font-cache drift between isolated and full-suite runs — a separate issue filed as follow-up #4.

**Bug surfaced during the run (separate issue, filed as follow-up #1)**: User tried to click the activity log button on the running e2e job card and got `HTTP 401` from `loadJobInteractions` at `notifications.js:7185`. Investigation revealed the method fetches `/api/get-job-interactions/{job_id}` without calling `await this.ensureValidToken()` first — a programmatic audit found **25 total `getAuthHeader()` fetch sites in notifications.js, of which 9 are compliant and 16 are missing the proactive token refresh**. The 30-min JWT TTL means any user idle during a long-running job will hit 401s on the non-compliant buttons. Full audit and proposed fix (add `authedFetch` helper + migrate all 25 sites) serialized to `src/rnd/v0.1.6/2026.04.10-notifications-js-auth-token-refresh-audit.md`.

**Files Changed — Lupin (3, committed this checkpoint)**:
- `src/rnd/v0.1.6/2026.04.10-notifications-js-auth-token-refresh-audit.md` — new plan doc for follow-up #1
- `TODO.md` — added 5 new pending items + 1 completed item for today's work
- `history.md` — this entry
- `.claude-session.md` — session 85b05d1d block

**Files Changed — CoSA (1, NOT committed, user commits from CoSA context)**:
- `src/cosa/agents/test_suite/job.py` — display fix (6 edits across 5 summary strings + cost_summary dict)

**Files Changed — deepily/scripts (1, NOT committed, user commits from that repo)**:
- `scripts/server/start-docker-lupin.sh` — one-line `pytest.ini` bind mount added at line 381

**Files Changed — Lupin working tree only (2, NOT committed — being relocated by follow-up #3)**:
- `src/tests/e2e_ui/__snapshots__/test_visual_regression/test_visual_page/profile.png` — re-baselined
- `src/tests/e2e_ui/__snapshots__/test_visual_regression/test_visual_page/notifications.png` — re-baselined

**Follow-ups filed** (all in TODO.md, ordered): #1 notifications.js auth refresh (plan doc ready), #2 test report filename UTC→EST/EDT, #3 move runtime artifacts out of src tree (user confirmed io/ external backup makes gitignore conflict non-blocking), #4 visual regression cold/warm drift, #5 research 5-6 stuck jobs in todo queue.

---

### 2026.04.10 - Session 1b8c1cc0 | Bug Fix: Done Bucket Job Card Render Parity

**Goal**: Fix divergence between dynamically-inserted (WS transition) and reload-loaded done-bucket job cards. They render the same logical state (`done`) through different code paths and produce visibly different results: dynamic cards show an irrelevant pause button and lack the trash button; reload cards lack scheduled/monopolize badges. User wants both paths fully equivalent and sharing a single rendering method.

**Root Causes**:
1. **Backend** (`src/cosa/rest/routers/queues.py`): the `if queue_name == "done":` branch built `job_data` without `scheduled_at`/`monopolize`/`paused` (the todo/run branch already includes them). On page reload, `/api/get-queue/done` never sent these fields → frontend had nothing to render.
2. **Frontend `renderJobCard`**: the scheduled badge was double-gated by `queueName === 'todo'` AND `schedDate > now`. Done cards were always excluded.
3. **Frontend `handleJobStateTransition`**: when a job transitioned todo→run→done live, the existing card was DOM-reparented and surgically morphed (spinner removed, completion badge added) — but the pause button was never removed and the trash button was never added.
4. **Frontend `renderHistoryCard`**: history-tab adapter omitted `scheduled_at`/`monopolize`/`paused`/`user_email` and set `_isHistory: true`, which a stale `renderJobCard` gate consumed to suppress the delete button.

**Fix**: Single source of truth via `renderJobCard()` — feed it complete data from every path, then make `renderJobCard()` itself queue-agnostic for the scheduled/monopolize badges.

**Files Changed — Lupin (2)**:
- `src/fastapi_app/static/js/notifications.js` — 4 surgical edits:
  - Ungated scheduled badge (line ~6664): renders for any queue when `job.scheduled_at` is set
  - Terminal-state (done/dead) WS transitions (line ~4805): full re-render via `renderJobCard` instead of surgical DOM morph — kills pause-button-persists and missing-trash-button bugs in one stroke
  - History card normalization (line ~5910): added `scheduled_at`/`monopolize`/`paused`/`user_email` fields
  - Removed `_isHistory` delete-button gate (line ~6797) — history cards now show trash like live cards
- `src/rnd/v0.1.6/2026.04.10-done-card-render-parity.md` — serialized plan (new)

**Files Changed — CoSA (1, committed separately from CoSA context)**:
- `src/cosa/rest/routers/queues.py` — added 3 fields to done-branch metadata response (`scheduled_at`, `monopolize`, `paused`), mirroring the todo/run branch

**Test**: py_compile + import-chain check on `queues.py` PASS. `node --check` on `notifications.js` PASS. Live `/api/get-queue/done` smoke returned 0 done jobs (no runtime data to assert against — server holds old code in memory). Manual UI verification deferred until after server restart.

**Commit**: 3faec04

### Session Summary
- **Total Fixes**: 1 (Done bucket job card render parity)
- **Files Changed**: 2 (`notifications.js`, `src/rnd/v0.1.6/2026.04.10-done-card-render-parity.md`)
- **GitHub Issues Closed**: none (ad-hoc bug)
- **Commits**: `3faec04` (fix), `332edd4` (tracking-doc hash refresh)

**Status**: Session closed 2026.04.10

---

### 2026.04.09 - Session ea400c01 | CoSA Commit: Sessions bacc971a+6b8670e7+f28d32d1

**Goal**: Commit pending CoSA changes from 3 sessions (8 files, +250/-38).

**CoSA Commit 7618499**: Idempotency cache for duplicate notifications, CBR prediction JSON parsing fix, cross-user WebSocket delivery for CC listener sessions, remediation snapshot JSON output for TestSuiteJob, stale queue entry guard.

**Files Committed — CoSA (8)**: `prediction_engine.py`, `test_suite/job.py`, `fifo_queue.py`, `notification_fifo_queue.py`, `routers/notifications.py`, `routers/queues.py`, `running_fifo_queue.py`, `websocket_manager.py`

---

### 2026.04.09 - Session f28d32d1 | Test Suite Remediation Snapshots

**Goal**: Add machine-readable remediation snapshot output to TestSuiteJob so test failures can be fed to BFE agents for automated fix cycles.

**Remediation Snapshot Feature**:
- Enhanced `_parse_junit_xml()` to extract per-failure details (classname, test name, type, message, traceback) from JUnit XML `<testcase>` elements
- Added JSON snapshot writer in `do_all()` — produces `*-remediation.json` alongside existing markdown reports in `io/test-suite/` when failures exist
- Added `remediation_snapshot_path` to API response (`queues.py`), WebSocket transition metadata (`running_fifo_queue.py`), and frontend normalization + rendering (`notifications.js`)
- 🔧 "Remediation Snapshot" link renders on done/dead job cards next to existing 📋 "View Full Report" link

**Bugs Found & Fixed During Debugging**:
- **ElementTree falsy Element bug**: `el = failure_el or error_el` evaluates to `None` when `<failure>` element has no child sub-elements (Python's `Element.__bool__()` returns `False` for childless elements). Fix: `el = failure_el if failure_el is not None else error_el`
- **`ET.parse()` vs `ET.fromstring()`**: Switched to `ET.fromstring()` for XML parsing (read file content first, then parse from string)

**Files Modified — CoSA (8, commit pending)**: `test_suite/job.py` (+82 lines: `json` import, failure detail extraction, JSON snapshot writer, `fromstring` fix, falsy Element fix), `routers/queues.py` (+1 line: `remediation_snapshot_path` in API dict), `running_fifo_queue.py` (+1 line: `remediation_snapshot_path` in WS metadata), plus 5 files from parallel session bacc971a
**Files Modified — Lupin (0)**: `notifications.js` changes were committed by parallel session bacc971a

**Remediation Snapshot JSON Schema (v1.0)**:
```json
{"schema_version": "1.0", "timestamp": "...", "suites_run": ["unit"],
 "summary": {"total_passed": 2882, "total_failed": 22, ...},
 "failures": [{"suite": "unit", "classname": "...", "name": "...",
               "type": "FAILED", "message": "...", "traceback": "..."}]}
```

---

### 2026.04.09 - Session bacc971a | Bug Fix: 4x Duplicate Notifications

**Goal**: Fix duplicate notifications (every message appearing 4 times) from overnight test jobs.

**Root cause**: Retry loop in `notify_user_async.py` sends up to 6 HTTP POSTs to `/api/notify` when user is offline. The server unconditionally pushed to FIFO queue AND persisted to PostgreSQL on EVERY request BEFORE checking connectivity. Each retry created a duplicate notification record. Timestamps (~1s apart) matched retry intervals [0, 1, 1, 2] exactly.

**Fix**: Server-side idempotency key — client generates UUID once per logical notification, sends it with all retry attempts. Server caches first response and returns it for duplicates. Also reordered fire-and-forget block: persist to PostgreSQL first (preserves history), then push to FIFO queue only if user is connected (eliminates phantom queue entries).

**Changes**:
- `notification_models.py`: Added `idempotency_key` field to `AsyncNotificationRequest` + `to_api_params()`
- `notify_user_async.py`: Auto-generate UUID idempotency key before retry loop
- `notifications.py` (CoSA): Module-level `OrderedDict` idempotency cache (60s TTL), reordered persist-before-push

**Files Modified — Lupin (2)**: `src/lupin_cli/notifications/notification_models.py`, `src/lupin_cli/notifications/notify_user_async.py`
**Files Modified — CoSA (1)**: `src/cosa/rest/routers/notifications.py`

**Bug Fix 2: CBR prediction showing raw JSON instead of answer string**

**Root cause**: Browser sends MC responses as `JSON.stringify({"answers":{"Commit":"Commit only"}})` — a JSON string. `_store_decision()` in `prediction_engine.py` checked `isinstance(str)` and blindly wrapped it in `{"answers":{"_other": <raw_json_string>}}` without attempting to parse the JSON first. CBR predictions then displayed: `Predicted: _other: {"answers":{"Commit":"Commit only"}}`.

**Fix**: Try `json.loads()` on string values before falling back to `_other` wrapping. If the string is valid JSON with an `answers` key, extract and use the structured answers directly.

**Files Modified — CoSA (1)**: `src/cosa/agents/prediction_engine/prediction_engine.py`

**Bug Fix 3: Activity log collapse toggle broken on job cards**

**Root cause**: CSS specificity — `.live-interactions .interactions-content` set `max-height: 200px` which overrode `.interactions-content.collapsed` `max-height: 0`. Toggle visually did nothing.

**Fix**: Added `.live-interactions .interactions-content.collapsed` rule with matching specificity.

**Files Modified — Lupin (1)**: `src/fastapi_app/static/css/notifications.css`

**Bug Fix 4: Job card activity log not showing live notifications**

**Root cause**: `appendNotificationToJobCard()` inserted entries into `interactions-content` container but never removed its `collapsed` class. `expandJobCard()` only expanded the outer `.job-card-details`, not the inner interactions section.

**Fix**: Auto-expand interactions section (remove `collapsed`, update expand button, show send-message row) when first notification is appended.

**Diagnostics**: Added `[DIAG-JR]` logging to server (`notifications.py`) and browser (`notifications.js`) for job routing verification. Confirmed notifications reach handler, `job_id` present, DOM element found — proved the issue was CSS/visibility, not routing.

**Files Modified — Lupin (1)**: `src/fastapi_app/static/js/notifications.js`
**Files Modified — CoSA (1)**: `src/cosa/rest/routers/notifications.py` (diagnostic log)

---

### 2026.04.09 - Session 6b8670e7 | Bug Fix: CC Listener Sessions Not Appearing

**Goal**: Debug why Claude Code hook notification listeners show 0 in diagnostic output despite being connected.

**Root cause**: User identity mismatch — CC listeners authenticate as `claude.code@lupin.deepily.ai` (service account) while browser sessions authenticate as the human user. The diagnostic and notification broadcasts only query the human user's session list, so listeners under the service account are invisible.

**Fix**: Targeted cross-user delivery using `emit_to_session_sync()` — directly targeting listener sessions by their deterministic session ID (`cc-listener-{job_id_hash}`) instead of relying on user-based broadcast.

**Changes**:
- Added `emit_to_session_sync()` to `WebSocketManager` — sync wrapper for cross-user session targeting
- Added cross-user listener delivery in `notification_fifo_queue.py` at both priority paths
- Added cross-user delivery for `user_initiated_message` events in `queues.py`
- Added cross-user diagnostic showing all CC listeners regardless of auth user in `notifications.py`
- Commented out misleading per-user listener count (always 0 due to user mismatch)

**Files Modified — CoSA (4)**: `websocket_manager.py`, `notification_fifo_queue.py`, `routers/notifications.py`, `routers/queues.py`

---

### 2026.04.08 - Session 97f29034 | CJ Flow UPE + Test Suite Hardening

**Goal**: Fix 4 open items from Session a312ee22: E2E Docker test crash, WebSocket admin broadcast, test failures, and UI bug fixes.

**E2E Docker Fix (exit 126)**:
- **Root cause**: `run-e2e-ui-tests.sh:324` hardcoded `.venv/bin/pytest` — shebang points to host Python path, doesn't exist in container. Container-aware postgres check (from previous session) worked fine.
- **Fix**: Replace with `$VENV_PYTHON -m pytest` (falls back to `python3` in Docker). Same fix in `run-presentation-regression.sh`.

**WebSocket Admin Broadcast (Option B)**:
- **Problem**: `emit_job_state_transition()` routed events only to job submitter — admin "all jobs" view never received real-time updates.
- **Fix**: Store `is_admin` in WebSocket session metadata at connect time. New `emit_to_admins_sync()` method broadcasts to admin sessions with `exclude_user_id` to avoid double delivery. Frontend `handleJobStateTransition()` filters by `queueFilterMode` + `user_email`. Verified with MockJob + unit test dry-run + live unit test.

**Test Suite Hardening (16 smoke → 12, 2 unit → 0)**:
- Fixed 4 genuine smoke test bugs: proxy UI header count (8→9), vLLM hardcoded URL (read from factory), voice injection session ID leak (patch `resolve_stable_session_id` at use site), argparse picking up pytest CLI args in 5 pipeline tests (`argv=[]`)
- Fixed 2 unit test PermissionErrors: mock `cu.get_project_root()` → `tmp_path` in TestStateTransitions
- Remaining: 11 server-dependent smoke tests, 1 LLM flaky, 11 unit timeout tests (pre-existing)

**Bug Fixes**:
- TestSuiteJob voice_io: `_dispatcher.notify()` → `_dispatcher.notify_progress()` (method didn't exist on AgentNotificationDispatcher)
- Activity Log toggle: `previousElementSibling` → `closest('.job-interactions-section')` for reliable header/button lookup across todo/run cards
- Activity Log send-message form: starts collapsed, toggles with content div
- Removed redundant "View Full Log" link from test suite abstract (📋 View Full Report already provides this)
- **False positive "FAILURES DETECTED"**: Test suite pass/fail was determined by process exit code, not parsed results. 335 passed / 0 failed reported as "FAIL" because exit code was non-zero (warnings/cleanup). Fixed all 4 locations to use `(failed + errors) == 0` instead of `exit_code == 0`

**Dockerfile cleanup**: Removed Flask comments, pinned torch 2.7.0, native CC binary install (`curl install.sh`), SDK 0.1.36→0.1.56, Python 3.11 symlink fix

**Commits**: `07cf84b` (15 files: Docker + test runners + smoke/unit fixes), `a349c83` (frontend admin filter)
**Files Modified — Lupin (16)**: `notifications.js` (admin filter + toggle fix + send-msg collapse), `notifications.css`, `Dockerfile`, `run-e2e-ui-tests.sh`, `run-presentation-regression.sh`, `run-smoke-tests.sh`, `run-unit-tests.sh`, 7 smoke tests, `test_test_suite_job.py`
**Files Modified — CoSA (25, commit pending)**: `websocket_manager.py` (+session_is_admin +emit_to_admins_sync), `queue_util.py` (+admin broadcast), `websocket.py` (+roles param), `cosa_interface.py` (notify→notify_progress), `job.py` (remove View Full Log + false positive fix: exit_code→parsed results), + 20 files from Session a312ee22

---

### 2026.04.08 - Session a312ee22 | Bug Fix: Queue Badge Counts + Process Owner Badge

**Goal**: Fix two CJ Flow UI issues: (1) queue accordion badge counts not updating until clicked, (2) no process owner identification on job cards in admin multi-user views.

**Bug 1 — Badge counts stale until accordion clicked**:
- **Root cause**: `handleJobStateTransition()` called `updateQueueCountFromDOM()` which counts `.job-card` elements in collapsed (empty) DOM containers. Cards are lazy-loaded on first expand.
- **Fix**: Added `queueCounts` local tracker seeded from server `data.total_jobs` on every `updateQueueLists()` call. Transition handler now increments/decrements counter and calls `updateQueueCountBadge()`. Guard for `fromQueue !== toQueue`, `Math.max(0)` floor, server re-seed on reconnect.

**Bug 2 — Process owner badge (user_email propagation)**:
- **Root cause**: `user_email` existed on all job objects (QueueableJob protocol) but was never sent to the frontend — missing from API responses and WebSocket transition metadata.
- **Fix**: Full ecosystem propagation: added `user_email` to API response dicts in `queues.py` (2 dicts), all 8 metadata dicts in `running_fifo_queue.py`, 2 metadata dicts in `todo_fifo_queue.py`, 1 in `queue_consumer.py`. Frontend maps `user_email` from both API and WebSocket paths. Green `.owner-badge` renders raw email, visible only in admin "all"/"others" filter modes.

**Files Modified — Lupin (2)**: `notifications.js` (queueCounts + owner badge), `notifications.css` (+.owner-badge)
**Files Modified — CoSA (4, commit pending)**: `queues.py`, `running_fifo_queue.py`, `todo_fifo_queue.py`, `queue_consumer.py`
**Commit**: a149363 (checkpoint 1)

#### Fix 2: Timezone-Aware Timestamps + Queue Job Delete Button

**Bug 3 — Timestamps showing UTC instead of EST**:
- **Root cause**: `datetime.now().isoformat()` used throughout codebase produces naive ISO strings. Docker container runs UTC. Browser interprets naive strings as local time, displaying UTC value 4-5 hours wrong.
- **Fix**: Added `get_current_datetime_iso()` to `util.py` — returns Eastern ISO strings with offset (e.g., `2026-04-08T14:08:19-04:00`). Replaced all frontend-facing `datetime.now().isoformat()` calls across 20 files (~65 call sites): 9 REST/WebSocket layer files (Tier 1) + 11 agent job files (Tier 2). No frontend changes needed — `new Date()` handles offset strings correctly.

**Bug 4 — No delete button for stuck/completed jobs**:
- **Root cause**: Running jobs only had graceful cancel (useless for stuck jobs). Done/dead queues had no removal mechanism. `FifoQueue.delete_by_id_hash()` existed but no API endpoint exposed it.
- **Fix**: Added `DELETE /api/queue/{queue_name}/{job_id}` endpoint with owner/admin auth. Frontend `deleteQueueJob()` function + 🗑 delete button on run/done/dead cards. `job_removed` WebSocket event for multi-client sync. Registered in INI + splainer.

**Files Modified — Lupin (4)**: `notifications.js`, `notifications.css`, `lupin-app.ini`, `lupin-app-splainer.ini`
**Files Modified — CoSA (22, commit pending)**: `util.py` (+function), `queue_util.py`, `websocket_manager.py`, `running_fifo_queue.py`, `queue_consumer.py`, `routers/queues.py` (+DELETE endpoint +timestamps), `routers/websocket.py`, `routers/system.py`, `routers/websocket_admin.py`, `routers/jobs.py`, `agentic_job_base.py`, 10 agent job files
**Tests**: Unit suite scheduled (ts-d8b84b8b), timestamps confirmed correct in UI
**Commit**: dbe59eb (checkpoint 2)

#### Fix 3: Post-Deploy Bug Fixes (2026.04.09)

**Bug 5 — Delete/agent badge overlap in history cards**: CSS `padding-left: 36px` added for done/dead card headers to make room for 🗑 button (same pattern as `.has-cancel`).

**Bug 6 — History delete button routing**: History cards rendered via `renderJobCard()` showed the queue delete button (🗑) which called `DELETE /api/queue/done/{id}` → 404. Fix: added `_isHistory: true` flag to normalized job object; `hasDeleteBtn` now checks `!job._isHistory`.

**Bug 7 — queue_list/queue_dict desync infinite loop**: `pop_next_eligible()` crashed with KeyError when `queue_dict` and `queue_list` got out of sync (concurrent `delete_by_id_hash()` from another thread). Consumer retried endlessly on the same stale job. Fix: guard `del` with `if job.id_hash not in self.queue_dict` — removes stale entry from list and continues.

**Files Modified — Lupin (2)**: `notifications.js` (_isHistory flag), `notifications.css` (padding fix)
**Files Modified — CoSA (1, commit pending)**: `fifo_queue.py` (desync guard)
**Commit**: 1c064d1

---


## Archives

- [2026-03-26 to 04-07](history/2026-03-26-to-04-07-history.md) — Sessions 379-a47f938e (BFE Phase 6, CJ Flow persistence, Sonnet pivot, UPE LanceDB isolation)
- [Full archive index](history/README.md)
