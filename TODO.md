# TODO

Last updated: 2026-04-08 (Session 97f29034 — CJ Flow UPE + Test Suite Hardening)

## Pending

- [ ] [LUPIN] **CoSA commit pending: Session 97f29034 + a312ee22 (25 files)** — Session 97f29034 additions: `websocket_manager.py` (+session_is_admin +emit_to_admins_sync +roles), `queue_util.py` (+admin broadcast), `websocket.py` (+roles param), `cosa_interface.py` (notify→notify_progress), `job.py` (remove View Full Log). Session a312ee22: `util.py` (+get_current_datetime_iso), 9 REST/WS files, 11 agent job files. Commit from CoSA repo context.
- [ ] [LUPIN] **4x Duplicate Notifications** — Notifications appear 4 times. Likely multiple WS sessions per user (queue + audio + cc-listener + zombie). Needs interactive reproduction and diagnostics. Deferred from Session 97f29034.
- [ ] [LUPIN] **E2E test scheduled 9:26 PM EST** — `ts-efba6552`. Check results next session if not reviewed tonight.
- [ ] [LUPIN] **BFE Phase 6: Live E2E test of automated repair loop**. All code implemented (6A-6F), 58 unit tests passing. Needs live E2E: enable `auto fix enabled = true` in INI, submit a presentation gen job with known-bad mutation, verify watchdog → BFE → resubmit cycle completes. Schedule as monopolized test-suite job after hours.
- [ ] [LUPIN] **Automated E2E testing workflow**: Design standard pattern for scheduling E2E/integration test runs as monopolized jobs at user-specified times. Becomes the modus operandi for all post-coding verification.

- [ ] [LUPIN] **Session 389 VERIFICATION — return to review today's work (NEXT SESSION)**. Two bodies of work landed in Session 389 that need end-to-end verification: (1) Voice routing training data complete coverage (5 content-gen agents, multi-placeholder expansion bug fix in xml_coordinator.py), (2) BFE Phase 5 Trust Proxy + Git Strategy (git_ops.py, run_git_strategy, 33 new tests, 2,831 unit tests passing). User shut down mid-session; resume with: summarize what was completed, verify commits landed (Lupin parent-repo + COSA nested-repo commits pending), confirm no regressions, identify any loose ends. Plan docs: `src/rnd/v0.1.6/2026.03.27-bug-fix-expediter/07-phase5-execution-log.md`, `src/cosa/agents/presentation_generator/rnd/2026.04.05-voice-routing-training-data-complete-coverage.md`.

- [x] [LUPIN] **Docker: Mount ~/.lupin/ as volume for test credentials** — FIXED Session 5946362f. Added `-v "$HOME/.lupin:/root/.lupin:ro"` to `start-docker-lupin.sh`. Verified: `test-env.sh` and `config` visible inside container after restart.
- [ ] [LUPIN] **Test-Suite Job — Phase 3 (conftest.py addoption) — DEFERRED to 2026-04-07**. Consolidate `smoke_direct` into unified `smoke` runner via pytest's `pytest_addoption` hooks (--auto-proxy, --cost-cap-usd, --group, etc.). ~30 min work. Not blocking anything. Plan: `src/rnd/2026.04.05-test-suite-agentic-job-comprehensive-expansion.md` Phase 3.
- [x] [LUPIN] **Test-Suite Job — Persist to DB** — FIXED Session 8042b0d1. Added `"test_suite"` to `AGENTIC_JOB_TYPES` in `job_persistence.py:42-51`. Follow-up: `mark_interrupted_jobs()` marks but doesn't re-enqueue; consider auto-re-enqueue for pending jobs on startup.
- [ ] [LUPIN] **TestSuiteJob — Surface stderr when subprocess crashes at startup**. When exit_code!=0 AND 0 tests found, response_text says "FAILURES DETECTED" with 0/0/0 — misleading. Should include captured stdout/stderr tail so operator sees the actual error immediately. Discovered Session 8042b0d1 when 142ms crash showed no diagnostic info.
- [ ] [LUPIN] **Test-Suite Job — INI-driven timeouts** (follow-up). Phase 2 uses hardcoded `SUITE_TIMEOUTS_SECONDS` dict in job.py. Promote to INI config keys so operators can tune without code changes. Original plan called for this; deferred for v1 pragmatism.
- [ ] [LUPIN] **Run PEFT trainer — training data REGENERATED & ready (USER-RUN GPU)**. Session 389 expanded training data for complete argument coverage across 5 content-gen agents: presentation_generator (5 placeholders + renderer/duration/audience/audience_context), research_to_presentation, podcast_generator, research_to_podcast, deep_research. Also added monopolize conditional_args for test_suite, target_languages multi-value conditional (es-MX/es-ES/es-AR + en/fr/de) for podcast agents. Fixed multi-placeholder expansion bug in xml_coordinator.py. 35,564 train + 4,446 test + 4,446 validate examples generated; all JSONL files validated. **When GPU free, USER runs**: `./src/scripts/run-agentic-intent-training.sh test` (1% sanity, 5-10 min) then `full` (~3-4 hrs). Plan: `src/cosa/agents/presentation_generator/rnd/2026.04.05-voice-routing-training-data-complete-coverage.md`.

- [x] [LUPIN] **Bug Fix Expediter — Phase 5: Trust Proxy + Git Strategy**. Session 389 COMPLETED. 33 new tests (16 git_ops + 17 phase5), 2,831 unit tests passing. 3 new files (git_ops.py, test_bfe_git_ops.py, test_bfe_phase5.py), 6 modified (state.py +COMMITTING +git fields, config.py +trust_mode, plan_writer.py +Git References, orchestrator.py +run_git_strategy, job.py wiring, INI+splainer). Trust-to-git mapping: L1-L2→commit_only, L3+→branch_and_pr via gh; gh unavailable degrades to branch_only. Multi-placeholder expansion bug fix in xml_coordinator.py. Execution log: `src/rnd/v0.1.6/2026.03.27-bug-fix-expediter/07-phase5-execution-log.md`.
- [x] [LUPIN] **Claude Agent SDK Upgrade 0.1.36 → 0.1.56** — Session db376295. Upgraded 20 patches (was 16 behind at 0.1.52, went to latest 0.1.56 to align with Dockerfile). RateLimitEvent handling added to 9 streaming loops in 3 files, version pin updated in requirements.txt. 162 unit tests passing. Analysis: `src/rnd/v0.1.6/2026.03.30-claude-agent-sdk-upgrade-0.1.36-to-0.1.52.md`.
- [x] [LUPIN] **Presentation Generator Visual Rendering Expansion — Phase 9A: MatplotlibRenderer** — Session 388: 30 new tests, all passing. MatplotlibRenderer + prompts + API client + orchestrator integration + seaborn dep. Plan doc: `src/rnd/v0.1.6/2026.03.14-presentation-generator/renderers/2026.04.01-matplotlib-renderer-implementation.md`
- [x] [LUPIN] **Presentation Generator Visual Rendering Expansion — Phase 9B: D2Renderer** — Session 388b: 25 new tests, all passing. D2Renderer + prompts + API client + orchestrator registration + d2 CLI install + Dockerfile update. Plan doc: `src/rnd/v0.1.6/2026.03.14-presentation-generator/renderers/2026.04.01-d2-renderer-implementation.md`
- [x] [LUPIN] **Presentation Generator Visual Rendering Expansion — Phase 10A: NanoBananaRenderer** — Session 388: 27 new tests, all passing. NanoBananaRenderer + GeminiImageClient + image prompts + INI config + orchestrator try/except registration. Plan doc: `src/rnd/v0.1.6/2026.03.14-presentation-generator/renderers/2026.04.01-nano-banana-renderer-implementation.md`
- [x] [LUPIN] **Presentation Generator Visual Rendering Expansion — Phase 10B: VeoRenderer** — Session 388b: 26 new tests, all passing. VeoRenderer + video prompts + GeminiImageClient generate_video() + config-driven Veo model + orchestrator + VISUAL_TYPES expanded 8→17. Plan doc: `src/rnd/v0.1.6/2026.03.14-presentation-generator/renderers/2026.04.01-veo-renderer-implementation.md`
- [ ] [LUPIN] **Presentation Generator Visual Rendering Expansion — Phase 11: Theme Integration**. Cross-cutting theme wiring for all renderers. Plan doc: `src/rnd/v0.1.6/2026.03.14-presentation-generator/renderers/05-theme-integration-plan.md`.
- [x] [LUPIN] ~~**Archive history.md — CRITICAL**~~ — Resolved: was 19.5k after Session 373b, now 10.4k (41.5%) after Session 375 archival
- [x] [LUPIN] **Presentation Generator Phase D verification — COMPLETED Session 8042b0d1**. Live E2E ran successfully: `pr-fc786e8e`, 469s (7m49s), 15 slides, $2.43 cost, 10 Claude API calls. All 4 gates auto-approved via scripted proxy. Full results: `src/rnd/v0.1.6/2026.03.14-presentation-generator/2026.04.05-phase-d-live-e2e-results.md`.
- [x] [LUPIN] **Presentation Generator — Sonnet as automated testing default** — COMPLETED Session 5946362f. Haiku ($0.06/run) produced 0 slides; pivoted to Sonnet (`claude-sonnet-4-6`). Sonnet run: `pr-512e5ca4`, 472s, **15 slides**, **$0.46** (81% cheaper than Opus), 8/8 sub-checks PASS. Updated INI, splainer, config.py defaults. Added `slide_count > 0` assertion + `--timeout` CLI arg + timeout 600→900s.
- [x] [LUPIN] **Phase D re-run through test-suite endpoint — COMPLETED Session 93c49ccb**. Ran via `POST /api/test-suite/submit` with Haiku (`claude-haiku-4-5-20251001`). Job `pr-b77c44d3`, 192s (3m12s), $0.06 cost (97% cheaper than Opus $2.43), 3 API calls, 15,226 in / 11,810 out tokens. **Quality issue**: 0 slides generated — pipeline completed without error but YAML output didn't produce parseable slides. Cost cap revised $2→$5.
- [x] [LUPIN] **Presentation Generator — Haiku quality investigation** — RESOLVED Session 5946362f. Inspected YAML artifact `pres-bd87e234`: valid YAML with `slides: []`. Root cause: Haiku content quality insufficient for structured YAML schema (only 3 API calls vs Opus's 10). Decision: pivot to Sonnet (confirmed working). Postmortem: `src/rnd/v0.1.6/2026.03.14-presentation-generator/2026.04.07-phase-d-postmortem.md`.
- [x] [LUPIN] **Smoke test timeout too short for test-suite path** — FIXED Session 5946362f. `DEFAULT_TIMEOUT` 600→900. Added `--timeout` CLI arg for operator override. Also updates `REQUEST_TIMEOUT` when provided.
- [ ] [LUPIN] **Interrupted job re-enqueue mechanism**. `mark_interrupted_jobs()` in `job_persistence.py` marks pending/running jobs as interrupted at startup but does NOT re-enqueue them. Long-running jobs (presentation ~8min, deep research ~15min) are lost on server restart. Proposed: persist constructor args in `metadata_json` at creation time, add `requeue_interrupted_jobs()` at startup with max retry guard. See postmortem plan: `~/.claude/plans/misty-noodling-babbage.md` Step 5.
- [ ] [LUPIN] **Run Opus through test-suite endpoint**. Sonnet validated (`pr-512e5ca4`, 15 slides, $0.46). Opus has never run through `POST /api/test-suite/submit` — the Apr 5 success was via rogue background bash. ~$2.43 cost.
- [x] [LUPIN] **CoSA commit — Session 8042b0d1 (4 files)** — Committed from CoSA repo context. Files: job.py (SUITE_SCRIPTS/timeouts), cost_tracker.py (pricing comment), config.py (presentation_gates), job_persistence.py (test_suite type).
- [x] [LUPIN] **CJ Flow Phase 5: Notifications UI + WebSocket Integration** — Session 382: 6 code steps + Phase 6 docs complete, 14/14 E2E Playwright tests pass, 2372 unit tests (0 regressions). Plan doc: `src/rnd/2026.03.28-cj-flow-phase-5-notifications-ui.md`
- [x] [LUPIN] **CJ Flow History: Delete & retry E2E tests** — Session 382b: 11-test manual rubric automated as 9 Playwright E2E tests (3 classes). 9/9 new tests pass, full regression 317/318 (1 pre-existing). Retry tests mock backend (LLM routing unavailable in test env). Plan doc: `src/rnd/v0.1.6/2026.03.27-cj-flow-history-delete-retry-manual-testing-rubric.md`
- [x] [LUPIN] Presentation Generator Phase 6: Marp Text Rendering — Session 382d: 6/6 tasks, 45 new tests, MarpTextRenderer + theme system + orchestrator integration
- [x] [LUPIN] Presentation Generator Phase 7: Visual Rendering — Session 382d: 7/7 tasks, 43 new tests, VisualRenderer ABC + MermaidRenderer + PlaceholderRenderer + registry + Gate 4
- [x] [LUPIN] **Presentation Generator Phase 8: Delivery & Chaining** — Session 383: `_deliver_async()` real implementation + DR→Presentation bridge (5 new files), factory, registry, router, main.py, PRODUCT_NAMES, job_persistence. 32 new unit tests. Automated testing infra: proxy Q&A scripts, config profiles, 3 integration scenarios, dry-run smoke test, voice routing utterances (65×2), UI checkbox + dropdown, E2E tests, skill doc checklist. Plan doc: `src/rnd/v0.1.6/2026.03.14-presentation-generator/10-phase-8-implementation-plan.md`
- [x] [LUPIN] Presentation Generator Phase C verification: CJ Flow dry-run queue submission + UI card — Session 374: 6/6 smoke tests pass, mode maps + HTML card + JS handler added
- [x] [LUPIN] Presentation Generator Phase 3: Ingest & Analyze — Content generation, first LLM work
- [x] [LUPIN] Presentation Generator Phase 4: Outline & Elaborate — Session 371: 7/7 tasks, 94 new tests
- [x] [LUPIN] Presentation Generator Phase 5: Serialize YAML — Session 371: 5/5 tasks, 17 new tests
- [x] [LUPIN] Presentation Generator: Wire `fuzzy_file_match` special handler — Session 371: already wired, added presentation-specific config key
- [x] [LUPIN] **Bug Fix: WebSocket 503 "user_not_available" — audio WS auth fix not yet working.** Root cause confirmed: audio WS endpoint connects without user auth, so after hot reloads only a "ghost" connection (in `active_connections` but not `user_sessions`) remains. Fix added auth_request handling to audio endpoint (`websocket.py:205-260`) but needs further debugging — test notification still failed. Diagnostic infrastructure in place (`[NOTIFY] ⚠️ OFFLINE DIAG`, `[WS-DIAG]` browser prefix, `[WS] STATE` logs). Plan doc: `~/.claude/plans/bubbly-churning-donut.md` — **Fixed Session 371**
- [x] [LUPIN] Phase 1: Create `admin@lupin.deepily.ai` account + update `~/.lupin/config` (manual) — Session 372: Done
- [x] [LUPIN] **Bug Fix: Voice injection silent crash on null title** — Session 372: `NotificationItem.title` was None, crashing listener's `startswith()`. Fixed at source: `title: str = ""` in constructor + API boundary normalization. 36/36 listener + 189/189 model tests pass.
- [x] [LUPIN] **CJ Flow Persistence Phase 6: Job History UI** — Session 371: Hybrid overlay model (Option C) with deduplication. 5th collapsible history section, configurable time window, delete/retry management, 19 new tests. Plan doc: `src/rnd/2026.03.13-cj-flow-persistence-plan.md`
- [x] [LUPIN] Phase 6 cleanup: Clean up existing 1001 `st-*` test notification artifacts (delete or reassign — decide after using filter) — **Fixed Session 371**
- [x] [LUPIN] Archive history.md — at 18.4k tokens, above 17k WARNING threshold (deferred from Session 371b) — **Superseded**: now 19.5k+, escalated to CRITICAL in Session 374 TODO above
- [x] [LUPIN] **Run clean full integration suite** — Session 380: **195 passed, 0 failed, 32 skipped** in 5:50. LanceDB isolation + warm test fixes verified clean. Added `--bg` flag + PID-file overlap protection to `run-integration-tests.sh` (same pattern as E2E runner). Fixed `test_admin_not_self_excludes_own_jobs` (500 from push pipeline unavailable in test env → skip gracefully).
- [x] [LUPIN] CoSA commit pending: `websocket.py` Fix 4 (WebSocketDisconnect handler + safe close) — committed from CoSA repo context
- [x] [LUPIN] CoSA commit pending: Session 383 — `local_embedding_engine.py` (added `local_files_only=True` to SentenceTransformer) — committed from CoSA repo context
- [x] [LUPIN] CoSA commit pending: Session 382b — `configuration_manager.py` (visual grouping stem split: `"_"` → whitespace) — committed from CoSA repo context
- [x] [LUPIN] CoSA commit pending: Session 380b fixes — `running_fifo_queue.py` (stack trace capture), `job_persistence.py` (stack_trace rich_field), `deep_research/job.py` (cost_summary in artifacts), `presentation_generator/job.py` (cost_summary tokens), `podcast_generator.py` (Field import), `presentation_generator.py` (Field import) — committed from CoSA repo context
- [x] [LUPIN] CoSA commit pending: Voice injection bug fix — `notification_fifo_queue.py`, `notifications.py`, `base_listener.py` — committed b544c78
- [x] [LUPIN] CoSA commit pending: session_name pipeline — `notification_fifo_queue.py` (session_name attr), `notifications.py` (session_name param + session_topic type) — committed b544c78
- [ ] [LUPIN] **TestSuiteJob: Manual + Automated Testing** — Pattern A implemented (Session 386). Remaining: (1) Fix voice_io dispatcher bug (`AgentNotificationDispatcher` missing `notify` attribute — notifications fall back to CLI), (2) Manual UI verification of submit card + scheduling, (3) Verify scheduling timezone fix with live scheduled job, (4) Run live pipeline smoke test with server, (5) Integration test for `POST /api/test-suite/submit`. Plan: `src/rnd/v0.1.6/2026.03.31-test-suite-agentic-job-plan.md`
- [x] [LUPIN] **Scheduled Long-Running Jobs in CJ Flow** — Pattern A (TestSuiteJob) fully implemented Session 386. Pattern B (PEFT training OS-level orchestrator) deferred. Planning doc: `src/rnd/v0.1.6/2026.03.30-scheduled-long-running-jobs.md`
- [x] [LUPIN] Run full E2E + integration test suite before merging branch to main — Session 385: all 4 layers passed (unit 2647, WS 50/50, E2E 14/14 pause/schedule, integration 196). Full E2E re-run needed for visual regression (2 pre-existing errors).
- [x] [LUPIN] CoSA commit pending: Session 385 — Unified Job State Machine (~25 CoSA files: job_state.py, queue_protocol, queue_util, job_persistence, fifo_queue, queue_consumer, running_fifo_queue, todo_fifo_queue, routers/queues, agent_base, agentic_job_base, solution_snapshot, 9 agent jobs, mock_job) — committed from CoSA repo context
- [ ] [LUPIN] Full E2E re-run needed to verify 2 visual regression errors are pre-existing (test_visual_regression.py profile + notifications)
- [x] [LUPIN] **Verify E2E UI test suite health — clean single run needed** — Session 377: **297 passed, 0 failed** in 17m12s. Session 372c's 23 errors confirmed as hot-swap collision (not real failures). Added `--bg` flag to `run-e2e-ui-tests.sh` with PID-file overlap protection to prevent recurrence. Updated 1 stale visual snapshot (notifications page). Suite is fully healthy.

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

### Prediction System: Validation + Documentation

- [ ] **[LUPIN] Prediction System Validation Campaign** — Unified 6-phase validation of UPE (7 slices, 87 unit + 21 E2E) and SWE proxy Layer 2 (shadow-mode capture). Phases: baseline, threshold tuning, SWE shadow-mode, gap tests (+6 E2E), visual QA, full lifecycle. 136 existing + 6 new = 142 total tests.
  - **Umbrella plan**: [`src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.25-prediction-system-validation-campaign.md`](src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.25-prediction-system-validation-campaign.md)
  - **UPE validation plan**: [`src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.11-upe-live-e2e-validation-plan.md`](src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.11-upe-live-e2e-validation-plan.md)
  - **SWE workload doc**: [`src/rnd/2026.02.25-swe-proxy-data-origin-and-workload-generator.md`](src/rnd/2026.02.25-swe-proxy-data-origin-and-workload-generator.md)
  - **Progress**: Phase 1 DONE. Phase 2 LanceDB isolation VERIFIED (Session 380) — 195/195 full suite pass, 21/21 prediction engine focused pass. Phases 3-6 can now proceed.
  - **LanceDB isolation plan**: [`src/rnd/2026.03.25-upe-lancedb-test-isolation.md`](src/rnd/2026.03.25-upe-lancedb-test-isolation.md) — implemented Session 378
  - **Implementation plan**: [`src/rnd/2026.03.26-upe-lancedb-test-isolation-and-warm-fix.md`](src/rnd/2026.03.26-upe-lancedb-test-isolation-and-warm-fix.md)
- [ ] **[LUPIN] Trust & Prediction Documentation Update** — Revise `src/docs/proxy-admin-guide.md` for Phase 3 conformal/ICRL + Phase 4 UPE prediction engine. Create `prediction-engine-reference.md`. Blocked by Prediction System Validation Campaign completion.
  - **Scope**: proxy-admin-guide.md (Sections 7, 9, 10), new prediction-engine-reference.md, docs/README.md links
  - **Umbrella plan**: [`src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.25-prediction-system-validation-campaign.md`](src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.25-prediction-system-validation-campaign.md)

### Config Migration — Claude Agent SDK

- [x] **[LUPIN] Config Migration**: Phases 0-4 complete — Session 364. Deep Research (24 keys + `from_config()`), Podcast Generator (27 keys + nested `from_config()`), LLM Client Factory (10 keys + INI loading). 2083 unit tests pass. Revised plan at `src/rnd/2026.03.14-claude-agent-sdk-config-migration-plan.md`.
- [ ] **[LUPIN] Phase 5: Update agentic voice workflow skill** — Ensure `/lupin-new-claude-agent-sdk-voice-workflow` scaffolds new agents with `from_config()` pattern by default. Update templates in `src/workflow/agentic-voice-workflow.md`.

### CJ Flow: Timed Execution + Monopolize + Pause/Resume (Session 381 — IN PROGRESS)

- [x] **[LUPIN] Phases 0-4: Backend complete** — Protocol fields (`scheduled_at`, `monopolize`, `paused`), consumer loop rewrite with `pop_next_eligible()` + dynamic wake-up timeout, 5 router updates, pause/resume REST endpoints, config keys, 25 new tests (all pass), 2338 unit regression clean.
- [ ] **[LUPIN] Phase 5: Notifications UI + WebSocket integration** — JS event subscriptions (`job_paused`, `job_resumed`), event handlers, paused/scheduled visual states on job cards, pause/resume toggle button, CSS. Continue next session.
- [ ] **[LUPIN] Phase 6: Documentation + E2E validation** — `websocket-events.md` updates, manual E2E test with live server.
- **Tracking doc**: [`src/rnd/v0.1.6/2026.03.30-cj-flow/2026.03.27-cj-flow-timed-execution-monopolize-pause.md`](src/rnd/v0.1.6/2026.03.30-cj-flow/2026.03.27-cj-flow-timed-execution-monopolize-pause.md)

### CJ Flow: Unified Job State Machine (Pre-Hybrid Fast Lane)

- [ ] **[LUPIN] Refactor fragmented state tracking** — Replace `status` field + queue position + `paused` boolean with unified `job_state` column (`pending → queued → scheduled → running → paused → completed/failed/cancelled`). Touches 15+ files: protocol, 7 job types, consumer, persistence, routers, UI. Dedicated preparatory effort before Hybrid Fast Lane.
- **Assessment doc**: [`src/rnd/v0.1.6/2026.03.30-cj-flow/2026.03.30-unified-job-state-machine-assessment.md`](src/rnd/v0.1.6/2026.03.30-cj-flow/2026.03.30-unified-job-state-machine-assessment.md)
- **CJ Flow hub**: [`src/rnd/v0.1.6/2026.03.30-cj-flow/00-index.md`](src/rnd/v0.1.6/2026.03.30-cj-flow/00-index.md)

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
- **Prerequisite**: Unified Job State Machine refactor must complete first (freshness review of this plan against new consumer loop)
- **Tracking doc**: `src/rnd/2026.02.19-approach-c-hybrid-queue-architecture.md`

### Playwright E2E Browser Testing (Session 252)

- [x] **[LUPIN] Research AI/automation for end-to-end testing** — Session 252: Research complete. Playwright Python + pytest-playwright recommended for FastAPI + vanilla HTML/JS stack
- [x] **[LUPIN] Implement Playwright E2E testing** — ALL 8 PHASES COMPLETE (Sessions 351-361). 265 E2E tests (253 functional + 12 visual regression) across 28 test files covering all 12 pages.
  - **Planning docs**: [`src/rnd/2026.02.23-automating-ui-testing/`](src/rnd/2026.02.23-automating-ui-testing/00-index.md)
  - **Phases 1-2**: DONE — Foundation + data-testid rollout (~266 testids across 13 files)
  - **Phase 3**: DONE — Auth Flow Tests (37 tests)
  - **Phase 4**: DONE — Page Smoke Tests (27 tests)
  - **Phase 5**: DONE — Admin Flow Tests (69 tests)
  - **Phase 6**: DONE — Notifications & Q&A Tests (86 tests)
  - **Phase 7**: DONE — WebSocket & Real-Time Tests (28 tests)
  - **Phase 8**: DONE — Visual Regression & CI (12 tests, JS normalization, Dockerfile, `--no-deps` starlette workaround)
  - **Full suite**: 2,102 unit + 50 WS + 265 E2E UI + 137 integration = ALL PASS
  - **Round 2** (future): Claude Code + Playwright MCP for AI-augmented test generation + self-healing selectors

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

### Presentation Generator Agent (Session 362 — IN PROGRESS)

- [ ] **[LUPIN] Presentation Generator Agent: Transform research docs into slide decks** — 🔄 IN PROGRESS. Phases 1-5 complete, Phase 6 beginning. Next: Phase 6 (Text Rendering: Marp Markdown).
  - **Goal**: Agentic process (Claude SDK) that transforms ~1200-word research documents or technical blog posts into 10-20 minute slide decks with presenter notes. Single orchestrator pattern (like Podcast Generator).
  - **Architecture**: 8-phase pipeline (ingest, analyze, outline, elaborate, serialize YAML, render Marp, render Mermaid visuals, deliver). 4 human-in-the-loop gates. Pluggable visual renderer registry. Theme cascade (INI -> YAML template -> per-presentation overrides).
  - **R&D directory**: [`src/rnd/2026.03.14-presentation-generator/`](src/rnd/2026.03.14-presentation-generator/00-index.md)
  - **Phase 0**: DONE — Strategy & design serialized, implementation plan & tracking created (4 docs)
  - **Phase 1**: DONE — Foundation (Job, Config, Voice I/O, CJ Flow packaging) — Session 367b
  - **Phase 2**: DONE — State models & orchestrator skeleton — Session 367b
  - **Phase 3**: DONE — Content generation: ingest & analyze
  - **Phase 4**: DONE — Content generation: outline & elaborate
  - **Phase 5**: DONE — Content generation: serialize YAML
  - **Phase 6**: Pending — Text rendering: Marp Markdown
  - **Phase 7**: Pending — Visual rendering: Mermaid + registry
  - **Phase 8**: Pending — Delivery & DR-to-Presentation chaining (Phase 8)

### CJ Flow Persistence (Sessions 357, 360, 367 — BACKEND COMPLETE)

- [x] **[LUPIN] CJ Flow Persistence: PostgreSQL-backed job history for agentic jobs** — ✅ ALL 5 PHASES COMPLETE. Backend fully implemented and E2E verified (Session 367).
  - **Goal**: Durable storage for AgenticJobBase jobs (DeepResearch, PodcastGenerator, ClaudeCode, SweTeam). Job state survives server restarts, enables job history queries, marks interrupted jobs.
  - **Architecture**: Central write-through via `emit_job_state_transition()` in `queue_util.py`
  - **Plan doc**: [`src/rnd/2026.03.13-cj-flow-persistence-plan.md`](src/rnd/2026.03.13-cj-flow-persistence-plan.md)
  - **Phase 0**: DONE — Plan serialized to R&D
  - **Phase 1**: DONE — Schema + SQLAlchemy model (`job_history` table, `add-job-history.sql`, `JobHistory` in postgres_models.py). 12 models, 12 tables. Table + 5 indexes deployed to lupin_db_dev.
  - **Phase 2**: DONE — Persistence service (`job_persistence.py`, 8 functions, 2 config keys). Full DB round-trip smoke test passes.
  - **Phase 3**: DONE — Write-through integration in `emit_job_state_transition()`. Persistence fires after WS emit, filtered by `is_agentic_job_type()`. 12 callsites audited, zero needed modification. Session 367.
  - **Phase 4**: DONE — Startup recovery (`mark_interrupted_jobs()`) in `main.py` lifespan. Session 367.
  - **Phase 5**: DONE — `GET /api/job-history` + `GET /api/job-history/{job_id}` endpoints with role-based auth. 17 unit tests, 9 integration tests. E2E smoke test 7/7 pass. Session 367.
  - **Regression**: 2155 unit tests pass, 0 new failures
- [ ] **[LUPIN] CJ Flow Persistence: Job History UI page** — Future scope. Backend + API complete, no browser page yet. Pick up in next session to scope a job history viewer page.

### Universal Prediction Engine: Live E2E Validation (Session 340)

- [ ] **[LUPIN] Live E2E validation of all 7 UPE slices** — **CONSOLIDATED** into [Prediction System Validation Campaign](src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.25-prediction-system-validation-campaign.md). See "Prediction System: Validation + Documentation" section above.

### Render Markdown Documents as HTML + Audio Player Viewer

- [x] **[LUPIN] Render markdown documents as HTML + in-browser MP3 player** — Completed. Markdown documents render as styled HTML pages; also created an Audio Player Viewer for in-browser MP3 playback.

### Trust Proxy Documentation Update

- [ ] **[LUPIN] Update trust proxy documentation** — **CONSOLIDATED** into [Trust & Prediction Documentation Update](src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.25-prediction-system-validation-campaign.md). See "Prediction System: Validation + Documentation" section above.

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
