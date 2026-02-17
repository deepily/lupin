# TODO

Last updated: 2026-02-16 (Top-1 + confirm checkpoint)

## Pending

### vLLM Upgrade for Qwen3-4B-Base (FIRST THING TOMORROW — Session 166)

- [x] **[LUPIN] Upgrade vLLM to >= 0.8.5** — ✅ COMPLETE (2026-02-13)
  - **Research doc**: `src/rnd/2026.02.10-qwen3-vllm-inference-slowdown-root-cause.md`

### Unified Smoke Test Framework Verification (RESUME TOMORROW)

- [x] **[LUPIN] Execute unified smoke test framework verification plan** - ✅ COMPLETE (2026-02-16). Return to `src/rnd/2026.02.13-unified-smoke-test-framework-verification-plan.md` and execute the verification steps.

### Pre-Execution Confirmation of Top Semantically Similar Matches (HIGH)

- [x] **[LUPIN] Pre-execution confirmation of top semantically similar matches** - ✅ COMPLETE (2026-02-16). Implemented "top-1 + confirm" strategy: removed 95% hard floor, 3-tier decision (100% auto-accept, >=90% ask user, <90% log and skip).

### Agentic Software Development Team (HIGH)

- [x] **[LUPIN] Begin design of Agentic Software Development Team** - ✅ COMPLETE (Sessions 205-210)
  - Phase 1: Foundation — agent definitions, state management, hooks, orchestrator (64 unit tests)
  - Phase 2: Delegation loop — SDK integration, live execution, coder role (34 unit tests, 915 total)
  - Phase 3: Tester verification loop — pytest runner, coder-tester iteration (31 unit tests, 946 total)
  - Phase 4: Trust-Aware Decision Proxy — 4-layer architecture, 6 engineering categories, trust tracker L1-L5, circuit breaker, ratification API (301 unit tests, 1265 total)
  - **Plan**: `src/rnd/2026.02.14-swe-team-phase-4-decision-proxy-architecture.md`

### CoSA Submodule Commit Backlog (HIGH)

- [ ] **[LUPIN] Commit CoSA submodule changes from Feb 16 sessions** - Multiple sessions modified CoSA files but couldn't commit from parent context:
  - SWE Team notification gaps (5 files: orchestrator.py, config.py, state_files.py, cosa_interface.py, voice_io.py)
  - answer_is_correct field (3 files: solution_snapshot.py, lancedb_solution_manager.py, running_fifo_queue.py)
  - Semantic match simplification (3 files: lancedb_solution_manager.py, todo_fifo_queue.py, file_based_solution_manager.py)

### SWE Team Interactive Proxy Smoke Testing (HIGH — TOMORROW)

- [ ] **[LUPIN] Update SWE team testing docs + begin interactive proxy smoke testing** - Session TBD
  - Update `src/rnd/2026.02.13-claude-code-agentic-dev-team/00-index.md`: Phases 2-5 status (Phases 2, 3, 4 are DONE, not PENDING)
  - Update `src/rnd/2026.02.13-claude-code-agentic-dev-team/03-testing-validation.md`: Add Phase 4 results (214 unit tests, trust tracker, circuit breaker, engineering proxy, decision store), Phase 4 gate checklist, regression row (946 → 1160)
  - Create new Q&A script: `src/conf/notification-proxy-scripts/swe-team.json` for SWE team decision proxy notifications
  - Create new test profile in `config.py:TEST_PROFILES` for SWE team
  - Write smoke test scenarios for the decision proxy agent
  - Add SWE team sender_id to `all-agents.json`

### DataFrame CRUD with Voice I/O (Session 132-136)

- [x] **[LUPIN] Phase 1: Storage Layer + Pydantic Models** - ✅ COMPLETE (Session 136)
  - 5 source files in `src/cosa/crud_for_dataframes/` (schemas, xml_models, storage, crud_operations, __init__)
  - 91 unit tests + 16 smoke tests, all passing
  - 4 config keys + prompt template stub
  - R&D docs: `src/rnd/headless-cc-for-dataframe-crud/`
  - Issues fixed: Pydantic ClassVar, XML None coercion, timestamp truncation
- [x] **[LUPIN] Phase 2: Agent Implementation** - ✅ COMPLETE (Session 143)
  - CrudForDataFramesAgent + TodoCrudAgent + CalendarCrudAgent + dispatcher + intent_extractor
  - 73 unit tests, all passing
- [x] **[LUPIN] Phase 3: Queue Integration + Voice Confirmation** - ✅ COMPLETE (Session 143)
  - Feature-flag routing swap in todo_fifo_queue.py, cache skip + serialization exclusion
  - Voice confirmation for destructive ops (delete, delete_list, update)
  - 26 unit tests, 449 total passing, 50 WebSocket smoke tests passing
- [ ] **[LUPIN] Interactive E2E Testing of CRUD Agents** (HIGH PRIORITY) - Execute the 29-scenario testing protocol at `src/rnd/headless-cc-for-dataframe-crud/testing-protocol.md`.
  - [x] Part 1: Mock pipeline tests (17/17 passed — routing, pipeline, cache, confirmation, prompt construction)
  - [x] Bug fix: CRUD agent completion — emit_job_state_transition, answer guard, done queue push (3 new tests, 532/532 pass)
  - [x] Bug fix: TTS focus mode stuck — staleness check in restoreTTSQueueState + exit in moveToRegularNotifications (Session 164)
  - [x] **Bug fix: delete_item deletes all records** — Session 189: dedup guard, multi-delete guard, infra column rejection. 6 new tests (816 total). Commit fd21f0c.
  - [x] Part 3: Curl smoke tests → **SUPERSEDED** by `test_crud_live_pipeline.py` (8-scenario automated test, Session 189)
  - [ ] **Run CRUD live pipeline test** — `test_crud_live_pipeline.py --mode direct` with notification proxy (`--profile crud`). **Testing guide**: `src/rnd/2026.02.11-crud-live-pipeline-testing-guide.md`. **RESUME NEXT SESSION.**
  - [ ] Part 2: Notifications UI tests (8 scenarios, live server)
- [ ] **[LUPIN] Phase 4: End-to-End Voice Workflows + Polish** - PENDING (blocked by Phase 3 ✅)

### Skills Management (Session 118 Discovery)

Skill candidates identified - create with `/plan-skills-management-create <skill-name>`:
- [ ] **notification-patterns** (HIGH) - cosa-voice MCP usage patterns (~250 lines)
- [ ] **path-management** (MEDIUM) - `cu.get_project_root()` vs bootstrap (~150 lines)
- [ ] **code-style-preferences** (LOW) - Spacing, alignment, getattr prohibition (~100 lines)

### Before Branch Merge (This Week)

- [x] **[LUPIN] Verify CJ Flow Queueable Job Protocol Compliance** - Session 124: Investigation complete, implementation verified compliant. Session 128: Verification complete.
  - **Report**: `src/rnd/2026.02.02-cj-flow-protocol-compliance-report.md`
  - **Finding**: ClaudeCodeJob implements all 22 protocol requirements for both BOUNDED and INTERACTIVE modes
- [x] **[LUPIN] CJ Flow verification: Dry run end-to-end testing for BOUNDED tasks** - Session 128: Complete
- [ ] **[LUPIN] CJ Flow verification: Dry run end-to-end testing for UNBOUNDED tasks** - Pending
- [x] **Run baseline testing plan** - Session 123: **COMPLETE** ✅
  - Unit tests: 168/199 (84.4%) → **195/195 (100%)**
  - All test infrastructure issues resolved
  - 4 debug scripts moved to `src/scripts/debug/`
  - See: `src/rnd/2026.02.02-test-suite-remediation-plan.md`
- [x] **[LUPIN] Run agentic job intent LORA 1% sample training** - ✅ COMPLETE (2026-02-13)
- [x] **[LUPIN] PEFT Training Optimization - Phase 1 Training Run** - Session 136: Phase 1 actual results: 92.2% exact match (target: 89%)
- [x] **[LUPIN] PEFT Training Optimization - Phase 2 Disambiguation** - Session 136: Code/data complete. Session 141: Model swap to 2026-02-05 training run, 15 disambiguation tests passing, router confirmed working
- [x] **[LUPIN] Rebalance XML training data to 1200 samples/command** - Session 145 (checkpoint): Fixed `run-agentic-intent-training.sh` (hardcoded 400→1200), expanded placeholders (research-topics 50→190, document-paths 50→179), removed near-miss none examples, replaced product names (Deep Dive, PodMaker, Doc-to-Pod) with natural phrasing
  - **Plan**: `src/rnd/2026.02.05-peft-trainer-optimization-plan.md`
  - **Analysis script**: `src/scripts/analyze-training-distribution.py`
- [x] **[LUPIN] PEFT Phase 2 — Results Dashboard + Explicit Routing + Quantization Strengthening** - Session 148 (checkpoint): Part A (results dashboard in peft_trainer.py), Part B (explicit routing phrases for 5 agents + new automatic routing mode command with 60 templates), Part C (strengthened podcast-generator, math, todo-list, none-of-the-above with disambiguation anchors). Bumped sample size 1200→1500.
  - **Plan**: `src/rnd/2026.02.07-peft-trainer-optimization-plan-part-2.md`
  - **461 unit tests passing**, zero regressions
  - **CoSA submodule files need separate commit**: xml_coordinator.py, peft_trainer.py, todo_fifo_queue.py
- [x] **[LUPIN] Everyday Calculator — ALL 31 STEPS COMPLETE** (Sessions 165-191)
  - [x] Phases 1-4: 94 unit tests, 17 mock pipeline tests, MathAgent fallback, 508 LORA templates
  - [x] Step 24: Automated 6-query test via Calculator mode (`test_calculator_live_pipeline.py`)
  - [x] Step 25: Auto-route test via LORA router (`test_calculator_live_pipeline.py --auto-route`) — Session 191
  - [x] Steps 29-30: LORA retrained, >95% accuracy, no regression
  - [x] Step 31: Full voice routing test (10 spoken queries, 8/10 correct routing)
  - **Implementation doc**: `src/rnd/2026.02.09-everyday-calculator-agent-implementation.md`
- [x] **[LUPIN] Run PEFT Phase 2 training + LORA retrain** - ✅ COMPLETE (2026-02-13). 39,871 examples, 35 commands trained.
- [x] **[LUPIN] Fuzzy file matching for LORA adapter podcast generation routing** - ✅ COMPLETE (2026-02-13)
- [x] **[LUPIN] Extended Parameter Training (Chunk 1.6)** - ✅ COMPLETE (2026-02-13)
- [x] **[LUPIN] Disambiguation Agent for Missing Arguments** - Session 130 (checkpoint): Implemented as RuntimeArgumentExpeditor
  - `src/cosa/agents/runtime_argument_expeditor/` (agent_registry.py, xml_models.py, expeditor.py)
  - LLM gap analysis against `--help` output, asks user via `notify_user_sync()` for missing args
  - Integrated into TodoFifoQueue elif chain + mock_job.py expeditor test mode
  - Shared `agentic_job_factory.py` DRY factory for both voice and REST paths
- [x] **Run Deep Research dry-run smoke test** - Session 115: All 5 tests passed (login, submit, structure, polling, verification). Job dr-6aa5d16d completed in ~10s with $0.00 cost.
- [x] **Run Podcast Generator dry-run API smoke test** - Session 115: All tests passed. Job pg-dd026977 completed in ~10s with $0.00 cost.
- [x] **Run Research→Podcast dry-run API smoke test** - Session 115: All tests passed. Job rp-221fe28e completed in ~14s with $0.00 cost.

### job_state_transition Implementation (Session 107 - Complete)

- [x] Phase 1: Add job_state_transition to config files
- [x] Phase 2: Add _emit_job_state_transition method to FifoQueue
- [x] Phase 3: Add server emissions (7 transition points)
- [x] Phase 4: Client subscription to job_state_transition
- [x] Phase 5: Client handler (handleJobStateTransition, insertJobMetadata)
- [x] Phase 6: Badge-only handlers
- [x] Phase 7: Placeholder DOM nodes in renderJobCard()
- [x] Phase 8: Remove cruft - data structures
- [x] Phase 9: Remove cruft - methods
- [x] Phase 10: Remove cruft - logic
- [x] WebSocket smoke tests after Phase 10
- [x] Manual browser verification of job transitions

### Bug Fix: Job Card Field Parity (Session 107 - For Next Session)

- [x] **Test bug fix**: WebSocket cards now include 6 missing fields (status, has_interactions, is_cache_hit, started_at, completed_at, duration_seconds)
- [x] Verify cards created via WebSocket match server-fetched cards after page refresh
- [x] Test with mock job submission (success path)
- [x] Test with mock job failure (error path)

### Implementation Plans

- [ ] **Config Migration**: Implement Claude Agent SDK config migration plan documented at `src/rnd/2026.01.27-claude-agent-sdk-config-migration-plan.md`

### Browser Testing (Agentic Job Submission)

- [x] **Test 1**: Deep Research submission - verify job queues with dr-xxxxxxxx ID
- [x] **Test 2**: Research→Podcast (checkbox) - verify rp-xxxxxxxx prefix and chained routing
- [x] **Test 3**: Podcast Generator - Direct path mode (immediate queue)
- [x] **Test 4**: Podcast Generator - Description mode (fuzzy match → multiple choice)
- [x] **Test 5**: Error handling - empty topic shows validation warning
- [x] **Test 6**: Dry-run mode - Deep Research breadcrumb notifications
- [x] **Test 7**: Dry-run mode - Podcast Generator breadcrumb notifications
- [x] **Test 8**: Dry-run mode - Chained workflow (both sets of breadcrumbs)

### Verification Checklist

- [x] Research card submits to `/api/deep-research/submit`
- [x] Checkbox routes to `/api/deep-research-to-podcast/submit`
- [x] Podcast card submits to `/api/podcast-generator/submit`
- [x] Job IDs use correct prefixes (dr-, rp-, pg-)
- [x] Jobs appear in queue UI after submission
- [x] STT buttons work for voice input
- [x] Loading spinners show during submission
- [x] Error messages display correctly

### Architecture Review

- [x] **Cache Hit Behavior**: Moved to bug-fix-queue.md - Session 118

### Future Considerations

- [ ] **[LUPIN] Add 60s safety timeout to TTS focus mode** - Prevent permanent stuck state when TTS queue items fail to play. **Partially addressed** (Session 164): Added staleness check on restore + exit in moveToRegularNotifications. Still need: runtime 60s timeout for cases where notification exists but user never responds and timeout doesn't fire. **File**: `src/fastapi_app/static/js/notifications.js:9374-9393`
- [ ] **Silent flag for notifications**: Consider adding a `silent` parameter to the cosa-voice notification system to suppress TTS during automated testing. Would require changes to: router request models, job classes, voice_io wrappers, and core notification functions.
- [ ] **Standardize compound job/user ID usage** - Currently compound IDs (job_id + user_id) are only used when submitting jobs to the standard queue entry point. Consider standardizing this pattern across all job submission paths to avoid inconsistency issues later.
  - **Current state**: Only standard Q entry point uses compound IDs
  - **Risk**: Inconsistent ID formats could cause routing/tracking bugs
  - **Action**: Audit all job submission paths and standardize on compound ID format
- [ ] **Standardize job-user-session association interface** - Jobs are repeatedly associated with users and sessions at multiple points: queue transfers, job submission, processing handoffs. This repetition suggests an opportunity for a unified interface.
  - **Current state**: Ad-hoc association at each queue transition point
  - **Risk**: Inconsistent association logic, potential for user/session mismatch bugs
  - **Action**: Design a single interface/method for job-user-session binding that all queue operations use
- [ ] **[LUPIN] Gist embeddings: keep vs. jettison** - Gist _text_ has value (Level 3 exact match), but gist _embeddings_ are dead code — stored but never searched. Jettisoning saves ~30% embedding cost per snapshot (2 of 7 embeddings) and removes unused search methods.
  - **Analysis**: `src/rnd/2026.02.09-gist-embeddings-analysis-keep-vs-jettison.md`
  - **Dead code**: `question_gist_embedding`, `solution_gist_embedding` fields, `get_snapshots_by_solution_gist_similarity()`, `get_question_gist_similarity()`
  - **Action**: Review analysis, decide keep/jettison, clean up if jettisoning

### Carried Over from Session 102

- [x] Test math agent notification fixes (hard refresh, ask "What's 11+11?", verify console logs and TTS) - Session 109 ✅
- [x] Verify both notifications appear in job card (not sender card)
- [x] Future: Add `tts_raw` parameter to cosa-voice MCP server

### COSA Submodule (Needs Separate Commit)

- [x] Commit API consistency fix: `deep_research.py` derives user_email from JWT
- [x] Commit dry-run mode additions to routers and job classes
- [x] Commit new `mock_clients.py` for Podcast Generator

---

## Next Version: v0.1.4

Voice I/O enhancements driven by cosa-voice MCP notification system. Both require planning documents before implementation.

### Pre-Development Setup

- [ ] **[LUPIN] Create baseline test report for wip-v0.1.4 branch** - Run `/smoke-test-baseline` to establish pass/fail baseline before starting development work. This ensures we can detect regressions introduced during v0.1.4 development.

### Runtime Argument Expeditor Testing (HIGH) - Session 130

- [x] **[LUPIN] Test Runtime Argument Expeditor end-to-end** - ✅ COMPLETE (Session 200): All three testing surfaces verified. 12/12 proxy-automated smoke scenarios pass, 814 unit tests pass. Root cause of `http_error`: missing `open_ended_batch` in `/api/notify` response_type validation — fixed. No secondary JWT auth issues.
  - **Design review**: Return tomorrow to review expeditor notification architecture (dual-auth, batch collection flow)
  - **Plan**: `src/rnd/2026.02.12-fix-expeditor-notification-dual-auth-plan.md`
- [x] **[LUPIN] Create testing plan for Runtime Argument Expeditor** - Session 131: Initial 49 tests. Sessions 144-160: Expanded to 115 unit tests across 13 classes, 9 interactive smoke scenarios. **Session 162**: Bug fix + 8 new tests (Class 15: TestOptionalArgPrompting), total 123 tests across 15 classes. **Session 163**: Timeout chain fix (60/60/120→180/180/300) + diagnostic logging for notification failure analysis.
  - **Unit tests**: `src/tests/unit/test_runtime_argument_expeditor.py` (123 tests, 15 classes)
  - **Smoke tests**: `src/tests/smoke/test_expeditor_mock_job_smoke.py` (3 automated + 9 interactive, 600s timeout)
  - **Testing plan**: `src/rnd/2026.02.07-runtime-argument-expeditor-testing-plan.md`
  - **Bug fix**: `expeditor.py` — replaced `if parsed.is_complete()` gate with deterministic user-visible-args diff (optional args now always prompted)
  - **Next**: Run interactive scenarios (`LUPIN_INTERACTIVE_TESTS=true`) — first scenario failure diagnosis via new `[Expeditor]` debug logging
- [x] **[LUPIN] Finish expanding smoke test matrix to 13 scenarios** - ✅ COMPLETE (2026-02-13)
- [x] **[LUPIN] Run interactive expeditor smoke tests 4-5** - Session 144: Fixed async deadlock (`asyncio.to_thread()` wrapper), tests 4-5 now pass. User responds to voice prompt, dry-run job completes with $0.00 cost.

### Cache Freshness Policy (HIGH) - Session 121/122

- [x] **Create planning document**: `src/rnd/2026.02.02-cache-freshness-implementation-plan.md` - Session 121
- [x] **Simple fix implemented**: Always re-execute cached code in `_format_cached_result()` - Session 122
  - Trade-off: Math queries re-execute unnecessarily (~100ms) but ensures time queries are always fresh
  - Full policy system (Phases 1-4) deferred until simple fix proves insufficient
- [ ] **Phase 1**: Foundation - Create `cache_freshness_policy.py`, add `cache_policy` to SolutionSnapshot, update LanceDB schema, add config keys
- [ ] **Phase 2**: Agent integration - Add property overrides to DateAndTimeAgent (VOLATILE), MathAgent (IMMUTABLE), WeatherAgent (VOLATILE)
- [ ] **Phase 3**: Enforcement - Add `_is_cache_immutable()` and `_handle_volatile_cache()` to running_fifo_queue.py
- [ ] **Phase 4**: Semantic match confirmation (deferred - add `ask_yes_no()` for approximate matches)

### Semantic Cache Hit Confirmation (MEDIUM) - Merged into Cache Freshness

- [x] **Planning document**: Merged into Cache Freshness Policy plan (`src/rnd/2026.02.02-cache-freshness-implementation-plan.md`)
- [ ] **Implementation**: Part of Cache Freshness Phase 4 (deferred)

### Voice Module Audit (MEDIUM)

- [ ] **Review cosa_interface.py vs voice_io.py** - Audit for overlap, redundancy, and execution flow clarity
  - **Files**: `src/cosa/agents/claude_code/cosa_interface.py`, `src/cosa/agents/claude_code/voice_io.py`
  - **Goal**: Understand and document the relationship between these modules
  - **Deliverable**: Refactor if redundancy found, or document if distinct purposes

### CJ Flow Persistence (HIGH)

- [ ] **Add persistence for CJ Flow job tracking** - Jobs are currently transient
  - **Goal**: Durable storage for ClaudeCode Job tracking state
  - **Affects**: Job state survives server restarts, enables job history/resume

### Post-Execution Feedback Loop (HIGH)

- [x] **Part 1: answer_is_correct** - Session 215 (checkpoint): Added `answer_is_correct` tri-state field (True/False/None) to SolutionSnapshot, LanceDB schema, and async non-blocking verification via `_fire_correctness_check_async()` in RunningFifoQueue. 12 unit tests, 1331 total passing.
  - **Files**: `solution_snapshot.py`, `lancedb_solution_manager.py`, `running_fifo_queue.py`, `test_answer_is_correct.py`
- [ ] **Part 2: Language/tone feedback** - PENDING
  - "Was the language and tone appropriate?" (yes/no)
- [ ] **Part 3: Data collection pipeline** - PENDING
  - Store feedback for potential fine-tuning / RLHF training data
  - **Affects**: possibly new feedback storage table

---

## Completed (Recent)

- [x] **[LUPIN] Refactor mock job client into standalone Notification Proxy Agent** - Sessions 210-211: Phase 4a proxy extraction (`src/cosa/agents/utils/proxy_agents/` shared base infrastructure) + standalone `src/cosa/agents/notification_proxy/` agent. Fully decoupled from mock job infrastructure.
- [x] **[LUPIN] Execute unified smoke test framework verification plan** - 2026-02-16
- [x] **[LUPIN] Add `refresh()` method to ConfigurationManager** - 2026-02-13: WON'T FIX. Planned as a convenience wrapper around `init( silent=True )` for runtime config reloads. Decided not to implement.
- [x] **[LUPIN] Upgrade vLLM to >= 0.8.5** - 2026-02-13: Qwen3-4B-Base native support confirmed
- [x] **[LUPIN] Run PEFT Phase 2 training + LORA retrain** - 2026-02-13: 39,871 examples, 35 commands
- [x] **[LUPIN] Finish expanding smoke test matrix to 13 scenarios** - 2026-02-13
- [x] **[LUPIN] Run agentic job intent LORA 1% sample training** - 2026-02-13
- [x] **[LUPIN] Fuzzy file matching for LORA adapter podcast generation routing** - 2026-02-13
- [x] **[LUPIN] Extended Parameter Training (Chunk 1.6)** - 2026-02-13
- [x] **[LUPIN] Embedding benchmark harness** - Session 194: Side-by-side local GPU vs OpenAI API comparison. Local 7-398x faster. File: `src/tests/smoke/test_embedding_benchmark.py`
- [x] **[LUPIN] Bug fix: Dead job card stuck in run bucket** - Session 199: Added missing `emit_job_state_transition()` call in `_handle_error_case()` for `run -> dead` transition. Only AgentBase error path was missing the WebSocket event — all other paths (agentic success/failure/crash, snapshot, cached) already emitted correctly. 814 unit tests pass.
- [x] **[LUPIN] Bug fix: Stopwatch API mismatch in cache hit path** - `_format_cached_result()` called non-existent `stop()` + `get_elapsed_millis()` → replaced with `get_delta_ms()`. 817 unit tests pass.
- [x] **[LUPIN] Bug fix: Missing WebSocket event in generic exception handler** - `_process_job()` except block now emits `job_state_transition( 'run', 'dead' )` + TTS notification, matching `_handle_error_case()` pattern. 817 unit tests pass.
- [x] **[LUPIN] Fix LanceDB Embedding Dimension Mismatch** - Session 198: Standardized all providers on 768 dims (OpenAI MRL truncation), added `_validate_embedding_dimensions()` to all 6 table classes, 811 tests pass. CoSA submodule changes need separate commit.
- [x] **[LUPIN] CJ Flow Branding + Bounded Job Packaging + Claude Code LORA Data** - Session 195
  - Part A: CJ Flow branding propagated to 12 files (docstrings/comments only)
  - Part B1: ClaudeCodeJob registered in agentic_job_factory.py, claude_code_queue.py router, agent_registry.py
  - Part B2: Hardcoded defaults (max_turns, timeout_seconds) externalized to lupin-app.ini config
  - Part B3: 420-line packaging guide at `src/rnd/2026.02.12-cj-flow-bounded-job-packaging-guide.md`
  - Part C1-C5: 66 voice templates + 100 placeholders + training pipeline (coordinator, prompt_generator, xml_models, templates)
  - Part C6: Training data regenerated — 39,871 examples, 35 commands, Claude Code at 1,500
  - 816 unit tests pass, zero regressions
  - **Plan**: `~/.claude/plans/eager-dazzling-gem.md`
- [x] **Deprecated util_xml.py Elimination**: Migrated all production code to Pydantic XML I/O - Session 116
  - Removed fallbacks from gister.py, confirmation_dialog.py
  - Added Pydantic to todo_fifo_queue.py, multimodal_munger.py
  - Removed ALL deprecated fallbacks from agent_base.py, bug_injector.py, raw_output_formatter.py
  - Rewrote xml_parser_factory.py to Pydantic-only (removed baseline and hybrid strategies)
  - Added deprecation warnings to util_xml.py
  - 12 files modified, all smoke tests passing
- [x] **Math Agent TTS Fix**: job_id pattern + user_email pipeline - Session 109, 110
  - Fix: Updated regex in `notification_models.py` to accept compound hash format
  - Fix: Added `user_email` as first-class constructor parameter (Session 110)
  - Verified: TTS now works for math questions via /api/push
- [x] job_state_transition Phases 6-10 (badge handlers, DOM nodes, cruft removal) - Session 107
- [x] WebSocket smoke tests for job_state_transition - Session 107
- [x] Bug fix implementation: Add 6 missing fields to WebSocket metadata - Session 107
- [x] Rename `currentUser` to `currentUserEmail` in notifications.js - Session 106
- [x] Remove redundant `user_email` from Deep Research JS request body - Session 106
- [x] Fix job cards not rendering when queue collapsed - Session 105
- [x] Fix TTS notification duplication in job cards - Session 104
- [x] Add dry-run checkboxes to agentic job submission UI - Session 103

---

*Completed items older than 7 days can be removed or archived.*
