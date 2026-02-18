# TODO

Last updated: 2026-02-17 (Session 222)

## Pending

### SWE Team Proxy Agent (HIGH PRIORITY)

- [ ] **[LUPIN] Finish implementing and testing first cut of SWE Team Proxy Agent** - Complete implementation and testing of the initial SWE Team notification proxy agent
- [ ] **[LUPIN] Test SWE agent team with small jobs** - Validate SWE team end-to-end with small, scoped tasks to verify orchestration and proxy behavior

### DataFrame CRUD with Voice I/O (Session 132-136)

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

### Voice Module Audit (MEDIUM)

- [ ] **Review cosa_interface.py vs voice_io.py** - Audit for overlap, redundancy, and execution flow clarity
  - **Files**: `src/cosa/agents/claude_code/cosa_interface.py`, `src/cosa/agents/claude_code/voice_io.py`
  - **Goal**: Understand and document the relationship between these modules
  - **Deliverable**: Refactor if redundancy found, or document if distinct purposes

### Smoke Test Coverage Audit (MEDIUM) ✅ DONE

- [x] **[LUPIN] Verify smoke test coverage across recent work** - Session 221: 6 new test files, 54 pytest methods, all passing
  - ST-1: `test_decision_proxy_offline_smoke.py` — TrustTracker, CircuitBreaker, CategoryTrust (15 tests)
  - ST-2: `test_swe_team_orchestrator_dry_run_smoke.py` — Dry-run pipeline, state, progress (10 tests)
  - ST-3: `test_queue_consumer_smoke.py` — Thread lifecycle, job processing (3 tests)
  - ST-4: `test_answer_feedback_smoke.py` — answer_is_correct tri-state round-trip (8 tests)
  - ST-5: `test_agentic_disambiguation_smoke.py` — Confirm/switch/cancel/timeout (4 tests)
  - ST-6: `test_simple_agents_instantiation_smoke.py` — Cal/DateTime/Todo constructors (14 tests)
  - **Deferred**: ST-7 (CRUD queue integration), ST-8 (Decision Proxy live), ST-9 (Classic agents live)

### CJ Flow Persistence (MEDIUM)

- [ ] **Add persistence for CJ Flow job tracking** - Jobs are currently transient
  - **Goal**: Durable storage for ClaudeCode Job tracking state
  - **Affects**: Job state survives server restarts, enables job history/resume

### Automated E2E Testing Research (MEDIUM)

- [ ] **[LUPIN] Research AI/automation for end-to-end testing of notifications, API, and UI** - Eliminate manual clicking, typing, and visual verification from the testing workflow
  - **Scope**: Notification delivery verification, API endpoint validation, UI state assertions, full workflow completion checks
  - **Goal**: Find tools/frameworks that can autonomously exercise the full stack (submit job → verify queue → check notifications → confirm UI renders correctly) without human interaction
  - **Candidates to evaluate**: Playwright/Puppeteer with AI assertions, browser-use agents, visual regression tools (Percy, Applitools), Claude Computer Use for UI verification, custom harness extending existing proxy auto-answer infrastructure
  - **Deliverable**: Comparison matrix of approaches with recommendation + proof-of-concept for top candidate

### Before Branch Merge

- [ ] **[LUPIN] Run and remediate full testing harness** - Unit, smoke, WebSocket, and integration tests. Fix any regressions before merge.
- [ ] **[LUPIN] CJ Flow verification: Dry run end-to-end testing for UNBOUNDED tasks** - Pending

### Implementation Plans

- [ ] **Config Migration**: Implement Claude Agent SDK config migration plan documented at `src/rnd/2026.01.27-claude-agent-sdk-config-migration-plan.md`

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

---

## Completed (Recent)

- [x] **Smoke Test Coverage Audit** - Session 221: 6 new test files, 54 pytest methods covering Decision Proxy, SWE Orchestrator dry-run, Queue Consumer, Answer Feedback, Agentic Disambiguation, Classic Agents. All passing.
- [x] **SWE Team Testing Docs Update** - Session 221: Updated 00-index.md (Phases 2-4 DONE), 04-surfaces testing design (Surfaces 2-3 PASS), all-agents.json entries
- [x] **Post-Execution Feedback Loop** - Session 215-220: answer_is_correct tri-state, language/tone feedback, data collection pipeline. All 3 parts complete.
- [x] **CoSA Submodule Commit Backlog** - Session 220: 16 files across 5 areas committed
- [x] **SWE Team Surface 3 Proxy Crash Fix** - Session 219: 3 bugs fixed (ImportError, ValueError, expeditor pass-through). 1343 tests pass.
- [x] **Agentic Software Development Team (Phases 1-4)** - Sessions 205-210: Foundation, delegation, tester loop, trust-aware decision proxy. 1265 unit tests.
- [x] **Pre-Execution Confirmation of Semantic Matches** - 2026-02-16: Top-1 confirm strategy, 3-tier decision
- [x] **Unified Smoke Test Framework Verification** - 2026-02-16
- [x] **vLLM Upgrade to >= 0.8.5** - 2026-02-13: Qwen3-4B-Base native support
- [x] **DataFrame CRUD Phases 1-3** - Sessions 132-143: Storage, agents, queue integration + voice confirmation. 190 tests.
- [x] **Before Branch Merge** - Sessions 123-148: CJ Flow compliance, baseline testing, PEFT training (Phases 1-2), calculator (31 steps), disambiguation agent, dry-run smoke tests
- [x] **job_state_transition (10 phases)** - Session 107: Config through cruft removal + WebSocket smoke tests
- [x] **Job Card Field Parity fix** - Session 107: 6 missing WebSocket metadata fields
- [x] **Browser Testing (8 tests)** + **Verification Checklist (8 items)** - Sessions 103-115
- [x] **Architecture Review: Cache Hit Behavior** - Session 118: Moved to bug-fix-queue.md
- [x] **Carried Over from Session 102** - Sessions 109+: Math agent TTS, job card notifications, tts_raw parameter
- [x] **COSA Submodule commits** - Sessions 115+: API consistency, dry-run mode, mock_clients
- [x] **[LUPIN] Refactor mock job client into standalone Notification Proxy Agent** - Sessions 210-211: Phase 4a proxy extraction + standalone agent. Fully decoupled from mock job infrastructure.
- [x] **[LUPIN] Add `refresh()` method to ConfigurationManager** - 2026-02-13: WON'T FIX.
- [x] **[LUPIN] Run PEFT Phase 2 training + LORA retrain** - 2026-02-13: 39,871 examples, 35 commands
- [x] **[LUPIN] Finish expanding smoke test matrix to 13 scenarios** - 2026-02-13
- [x] **[LUPIN] Fuzzy file matching for LORA adapter podcast generation routing** - 2026-02-13
- [x] **[LUPIN] Extended Parameter Training (Chunk 1.6)** - 2026-02-13
- [x] **[LUPIN] Embedding benchmark harness** - Session 194: Local GPU 7-398x faster than OpenAI API.
- [x] **[LUPIN] Bug fix: Dead job card stuck in run bucket** - Session 199: Missing `emit_job_state_transition()` in `_handle_error_case()`. 814 tests pass.
- [x] **[LUPIN] Bug fix: Stopwatch API mismatch in cache hit path** - `_format_cached_result()` → replaced with `get_delta_ms()`. 817 tests pass.
- [x] **[LUPIN] Bug fix: Missing WebSocket event in generic exception handler** - 817 tests pass.
- [x] **[LUPIN] Fix LanceDB Embedding Dimension Mismatch** - Session 198: Standardized on 768 dims. 811 tests pass.
- [x] **[LUPIN] CJ Flow Branding + Bounded Job Packaging + Claude Code LORA Data** - Session 195: 816 tests pass.
- [x] **Deprecated util_xml.py Elimination** - Session 116: Migrated all production code to Pydantic XML I/O.
- [x] **Math Agent TTS Fix** - Sessions 109-110: job_id pattern + user_email pipeline.
- [x] job_state_transition Phases 6-10 + WebSocket smoke tests - Session 107
- [x] Bug fix: Add 6 missing fields to WebSocket metadata - Session 107
- [x] Rename `currentUser` to `currentUserEmail` in notifications.js - Session 106
- [x] Remove redundant `user_email` from Deep Research JS request body - Session 106
- [x] Fix job cards not rendering when queue collapsed - Session 105
- [x] Fix TTS notification duplication in job cards - Session 104
- [x] Add dry-run checkboxes to agentic job submission UI - Session 103

---

*Completed items older than 7 days can be removed or archived.*
