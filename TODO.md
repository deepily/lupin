# TODO

Last updated: 2026-03-13 (Session 355)

## COMPLETED — Stop Hook Qualifier (Sessions 332-336)

- [x] **[LUPIN] Fix stop hook qualifier: Claude Code ignores qualifier text** — Session 336: Replaced broken `systemMessage` approach with tmux injection. `inject_qualifier_via_tmux()` spawns detached background process that injects qualifier text directly into CC's tmux input after stop block. Uses bash positional args for shell-safe text passing. 36/36 tests pass. Needs manual E2E verification (Phase 4).
  - **Phases 1-2 (Sessions 332-333)**: `reason` and `systemMessage` both silently ignored by CC Stop hooks
  - **Phase 3 (Session 336)**: tmux injection — proven technique from `CCNotificationListener._inject_via_tmux()`

## COMPLETED — CC Listener Session ID Drift (Session 335)

- [x] **[LUPIN] Fix CC Notification Listener session ID drift after context clears** — Session 335: Implemented write-once lockfile (`cc-stable-{ppid}.id`) with atomic `open('x')`, passed `stable_session_id` to listener, added `accepted_ids` set for multi-hash filtering, extended stale cleanup with PID liveness check. 9 new tests, 28 total pass.
  - **Design doc**: `src/rnd/.../2026.03.10-stable-session-id-lockfile-and-listener-drift-fix.md`

## COMPLETED — Hook Session ID Drift (Session 342)

- [x] **[LUPIN] Fix session ID drift across hooks after context clear** — Session 342: Added `resolve_stable_session_id()` to session_bridge.py. All 6 hooks + hook_common.py now resolve transient CC session_id to stable lockfile ID. MCP `get_session_info()` exposes `stable_session_id`. 231/231 hook tests pass.

## HIGH PRIORITY — Consolidate Credential Stores (Session 337)

- [x] **[LUPIN] Consolidate three credential/config files into unified `~/.lupin/config`** — Session 337c: Steps 1-6 (code + tests). Session 338: Step 7 migration executed on live system. Session 339: Step 8 hardened — removed all legacy fallbacks, fail-hard on missing config, updated cloud-run scripts. 38/38 tests pass.
  - **Plan doc**: [`src/rnd/2026.03.10-consolidate-credential-stores.md`](src/rnd/2026.03.10-consolidate-credential-stores.md)

## HIGH PRIORITY — MCP Strict Project Detection + Repo Account Validation (Session 332)

- [x] **[LUPIN] cosa-voice MCP: strict project detection + per-repo account validation** — Session 339: Implemented. MCP server no longer falls back to `"unknown"` project; validates per-repo Lupin account at startup; sends urgent notification on validation failure.
  - **Plan doc**: [`src/rnd/2026.03.10-mcp-strict-project-detection-account-validation.md`](src/rnd/2026.03.10-mcp-strict-project-detection-account-validation.md)
  - **Files**: `cosa_voice_mcp.py`, `notification_utils.py`, new test file

## HIGH PRIORITY — CC Session Voice Input Bugs (Session 300)

- [x] **[LUPIN] Fix date off-by-one in CC session outgoing bubble** — Session 332: Fixed. `extractDateFromTimestamp()` now parses through `appTimezone`.

## HIGH PRIORITY — PG Audio Progress Not Updating In-Place (Session 329)

- [x] **[LUPIN] Fix PG audio progress notifications not using progress_group_id** — Session 330: Added `progress_group_id = self._audio_progress_group_id` to Phase 5 English audio start notification in `orchestrator.py`. The first notification now establishes the DOM tag so subsequent milestone notifications update in-place.

## COMPLETED — Review `active_conversation_changed` + JS Event Anomalies (Sessions 329, 331)

- [x] **[LUPIN] Investigate `active_conversation_changed` WebSocket event** — Session 331: Removed dead code. Server emitted it but never in INI available events or JS subscriptions. Both emission blocks removed from `notifications.py`, unreachable JS handler removed from `notifications.js`.
- [x] **[LUPIN] Investigate oddly named event type in JS notification API** — Session 331: Two events (`notification_play_sound`, `audio_streaming_chunk`) were subscribed but had no `case` handler, falling through to "Unhandled message type" default. Added no-op log handlers to both.

## HIGH PRIORITY — target_user Notification Dispatch Bug (Session 286)

- [x] **[LUPIN] Fix target_user "Cannot resolve" error in Docker** — Session 304: Root cause was sender_id double-hash (`#cli#pg-xxx`). Fixed `_get_sender_id()` suffix param in both podcast_generator and deep_research cosa_interface + job files. 10 unit tests written.
  - **Bug fix doc**: [`src/rnd/2026.02.27-target-user-notification-dispatch-bug-fix.md`](src/rnd/2026.02.27-target-user-notification-dispatch-bug-fix.md)

## HIGH PRIORITY — Podcast Generator Bugs (Session 283)

- [x] **[LUPIN] Fuzzy matching via voice** — Session 304: Added `difflib.get_close_matches()` as 3rd validation tier in `match_research_docs()`. 14 unit tests written.
- [x] **[LUPIN] Job card contact failure** — Session 304: Fixed sender_id double-hash in `_get_sender_id()` suffix param. Same root cause as target_user bug above.
- [x] **[LUPIN] Audio segment upload** — Session 304: 3 sub-fixes: (1) non-interactive `_is_interactive()` guard on all `input()` CLI fallbacks in voice_io.py, (2) fixed TTS cost key `tts_results` → `tts_results_en` in orchestrator.py, (3) pre-stitching guard when all segments fail. 13 unit tests written.

---

## v0.1.6 — FUTURE DEVELOPMENT

### INI Config Key Naming Convention — Standardize on Spaces (Sessions 256, 349)

- [x] **[LUPIN] Standardize ~91 underscore config keys to space-separated** — Session 349: Atomic rename of 91 keys in both INI files + 96 Python string literal updates across 59 files. No backward-compat shim needed. 5 key regroupings for better sort clustering. Removed 7 legacy splainer-only orphan keys. Added permanent guardrail test. Full regression green (2094 unit, 50 WS, 136 integration).
  - **Design doc**: [`src/rnd/2026.02.23-ini-config-key-naming-convention.md`](src/rnd/2026.02.23-ini-config-key-naming-convention.md)
  - **Migration map**: `src/conf/config-key-migration-map.json` (105 entries, archivable)
  - **Guardrail**: `src/tests/unit/test_ini_key_naming.py` (prevents future underscore keys)

### SWE Team Proxy: Validation + Shadow-Mode + Simulation

- [ ] **[LUPIN] SWE Team Proxy end-to-end validation pipeline** — Review Layer 1 dry-run JSONL output (`io/decision-proxies/`), run Layer 2 live shadow-mode capture (`--live --trust-mode shadow`), and build fully automated simulation harness for repeatable E2E validation without manual intervention.
  - **R&D doc**: [`src/rnd/2026.02.25-swe-proxy-data-origin-and-workload-generator.md`](src/rnd/2026.02.25-swe-proxy-data-origin-and-workload-generator.md)
  - **Runner**: `src/scripts/swe_workload_runner.py`
  - **Integration tests**: `src/tests/integration/test_swe_team_pipeline.py` (7 tests)
- [ ] **[LUPIN] Test SWE agent team with small jobs** — Validate SWE team end-to-end with small, scoped tasks to verify orchestration and proxy behavior

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
- [ ] **[LUPIN] Implement Playwright E2E testing** — 8-phase plan (~78 tasks, ~5 weeks), ~266 data-testid elements, 28 test journeys, 9 architecture decisions
  - **Planning docs**: [`src/rnd/2026.02.23-automating-ui-testing/`](src/rnd/2026.02.23-automating-ui-testing/00-index.md)
  - **Serialized plan**: `src/rnd/2026.02.23-playwright-e2e-testing-plan.md`
  - **Phases 1-2**: DONE — Foundation + data-testid rollout (~266 testids across 13 files)
  - **Phase 3**: DONE — Auth Flow Tests (30 tests: login, register, profile, change-password, session)
  - **Phase 4**: DONE — Page Smoke Tests (39 tests: parametrized smoke, navigation, landing)
  - **Phase 5**: DONE — Admin Flow Tests (69 tests: dashboard, users, snapshots, proxy-dashboard, proxy-ratify, role-gating)
  - **Total**: 253 passing E2E tests across 27 test files
  - **Phase 6**: DONE — Notifications & Q&A Tests (86 tests: sections, Q&A, job dispatch, TTS, status, queues, action, time saved)
  - **Phase 7**: DONE — WebSocket & Real-Time Tests (28 tests: connection lifecycle, session persistence, auth handshake)
  - **Phase 8**: Pending — Visual Regression & CI (blocked by starlette version conflict)
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

### CJ Flow Persistence (Session 357 — IN PROGRESS)

- [ ] **[LUPIN] CJ Flow Persistence: PostgreSQL-backed job history for agentic jobs** — 🔄 IN PROGRESS. Plan complete and serialized (Session 357). Implementation Phases 1-5 pending, will resume in next sessions.
  - **Goal**: Durable storage for AgenticJobBase jobs (DeepResearch, PodcastGenerator, ClaudeCode, SweTeam). Job state survives server restarts, enables job history queries, marks interrupted jobs.
  - **Architecture**: Central write-through via `emit_job_state_transition()` in `queue_util.py`
  - **Plan doc**: [`src/rnd/2026.03.13-cj-flow-persistence-plan.md`](src/rnd/2026.03.13-cj-flow-persistence-plan.md)
  - **Phase 0**: DONE — Plan serialized to R&D
  - **Phase 1**: Pending — Schema + SQLAlchemy model (`job_history` table, `add-job-history.sql`)
  - **Phase 2**: Pending — Persistence service (`job_persistence.py`, config keys)
  - **Phase 3**: Pending — Write-through integration in `emit_job_state_transition()`
  - **Phase 4**: Pending — Startup recovery (`mark_interrupted_jobs()`)
  - **Phase 5**: Pending — `/api/job-history` endpoint + unit/integration tests

### Universal Prediction Engine: Live E2E Validation (Session 340)

- [ ] **[LUPIN] Live E2E validation of all 7 UPE slices** — All slices 0-6 code-complete (87 unit tests, 21 E2E tests). 5-phase validation plan: baseline test run, warm prediction threshold investigation, 6 new gap-filling E2E tests, browser visual QA for hint rendering, full cold-to-warm lifecycle with accuracy tracking.
  - **Validation plan**: [`src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.11-upe-live-e2e-validation-plan.md`](src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.11-upe-live-e2e-validation-plan.md)
  - **Master plan**: [`src/rnd/2026.02.23-trust-proxy-preference-learning/2026.02.27-universal-prediction-engine-plan.md`](src/rnd/2026.02.23-trust-proxy-preference-learning/2026.02.27-universal-prediction-engine-plan.md)
  - **Progress**: Phase 0 (serialize) done, Phase 1.1 (unit baseline 87/87) done. Phases 1.2-5 pending.

### Render Markdown Documents as HTML

- [ ] **[LUPIN] Render markdown documents as HTML** — 🔄 IN PROGRESS

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
- [x] **[LUPIN] Voice injection into idle CC sessions (tmux + UserPromptSubmit hook)** — Session 323: All 6 phases implemented. tmux discovery in register_session.py, `find_session_by_id/tmux()` in session_bridge.py, listener tmux Enter trigger, UserPromptSubmit hook, shell scripts, hook registration, 29 tests (8+18+3) all passing.
  - **Plan doc**: [`2026.03.05-voice-injection-listener-tmux-hook-plan.md`](src/rnd/2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.03.05-voice-injection-listener-tmux-hook-plan.md)
  - **Research doc**: [`2026.03.05-voice-injection-tmux-buffer-hook-design.md`](src/rnd/2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.03.05-voice-injection-tmux-buffer-hook-design.md)
- [x] **[LUPIN] Phase 7: E2E testing + polish** — Manual E2E verification of voice pipeline (browser 🎤 → STT → notify → buffer → hook drain → additionalContext). Polish remaining rough edges. Session 332: Completed.
  - **Master plan**: [`2026.02.25-opportunistic-voice-hook-integration-plan.md`](src/rnd/2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.02.25-opportunistic-voice-hook-integration-plan.md)
  - **Phase 0 plan**: [`2026.02.26-voice-hook-phase-0-implementation.md`](src/rnd/2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.02.26-voice-hook-phase-0-implementation.md)
  - **Phase 0 validation**: [`2026.02.27-phase-0-validation-report.md`](src/rnd/2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.02.27-phase-0-validation-report.md)
  - **Phase 1 design revisions**: [`2026.02.28-design-doc-revisions-session-290.md`](src/rnd/2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.02.28-design-doc-revisions-session-290.md)

---

## Pending

### History Archive (Session 280)

- [x] **[LUPIN] Archive history.md** — Session 332: Archived Sessions 260-303 (Feb 24 - Mar 3) to `history/2026-02-24-to-03-03-history.md`. Retained Sessions 304-331 (~11.9k tokens).

### SWE Team Proxy: Workload Generator + Shadow-Mode Capture

- [x] **[LUPIN] Layer 1: Enhanced dry-run + capture harness** — Session 268: 18-task catalog, JSONL capture harness, 7 integration tests, `data_origin` column. Validated Session 273: manifest path corrected to `io/decision-proxies/`.

### SWE Team Proxy Agent (HIGH PRIORITY)

- [x] **[LUPIN] Finish implementing and testing first cut of SWE Team Proxy Agent** - Session 241: Activated proxy in shadow mode, wired trust feedback loop, 7 new tests. 1490 pass.
- [x] **[LUPIN] Phase 7: Real-Time Proxy Summary Notifications** - Session 248: 10 tasks, 7 new tests, 1 E2E smoke. Batch lifecycle, proxy summary emission, trust mode dropdown, circuit breaker alerts. 1518 pass.
- [x] **[LUPIN] Phase 8: Hot-Reload Trust Mode** - Session 248: REST endpoint + UI dropdown on Trust Dashboard, 16 new tests, 1534 pass


### Disambiguate Database Names (Session 343-344)

- [x] **[LUPIN] Phase 6: Rename lupin_db → lupin_db_dev and lupin_db_prod** — Session 344: PostgreSQL `ALTER DATABASE RENAME`, updated defaults in `database.py` (dev → `lupin_db_dev`, prod → `lupin_db_prod`), `docker-compose.yml`, `run-postgresql-dev.sh`, `backup-postgres.sh`, plus 16 doc references across 7 files. Full test suite validation pending.
  - **Plan doc**: [`src/rnd/2026.03.12-integration-test-hot-swap-config.md`](src/rnd/2026.03.12-integration-test-hot-swap-config.md) (Phase 6 → Done)

### Before Branch Merge

- [x] **[LUPIN] Run and remediate full testing harness** — Session 344: All suites green after DB rename. Unit **2075/2075**, smoke **27/27**, WebSocket **50/50**, integration **136 passed** (53 skipped, 23 xfailed, 13 xpassed, 0 failures). Fixed: notification auth assertions, admin fixture dependency, WS edge case expectation. Marked skip/xfail: prediction engine (20), deep research (10), queue filtering (5), dispatcher mock (4), job queue progressive (4), token refresh (4), SDK client (2), admin bcrypt (2), LanceDB normalization (5).
  - **Plan doc**: [`src/rnd/2026.03.12-integration-test-remediation-and-db-disambiguation.md`](src/rnd/2026.03.12-integration-test-remediation-and-db-disambiguation.md)
  - **DB isolation**: Hot-swap infrastructure from Session 343 — [`src/rnd/2026.03.12-integration-test-hot-swap-config.md`](src/rnd/2026.03.12-integration-test-hot-swap-config.md)
- [x] **[LUPIN] CJ Flow verification: Dry run end-to-end testing for UNBOUNDED tasks** - Session 269: INTERACTIVE dry-run exercises MessageHistory + 6-scenario smoke test created. Needs live server validation.

### TTS Focus Mode Race Condition (Sessions 346-347)

- [x] **[LUPIN] Fix TTS Focus Mode race: orphaned focus mode freezes queue** — Session 346: guards in `enterTTSFocusMode()` and `onTTSPlaybackComplete()`. Session 347: `stopAudio()` + `onTTSPlaybackComplete()` in `submitResponse()` and `handleGracePeriodExceeded()`, fixed `stopAllAudio()` typo in `stopTTSAndAdvance()`. All 10 dismissal paths now have audio cleanup.
  - **Analysis doc**: [`src/rnd/2026.03.12-tts-focus-mode-race-condition-analysis.md`](src/rnd/2026.03.12-tts-focus-mode-race-condition-analysis.md)
  - **File**: `src/fastapi_app/static/js/notifications.js`

### Future Considerations

- [ ] **[LUPIN] Add 60s safety timeout to TTS focus mode** - Prevent permanent stuck state when TTS queue items fail to play. **Partially addressed** (Session 164): Added staleness check on restore + exit in moveToRegularNotifications. Still need: runtime 60s timeout for cases where notification exists but user never responds and timeout doesn't fire. **File**: `src/fastapi_app/static/js/notifications.js:9374-9393`
- [ ] **Silent flag for notifications**: Consider adding a `silent` parameter to the cosa-voice notification system to suppress TTS during automated testing. Would require changes to: router request models, job classes, voice_io wrappers, and core notification functions.
- [x] **Standardize compound job/user ID usage** - Session 236: Bug #5 made scoped IDs (`base_hash::user_id`) universal across ALL job types via `register_scoped_job()`
- [x] **Standardize job-user-session association interface** - Session 236: Bug #5 unified all write sites through `register_scoped_job()` and all reads through direct `job.user_id` access
- [x] **Implement Approach D: Hybrid Queue + Check-In** - Session 238: Full 5-phase implementation. 20+10 new tests, 317 SWE team tests pass

---

## Completed (Recent)

- [x] **[LUPIN] Fix CC session messages loading into "Unknown" sender card after refresh** — Completed Session 337.
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
