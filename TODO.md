# TODO

Last updated: 2026-03-02 (Session 297)

## HIGH PRIORITY — target_user Notification Dispatch Bug (Session 286)

- [ ] **[LUPIN] Fix target_user "Cannot resolve" error in Docker** — Code plumbing done (7 files), error persists. Next: write `test_target_user_dispatch.py` to reproduce the exact failure, then iterate. Key suspects: Docker env isolation, notification paths bypassing patched dispatcher.
  - **Bug fix doc**: [`src/rnd/2026.02.27-target-user-notification-dispatch-bug-fix.md`](src/rnd/2026.02.27-target-user-notification-dispatch-bug-fix.md)
  - **CoSA files modified**: `agent_notification_dispatcher.py`, 4x `cosa_interface.py`, 2x `job.py`

## HIGH PRIORITY — Podcast Generator Bugs (Session 283)

- [ ] **[LUPIN] Fuzzy matching via voice** — Vocal paraphrase can't generate file list for podcast source. Voice input produces approximate matches that don't resolve to valid file paths.
- [ ] **[LUPIN] Job card contact failure** — Podcast generator job fails to contact job card while in running bucket. UI shows no progress updates during execution.
- [ ] **[LUPIN] Audio segment upload** — Podcast generator fails to properly process/upload audio segments. Final audio stitching or upload step breaks.

---

## v0.1.6 — FUTURE DEVELOPMENT

### INI Config Key Naming Convention — Standardize on Spaces (Session 256)

- [ ] **[LUPIN] Standardize ~98 underscore config keys to space-separated** — 6-phase migration: backward-compat shim → INI rename → Lupin code (18 files) → CoSA code (62 files) → remove shim + guardrail test. ~2 weeks estimated.
  - **Design doc**: [`src/rnd/2026.02.23-ini-config-key-naming-convention.md`](src/rnd/2026.02.23-ini-config-key-naming-convention.md)
  - **Scope**: ~98 keys, ~80 files (18 Lupin + 62 CoSA), both INI files + splainer
  - **Priority**: Medium — no functional impact, improves consistency and predictability

### Config Migration — Claude Agent SDK

- [ ] **[LUPIN] Config Migration**: Implement Claude Agent SDK config migration plan documented at `src/rnd/2026.01.27-claude-agent-sdk-config-migration-plan.md`

### CJ Flow: Hybrid Fast Lane + Bounded Agentic Pool (Session 237)

- [ ] **[LUPIN] Phase 1.1: Add RLock to FifoQueue** — `fifo_queue.py`: wrap all mutating + reading methods with `threading.RLock()`
- [ ] **[LUPIN] Phase 1.2: Add config key** — `lupin-app.ini` + `lupin-app-splainer.ini`: `cj flow max concurrent agentic jobs = 3`
- [ ] **[LUPIN] Phase 1.3: Write thread safety tests** — `test_fifo_queue_thread_safety.py`: 4 concurrency tests
- [ ] **[LUPIN] Phase 1.4: Verify Phase 1** — New + existing unit tests pass
- [ ] **[LUPIN] Phase 2.1: Agentic pool + dispatcher refactor** — `running_fifo_queue.py`: ThreadPoolExecutor, route by isinstance, new methods
- [ ] **[LUPIN] Phase 2.2: Update shutdown sequence** — `main.py`: add pool shutdown before consumer thread
- [ ] **[LUPIN] Phase 2.3: Write agentic pool tests** — `test_agentic_pool.py`: 10 pool behavior tests
- [ ] **[LUPIN] Phase 2.4: Verify Phase 2** — New + existing unit tests pass
- [ ] **[LUPIN] Phase 3.1: API endpoint** — `/api/queue/pool-status` (optional)
- [ ] **[LUPIN] Phase 3.2: Integration verification** — Manual E2E test with concurrent agentic + sync jobs
- **Tracking doc**: `src/rnd/2026.02.19-approach-c-hybrid-queue-architecture.md`

### Playwright E2E Browser Testing (Session 252)

- [x] **[LUPIN] Research AI/automation for end-to-end testing** — Session 252: Research complete. Playwright Python + pytest-playwright recommended for FastAPI + vanilla HTML/JS stack
- [ ] **[LUPIN] Implement Playwright E2E testing** — 8-phase plan (~78 tasks, ~5 weeks), 189 data-testid elements, 28 test journeys, 9 architecture decisions
  - **Planning docs**: [`src/rnd/2026.02.23-automating-ui-testing/`](src/rnd/2026.02.23-automating-ui-testing/00-index.md)
  - **Serialized plan**: `src/rnd/2026.02.23-playwright-e2e-testing-plan.md`
  - **Phases**: Foundation → data-testid rollout → Auth tests → Page smoke → Admin tests → Notifications/Q&A → WebSocket → Visual regression + CI
  - **Round 2**: Claude Code + Playwright MCP for AI-augmented test generation + self-healing selectors

### DataFrame CRUD with Voice I/O — UI Testing + Voice Polish

- [ ] **[LUPIN] Interactive E2E Testing of CRUD Agents** — Execute the 29-scenario testing protocol at `src/rnd/2026.02.04-headless-cc-for-dataframe-crud/testing-protocol.md`.
  - [x] Part 1: Mock pipeline tests (17/17 passed — routing, pipeline, cache, confirmation, prompt construction)
  - [x] Bug fix: CRUD agent completion — emit_job_state_transition, answer guard, done queue push (3 new tests, 532/532 pass)
  - [x] Bug fix: TTS focus mode stuck — staleness check in restoreTTSQueueState + exit in moveToRegularNotifications (Session 164)
  - [x] **Bug fix: delete_item deletes all records** — Session 189: dedup guard, multi-delete guard, infra column rejection. 6 new tests (816 total). Commit fd21f0c.
  - [x] Part 3: Curl smoke tests → **SUPERSEDED** by `test_crud_live_pipeline.py` (8-scenario automated test, Session 189)
  - [x] **Run CRUD live pipeline test** — `test_crud_live_pipeline.py --mode direct --auto-proxy`. Session 267 fixed credential mismatch (CREDENTIAL_ENV_PREFIX unified).
  - [ ] Part 2: Notifications UI tests (8 scenarios, live server) — **Leverage Playwright E2E infrastructure**
- [ ] **[LUPIN] Phase 4: End-to-End Voice Workflows + Polish** - PENDING (blocked by Phase 3 ✅)
- **Note**: Moved to v0.1.6 to leverage Playwright E2E testing infrastructure for UI test automation

### CJ Flow Persistence

- [ ] **Add persistence for CJ Flow job tracking** - Jobs are currently transient
  - **Goal**: Durable storage for ClaudeCode Job tracking state
  - **Affects**: Job state survives server restarts, enables job history/resume

### Trust Proxy Documentation Update

- [ ] **[LUPIN] Update trust proxy documentation after Phases 3-4 of preference learning** — Revise `src/docs/proxy-admin-guide.md` and related docs to reflect preference learning algorithms, new trust escalation paths, and updated decision proxy behavior.
  - **Partially unblocked**: Phase 3 implemented (Session 266). Phase 4 pending.
  - **Scope**: Admin guide, API reference, R&D docs

---

## v0.1.5 — HIGH PRIORITY

### Voice I/O Integration with Claude Code System Hooks (Sessions 272-278)

- [x] **[LUPIN] Review and finalize voice hook integration draft plan** — Session 276: Plan reviewed, 3 ADs confirmed (AD-2, AD-5, AD-6), master plan updated.
- [x] **[LUPIN] Phase 0: Hook Contract Validation** — Session 276: 5 test hooks live, shared library + session bridge implemented, hooks capturing real CC payloads.
- [x] **[LUPIN] Align hook & MCP sender_id for per-session routing** — Session 278: `build_sender_id_for_cc()` in session bridge, `send_tts()` auto-resolves sender_id, MCP server uses session bridge instead of random UUID, background upgrade thread. 1692 unit tests pass.
- [x] **[LUPIN] Phase 0 validation: Analyze captured payloads** — Session 283: Validation report created from 3,430 payloads (1,686 pre_tool_use, 1,620 post_tool_use, 69 notification, 28 stop, 26 session_start). All 12 gate checks passed. Report at `src/rnd/.../2026.02.27-phase-0-validation-report.md`.
  - **Logs dir**: `io/claude_code_hooks/logs/`
  - **Session bridge file**: `~/.claude/sessions/cc-{PID}.json` — 26 files verified
- [x] **[LUPIN] Phase 1: Notification System Extensions** — Session 290: Revised architecture — `user_initiated_message` type (not VOICE_INPUT), stateful WebSocket listener (CCNotificationListener subclassing BaseWebSocketListener), INI-based credentials, atomic JSONL buffer drain. 5 new files, 7 modified, 35 new tests (all pass). See [Design Doc Revisions](src/rnd/2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.02.28-design-doc-revisions-session-290.md).
- [x] **[LUPIN] Phases 2-3: Hook infrastructure + voice output** — Session 292: 7 hooks renamed to production, smart TTS (silent/announce/default), voice buffer drain + acknowledge. 82 hook tests.
- [x] **[LUPIN] Phases 4-6: Voice injection, approvals, browser capture** — Session 296: additionalContext injection (Pre/PostToolUse), Stop hook blocking with counter safety valve, MCP voice bypass, PermissionRequest 3-path flow (auto-allow, buffer-redirect, sync), CC session voice capture UI. 126 hook tests.
- [ ] **[LUPIN] Phase 7: E2E testing + polish** — Manual E2E verification of voice pipeline (browser 🎤 → STT → notify → buffer → hook drain → additionalContext). Polish remaining rough edges.
  - **Master plan**: [`2026.02.25-opportunistic-voice-hook-integration-plan.md`](src/rnd/2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.02.25-opportunistic-voice-hook-integration-plan.md)
  - **Phase 0 plan**: [`2026.02.26-voice-hook-phase-0-implementation.md`](src/rnd/2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.02.26-voice-hook-phase-0-implementation.md)
  - **Phase 0 validation**: [`2026.02.27-phase-0-validation-report.md`](src/rnd/2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.02.27-phase-0-validation-report.md)
  - **Phase 1 design revisions**: [`2026.02.28-design-doc-revisions-session-290.md`](src/rnd/2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.02.28-design-doc-revisions-session-290.md)

---

## Pending

### History Archive (Session 280)

- [ ] **[LUPIN] Archive history.md** — At 18,951 tokens (75.8%). Archive sessions older than 14 days to stay below 17k threshold.

### SWE Team Proxy: Workload Generator + Shadow-Mode Capture (HIGH PRIORITY)

- [x] **[LUPIN] Layer 1: Enhanced dry-run + capture harness** — Session 268: 18-task catalog, JSONL capture harness, 7 integration tests, `data_origin` column. Validated Session 273: manifest path corrected to `io/decision-proxies/`.
- [ ] **[LUPIN] Layer 1 output review** — Return to review dry-run JSONL output at `io/decision-proxies/`. Validate classifier accuracy, confidence distributions, and category coverage across full 18-task catalog run.
- [ ] **[LUPIN] Layer 2: Live shadow-mode capture** — Run real SWE Team pipeline with `--live --trust-mode shadow`. Requires architectural decision: sandboxed execution (worktree/Docker) vs planning-only mode (stop before coder writes code). Deferred until Layer 1 output is reviewed.
  - **R&D doc**: [`src/rnd/2026.02.25-swe-proxy-data-origin-and-workload-generator.md`](src/rnd/2026.02.25-swe-proxy-data-origin-and-workload-generator.md)
  - **Runner**: `src/scripts/swe_workload_runner.py` (supports `--live --trust-mode shadow`)
  - **Integration tests**: `src/tests/integration/test_swe_team_pipeline.py` (7 tests)

### SWE Team Proxy Simulation (HIGH PRIORITY)

- [ ] **[LUPIN] Create SWE team proxy simulation with fully automated interaction** — Build a simulation harness where all SWE team interactions (orchestrator → proxy → decision → feedback) are simulated and automated, enabling repeatable end-to-end validation without manual intervention.

### SWE Team Proxy Agent (HIGH PRIORITY)

- [x] **[LUPIN] Finish implementing and testing first cut of SWE Team Proxy Agent** - Session 241: Activated proxy in shadow mode, wired trust feedback loop, 7 new tests. 1490 pass.
- [x] **[LUPIN] Phase 7: Real-Time Proxy Summary Notifications** - Session 248: 10 tasks, 7 new tests, 1 E2E smoke. Batch lifecycle, proxy summary emission, trust mode dropdown, circuit breaker alerts. 1518 pass.
- [x] **[LUPIN] Phase 8: Hot-Reload Trust Mode** - Session 248: REST endpoint + UI dropdown on Trust Dashboard, 16 new tests, 1534 pass
- [ ] **[LUPIN] Test SWE agent team with small jobs** - Validate SWE team end-to-end with small, scoped tasks to verify orchestration and proxy behavior

### Universal Prediction Engine: End-to-End Validation (HIGH PRIORITY)

- [ ] **[LUPIN] End-to-end test Slices 0 + 1 + 1.5** — With FastAPI server running, trigger `ask_yes_no` notifications via cosa-voice MCP. Verify: (1) prediction hints appear in WebSocket push, (2) after accumulating responses with qualifiers, `predicted_qualifier` field appears in hints, (3) `prediction_log` table records predictions + outcomes with accuracy tracking.
  - **Plan doc**: [`src/rnd/2026.02.23-trust-proxy-preference-learning/2026.02.27-universal-prediction-engine-plan.md`](src/rnd/2026.02.23-trust-proxy-preference-learning/2026.02.27-universal-prediction-engine-plan.md)
  - **Slices implemented**: 0 (foundation), 1 (binary yes/no), 1.5 (qualified yes/no), 2 (MC exclusive), 3 (MC inclusive)
  - **Slices 4+5 (CODE COMPLETE)**: open_ended + open_ended_batch — two-tier retrieval + LLM synthesis via Phi-4 14B. 36 unit tests pass. Needs live E2E validation.
  - **Slice 3 plan**: [`src/rnd/2026.03.02-slice-3-multi-select-mc-prediction.md`](src/rnd/2026.03.02-slice-3-multi-select-mc-prediction.md)
  - **Slices 4+5 plan**: [`src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.02-slices-4-5-open-ended-prediction.md`](src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.02-slices-4-5-open-ended-prediction.md)
  - **HTTP embedding fallback**: Session 293 — PredictionEngine now falls back to `/api/embeddings/generate` when local GPU unavailable (unblocks test-process embedding generation)
  - **Warm E2E tests**: 5 new scenarios (9-13) in `test_prediction_engine_e2e.py` — CBR yes/no, qualifier, accuracy correct/incorrect, MC warm
  - **Unit tests**: 87 pass (36 open-ended + 31 MC + 20 qualifier)

### Before Branch Merge

- [ ] **[LUPIN] Run and remediate full testing harness** - Unit, smoke, WebSocket, and integration tests. Fix any regressions before merge.
- [x] **[LUPIN] CJ Flow verification: Dry run end-to-end testing for UNBOUNDED tasks** - Session 269: INTERACTIVE dry-run exercises MessageHistory + 6-scenario smoke test created. Needs live server validation.

### Future Considerations

- [ ] **[LUPIN] Add 60s safety timeout to TTS focus mode** - Prevent permanent stuck state when TTS queue items fail to play. **Partially addressed** (Session 164): Added staleness check on restore + exit in moveToRegularNotifications. Still need: runtime 60s timeout for cases where notification exists but user never responds and timeout doesn't fire. **File**: `src/fastapi_app/static/js/notifications.js:9374-9393`
- [ ] **Silent flag for notifications**: Consider adding a `silent` parameter to the cosa-voice notification system to suppress TTS during automated testing. Would require changes to: router request models, job classes, voice_io wrappers, and core notification functions.
- [x] **Standardize compound job/user ID usage** - Session 236: Bug #5 made scoped IDs (`base_hash::user_id`) universal across ALL job types via `register_scoped_job()`
- [x] **Standardize job-user-session association interface** - Session 236: Bug #5 unified all write sites through `register_scoped_job()` and all reads through direct `job.user_id` access
- [x] **Implement Approach D: Hybrid Queue + Check-In** - Session 238: Full 5-phase implementation. 20+10 new tests, 317 SWE team tests pass

---

## Completed (Recent)

- [x] **Centralized Navigation & URL Naming Conventions** — Unified nav and URL patterns for entire suite of static HTML/plain vanilla JavaScript pages covering all user and admin tasks - Session 247
- [x] **CRUD Live Pipeline Test** - `test_crud_live_pipeline.py --mode direct --auto-proxy` passing. Session 267 fixed credential mismatch (CREDENTIAL_ENV_PREFIX unified).
- [x] **SWE Team Proxy: Preference Learning** - Sessions 258-266: Phases 0-3 complete. Embedding infrastructure, CBR + Beta-Bernoulli trust, seed data (50 decisions), BLR + Thompson Sampling, Conformal Guarantees + ICRL. 1645 total tests pass.
- [x] **Skill: notification-patterns** - cosa-voice MCP usage patterns skill created (~250 lines)
- [x] **Gist embeddings: jettisoned** - Dead embedding code removed, ~30% embedding cost savings per snapshot (2 of 7 embeddings). Removed `question_gist_embedding`, `solution_gist_embedding` fields and unused search methods.
- [x] **Voice Module Audit** - Session 260: Full 5-phase refactoring of `cosa_interface.py` vs `voice_io.py`. Created shared `AgentNotificationDispatcher`, `sender_id.py`, `feedback_analysis.py`, `sync_notify.py`. Eliminated ~1,548 lines of duplication across 16 files. 1538 unit tests pass.
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
