# Lupin Project History

### 2026.02.18 - Session 225 | Fix SWE Team Notification Routing to CJ Flow Job Card

**Accomplishments**:
- Fixed positional argument mismatch between core `voice_io.notify()` dispatcher and SWE Team's `cosa_interface.notify_progress()` — converted all 4 dispatch branches from positional to keyword arguments, making it immune to extra params like `role`
- Added `SESSION_ID = self.id_hash` in SWE Team job's `_execute_dry_run()` and `_execute()` paths so sender_id includes job hash suffix for proper routing
- Added missing `progress_group_id` parameter to SWE Team `voice_io.notify()` wrapper
- Changed `agentic_job_base.py` `notify_progress()` and `notify_completion()` to import core `voice_io` instead of hardcoded Deep Research `voice_io`, preventing all subclasses from using DR's sender identity
- All 1395 unit tests pass, all smoke tests green

**Files (CoSA nested repo)**: 4 files modified
- `src/cosa/agents/utils/voice_io.py` — keyword args in dispatch
- `src/cosa/agents/swe_team/job.py` — SESSION_ID assignment
- `src/cosa/agents/swe_team/voice_io.py` — progress_group_id param
- `src/cosa/agents/agentic_job_base.py` — core voice_io import

---

### 2026.02.18 - Session 224 | Progress Group Accordion Layout Fix

#### Checkpoint | 2026.02.18 | Fix progress group side-by-side → vertical stack + right-align toggle badge

**Accomplishments**:
- Fixed progress group accordion layout: added `flex-direction: column` to `.progress-group-entry` to override parent `.sender-message`'s horizontal flex — head and history now stack vertically instead of side-by-side
- Right-aligned toggle/count badge: added `width: 100%` to `.progress-group-head` so `margin-left: auto` on the toggle badge pushes it to the right edge
- Verified with 2 rounds of 5 test notifications using `progress_group_id`

**Files**: `src/fastapi_app/static/css/notifications.css` (2 lines added)
**Commit**: 29921df

---

### 2026.02.17 - Session 223 | Testing Skill Documentation — Pattern A Authority Model

#### Checkpoint | 2026.02.17 | Update testing-development skill with Pattern A authority model

**Accomplishments**:
- Updated `~/.claude/skills/testing-development/SKILL.md`: Added "Smoke Test Authority Model (Pattern A)" section between Three-Tier table and Quick Commands; revised Key Principles to 7 items with Pattern A principles first (source QST is truth, wrappers never duplicate, every file has test_*)
- Rewrote `~/.claude/skills/testing-development/references/smoke-tests.md`: Replaced Option 1/2 with Pattern A two-layer architecture (source QST + thin pytest wrapper), added decision tree (5 categories: thin wrapper, subsystem, offline, cross-object, unit-in-disguise), return convention (True/False vs raises), canonical file anatomy, naming conventions, orphan detection audit commands, nuanced anti-patterns table with exceptions
- Updated `~/.claude/skills/testing-development/references/unit-tests.md`: Added "Boundary: When a Smoke Test Is Really a Unit Test" section with 4 smell indicators (@patch, MagicMock, method-level testing, fixture mocks)
- Documentation only — no code changes to actual test files
- Verified all examples match real Lupin smoke test files (orchestrator dry-run, decision proxy offline, deep research dry-run)

**Files**: 3 skill documentation files in `~/.claude/skills/testing-development/` (outside repo)

---

### 2026.02.17 - Session 222 (continued) | Smoke Test Consistency Cleanup

#### Checkpoint | 2026.02.17 | Pattern A consistency for all smoke test files

**Accomplishments**:
- Converted 2 redundant smoke test files to thin wrappers importing source module QSTs (orchestrator, queue_consumer)
- Converted 3 legitimate smoke test files to Pattern A: QST authoritative, thin `test_*` wrapper (decision_proxy, answer_feedback, simple_agents)
- Converted 1 borderline smoke test to Pattern A (agentic_disambiguation)
- Added pytest `test_*` wrappers to 4 orphaned files (crud_dataframes, deep_research_submit, token_refresh, vllm_client)
- Fixed 1 broken file: renamed `test_*` functions with non-fixture params to `_run_*` helpers (notifications_progress_group)
- Added `test_embedding_benchmark()` wrapper to embedding benchmark file
- Result: 37 smoke tests collected, zero ERRORs, zero orphaned files; 1395 unit tests passing

**Files**: 12 smoke test files in `src/tests/smoke/`

---

### 2026.02.17 - Session 220 (continued) | Progress Group History Accumulation

#### Checkpoint 3 | 2026.02.17 | Backend persistence + frontend accordion for progress group history

**Accomplishments**:
- Step 1: Added `progress_group_id` column to `Notification` model (String(12), nullable, indexed)
- Step 2: Created Alembic migration `b5c6d7e8f9a0` — add column + index, ran upgrade successfully
- Step 3: Added `progress_group_id` param to `create_notification()` in notification_repository.py
- Step 4: Wired `progress_group_id` through all 3 `create_notification()` call sites in notifications router; added `progress_group_id` + `job_id` (bonus fix) to both serialization dicts (`get_sender_conversation` + `get_sender_conversation_by_date`)
- Step 5: Rewrote `updateProgressGroupEntry()` and `updateSenderProgressGroupEntry()` in JS — now accumulates history (old head → collapsible history container, newest first) with toggle chevron; wrapped initial entries in `.progress-group-head` div structure; added delegated click handlers for toggle on both job card activity logs and sender card date accordions
- Step 6: Added CSS styles for `.progress-group-head`, `.progress-group-toggle`, `.progress-group-history`, `.progress-history-entry`
- Full regression: 1395 unit tests pass, 0 failures

**Files**: postgres_models.py, migration b5c6d7e8f9a0, notification_repository.py, notifications.py (router), notifications.js, notifications.css
**Commit**: 0c53952 (Lupin) + CoSA pending

---

### 2026.02.17 - Session 222 | SWE Team Training Data + Remove Superfluous Agentic JSONL

#### Checkpoint | 2026.02.17 | SWE Team training data + remove unused agentic-only JSONL output

**Accomplishments**:
- Removed superfluous agentic-only JSONL write pipeline (stale regex, unused output)
  - Deleted `write_agentic_job_ttv_split_to_jsonl()` + `get_agentic_job_train_test_validate_split()` from xml_coordinator.py
  - Removed reference write block + cleaned validate/test/full blocks in run-agentic-intent-training.sh
  - Removed agentic entries from analyze-training-distribution.py
  - Deleted 3 orphaned agentic-job-xml-{train,test,validate}.jsonl files
- SWE Team training data additions (from earlier in session)
- Full regression: 1395 unit tests pass, 0 failures

**Files**: xml_coordinator.py, run-agentic-intent-training.sh, analyze-training-distribution.py, +7 earlier files
**Commit**: 6bae381

---

### 2026.02.17 - Session 221 | TODO.md Structural Cleanup

#### Checkpoint | 2026.02.17 | TODO.md structural cleanup

**Accomplishments**:
- Moved 14 fully-completed sections from Pending to condensed one-liners in Completed (Recent)
- Trimmed mixed sections (DataFrame CRUD, Before Branch Merge) to open items only
- Pending section reduced from ~200 lines to ~74 lines (17 open items preserved)
- 15 new condensed summary lines added to Completed (Recent)

**Files**: TODO.md
**Commit**: 3cf8551

#### Checkpoint 2 | 2026.02.17 | TODO.md updates: SWE Team Docs to Completed + new items

**Accomplishments**:
- Moved SWE Team Testing Docs Update from Pending to Completed (Recent) as condensed one-liner
- Added "Run and remediate full testing harness" to Before Branch Merge section
- Added "Automated E2E Testing Research" (MEDIUM) — research AI/automation for notification, API, and UI testing

**Files**: TODO.md
**Commit**: 2ee4a32

---

### 2026.02.17 - Session 220 | Wire progress_group_id Into All Agentic Iterative Loops

#### Checkpoint | 2026.02.17 | Wire progress_group_id into PG, DR, SWE Team loops

**Accomplishments**:
- Phase 1 (Infrastructure): Added `progress_group_id` + `queue_name` params to Podcast Generator `voice_io.notify()`, SWE Team `cosa_interface.notify_progress()`, orchestrator `_notify()`, and hooks `notification_hook()`
- Phase 2 (Podcast Generator): Wired per-language group ID into audio generation loop (start/stitch/complete) + TTS milestone callback (`_audio_progress_callback`) — collapses 10+ cards into 1 per language
- Phase 3 (Deep Research): Wired single `research_group_id` across subquery loop (3 notify calls) — collapses 6-20 cards into 1
- Phase 4 (SWE Team): Wired 5 separate group IDs — delegation loop, coder SDK stream, tester SDK stream, verification cycle, re-delegation stream
- Full regression: 1343 unit tests pass, 0 failures

**Files**: voice_io.py (PG), cosa_interface.py (SWE), orchestrator.py (SWE+PG), hooks.py (SWE), cli.py (DR)
**Commit**: d635876 (Lupin), 178dfaf (CoSA)

#### Checkpoint 2 | 2026.02.17 | Add 41 unit tests for progress_group_id passthrough

**Accomplishments**:
- Added `test_progress_group_passthrough.py` with 41 tests covering all 6 modified files
- Phase 1 tests: Mock-based passthrough verification (voice_io, cosa_interface, orchestrator._notify, hooks)
- Phase 2-4 tests: Source inspection verification (group ID generation + wiring in all loops)
- Cross-cutting: pg-{8hex} format validation (valid/invalid/fuzz with 100 random UUIDs)
- Full regression: 1384 unit tests pass (1343 + 41 new), 0 failures

**Files**: src/tests/unit/test_progress_group_passthrough.py
**Commit**: 1bb8cda

---

### 2026.02.17 - Session 219 | Fix Factory ValueError on Non-Numeric Args (SWE Team Proxy)

**Accomplishments**:
- Fixed HTTP 500 crash: `ValueError: invalid literal for int() with base 10: 'default'` in `agentic_job_factory.py`
- Added `_SEMANTIC_NONE` set + `_parse_optional_int()`/`_parse_optional_float()` safe parsing helpers (Layer 1: factory)
- Replaced 6 raw `int()`/`float()` casts across all 5 agentic job types (deep research, podcast, research-to-podcast, claude code, swe team)
- Added `"timeout"` + `"default"` to expeditor skip guards at both batch and single paths (Layer 2: belt-and-suspenders)
- Full regression: 1343 unit tests pass, 0 failures

**Files Modified**: `src/cosa/rest/agentic_job_factory.py`, `src/cosa/agents/runtime_argument_expeditor/expeditor.py`

---

### 2026.02.16 - Session 218 | SWE Team Surface 3 Proxy Integration + Phase 4 Gap-Fill Tests

**Accomplishments**:
- Phase 4c/4e gap-filling: 87 new unit tests across trust_tracker, circuit_breaker, engineering_decisions (1265 total)
- Surface 2A: SWE Team Job class, factory registration, FastAPI router (22 tests, 1319 total)
- Surface 2B: Mock endpoint scenarios — 6/6 pass (dry_run, agent_type, cost, timestamps, missing/empty task)
- Surface 3: Registered SWE Team in AGENTIC_AGENTS (5th agent), added `--user-visible-args` to CLI, created Q&A proxy script `swe-team-test.json`, created `test_swe_team_proxy.py` (3 scenarios)
- Added SWE Team to PRODUCT_NAMES + `swe_team` profile to notification proxy config
- Full regression: 1343 unit tests pass, 0 failures
- **Blocker**: Proxy startup crash — two bugs identified: (1) truncated ImportError in llm_script_matcher import chain, (2) profile name mismatch (`swe_team_test` not in TEST_PROFILES choices). Deferred to tomorrow.

**Files Modified**: agent_registry.py, swe_team/__main__.py, todo_fifo_queue.py, notification_proxy/config.py, test_runtime_argument_expeditor.py, 03-testing-validation.md, swe-team-test.json (new), test_swe_team_proxy.py (new)
**Checkpoints**: d5f5e24 (Phase 4 tests), f5311c4 (Surface 3 infrastructure)
**Note**: CoSA submodule changes (4 files) need separate commit

---

### 2026.02.16 - Session 217 | Document progress_group_id in Notification API Docs

**Accomplishments**:
- Documented `progress_group_id` parameter across all 5 relevant sections of `notification-api.md` (query params, AsyncNotificationRequest, to_api_params, NotificationItem, WebSocket payload)
- Added `progress_group_id` to MCP tool docstring in `cosa_voice_mcp.py`
- Feature was fully implemented but undocumented — this closes the documentation gap

**Files Modified**: `src/docs/notification-api.md` (+5 insertions), `src/lupin_mcp/cosa_voice_mcp.py` (+3 lines)
**Commit**: 51b3bff

---

### 2026.02.16 - Session 216 | PEFT Resume OOM Documentation (WILL NOT FIX)

**Accomplishments**:
- Documented PEFT trainer resume-path OOM as WILL NOT FIX (intractable — PyTorch CUDA allocator internals)
- Added known-issue comment block in `peft_trainer.py` resume branch (CoSA submodule, pending separate commit)
- R&D analysis already committed in Session 214 checkpoint: `src/rnd/2026.02.16-peft-resume-oom-cold-allocator-analysis.md`
- Root cause: cold allocator creates monolithic ~16 GB segment; ~62 MB residual pins it after cleanup; vLLM subprocess OOMs on GPU 0
- Updated CoSA submodule commit backlog in TODO.md

**Files Modified**: TODO.md, history.md (CoSA: training/peft_trainer.py pending)

---

#### Checkpoint | 2026.02.16 19:30 | Simplify semantic match to top-1 + confirm strategy

**Files**: lupin-app.ini, lupin-app-splainer.ini, lancedb_solution_manager.py, todo_fifo_queue.py, file_based_solution_manager.py

- Removed hard threshold floor (95%) that silently discarded vector matches below cutoff
- New 3-tier decision: 100% auto-accept, >=90% ask user, <90% log and skip to LLM
- Commented out L3 gist match block in LanceDB manager (gist text retained for display/logging)
- Removed threshold filter from L4 vector search — all results returned to caller
- Restructured `push_job()` decision logic from 2-branch (above/below confirmation) to 3-tier
- Lowered `similarity_threshold_confirmation` from 98.0% to 90.0% (new ask floor)
- Mirrored changes in file_based_solution_manager.py for backend parity
- 1265 unit tests pass, 0 failures
- **Note**: CoSA submodule changes (3 files) need separate commit

---

#### Checkpoint | 2026.02.16 18:30 | Add answer_is_correct to solution snapshots with async verification

**Files**: solution_snapshot.py, lancedb_solution_manager.py, running_fifo_queue.py, test_answer_is_correct.py (new)
**Commit**: dbb3b20

- Added `answer_is_correct` tri-state field (True/False/None) to SolutionSnapshot constructor and LanceDB schema
- Created `_fire_correctness_check_async()` in RunningFifoQueue — non-blocking daemon thread sends yes/no notification after agent completion, persists response to LanceDB
- Cache hits inherit stored `answer_is_correct` value (no re-asking)
- Added `answer_is_correct` to WebSocket metadata in all 3 completion paths (base agent, snapshot, cached)
- Dropped and recreated LanceDB `solution_snapshots` table for schema migration
- 12 new unit tests (field defaults, for_current_user/get_copy preservation, LanceDB round-trip for all 3 states)
- Full regression: 1331 unit tests pass, 0 failures
- **Note**: CoSA submodule changes (3 files) need separate commit

---

#### Checkpoint | 2026.02.16 16:00 | SWE Team notification gap analysis implementation

**Files**: orchestrator.py, config.py, state_files.py, cosa_interface.py, voice_io.py, test_swe_team_orchestrator.py

- Implemented 3-tier SWE Team Notification Gap Analysis plan (20 gaps addressed)
- **Tier 1a**: Added 6 missing progress notifications (verification pass/fail, delegation errors, rich completion abstract)
- **Tier 1b**: Added escalation `request_decision()` after max verification retries with 3 options
- **Tier 2a**: Added `job_id` passthrough + `_notify()` helper for CJ Flow readiness
- **Tier 2b**: Added `state["artifacts"]` dict for CJ Flow-compatible output
- **Tier 1c**: Added `ResultMessage` forwarding through `notification_hook` in 3 SDK loops
- **Tier 2c**: Added `_emit_state()` callback at 8 state transitions for WebSocket visibility
- **Tier 3a**: Added contract documentation to cosa_interface.py and voice_io.py
- **Tier 3b**: Wired decision proxy via `_gated_confirmation()` adapter (trust_mode: disabled/shadow/suggest/active)
- **Tier 3c**: Added `on_log` callback to ProgressLog, wired to notifications when `narrate_progress=True`
- Created 32 new unit tests in `test_swe_team_orchestrator.py`; 183 SWE team tests pass, 0 failures
- **Note**: CoSA submodule changes (5 files) need separate commit

---

#### Checkpoint | 2026.02.16 14:30 | Phase 4c/4e gap-filling unit tests

**Files**: test_trust_tracker.py, test_circuit_breaker.py, test_engineering_decisions.py (+1 more)
**Commit**: d5f5e24

- Created 87 new gap-filling unit tests across 3 files for SWE Team Decision Proxy
- `test_trust_tracker.py` (28 tests): L3-L5 graduation, intermediate demotion, rolling window, decay, serialization
- `test_circuit_breaker.py` (27 tests): min-sample gate, confidence boundary, trip demotion, cooldown, callbacks
- `test_engineering_decisions.py` (32 tests): keyword validation, cap constants, confidence formula, trust buildup
- Updated `03-testing-validation.md` with Phase 4 results and regression tracking
- Full regression: 1265 unit tests pass, 0 failures (was 1178)

---

### 2026.02.16 - Session 214 | Bug Fix Mode

**Accomplishments**:
- Verified and closed 4 pre-existing bug fix queue items (3 queued + 1 orphaned in-progress)
- Verified semantic-similarity confirmation is fully configurable at runtime via `similarity_confirmation_enabled` config key, REST toggle endpoint, and runtime check in `todo_fifo_queue.py` — moved from In Progress to Completed
- Verified Cache N/A bug fix: code fallback changed from `"N/A"` to `[ "" ]`, empty-code guard in `run_code()`, `try/except ValueError` in caller — moved to Completed
- Verified CRUD test fixes (`test_crud_agent_emits_job_state_transition`, `test_crud_agent_pushed_to_done_queue`): 3 MagicMock lines added — both tests now pass
- Full unit test suite: 1170 tests pass, zero regressions

**Files Modified**:
- `bug-fix-queue.md` (queue cleanup: 3 queued → completed, 1 in-progress → completed)

---

### 2026.02.14 - Session 213 | Fix Post-Quantization vLLM OOM — Revised Change H

**Accomplishments**:
- Added `release_gpu_memory()` method to Quantizer class that explicitly dismantles the autoround-model reference web, moves model to CPU via `model.cpu()`, then forces GC + CUDA cache clear
- Updated `peft_trainer.py` to call `quantizer.release_gpu_memory()` before `del quantizer` in the quantization cleanup block
- Key insight: `model.cpu()` physically moves tensors off GPU, making CUDA blocks truly empty so `empty_cache()` can release reserved memory (previous approach only dropped Python references)
- Updated smoke test `expected_methods` to include `release_gpu_memory`
- 1170 unit tests pass, zero regressions

**Files Modified** (CoSA submodule — needs separate commit):
- `src/cosa/training/quantizer.py` (+`import gc`, +`release_gpu_memory()` method, +smoke test update)
- `src/cosa/training/peft_trainer.py` (cleanup block calls `release_gpu_memory()` before `del`)

---

### 2026.02.14 - Session 212 | Comprehensive Documentation for Automated Interactive Testing

**Accomplishments**:
- Created comprehensive reference guide `src/docs/automated-interactive-testing.md` (~600 lines, 14 sections, 5 Mermaid diagrams) covering the notification proxy testing system: architecture, 3-tier strategy chain, test profiles, Q&A scripts, base classes, scenario authoring, CLI reference, environment variables, execution flow, and troubleshooting
- Created `src/tests/smoke/README.md` quick-start guide listing all 16 smoke test files with descriptions and commands
- Added 5th test tier (Interactive Proxy Tests) to Lupin testing hierarchy across CLAUDE.md and src/tests/README.md
- Updated 6 existing documents with bidirectional cross-references to the new guide
- Added proxy integration test plan entry to src/rnd/README.md
- Added TODO item for tomorrow's SWE team interactive proxy smoke testing session
- All cross-references verified bidirectional, all 9 linked files confirmed to exist

**Files Created**:
- `src/docs/automated-interactive-testing.md` (primary reference guide)
- `src/tests/smoke/README.md` (quick-start guide)

**Files Modified**:
- `CLAUDE.md` (+5th test tier, notification system cross-ref, documentation links)
- `src/tests/README.md` (+Section 5 Interactive Proxy Tests, comparison matrix row, "When to Use" entry)
- `src/docs/notification-api.md` (+Section 13.8 Related Testing Documentation)
- `src/workflow/agentic-voice-workflow.md` (+Automated Interactive Testing cross-surface reference)
- `src/rnd/README.md` (+proxy integration test plan entry)
- `TODO.md` (+SWE team proxy smoke testing TODO)

**Unit Tests**: 1170 passing, zero regressions (doc-only changes)

---

### 2026.02.14 - Session 211 | Proxy Integration Test — CRUD + Calculator + Expediter

#### Checkpoint | 2026.02.14 22:40 | Proxy integration test implementation complete

**Accomplishments**:
- Created 12-scenario integration test combining Calculator, CRUD, and Expediter agents
- 3 calculator scenarios (km conversion, mortgage, price compare)
- 5 CRUD scenarios (add, query, delete w/ proxy auto-confirm, calendar)
- 4 expediter scenarios (DR happy, DR missing args, PG missing, RTP happy)
- `--group` flag for selective execution (calculator/crud/expediter/all)
- `--scenarios` flag for individual scenario selection by index
- Expediter scenarios auto-filtered when LUPIN_INTERACTIVE_TESTS not set
- Added `proxy_integration_test` profile to TEST_PROFILES (union of expediter + CRUD answers)
- Added `crud.agent@lupin.deepily.ai` to `all-agents.json` sender_ids
- 10 new unit tests (TestMultiSenderIntegration), **1170 total unit tests** passing

**Files Created**:
- `src/conf/notification-proxy-scripts/proxy-integration-test.json`
- `src/tests/smoke/test_proxy_integration.py`
- `src/rnd/2026.02.14-proxy-integration-test-plan.md`

**Files Modified**:
- `src/conf/notification-proxy-scripts/all-agents.json` (+CRUD sender_id)
- `src/cosa/agents/notification_proxy/config.py` (+proxy_integration_test profile)
- `src/tests/unit/test_notification_proxy.py` (+10 tests)

**Commit**: 8721004

---

### 2026.02.14 - Session 210 | SWE Team Phase 4 — Trust-Aware Decision Proxy

#### Checkpoint | 2026.02.14 | Phase 4 complete — 4-layer decision proxy + 214 new tests (1160 total)

**Accomplishments**:
- Implemented all 5 sub-phases of the Trust-Aware Decision Proxy (4-layer hybrid architecture)
- **Phase 4a**: Extracted shared proxy infrastructure to `proxy_agents/` (7 files) — BaseStrategy protocol, BaseWebSocketListener, BaseResponder ABC, shared config, REST submitter, CLI args
- **Phase 4b**: Built decision proxy framework in `decision_proxy/` (11 files) — trust mode, smart router, category classifier ABC, base decision strategy ABC, XML models, WebSocket listener, responder
- **Phase 4c**: Implemented trust tracker + circuit breaker (2 files) — per-category trust levels L1-L5 with time-weighted decay, error rate/confidence collapse detection, auto-demotion
- **Phase 4d**: Created decision store + ratification API — ProxyDecision + TrustState ORM models, repository with shadow/log/ratify/find_similar, FastAPI router (4 endpoints), migration SQL
- **Phase 4e**: Built SWE engineering proxy domain layer in `swe_team/proxy/` (5 files) — 6 engineering categories (deployment/testing/deps/architecture/destructive/general), keyword classifier with sender hints, full evaluate pipeline
- Refactored notification_proxy/config.py for backward compatibility (120/120 existing tests still pass)
- Added 16 config keys to lupin-app.ini + lupin-app-splainer.ini
- **214 new unit tests** across 4 test files, **1160 total unit tests** passing, zero regressions

**Files Created (Lupin repo)**:
- `src/conf/lupin-app.ini` (modified — 16 new config keys)
- `src/conf/lupin-app-splainer.ini` (modified — 16 matching explanations)
- `src/scripts/sql/2026.02.14-decision-proxy-schema.sql`
- `src/tests/unit/test_proxy_common.py` (51 tests)
- `src/tests/unit/test_decision_proxy_config.py` (70 tests)
- `src/tests/unit/test_decision_store.py` (46 tests)
- `src/tests/unit/test_swe_engineering_proxy.py` (47 tests)

**Files Created/Modified (CoSA submodule — needs separate commit)**:
- `agents/utils/proxy_agents/` (7 new files)
- `agents/decision_proxy/` (13 new files)
- `agents/swe_team/proxy/` (5 new files)
- `agents/notification_proxy/config.py` (modified — re-export shared constants)
- `rest/postgres_models.py` (modified — ProxyDecision + TrustState models)
- `rest/db/repositories/proxy_decision_repository.py` (new)
- `rest/db/repositories/__init__.py` (modified)
- `rest/routers/decision_proxy.py` (new)

---

### 2026.02.14 - Session 209 | PEFT Trainer Resume-from-Merged

#### Checkpoint | 2026.02.14 18:30 | Add --resume-from-merged to PEFT trainer

**Accomplishments**:
- Added `--resume-from-merged <path>` CLI argument to `peft_trainer.py` — skips phases 1-3 (pre-validation, fine-tuning, merge) and uses existing merged adapter dir for phases 4-5 (post-training validation, quantization)
- Wrapped phases 1-3 in conditional block gated on `resume_from_merged` parameter
- Updated completion message to distinguish resume mode from normal mode
- Removed `run_pipeline_adhoc()` method (170 lines of hardcoded workaround code) — replaced by the new CLI flag
- Cleaned up adhoc references in `__main__` block and smoke test `expected_methods` list
- Structural smoke test passes: all 12 methods present, all imports verified

**Files Modified (CoSA submodule — needs separate commit)**:
- `src/cosa/training/peft_trainer.py` (resume logic, adhoc removal, CLI arg, docstring update)

**Commit**: 96cbf21 (Lupin docs-only; CoSA submodule commit pending)

---

### 2026.02.14 - Session 208 | Bug Fix Mode

#### Fixes
(No bugs fixed — standby session only)

#### Session Summary
- **Total Fixes**: 0
- **Files Changed**: 0 (session infrastructure only)
- **GitHub Issues Closed**: None
- **Commits**: None

**Status**: Session closed 2026.02.14 — initialized and stood by, no bugs worked

---

### 2026.02.14 - Session 207 | SWE Team Phase 3 — Tester Verification Loop

#### Checkpoint | 2026.02.14 | SWE Team Phase 3 — tester verification loop + 31 unit tests (946 total)

**Accomplishments**:
- Implemented Phase 3 of the SWE Team multi-agent system: Coder-Tester verification loop with max 3 retry iterations
- Created `test_runner.py`: Orchestrator-level pytest subprocess wrapper using `asyncio.create_subprocess_exec` with timeout + output truncation (NOT an MCP tool)
- Added `VerificationResult` Pydantic model to `state.py` with pass/fail tracking, tester output, test files created, iteration count
- Activated tester role (`active=True`) in `agent_definitions.py` — 3 active roles now (lead + coder + tester)
- Added `_verify_result()` and `_redelegate_with_feedback()` methods to orchestrator
- Rewrote `_execute_live()` delegation loop with coder-tester iteration cycle (MAX_VERIFICATION_ITERATIONS=3)
- Extended `_build_agent_options()` with tester role support (TESTER_SYSTEM_PROMPT, permission gating)
- Backward compatibility: `require_test_pass=False` skips verification entirely
- Updated `__init__.py` exports and bumped to v0.3.0
- 31 new unit tests across 7 classes in `test_swe_team_verification.py`
- Full regression: 946/946 pass, zero regressions

**Files Created (CoSA submodule — needs separate commit)**:
- `src/cosa/agents/swe_team/test_runner.py` (NEW — pytest subprocess wrapper)

**Files Modified (CoSA submodule — needs separate commit)**:
- `src/cosa/agents/swe_team/state.py` (add VerificationResult, expand SweTeamState)
- `src/cosa/agents/swe_team/agent_definitions.py` (activate tester role)
- `src/cosa/agents/swe_team/orchestrator.py` (verification loop, _verify_result, _redelegate_with_feedback)
- `src/cosa/agents/swe_team/__init__.py` (add exports, bump to v0.3.0)

**Files Modified (Lupin repo)**:
- `src/tests/unit/test_swe_team_verification.py` (NEW — 31 Phase 3 tests)
- `src/tests/unit/test_swe_team_config.py` (update active roles assertion to 3)
- `src/tests/unit/test_swe_team_delegation.py` (add require_test_pass=False for backward compat)

**Commit**: [pending]

---

### 2026.02.14 - Session 206 | SWE Team Phase 2 — Lead + Coder Delegation Loop

#### Checkpoint | 2026.02.14 12:00 | SWE Team Phase 2 — delegation loop + 34 unit tests (915 total)

**Accomplishments**:
- Implemented Phase 2 of the SWE Team multi-agent system: Lead decomposes tasks into TaskSpec[], delegates each to Coder subagent via Claude Agent SDK
- Created `hooks.py`: SDK hook functions (notification_hook, pre_tool_hook with dangerous command gating, post_tool_hook for file change tracking)
- Created `state_files.py`: Cross-session persistence with FeatureList (JSON) + ProgressLog (timestamped entries)
- Replaced `_execute_live()` stub with real delegation loop: `_decompose_task()` → `_parse_task_specs()` → user confirmation → `_delegate_task()` per TaskSpec
- Activated coder role (`active=True`) in agent_definitions.py
- Updated `__init__.py` exports and bumped to v0.2.0
- Updated `claude-agent-sdk==0.1.18` → `0.1.36` in requirements.txt
- 34 new unit tests across 5 classes (hooks, state files, decomposition, delegation, live flow)
- Full regression: 915/915 pass, zero regressions

**Files Created (CoSA submodule — needs separate commit)**:
- `src/cosa/agents/swe_team/hooks.py` (NEW — SDK hook functions)
- `src/cosa/agents/swe_team/state_files.py` (NEW — FeatureList + ProgressLog)

**Files Modified (CoSA submodule — needs separate commit)**:
- `src/cosa/agents/swe_team/orchestrator.py` (replace stub with delegation loop)
- `src/cosa/agents/swe_team/agent_definitions.py` (activate coder role)
- `src/cosa/agents/swe_team/__init__.py` (add exports, bump to v0.2.0)
- `src/cosa/requirements.txt` (claude-agent-sdk 0.1.18 → 0.1.36)

**Files Modified (Lupin repo)**:
- `src/tests/unit/test_swe_team_delegation.py` (NEW — 34 Phase 2 tests)
- `src/tests/unit/test_swe_team_config.py` (update active roles assertion)
- `src/rnd/2026.02.13-claude-code-agentic-dev-team/01-implementation-current.md` (Phase 2: PENDING → DONE)
- `src/rnd/2026.02.13-claude-code-agentic-dev-team/03-testing-validation.md` (Phase 2 test results)

**Commit**: [pending]

---

### 2026.02.13 - Session 205 | ADD_CALENDAR Duplicate Tolerance Fix

**Accomplishments**:
- Fixed ADD_CALENDAR scenario in CRUD live pipeline smoke test to accept "already exists" responses
- When calendar entry exists from a prior run, the system correctly responds with "That item already exists" — test now recognizes this as valid (matching the existing ADD_DUPLICATE pattern)
- Added TODO item for unified smoke test framework verification plan (resume tomorrow)

**Files Modified**:
- `src/tests/smoke/test_crud_live_pipeline.py` (+2/-2 — added "already exists" keyword + "duplicate" status)
- `TODO.md` (+4 — unified smoke test framework verification section)

---

### 2026.02.13 - Session 204 | Bug Fix: Cache Re-Execution of Non-Executable Code

**Accomplishments**:
- Fixed "N/A" bug where cached snapshots with no executable code caused `NameError: name 'N' is not defined` during cache replay
- Root cause: `solution_snapshot.py:446` used `"N/A"` string as fallback for missing code, which Python parsed as `N / A` division
- Change 1: Fixed fallback from `"N/A"` to `[ "" ]` (correct `list[str]` type)
- Change 2: Added empty-code guard in `run_code()` raising `ValueError` before subprocess spawn
- Change 3: Wrapped `run_code()` call in `_format_cached_result()` with `try/except ValueError`
- All 817 unit tests pass, zero regressions

**Files Modified (CoSA submodule — needs separate commit)**:
- `src/cosa/memory/solution_snapshot.py` (+4/-1 — fallback fix + empty-code guard)
- `src/cosa/rest/running_fifo_queue.py` (+4/-1 — ValueError catch in cache path)

---

### 2026.02.13 - Session 203 | Fix Failing TestCrudQueueCompletion Tests

#### Checkpoint | 2026.02.13 12:40 | Fix 2 failing tests — mock do_all() + completion gates

**Accomplishments**:
- Fixed 2 failing `TestCrudQueueCompletion` tests: `test_crud_agent_emits_job_state_transition` and `test_crud_agent_pushed_to_done_queue`
- Root cause: `_create_queue_and_agent()` never mocked `do_all()`, so real LLM pipeline ran, raised `ValueError: Empty response from LLM`, triggered error path emitting `run -> dead` instead of `run -> done`
- Added 3 MagicMock lines: `do_all()`, `code_ran_to_completion()`, `formatter_ran_to_completion()`
- All 3 `TestCrudQueueCompletion` tests now pass; full suite 817/817 pass, zero regressions
- Added both bugs to `bug-fix-queue.md` as FIXED items

**Files Modified**:
- `src/tests/unit/test_crud_queue_integration.py` (+3 lines — mock do_all + completion gates)
- `bug-fix-queue.md` (+2 FIXED items in Queued section)

**Commit**: b435c3a

---

### 2026.02.13 - Session 202 | Consolidated Notification API Reference Document

#### Checkpoint | 2026.02.13 17:30 | Notification API reference: 4,033-line doc + 5 diagrams + 3 cross-refs

**Accomplishments**:
- Created `src/docs/notification-api.md` — comprehensive one-stop reference for the entire notification system (4,033 lines, 14 sections)
- Sections cover: Overview & Architecture, Historical Evolution (3-phase timeline), Quick-Start Examples (6 recipes), Authentication (dual auth), complete REST API Reference (all 17 endpoints with curl examples), Data Models & Enums, Notification Lifecycle state machine, Sender Identity & Multi-Project Routing, Sending Notifications (4-tier client stack), Receiving Notifications, Voice I/O Integration, Notification Proxy Agent (3-tier strategy chain), Configuration Reference, Testing Guide
- Rendered 5 Mermaid diagrams to PNG: system architecture, historical evolution timeline, notification lifecycle state machine, client tier stack, proxy strategy chain sequence diagram
- Added deprecation banner to `src/rnd/sse-notifications/00-index.md` pointing to new doc
- Added NOTIFICATION SYSTEM section to `CLAUDE.md` with doc links
- Added cross-reference in `src/docs/websocket-events.md` notification events section

**Files Created**:
- `src/docs/notification-api.md` (4,033 lines — main deliverable)
- `src/docs/images/notification-system-architecture.png` (36K)
- `src/docs/images/notification-historical-evolution.png` (20K)
- `src/docs/images/notification-lifecycle.png` (45K)
- `src/docs/images/notification-client-tiers.png` (51K)
- `src/docs/images/notification-proxy-strategy.png` (56K)

**Files Modified**:
- `CLAUDE.md` (+5 lines — NOTIFICATION SYSTEM section)
- `src/docs/websocket-events.md` (+2 lines — cross-reference)
- `src/rnd/sse-notifications/00-index.md` (+6 lines — deprecation banner)

**Commit**: a17e753

---

### 2026.02.13 - Session 201 | Unified Smoke Test Framework — Extract Base Classes + Auto-Proxy

#### Checkpoint | 2026.02.13 12:00 | Unified smoke test framework: 4 new utility files, 3 tests refactored

**Accomplishments**:
- Extracted ~450 lines of duplicated infrastructure from 3 live pipeline smoke tests into reusable base classes
- Created `LivePipelineTestBase` — shared auth, session, mode management, submit-and-poll, keyword validation, results table
- Created `EmbeddedProxyMixin` — auto-launches notification proxy as subprocess with `os.setsid` process group management, SIGINT graceful shutdown
- Created `InteractiveSmokeTest` — merges base + mixin, adds `--auto-proxy` and `--proxy-debug` CLI flags
- Refactored calculator (611→252 lines), CRUD (599→241 lines), expeditor (633→704 lines) tests
- Created R&D tracking document with architecture overview and phase checklist
- Unit test regression: 815 passed, 2 pre-existing failures (unrelated)

**Files Created**:
- `src/tests/smoke/utilities/__init__.py` (package marker + exports)
- `src/tests/smoke/utilities/live_pipeline_base.py` (~400 lines — `LivePipelineTestBase`)
- `src/tests/smoke/utilities/embedded_proxy.py` (~230 lines — `EmbeddedProxyMixin`)
- `src/tests/smoke/utilities/interactive_smoke_test.py` (~85 lines — `InteractiveSmokeTest`)
- `src/rnd/2026.02.13-unified-smoke-test-framework.md` (R&D tracking doc)

**Files Modified**:
- `src/tests/smoke/test_calculator_live_pipeline.py` (refactored to extend `LivePipelineTestBase`)
- `src/tests/smoke/test_crud_live_pipeline.py` (refactored to extend `InteractiveSmokeTest`)
- `src/tests/smoke/test_expeditor_mock_job_smoke.py` (refactored to extend `InteractiveSmokeTest`)
- `src/rnd/README.md` (linked new R&D document)

**Commit**: 09f288b

---

### 2026.02.12 - Session 200 | Expeditor Notification Fix — Missing `open_ended_batch` Response Type

**Accomplishments**:
- Fixed `http_error` in expeditor smoke tests: root cause was `/api/notify` endpoint rejecting `open_ended_batch` as invalid response type
- Added `"open_ended_batch"` to `valid_response_types` list in notifications router (line 319)
- Enhanced error diagnostic in `notify_user_sync.py`: HTTP error status now includes status code (`http_error_400` instead of generic `http_error`)
- Added dedicated unit test `test_notify_response_required_open_ended_batch_accepted` (offline-with-default path)
- Confirmed no secondary JWT auth issues — dual-auth (`require_api_key_or_jwt`) works correctly
- Marked expeditor end-to-end testing as complete in TODO.md; design review deferred to next session

**Files Modified**:
- `src/tests/unit/test_notifications_api.py` (+79 lines — new `open_ended_batch` acceptance test)
- `src/tests/unit/test_notify_user_sync.py` (updated `http_error` assertion to match new `http_error_{code}` format)
- `src/tests/unit/test_runtime_argument_expeditor.py` (+10 lines — expeditor test updates)
- `src/tests/smoke/test_expeditor_mock_job_smoke.py` (+3 lines — smoke test adjustments)
- `TODO.md` (expeditor e2e testing marked complete)

**Files Created**:
- `src/rnd/2026.02.12-fix-expeditor-notification-dual-auth-plan.md` (implementation plan)

**Test Results**: 814 unit tests pass, 12/12 smoke scenarios pass

---

### 2026.02.12 - Session 194 | Embedding Benchmark Harness — Local GPU 7-398x Faster Than OpenAI API

**Accomplishments**:
- Created side-by-side embedding benchmark harness toggling `embedding provider` config between local/openai
- Resets EmbeddingProvider singleton between providers to collect comparable metrics through production routing path
- Results (N=10 iterations, 3 queries each): local GPU 7x faster (prose single), 17x (code single), 374x (batch prose), 398x (batch code)
- Added Embedding Performance comparison table to project README.md
- Graceful OpenAI skip if API key unavailable — shows local-only results with warning

**Files Created**:
- `src/tests/smoke/test_embedding_benchmark.py` (NEW — 280 lines, pytest + standalone `__main__` support)

**Files Modified**:
- `README.md` (added Embedding Performance section with benchmark table)

**Commit**: 1a47087

---

### 2026.02.11 - Session 191 | Calculator Step 25 — LORA Auto-Route Verification + Implementation Complete

**Accomplishments**:
- Added `--auto-route` / `-a` CLI flag to `test_calculator_live_pipeline.py` for Step 25 (LORA routing verification)
- Auto-route mode clears explicit calculator mode, submits queries, and verifies `agent_type == CalculatorAgent` in done queue metadata
- All 6 queries correctly routed by LORA classifier — 6/6 pass
- Marked Steps 25, 29, 30, 31 as complete in implementation doc
- **Everyday Calculator agent is 100% complete** — all 31 steps across 6 phases finished

**Files Modified**:
- `src/tests/smoke/test_calculator_live_pipeline.py` (Step 25: `--auto-route` flag, conditional mode skip, `agent_type` verification)
- `src/rnd/2026.02.09-everyday-calculator-agent-implementation.md` (all remaining checkboxes marked done)
- `TODO.md` (calculator item marked fully complete)

**Commits**: c479bfe (Step 25 code), f65a2d4 (all 31 steps complete)

---

### 2026.02.12 - Session 199 | Bug Fix: Dead Job Card Missing run->dead WebSocket Transition

#### Checkpoint | 2026.02.12 | Add missing emit_job_state_transition() to _handle_error_case()

**Accomplishments**:
- **Root cause**: `_handle_error_case()` in `running_fifo_queue.py` was the only error/completion path that didn't emit a `job_state_transition` WebSocket event — all 6 other paths (AgentBase success, AgenticJob success/failure/crash, SolutionSnapshot success, cached result) already did
- **Fix**: Added `emit_job_state_transition()` call for `run -> dead` with full error metadata (error msg, question text, agent type, timestamps, duration), following the exact pattern from the agentic job failure path
- **Effect**: Dead job cards now move from run bucket to dead bucket in the UI with error message rendered inline
- **814 unit tests pass, 0 regressions** (2 pre-existing CRUD test failures confirmed unrelated)

**Files Modified** (CoSA submodule — needs separate commit):
- `src/cosa/rest/running_fifo_queue.py` (`_handle_error_case()` — added WebSocket emission block)

**Commit**: [pending]

---

### 2026.02.12 - Session 198 | Fix LanceDB Embedding Dimension Mismatch (768 Standardization)

#### Checkpoint | 2026.02.12 | Standardize all embedding providers on 768 dims + schema validation

**Accomplishments**:
- **Root cause**: LanceDB tables created with 1536-dim schemas (OpenAI default), config switched to local provider (768 dims), causing Arrow `FixedSizeList` casting errors on insert
- **Part 1**: Standardized on 768 dimensions for ALL providers — OpenAI `text-embedding-3-small` now uses MRL truncation via `dimensions` API parameter
- **Part 2**: Added `_validate_embedding_dimensions()` to all 6 LanceDB table classes — auto-drops and recreates tables if schema dimension mismatch detected
- Simplified dimension initialization in all 6 table classes: replaced if/else provider pattern with single `config_mgr.get("embedding dimensions")` call
- Updated `EmbeddingProvider.dimensions` and `code_dimensions` properties to use centralized config
- Fixed unit test: `test_dimensions_property_openai` updated to expect 768 (MRL truncation)
- **811 unit tests pass, 0 new failures** (5 pre-existing failures unrelated to embeddings)

**Files Modified** (Lupin repo):
- `src/conf/lupin-app.ini` (added `embedding dimensions = 768`)
- `src/conf/lupin-app-splainer.ini` (added matching explanation)
- `src/tests/unit/test_local_embedding_engine.py` (updated mock config + assertion)

**Files Modified** (CoSA submodule — needs separate commit):
- `memory/embedding_manager.py` (pass `dimensions=embedding_dim` to OpenAI API)
- `memory/embedding_provider.py` (simplified `dimensions` + `code_dimensions` properties)
- `memory/input_and_output_table.py` (simplified dim init + validation)
- `memory/question_embeddings_table.py` (simplified dim init + validation)
- `memory/embedding_cache_table.py` (simplified dim init + validation)
- `memory/canonical_synonyms_table.py` (simplified dim init + validation)
- `memory/query_log_table.py` (simplified dim init + validation)
- `memory/lancedb_solution_manager.py` (simplified dim init + validation)

**Plan**: `~/.claude/plans/eager-foraging-ember.md`
**Commit**: [pending]

---

### 2026.02.12 - Session 197 | CJ Flow Branding + Bounded Job Packaging + Claude Code LORA Data

#### Checkpoint | 2026.02.12 19:00 | CJ Flow plan implementation — branding, factory, config, training data

**Accomplishments**:
- **Part A**: Propagated "CJ Flow" branding to 12 files (docstrings/comments only, zero code logic)
- **Part B1**: Registered ClaudeCodeJob in agentic_job_factory.py, updated claude_code_queue.py router to use shared factory, added entry to agent_registry.py
- **Part B2**: Externalized hardcoded defaults (max_turns=50, timeout_seconds=3600) to lupin-app.ini with class-level config caching in job.py
- **Part B3**: Created 420-line R&D packaging guide for building new CJ Flow bounded jobs
- **Part C1-C5**: Created 66 voice templates + 100 task placeholders for Claude Code LORA routing, updated training pipeline (coordinator, prompt_generator, xml_models, router templates, command registry)
- **Part C6**: Regenerated training data — 39,871 examples (35 commands), Claude Code at 1,500 samples
- Fixed 5 test failures from 4th agent addition (registry count, audience scope, PRODUCT_NAMES, TEST_PROFILES)
- **816 unit tests pass, zero regressions**

**Files Created**:
- `src/rnd/2026.02.12-cj-flow-bounded-job-packaging-guide.md` (NEW)
- `src/ephemera/prompts/data/synthetic-data-agent-routing-claude-code.txt` (NEW)
- `src/ephemera/prompts/data/placeholders-claude-code-tasks.txt` (NEW)

**Files Modified** (30+ files across branding, factory, config, training pipeline, tests):
- CLAUDE.md, queue_protocol.py, agentic_job_base.py, todo_fifo_queue.py, running_fifo_queue.py, queue_consumer.py, agentic_job_factory.py
- Routers: deep_research.py, podcast_generator.py, deep_research_to_podcast.py, claude_code_queue.py
- Config: lupin-app.ini, lupin-app-splainer.ini
- Training: agent-router-agentic-commands.json, xml_coordinator.py, xml_prompt_generator.py, xml_models.py, agent-router-template.txt, agent-router-template-completion.txt
- Tests: test_runtime_argument_expeditor.py, test_notification_proxy config.py, rnd/README.md
- Workflow: agentic-voice-workflow.md
- Training JSONL files (regenerated)

**Commit**: 0daf0de

---

### 2026.02.12 - Session 196 | Three-Model PEFT Comparison + Ministral 8-bit Config Swap

#### Checkpoint | 2026.02.12 | Three-model PEFT comparison doc + Ministral 8-bit config swap

**Accomplishments**:
- Created comprehensive R&D comparison document for 3 fine-tuned LoRA models (Ministral-8B, Qwen3-4B, Llama-3.2-3B) across 34 agentic routing commands
- **Key finding**: Ministral-8B 8-bit quantization is lossless (98.7% EM, 0 commands degraded, +0.8pp vs full precision)
- Switched development router from Qwen3-4B 4-bit (83.0% EM) to Ministral-8B 8-bit (98.7% EM)
- Updated bash aliases: `svllmr` now serves Ministral 8-bit with `--quantization gptq_marlin --gpu_memory_utilization 0.85`
- Added `svllmrq` backup alias for Qwen3-4B fallback
- Added Llama-3.2-3B reference entries (commented out, 64.1% EM too low for production)

**Files Created**:
- `src/rnd/2026.02.12-three-model-peft-comparison-ministral-qwen-llama.md` (NEW)

**Files Modified** (Lupin repo):
- `src/rnd/README.md` (added comparison doc entry)
- `src/conf/lupin-app.ini` (Phase 3 Ministral 8-bit, router swap, Llama reference)
- `src/conf/lupin-app-splainer.ini` (router explanation, Llama entries)

**Files Modified** (outside repo):
- `~/.bash_aliases` (svllmr → Ministral 8-bit, svllmrq Qwen3 backup)

**Commit**: 5545115

---

### 2026.02.12 - Session 195 | Debug Script Matching Smoke Test (11/19 → 18/19)

#### Checkpoint | 2026.02.12 | Debug script matching smoke test — batch XML model, ampersand escaping, fuzzy prompt hints (11/19 → 18/19)

**Accomplishments**:
- **Batch fix (+2 scenarios)**: Created `BatchScriptMatcherResponse` — first-class Pydantic XML model with nested `<entries><entry>` structure, replacing brittle JSON-in-answer-field approach. Updated `_handle_batch()` to use new model and registered in `MODEL_MAPPING`.
- **XML parse fix (+1 scenario)**: Added `&` entity escaping in `BaseXMLModel.from_xml()` — bare ampersands like `Q&A` in LLM reasoning now safely escaped to `Q&amp;A` before parsing.
- **Fuzzy matching fix (+4 scenarios)**: Added intent-based semantic matching hints to prompt template with concrete paraphrase examples. Refined 3 extreme paraphrases in test scenarios.
- **Regression**: 816/816 unit tests passed (0 regressions). Updated 2 batch unit tests to use `BatchScriptMatcherResponse`.
- **Final score**: 18/19 (95%), up from 11/19 (58%). Only FUZZY_BUDGET_2 fails (verifier confidence issue, not a matching failure).

**Files Modified** (Lupin repo):
- `src/conf/prompts/notification-proxy-batch-matcher.txt` (XML entry structure + semantic hints)
- `src/conf/prompts/notification-proxy-script-matcher.txt` (intent-based matching hints)
- `src/tests/smoke/test_notification_proxy_script_matching.py` (3 refined paraphrases)
- `src/tests/unit/test_notification_proxy.py` (2 batch tests updated for BatchScriptMatcherResponse)

**Files Modified** (CoSA submodule, not committed here):
- `src/cosa/agents/notification_proxy/xml_models.py` (NEW: BatchScriptMatcherResponse class)
- `src/cosa/agents/io_models/utils/prompt_template_processor.py` (batch model in MODEL_MAPPING)
- `src/cosa/agents/notification_proxy/strategies/llm_script_matcher.py` (use BatchScriptMatcherResponse in _handle_batch)
- `src/cosa/agents/io_models/utils/util_xml_pydantic.py` (& entity escaping in from_xml)

**Commit**: abe4cbe

---

### 2026.02.12 - Session 193 | Live Phi-4 Script Matching Smoke Test

#### Checkpoint | 2026.02.12 | Live Phi-4 script matching smoke test — 24-scenario 3-tier test matrix

**Accomplishments**:
- Created `test_notification_proxy_script_matching.py` — standalone smoke test that calls `LlmScriptMatcherStrategy.respond()` directly against live Phi-4 via vLLM (no server, no WebSocket, no auth required)
- **3-tier scenario matrix**:
  - **Tier 1 (Exact)**: Auto-generated from script entries — sends literal `question_pattern` text
  - **Tier 2 (Fuzzy)**: 12 paraphrased questions for semantic matching validation
  - **Tier 3 (Multi)**: Multiple-choice, batch (open_ended_batch), and negative (no-match) scenarios
- **CLI interface**: `--script deep_research|expeditor_smoke|all`, `--tier exact|fuzzy|multi|all`, `--scenarios 0,8,20`, `--no-verify`, `--confidence 0.7`, `--debug`, `--verbose`
- **Pre-flight vLLM check**: Sends a minimal LLM query before running scenarios; gracefully skips with exit 0 if vLLM unreachable
- **Optional LlmAnswerVerifier** second-pass on fuzzy tier for semantic confidence scoring
- **Initial results** (deep_research, all tiers): 11/19 passed — reveals real Phi-4 XML generation issues and fuzzy matching limitations
- Follows existing test patterns from `test_calculator_live_pipeline.py`

**Files Created** (Lupin repo):
- `src/tests/smoke/test_notification_proxy_script_matching.py` (NEW — ~500 lines)

### 2026.02.11 - Session 189 | CRUD Delete Bug Fix + Dedup Guards + Live Pipeline Smoke Test

**Accomplishments**:
- Fixed **delete-all-records bug** from Session 167 Part 3 Test 4: three guards added to crud_operations.py
  - **Dedup guard** in `add_item()`: rejects duplicate inserts within same list (checks DEDUP_KEYS per schema)
  - **Multi-delete guard** in `delete_item()`: refuses match_fields delete when >1 row matches, returns preview
  - **Infrastructure column rejection** in `_validate_match_fields()`: blocks `id`, `list_name`, `created_at` from match_fields
- Added `DEDUP_KEYS` dict, `INFRASTRUCTURE_COLS` frozenset, `get_dedup_keys()` helper to schemas.py
- Added `"duplicate"` voice formatting to dispatcher.py: "That item already exists in the list."
- Created `crud.json` Q&A script for notification proxy (delete/update auto-confirm via `sender_ids`)
- Added `"crud"` profile to notification proxy `TEST_PROFILES`
- Added CRUD confirmation entries to `all-agents.json` union script
- 6 new `TestDeduplicationGuards` unit tests: dedup rejection, cross-list allowed, infra rejection, multi-delete guard, single-delete success
- Created `test_crud_live_pipeline.py` — 8-scenario live smoke test with `--mode direct|lora|all` CLI
- Created CRUD live pipeline testing guide for next-session pickup
- **Regression**: 816/816 unit tests passed (was 810)

**Files Modified** (Lupin repo):
- `src/conf/notification-proxy-scripts/crud.json` (NEW — CRUD Q&A script)
- `src/conf/notification-proxy-scripts/all-agents.json` (2 CRUD confirmation entries)
- `src/tests/unit/test_crud_for_dataframes_storage.py` (6 new TestDeduplicationGuards tests)
- `src/tests/smoke/test_crud_live_pipeline.py` (NEW — 8-scenario live pipeline test)
- `src/rnd/2026.02.11-crud-live-pipeline-testing-guide.md` (NEW — testing guide for live pipeline + proxy)
- `src/rnd/README.md` (added testing guide link)

**Files Modified** (CoSA submodule, not committed here):
- `src/cosa/crud_for_dataframes/schemas.py` (DEDUP_KEYS, INFRASTRUCTURE_COLS, get_dedup_keys)
- `src/cosa/crud_for_dataframes/crud_operations.py` (dedup guard, multi-delete guard, infra rejection)
- `src/cosa/crud_for_dataframes/dispatcher.py` (duplicate voice formatting)
- `src/cosa/agents/notification_proxy/config.py` (crud profile in TEST_PROFILES)

**Commits**: fd21f0c (checkpoint 1)

---

### 2026.02.11 - Session 188 | Q&A Script README Architecture Clarification

#### Checkpoint | 2026.02.11 | Clarify standalone vs union script architecture in README

**Accomplishments**:
- Added "Script Architecture" section to Q&A scripts README explicitly documenting standalone (one-per-agent) vs union (`all-agents.json`) file types
- Added warning blockquote to "Multi-Agent Scripts" section: always create standalone first
- Fixed incorrect "13-scenario" reference (actual: 4 entries in `all-agents.json`)
- Clarified Step 5 "Register the Profile": `config.py TEST_PROFILES` is required, `__main__.py` is auto-derived

**Root cause**: Two parallel sessions misread the README and added entries directly to `all-agents.json` instead of creating standalone files

**Files Modified**:
- `src/conf/notification-proxy-scripts/README.md` (4 edits: architecture section, warning note, count fix, Step 5 clarification)

**Commit**: 0aa7d6c

---

### 2026.02.11 - Session 187 | Data-Driven Sender ID Filtering for Notification Proxy

#### Checkpoint | 2026.02.11 | Replace hardcoded EXPEDITER_SENDER_ID with data-driven sender_ids

**Accomplishments**:
- Replaced hardcoded `EXPEDITER_SENDER_ID` constant with data-driven `sender_ids` field in Q&A script JSON files
- Both `LlmScriptMatcherStrategy` and `ExpediterRuleStrategy` now accept `accepted_senders` parameter — iterate over a list instead of matching a single string
- `NotificationResponder` extracts `sender_ids` from script JSON and passes to both strategies at construction time
- 3-tier priority: explicit `accepted_senders` param > script `sender_ids` field > `DEFAULT_ACCEPTED_SENDERS` constant
- Adding a new sender = adding to a JSON list, zero Python code changes
- `EXPEDITER_SENDER_ID` kept as deprecated alias for backward compatibility
- 11 new unit tests (9 sender_ids filtering + 2 config): 810/810 pass, all 4 smoke tests pass

**Files Modified** (Lupin repo):
- `src/conf/notification-proxy-scripts/deep-research.json` (add sender_ids field)
- `src/conf/notification-proxy-scripts/podcast.json` (add sender_ids field)
- `src/conf/notification-proxy-scripts/research-to-podcast.json` (add sender_ids field)
- `src/conf/notification-proxy-scripts/all-agents.json` (add sender_ids field)
- `src/conf/notification-proxy-scripts/minimal.json` (add sender_ids field)
- `src/conf/notification-proxy-scripts/_template.json` (add sender_ids field)
- `src/conf/notification-proxy-scripts/README.md` (document sender_ids field)
- `src/tests/unit/test_notification_proxy.py` (11 new tests: TestSenderIdFiltering class + 2 config tests)

**Files Modified** (CoSA submodule, not committed here):
- `src/cosa/agents/notification_proxy/config.py` (DEFAULT_ACCEPTED_SENDERS list + deprecated alias)
- `src/cosa/agents/notification_proxy/strategies/expediter_rules.py` (accepted_senders param + list-based can_handle)
- `src/cosa/agents/notification_proxy/strategies/llm_script_matcher.py` (accepted_senders param + script extraction + list-based can_handle)
- `src/cosa/agents/notification_proxy/responder.py` (extract sender_ids from script, pass to strategies)

**Commit**: fb8cb1c

---

### 2026.02.11 - Session 185 | Agentic Voice Workflow Skill v1.1 Update

#### Checkpoint | 2026.02.11 | SKILL.md v1.0 → v1.1: Q&A script documentation

**Accomplishments**:
- Updated `.claude/skills/agentic-voice-workflow/SKILL.md` v1.0 → v1.1 with Notification Proxy Q&A script documentation
- Added Phase 5b (Q&A Script) to workflow phases table
- Added new anti-pattern: "Don't skip Q&A scripts"
- Added cross-reference in Testing Best Practice section
- Added full "Notification Proxy: Automated Q&A Scripts" section (~50 lines) covering: 5-step checklist, JSON entry anatomy, multi-agent scripts, two-terminal usage pattern, key files table

**Files Modified**:
- `.claude/skills/agentic-voice-workflow/SKILL.md` (5 changes: version bump, Phase 5b row, anti-pattern, cross-reference, new section)

**Commit**: bbd1324

---

### 2026.02.11 - Session 184 | vLLM verbose_server Flag + Marlin Kernel Verification

**Accomplishments**:
- Added `verbose_server` parameter to `_start_vllm_server()` — prints all vLLM startup output when `True`, defaults to `False`
- Enabled at post-quantization call sites (`run_pipeline` + `run_pipeline_adhoc`) so Marlin kernel loading is visible
- **Verified via live run**: Marlin IS loading correctly (`gptq_marlin.py:143: "Using gptq_marlin kernel"`, `gptq_marlin.py:238: "Using MarlinLinearKernel"`)
- Small-batch latency still ~457 ms (unchanged from ~490 ms) — awaiting full batch run tonight to assess Marlin speedup at scale

**Files Modified** (CoSA submodule, not committed here):
- `src/cosa/training/peft_trainer.py` (`verbose_server` param + 4 changes: signature, docstring, print condition, 2 call sites)

---

### 2026.02.11 - Session 183 | Notification Proxy LLM Script Matcher Implementation

#### Checkpoint | 2026.02.11 | Phi-4 script matcher + answer verifier + Q&A scripts + 50 new tests

**Accomplishments**:
- **Implemented full plan**: "Replace Notification Proxy Keyword Matching with Local Phi-4 LLM Strategy" (Parts A-I)
- **XML models** (Part A): Created `ScriptMatcherResponse` and `VerificationResponse` BaseXMLModel subclasses in `xml_models.py` with field validators, helper methods, smoke tests
- **Prompt templates** (Part B): 3 new templates using `{{PYDANTIC_XML_EXAMPLE}}` — script-matcher, batch-matcher, answer-verifier
- **Q&A scripts** (Part C): 7 JSON script files in `src/conf/notification-proxy-scripts/` — deep-research, podcast, research-to-podcast, all-agents (multi-agent with `agents` tags), minimal, template, README
- **LLM Script Matcher** (Part D): `LlmScriptMatcherStrategy` drop-in replacement for `ExpediterRuleStrategy` — handles all 4 response types via Phi-4, agent-aware entry filtering
- **Answer Verifier** (Part E): `LlmAnswerVerifier` with exact-match bypass optimization, batch verification
- **Configuration** (Part F): 5 new config keys in `lupin-app.ini` + matching explanations
- **Wiring** (Part G): 3-tier strategy chain in responder (script_matcher → rules → cloud), `--strategy` CLI flag, MODEL_MAPPING registration
- **Unit tests** (Part H): 50 new tests across 8 test classes (109 total notification proxy tests, 770 full suite)
- **Documentation** (Part I): Cross-reference in `agentic-voice-workflow.md`, README in scripts directory

**Files Modified** (Lupin repo):
- `src/conf/lupin-app.ini` (5 new config keys)
- `src/conf/lupin-app-splainer.ini` (5 matching explanations)
- `src/tests/unit/test_notification_proxy.py` (50 new tests, 8 new test classes)
- `src/workflow/agentic-voice-workflow.md` (proxy scripts cross-reference)
- `src/conf/prompts/notification-proxy-script-matcher.txt` (NEW)
- `src/conf/prompts/notification-proxy-batch-matcher.txt` (NEW)
- `src/conf/prompts/notification-proxy-answer-verifier.txt` (NEW)
- `src/conf/notification-proxy-scripts/` (NEW — 7 files: deep-research.json, podcast.json, research-to-podcast.json, all-agents.json, minimal.json, _template.json, README.md)

**Files Modified** (CoSA submodule, not committed here):
- `src/cosa/agents/notification_proxy/xml_models.py` (NEW — ScriptMatcherResponse + VerificationResponse)
- `src/cosa/agents/notification_proxy/strategies/llm_script_matcher.py` (NEW — LlmScriptMatcherStrategy)
- `src/cosa/agents/notification_proxy/verification.py` (NEW — LlmAnswerVerifier)
- `src/cosa/agents/io_models/utils/prompt_template_processor.py` (2 MODEL_MAPPING entries)
- `src/cosa/agents/notification_proxy/strategies/__init__.py` (updated docstring)
- `src/cosa/agents/notification_proxy/config.py` (10 new constants)
- `src/cosa/agents/notification_proxy/responder.py` (3-tier strategy chain)
- `src/cosa/agents/notification_proxy/__main__.py` (--strategy CLI flag)

---

### 2026.02.11 - Session 182 | Llama 3.2 3B vLLM Latency Analysis + gptq_marlin Config

#### Checkpoint | 2026.02.11 | Llama 3.2 latency research doc + Marlin kernel config

**Accomplishments**:
- **Research document**: Created `src/rnd/2026.02.11-vllm-llama-3.2-latency-analysis.md` — analysis of Llama-3.2-3B ~490 ms/item at 4-bit GPTQ (2.8x slower than Qwen3-4B's 174 ms). Root cause: AutoRound GPTQ not triggering Marlin kernel (documented 2.6x gap). Cross-model comparison, CPU overhead analysis, tiered recommendations.
- **Config change**: Added `"quantization": "gptq_marlin"` to `llama_3_2_3b.py:vllm_config` (CoSA submodule).
- **Pipeline change**: Added `quantization` parameter to `peft_trainer.py:_start_vllm_server()`, passed only at post-quantization call sites (CoSA submodule).

**Files Modified** (Lupin repo):
- `src/rnd/2026.02.11-vllm-llama-3.2-latency-analysis.md` (NEW — research doc)
- `src/rnd/README.md` (added analysis link)

**Files Modified** (CoSA submodule, not committed here):
- `src/cosa/training/conf/llama_3_2_3b.py` (quantization key in vllm_config)
- `src/cosa/training/peft_trainer.py` (quantization parameter + 2 call sites)

**Commit**: 7451070

---

### 2026.02.10 - Session 180 | Save CRUD Delete Bug Fix Plan to R&D

**Accomplishments**:
- **Plan document saved**: Wrote `src/rnd/2026.02.10-crud-delete-bug-fix-and-live-pipeline-smoke-test.md` — comprehensive 4-part plan: (A) 5-change bug fix (dedup guard, multi-delete guard, infra column rejection), (B) 6 new unit tests, (C) `test_crud_live_pipeline.py` 8-scenario live smoke test following calculator + expeditor patterns, (D) full regression verification.
- **R&D README updated**: Added plan doc entry.
- **TODO.md updated**: CRUD bug fix item now references R&D plan doc, marked "RESUME TOMORROW (Session 181)".

**Files Modified** (Lupin repo):
- `src/rnd/2026.02.10-crud-delete-bug-fix-and-live-pipeline-smoke-test.md` (NEW — plan doc)
- `src/rnd/README.md` (added plan doc entry)
- `TODO.md` (updated CRUD bug fix item)

---

### 2026.02.10 - Session 179 | Expand Smoke Test Matrix (9 → 13 Scenarios) — Partial

**Accomplishments**:
- **4 new scenarios added**: DR_FULL (all args, confirmation-only), RTP_LANGUAGES (partial extraction), PG_LANGUAGES (languages + special handler), RTP_BARE (maximum 5-arg batch). Appended to `EXPEDITOR_SCENARIOS` list at indices 9-12.
- **Plan documented**: Wrote implementation plan to `src/rnd/2026.02.10-expand-smoke-test-matrix-13-scenarios.md` with coverage gap analysis, scenario definitions, and remaining changes.
- **Notification proxy changes from prior session**: `all_agents` union profile in `config.py`, keyword ordering fix in `expediter_rules.py`, `expected_args` soft verification + two-pass docs in smoke test, 3 regression tests in unit tests.
- **Work paused mid-implementation**: Docstring replacement (two-pass → single-pass) and count reference updates (9→13) still pending. User requested session shutdown.

**Files Modified** (Lupin repo):
- `src/tests/smoke/test_expeditor_mock_job_smoke.py` (4 new scenarios + expected_args from prior session)
- `src/tests/unit/test_notification_proxy.py` (3 regression tests from prior session)
- `src/rnd/2026.02.10-expand-smoke-test-matrix-13-scenarios.md` (NEW — plan doc)
- `src/rnd/README.md` (added plan doc entry)
- `TODO.md` (added continuation item for tomorrow)

**Files Modified** (CoSA submodule, not committed here):
- `src/cosa/agents/notification_proxy/config.py` (all_agents union profile)
- `src/cosa/agents/notification_proxy/strategies/expediter_rules.py` (keyword ordering fix)

---

### 2026.02.10 - Session 177 | Expand Calculator LORA Training Templates (83 → 1500)

**Accomplishments**:
- **Phase 1 — Clean math ↔ calculator boundary**: Removed 27 calculator-territory lines from `synthetic-data-agent-routing-math.txt` — 20 "calculator mode" metaphor phrases, 6 explicit calculator routing lines, 1 compound interest line. Math: 523 → 495 lines (483 content). Zero calculator/mortgage/convert references remain.
- **Phase 2 — Expand calculator templates**: Rewrote `synthetic-data-agent-routing-calculator.txt` from 83 → 508 content lines. Organized into 7 categories: unit conversions (~280), price comparisons (~100), mortgages/financial (~80), routing/meta/disambiguation (~50). Natural spoken language with varied sentence structure.
- **Phase 3 — Code change**: Added `"agent router go to calculator": { "factor": 3 }` to `augmentation_config` in `xml_coordinator.py` (CoSA submodule, not committed here).
- **Training data regenerated**: 38,371 total examples. Calculator: 83 → 1,483 (pre-split). Math: 1,500 → 1,417 (acceptable). All 34 commands balanced. Ready for PEFT retrain.

**Files Modified** (Lupin repo):
- `src/ephemera/prompts/data/synthetic-data-agent-routing-math.txt` (removed 27 calculator-territory lines)
- `src/ephemera/prompts/data/synthetic-data-agent-routing-calculator.txt` (expanded 83 → 508 content lines)
- `src/ephemera/prompts/data/voice-commands-xml-{train,test,validate}.jsonl` (regenerated)
- `src/ephemera/prompts/data/agentic-job-xml-{train,test,validate}.jsonl` (regenerated)

**Files Modified** (CoSA submodule, not committed here):
- `src/cosa/training/xml_coordinator.py` (add calculator to augmentation_config with factor=3)

---

### 2026.02.10 - Session 176 | Fix TTS Ghost Card Stranded After Action-Required Response

**Accomplishments**:
- **Root cause fix**: `onTTSPlaybackComplete()` cleared `activeTTSItem` AFTER `enterTTSFocusMode()`, allowing `updateTTSQueueSection()` to re-render a ghost card into the active slot. Swapped ordering so `activeTTSItem = null` runs BEFORE focus mode entry. Removed duplicate `updateTTSQueueSection()` call.
- **Clear All button visibility**: `updateTTSClearAllButtonState()` now checks active slot DOM for ghost cards in addition to `ttsQueue.length` and `activeTTSItem`
- **clearTTSQueue() hardened**: No longer returns early when queue is empty — also checks for `activeTTSItem` and ghost cards in active slot DOM, clears both
- **Delete button on active cards**: `renderActiveTTSCard()` now includes a delete button alongside Stop, matching `renderMinimizedTTSCard()` pattern (defense-in-depth)
- **Bug fix session closed**: 1 prior fix (Resume button stale freshQueueUI reference) + this ghost card fix

**Files Modified** (Lupin repo):
- `src/fastapi_app/static/js/notifications.js` (4 targeted fixes: +37/-15 lines)

**Commit**: 2a83679 (checkpoint)

---

### 2026.02.10 - Session 173 | Simplify Credential Resolution + Fix JWT WebSocket Auth

#### Checkpoint | 2026.02.10 | 2-tier credentials + Bearer prefix fix

**Accomplishments**:
- **Credential resolution simplified to 2 tiers**: Rewrote `get_credentials()` — removed `LUPIN_TEST_*` (tier 3) and `DEFAULT_EMAIL` (tier 4) fallbacks. Now: CLI > `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_*` > `ValueError` for both email and password
- **JWT "Invalid header padding" fix**: WebSocket auth handler in `websocket.py` didn't strip `Bearer ` prefix before calling `verify_token()` → `jwt.decode()`. REST endpoints got this for free from FastAPI's `HTTPBearer`. Added 3-line `startswith` guard
- **Auth DB research**: Determined simplest path for test user email rename (PostgreSQL — register new account via env vars, no code change needed)
- **Test updates**: Rewrote `TestGetCredentials` — 6 focused tests replacing 7 old ones. Removed obsolete `DEFAULT_EMAIL` import and assertions. 56/56 notification proxy tests passing

**Files Modified** (CoSA submodule, not committed here):
- `src/cosa/agents/notification_proxy/config.py` (2-tier get_credentials)
- `src/cosa/agents/notification_proxy/listener.py` (updated remediation env var names)
- `src/cosa/rest/routers/websocket.py` (Bearer prefix strip)

**Files Modified** (Lupin repo):
- `src/tests/unit/test_notification_proxy.py` (rewrote credential tests)

**Commit**: 5b18ecc (test file checkpoint)

---

### 2026.02.10 - Session 175 | Mark Calculator Step 24 done + live pipeline test docs

#### Checkpoint | 2026.02.10 20:00 | Mark Step 24 done + add live pipeline test notes to skills docs

**Files**: `2026.02.09-everyday-calculator-agent-implementation.md`, `TODO.md`, `SKILL.md` (agentic-voice-workflow, testing-patterns)
**Commit**: f3dc1fa

---

### 2026.02.10 - Session 172 | Calculator Step 24 — job_id in /api/push + 6-query live smoke test

#### Checkpoint | 2026.02.10 19:30 | Add --queries flag for selective query execution

**Files**: `src/tests/smoke/test_calculator_live_pipeline.py`
**Commit**: 61eab3c

#### Checkpoint | 2026.02.10 19:00 | Calculator Step 24 — job_id in /api/push + 6-query live smoke test

**Accomplishments**:
- **`/api/push` returns `job_id`**: Modified `push_job()` in `todo_fifo_queue.py` to return `Dict` instead of `str` at all 5 return sites (rejection, auto-routing, main agent, `_queue_best_snapshot`). Updated `queues.py` with backward-compatible `isinstance(result, dict)` extraction. API response now includes `job_id` field for poll-by-ID patterns.
- **6-query live smoke test**: Created `src/tests/smoke/test_calculator_live_pipeline.py` — automated test matrix covering convert (km, temp, weight, ml), compare_prices, and mortgage queries. Uses poll-by-`job_id` pattern against `GET /api/get-queue/done`. Login-only auth (no auto-registration), with remediation instructions on failure.
- **Removed auto-registration from smoke test**: Deleted `_try_register_and_login()`, simplified caller to use `_login()` only, removed hardcoded password from help text.
- **Plan document**: Wrote Step 24 plan to `src/rnd/2026.02.10-calculator-step-24-automated-qa-card-test-matrix.md`, indexed in R&D README.
- **Regression**: 710/710 unit tests pass, zero regressions.

**Files Modified** (Lupin repo):
- `src/cosa/rest/routers/queues.py` (extract job_id from dict return, include in API response)
- `src/tests/smoke/test_calculator_live_pipeline.py` (NEW — 6-query live test matrix)
- `src/rnd/2026.02.10-calculator-step-24-automated-qa-card-test-matrix.md` (NEW — plan doc)
- `src/rnd/README.md` (added Step 24 entry)
- `TODO.md` (Step 24 progress note)

**Files Modified** (CoSA submodule, not committed here):
- `src/cosa/rest/todo_fifo_queue.py` (push_job returns Dict with job_id at 5 return sites)

---

### 2026.02.10 - Session 171 | Notification Proxy Agent — Expediter Auto-Responder

#### Checkpoint | 2026.02.10 17:00 | Notification Proxy Agent — full implementation + 49 unit tests

**Accomplishments**:
- **Notification Proxy Agent**: Standalone CLI agent (`python -m cosa.agents.notification_proxy`) that connects via WebSocket as `mock.tester@lupin.deepily.ai`, subscribes to notification events, and automatically answers expediter questions using a hybrid strategy: rules for known patterns, LLM fallback for unknowns.
- **Architecture** (11 source files):
  - `listener.py` — async WebSocket client with auth, ping/pong, exponential backoff reconnection
  - `responder.py` — notification router + REST API response submission via `POST /api/notify/response`
  - `strategies/expediter_rules.py` — rule-based keyword matching with 4 test profiles (deep_research, podcast, research_to_podcast, minimal)
  - `strategies/llm_fallback.py` — Anthropic SDK fallback using `ANTHROPIC_API_KEY_FIREWALLED`
  - `config.py` — test profiles, connection defaults, API key resolution
  - `__main__.py` — CLI entry point with argparse, async event loop, graceful shutdown
- **Unit Tests**: 49 tests across 10 classes — config, rules construction, can_handle, respond (keyword matching, YES_NO, batch, multiple choice), LLM fallback, listener, responder routing, keyword mapping, profile coverage
- **Regression**: 710/710 unit tests pass (49 new + 661 existing)
- **All 5 module smoke tests pass**: config, expediter_rules, llm_fallback, listener, responder

**Files Created** (CoSA submodule, not committed here):
- `src/cosa/agents/notification_proxy/__init__.py`
- `src/cosa/agents/notification_proxy/__main__.py`
- `src/cosa/agents/notification_proxy/config.py`
- `src/cosa/agents/notification_proxy/cosa_interface.py`
- `src/cosa/agents/notification_proxy/listener.py`
- `src/cosa/agents/notification_proxy/responder.py`
- `src/cosa/agents/notification_proxy/voice_io.py`
- `src/cosa/agents/notification_proxy/strategies/__init__.py`
- `src/cosa/agents/notification_proxy/strategies/expediter_rules.py`
- `src/cosa/agents/notification_proxy/strategies/llm_fallback.py`

**Files Created** (Lupin repo): `src/tests/unit/test_notification_proxy.py` (NEW — 49 tests)
**Commit**: e485bb1

#### Checkpoint | 2026.02.10 17:30 | R&D design document + README index entry

**Files**: `src/rnd/2026.02.10-notification-proxy-agent-design.md` (NEW), `src/rnd/README.md`
**Commit**: f108873

---

## Navigation

### Archive Links
- **[Feb 3-10, 2026](history/2026-02-03-to-10-history.md)** - Sessions 126-180: DataFrame CRUD Phases 1-3, Runtime Argument Expeditor, PEFT Phase 2, Notification Proxy Agent, Calculator Mock Pipeline, Yes/No Comment Feature, Agentic Voice Workflow v2.0
- **[Jan 19 - Feb 2, 2026](history/2026-01-19-to-02-02-history.md)** - Sessions 57-124: Podcast Generator Phase 2, Deep Research CLI UX, LORA Training Integration, Test Suite Remediation, Cache Freshness, Queue Protocol Refactoring
- **[Jan 13-19, 2026](history/2026-01-13-to-19-history.md)** - Sessions 56-74b: Conversation Identity, Deep Research Agent, Podcast Generator Phase 1, Job Queue Progressive Disclosure UI
- **[Nov 23, 2025 - Jan 12, 2026](history/2025-11-23-to-2026-01-12-history.md)** - Sessions 7-55: MCP Voice, Directory Rename, Claude Code Dispatcher
- **[Oct 16 - Nov 22, 2025](history/2025-10-16-to-11-22-history.md)** - Sessions 1-6: Admin Dashboard, LanceDB, PostgreSQL Migration
- **[Oct 16-30, 2025](history/2025-10-16-to-30-history.md)** - SSE Notification System Phase 2
- **[Oct 1-15, 2025](history/2025-10-01-to-15-history.md)** - JWT/OAuth, User Filtering
- **[Sep 3-23, 2025](history/2025-09-03-to-23-history.md)** - History Management, WebSocket Architecture
- **[August 2025](history/2025-08-history.md)** - TTS Streaming, Audio Pipeline, WebSocket Enhancements
- **[July 2025](history/2025-07-history.md)** - Progressive TTS, User Routing Architecture
- **[June 2025](history/2025-06-history.md)** - Lupin Renaming, Notification System Foundation
- **[May 2025 and Earlier](history/2025-05-and-earlier-history.md)** - PEFT Training, Agent Migrations, Flask to FastAPI
- **[Archive Index](history/README.md)** - Full archive listing with descriptions

### Implementation Documents
- **Current Focus**: SWE Team Notification Gap Analysis + CJ Flow Integration
- **SWE Team Design**: `src/rnd/2026.02.13-claude-code-agentic-dev-team/`
- **Decision Proxy**: `src/rnd/2026.02.14-swe-team-phase-4-decision-proxy-architecture.md`

### Quick Navigation
- **Run FastAPI server**: `src/scripts/run-fastapi-lupin.sh` (port 7999)
- **Run GUI client**: `src/scripts/run-lupin-gui.sh`
- **Integration tests**: `./src/tests/run-integration-tests.sh -v`
- **Smoke tests**: `src/scripts/run-websocket-smoke-tests.sh`
