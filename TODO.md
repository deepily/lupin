# TODO

Last updated: 2026-02-24 (Session 266)

## v0.1.6 — FUTURE DEVELOPMENT

### INI Config Key Naming Convention — Standardize on Spaces (Session 256)

- [ ] **[LUPIN] Standardize ~98 underscore config keys to space-separated** — 6-phase migration: backward-compat shim → INI rename → Lupin code (18 files) → CoSA code (62 files) → remove shim + guardrail test. ~2 weeks estimated.
  - **Design doc**: [`src/rnd/2026.02.23-ini-config-key-naming-convention.md`](src/rnd/2026.02.23-ini-config-key-naming-convention.md)
  - **Scope**: ~98 keys, ~80 files (18 Lupin + 62 CoSA), both INI files + splainer
  - **Priority**: Medium — no functional impact, improves consistency and predictability

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

### CJ Flow Persistence

- [ ] **Add persistence for CJ Flow job tracking** - Jobs are currently transient
  - **Goal**: Durable storage for ClaudeCode Job tracking state
  - **Affects**: Job state survives server restarts, enables job history/resume

### Trust Proxy Documentation Update

- [ ] **[LUPIN] Update trust proxy documentation after Phases 3-4 of preference learning** — Revise `src/docs/proxy-admin-guide.md` and related docs to reflect preference learning algorithms, new trust escalation paths, and updated decision proxy behavior.
  - **Partially unblocked**: Phase 3 implemented (Session 266). Phase 4 pending.
  - **Scope**: Admin guide, API reference, R&D docs

### Centralized Navigation & URL Naming Conventions

- [x] **[LUPIN] Create centralized navigation and URL naming conventions** — Unified nav and URL patterns for entire suite of static HTML/plain vanilla JavaScript pages covering all user and admin tasks - Session 247

---

## v0.1.5 — HIGH PRIORITY

---

## Pending

### SWE Team Approach D: Post-Implementation Verification (MEDIUM)

- [x] **[LUPIN] Approach D: Rename user_message → user_initiated_message** — 4 files renamed, 330 unit tests pass
- [x] **[LUPIN] Approach D: Automated smoke test** — `test_approach_d_user_messages.py`, 10 scenarios, 10/10 PASS
- [x] **[LUPIN] Approach D: Fix running queue poll bug + configurable dry-run** — Response key fix, 10-phase 1.5s dry-run loop
- [x] **[LUPIN] Commit CoSA changes for Approach D** — 5 CoSA files modified (notification_client.py NEW, orchestrator.py, config.py, job.py, queues.py). Committed in CoSA context

### SWE Team Proxy Agent (HIGH PRIORITY)

- [x] **[LUPIN] Finish implementing and testing first cut of SWE Team Proxy Agent** - Session 241: Activated proxy in shadow mode, wired trust feedback loop, 7 new tests. 1490 pass.
- [x] **[LUPIN] Phase 7: Real-Time Proxy Summary Notifications** - Session 248: 10 tasks, 7 new tests, 1 E2E smoke. Batch lifecycle, proxy summary emission, trust mode dropdown, circuit breaker alerts. 1518 pass.
- [x] **[LUPIN] Phase 8: Hot-Reload Trust Mode** - Session 248: REST endpoint + UI dropdown on Trust Dashboard, 16 new tests, 1534 pass
- [ ] **[LUPIN] Test SWE agent team with small jobs** - Validate SWE team end-to-end with small, scoped tasks to verify orchestration and proxy behavior
- [ ] **[LUPIN] Commit CoSA changes for proxy activation** — 2 CoSA files modified (config.py, orchestrator.py). Must commit in CoSA context separately

### DataFrame CRUD with Voice I/O (Session 132-136)

- [ ] **[LUPIN] Interactive E2E Testing of CRUD Agents** (HIGH PRIORITY) - Execute the 29-scenario testing protocol at `src/rnd/2026.02.04-headless-cc-for-dataframe-crud/testing-protocol.md`.
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
- [x] **notification-patterns** (HIGH) - cosa-voice MCP usage patterns (~250 lines) — DONE
- [ ] **code-style-preferences** (LOW) - Spacing, alignment, getattr prohibition (~100 lines)

### Smoke Test Coverage Audit (MEDIUM) ✅ DONE

- [x] **[LUPIN] Verify smoke test coverage across recent work** - Session 221: 6 new test files, 54 pytest methods, all passing
  - ST-1: `test_decision_proxy_offline_smoke.py` — TrustTracker, CircuitBreaker, CategoryTrust (15 tests)
  - ST-2: `test_swe_team_orchestrator_dry_run_smoke.py` — Dry-run pipeline, state, progress (10 tests)
  - ST-3: `test_queue_consumer_smoke.py` — Thread lifecycle, job processing (3 tests)
  - ST-4: `test_answer_feedback_smoke.py` — answer_is_correct tri-state round-trip (8 tests)
  - ST-5: `test_agentic_disambiguation_smoke.py` — Confirm/switch/cancel/timeout (4 tests)
  - ST-6: `test_simple_agents_instantiation_smoke.py` — Cal/DateTime/Todo constructors (14 tests)
  - **Deferred**: ST-7 (CRUD queue integration), ST-8 (Decision Proxy live), ST-9 (Classic agents live)



### Slash Command Cleanup (LOW)

- [ ] **[LUPIN] Deprecate old standalone test commands** - Remove `smoke-test-baseline.md`, `smoke-test-remediation.md`, `lupin-test-harness-update.md` from `.claude/commands/`. They use deprecated `notify-claude-async` and duplicate the new `plan-*` commands.
- [ ] **[LUPIN] Audit other repos for verbatim-copy slash command bug** - Check if any other projects have planning-is-prompting config in their test slash commands (same bug fixed in Session 222 for Lupin).
- [ ] **[LUPIN] Update install wizard to generate from templates** - Instead of copying planning-is-prompting versions verbatim, the wizard should use `workflow/slash-command-templates/` and prompt for project-specific values.

### Before Branch Merge

- [ ] **[LUPIN] Run and remediate full testing harness** - Unit, smoke, WebSocket, and integration tests. Fix any regressions before merge.
- [ ] **[LUPIN] CJ Flow verification: Dry run end-to-end testing for UNBOUNDED tasks** - Pending

### Implementation Plans

- [ ] **Config Migration**: Implement Claude Agent SDK config migration plan documented at `src/rnd/2026.01.27-claude-agent-sdk-config-migration-plan.md`

### Future Considerations

- [ ] **[LUPIN] Add 60s safety timeout to TTS focus mode** - Prevent permanent stuck state when TTS queue items fail to play. **Partially addressed** (Session 164): Added staleness check on restore + exit in moveToRegularNotifications. Still need: runtime 60s timeout for cases where notification exists but user never responds and timeout doesn't fire. **File**: `src/fastapi_app/static/js/notifications.js:9374-9393`
- [ ] **Silent flag for notifications**: Consider adding a `silent` parameter to the cosa-voice notification system to suppress TTS during automated testing. Would require changes to: router request models, job classes, voice_io wrappers, and core notification functions.
- [x] **Standardize compound job/user ID usage** - Session 236: Bug #5 made scoped IDs (`base_hash::user_id`) universal across ALL job types via `register_scoped_job()`
- [x] **Standardize job-user-session association interface** - Session 236: Bug #5 unified all write sites through `register_scoped_job()` and all reads through direct `job.user_id` access
- [x] **Implement Approach D: Hybrid Queue + Check-In** - Session 238: Full 5-phase implementation. 20+10 new tests, 317 SWE team tests pass

---

## Completed (Recent)

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
