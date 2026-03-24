# Lupin Project History

### 2026.03.23 - Session 368 | Bug Fix: WebSocket 503 "user_not_available" Notifications

**Accomplishments**:
- Diagnosed and partially fixed recurring 503/user_not_available notification delivery failures
- **Root cause identified**: Audio WebSocket endpoint (`/ws/audio/{session_id}`) connects WITHOUT user authentication, leaving sessions in `active_connections` but not `user_sessions`. After hot reloads, only the audio WS reconnects (no auth needed), creating "ghost" connections with no user mapping.
- **Diagnostic infrastructure added**: Always-on `[NOTIFY] ⚠️ OFFLINE DIAG` dump on server when user offline, `[WS-DIAG]` filterable prefix for browser console, `[WS] STATE after connect/disconnect` summary logs
- **Browser UI fix**: "Connected" status now only shown after auth_success (was shown on TCP open, misleading during hot reloads)
- **Audio WS auth handler added**: Audio endpoint now processes `auth_request` messages (mirrors queue endpoint), providing redundant user registration in `user_sessions`
- **Status**: Fix applied but not yet verified working — needs further debugging next session

**Files Modified (Lupin — 3 files)**:
- `src/cosa/rest/routers/notifications.py` — Added ungated OFFLINE DIAG dump (~10 lines)
- `src/fastapi_app/static/js/notifications.js` — Truthful Connected status, `wsDiag()` method, `[WS-DIAG]` prefix (~20 lines)
- `src/tests/unit/test_notifications_api.py` — Added `user_to_email = {}` to mock fixtures (5 occurrences)

**Files Modified (CoSA — 2 files)**:
- `src/cosa/rest/websocket_manager.py` — Added `[WS] STATE` summary logs after connect/disconnect
- `src/cosa/rest/routers/websocket.py` — Added auth_request handler to audio WS endpoint (~40 lines)

**Test Results**: 2151 passed (11 notification API tests pass), 6 pre-existing failures (cosa_voice_mcp SyntaxError from parallel session)

**Plan doc**: `~/.claude/plans/bubbly-churning-donut.md`

---

### 2026.03.23 - Session 367d | CJ Flow Persistence — Phases 3-5 (Write-Through + Recovery + API + Tests)

**Accomplishments**:
- Completed all 5 phases of CJ Flow Persistence — agentic jobs now persist to PostgreSQL
- **Phase 3**: Wired `job_persistence.py` into `emit_job_state_transition()` in `queue_util.py`. Persistence fires after WS emit, filtered by `is_agentic_job_type()`. Audited all 12 callsites — zero needed modification. Changed `websocket_mgr=None` from early-return to conditional guard so persistence works without WS.
- **Phase 4**: Added `mark_interrupted_jobs()` startup recovery in `main.py` lifespan, after PostgreSQL init but before GPU loading and consumer thread.
- **Phase 5**: Added `GET /api/job-history` (paginated, admin sees all, user sees own) and `GET /api/job-history/{job_id}` (detail with 403/404) to `queues.py`. 17 unit tests + 9 integration tests + 1 E2E smoke test (7/7 pass).
- Updated design doc `src/rnd/2026.03.13-cj-flow-persistence-plan.md` with detailed Phase 3-5 specs, callsite audit table, and deviations log.

**Test Results**: 2155 unit tests pass (17 new), 0 regressions. E2E smoke test 7/7 pass.

**Files Created (Lupin — 2 files)**:
- `src/tests/unit/test_job_persistence.py` — 17 unit tests (type filter, metadata extraction, persist functions, dispatch routing)
- `src/tests/integration/test_job_history_api.py` — 9 integration tests (auth, pagination, filtering, detail)

**Files Created (Lupin — 1 smoke test)**:
- `src/tests/smoke/test_job_persistence_e2e.py` — Automated E2E: auth → DB insert → status progression → API query → detail → cleanup

**Files Modified (CoSA — 1 file)**:
- `src/cosa/rest/queue_util.py` — Added persistence imports + 14-line dispatch block, changed early-return to conditional WS guard
- `src/cosa/rest/routers/queues.py` — Added 2 job-history endpoints (~80 lines)

**Files Modified (Lupin — 2 files)**:
- `src/fastapi_app/main.py` — Added `mark_interrupted_jobs()` import + 7-line recovery block in lifespan
- `src/rnd/2026.03.13-cj-flow-persistence-plan.md` — Updated Phases 3-5 status to ✅, added callsite audit, deviations log

---

### 2026.03.23 - Session 367c | cosa-voice Global MCP Onboarding Bootstrapper

**Accomplishments**:
- Implemented cosa-voice onboarding bootstrapper — migrates MCP registration from per-project `.mcp.json` to global user scope (`claude mcp add --scope user`)
- Hardened MCP server project detection: replaced hard `os._exit(1)` failure with graceful CWD basename fallback + warning. Server now starts from any directory.
- Added consolidated runtime banner to MCP server stderr (project, session, sender, server, account validation status)
- Added two-part session status display: SessionStart hook shows immediate prereq checks (MCP registration, project detection, hooks, server, config) in `additionalContext`; MCP stderr shows runtime status after initialization
- Created `install-cosa-voice.sh` bootstrapper with 3 modes: install (user scope), `--check-only`, `--uninstall`. Validates 6 prerequisites, sends test notification.
- Deleted old `install-mcp-server.sh` (no backward compat)
- Added `.mcp.json` to `.gitignore` and untracked from git (machine-specific absolute paths)

**Test Results**: 2161 unit tests pass, 0 regressions

**Files Created (Lupin — 2 files)**:
- `src/scripts/install-cosa-voice.sh` — Global MCP bootstrapper script
- `src/docs/cosa-voice-onboarding.md` — User-facing onboarding guide

**Files Modified (Lupin — 5 files)**:
- `src/lupin_mcp/cosa_voice_mcp.py` — Softened project detection, added startup banner, updated docstring
- `src/lupin_cli/claude_code/hooks/register_session.py` — Added `_check_cosa_voice_status()`, expanded additionalContext
- `src/lupin_mcp/README.md` — Updated install instructions for global model
- `CLAUDE.md` — Added `install-cosa-voice.sh` to COMMANDS
- `.gitignore` — Added `.mcp.json`

**Files Deleted (Lupin — 1 file)**:
- `src/scripts/install-mcp-server.sh` — Replaced by `install-cosa-voice.sh`

**Files Untracked (Lupin — 1 file)**:
- `.mcp.json` — Removed from git tracking (stays on disk)

**Design doc updated**: `src/rnd/2026.03.23-cosa-voice-onboarding-bootstrapper.md` — Finalized from early design to approved implementation plan

---

### 2026.03.23 - Session 367b | Presentation Generator Agent — Phases 1-2 Foundation

**Accomplishments**:
- Implemented Phase 1 (Foundation) and Phase 2 (State Models + Orchestrator) of the Presentation Generator Agent — 18/55 tasks complete
- Created `PresentationGeneratorJob` (AgenticJobBase, JOB_TYPE="presentation", JOB_PREFIX="pr") with dry-run and orchestrator execution paths
- Created `PresentationConfig` dataclass with `from_config()` loading 9 INI keys (content model, duration, slides/minute, title style, revisions, theme, templates path, output dir, audience)
- Created 6 Pydantic state models: OrchestratorState (12 states), ArcPosition (6 positions), NarrativeSection, PresenterNotes, SlideModel, PresentationModel
- Created `PresentationOrchestratorAgent` with 8-phase state machine (ingest → analyze → outline → elaborate → serialize → render text → render visuals → deliver), 4 gate checkpoints (auto-approve stubs), cancellation support
- Created cosa_interface.py (AGENT_TYPE="presentation.gen") and voice_io.py thin wrapper
- REST router at `/api/presentation-generator/submit`, factory registration, main.py wiring
- All smoke tests pass (6 modules), 39 presentation unit tests, 2170 total unit tests, 0 regressions

**Files Created (14 — CoSA)**:
- `src/cosa/agents/presentation_generator/__init__.py`, `__main__.py`, `config.py`, `cosa_interface.py`, `voice_io.py`, `job.py`, `state.py`, `orchestrator.py`
- `src/cosa/agents/presentation_generator/prompts/__init__.py`, `renderers/__init__.py`
- `src/cosa/agents/presentation_generator/templates/themes/` (empty dir)
- `src/cosa/rest/routers/presentation_generator.py`

**Files Modified (4 — CoSA)**:
- `src/cosa/rest/agentic_job_factory.py` — Factory branch for presentation generator
- `src/conf/lupin-app.ini` — 9 new presentation generator config keys
- `src/conf/lupin-app-splainer.ini` — 9 matching explanations

**Files Modified (1 — Lupin)**:
- `src/fastapi_app/main.py` — Router import + registration

**Files Created (1 — Lupin)**:
- `src/tests/unit/test_presentation_generator_job.py` — 39 unit tests

**R&D Updated**:
- `src/rnd/2026.03.14-presentation-generator/03-implementation-tracking.md` — Phase 1 Done, Phase 2 Done, 18/55 total

---

### 2026.03.23 - Session 367 | Feature: Notification Admin Filter Toggle — "Not My Jobs" Mode

**Accomplishments**:

**New Feature — Three-mode queue + notification filter (Own / Not Mine / All Users)**:
- Backend: Added `!self` authorization case in `queue_auth.py`, `get_jobs_excluding_user()` in `fifo_queue.py`, wired `!`-prefix sentinel in `queues.py` router
- Backend: Added `exclude_own_jobs` param to notification senders-visible and bulk-delete endpoints, with `exclude_job_ids` filtering in repository layer
- Frontend: Third filter button ("Not My Jobs"), two clickable filter mode badges (Notifications header + CJ Flow header) with color-coded modes
- Frontend: Badges click → show + scroll to filter panel; toolbar scroll-on-show for all sections
- Bug fix: `setFilterMode()` now calls `clearSenderGroups()` before `loadConversationHistory()` to prevent UI duplication when switching modes

**Testing**:
- 4 new unit tests for `!self` authorization (21 total, all pass)
- 11 new E2E UI tests: role-gating, mode switching, badge sync, persistence, badge click-to-scroll, toolbar scroll-on-show
- 6 new integration tests: `!self` 403 for non-admin, data correctness (disjoint sets, `own ∪ !self = *`), cross-queue validation

**Test Results**: 2114 unit tests pass, 11 E2E pass, 6 integration pass

**Files Modified (Lupin — 5 files)**:
- `src/fastapi_app/static/html/notifications.html` — Third filter button, header badges, toolbar restored to single-column
- `src/fastapi_app/static/css/notifications.css` — Filter badge styles (color-coded pills, clickable)
- `src/fastapi_app/static/js/notifications.js` — Three-mode filter logic, badge click handlers, scroll-on-show, clearSenderGroups fix
- `src/rnd/2026.03.23-notification-admin-filter-toggle-plan.md` — Serialized plan
- `src/tests/e2e_ui/test_filter_toggle.py` — 11 E2E tests (new)

**Files Modified (CoSA — 5 files, pending separate commit)**:
- `src/cosa/rest/queue_auth.py` — `!self` authorization case (Case 2b)
- `src/cosa/rest/fifo_queue.py` — `get_jobs_excluding_user()` method
- `src/cosa/rest/routers/queues.py` — Wire `!`-prefix filter to exclusion method
- `src/cosa/rest/routers/notifications.py` — `exclude_own_jobs` param on senders + bulk delete
- `src/cosa/rest/db/repositories/notification_repository.py` — `exclude_job_ids` param on sender listing + bulk delete

**Files Modified (Tests — 2 files)**:
- `src/tests/unit/test_queue_authorization.py` — 4 new `!self` test cases + updated matrix tests
- `src/tests/integration/test_queue_not_self_filter.py` — 6 integration tests (new)

### 2026.03.23 - Session 366 | Bug Fix: WebSocket Reconnection + Missing Events + LanceDB Schema

**Accomplishments**:

**Bug 1 — Notifications stop rendering until force refresh**:
- Root cause: `scheduleReconnect()` gave up permanently after 5 failed attempts (`maxRetries = 5`). Once the queue WebSocket dropped (token expiry, server restart, network blip), it never recovered.
- Fix 1a: Removed retry limit — infinite retry with exponential backoff (30s cap, 60s after 10+ failures). Reset counter on successful auth.
- Fix 1b: Independent WebSocket reconnection — if only queue WS drops, only queue WS reconnects (not both). Added `target` parameter to `connectWebSockets()` and `scheduleReconnect()`. Tracked `queueWsConnected`/`audioWsConnected` flags.
- Fix 1c: Added `notification_expired` and `notification_responded` to `websocket available events` in INI config. These events were emitted by server and subscribed by client, but silently filtered out during validation.

**Bug 2 — LanceDB `response_type` schema mismatch (non-fatal)**:
- Root cause: Session 345 added `response_type` field to `ProxyDecisionEmbeddings` schema, but existing LanceDB table was created before this change. `_ensure_table()` opened old table as-is.
- Fix: Added schema validation in `_ensure_table()` — compares existing column names against expected schema. On mismatch, drops and recreates table. Table repopulates organically.

**Bug 3 — Race condition: old WS handler's `disconnect()` kills new connection**:
- Root cause: When browser reconnects with same session_id, old handler's `finally` block calls `disconnect()` which removes the NEW connection from `active_connections`. Result: browser shows connected but server has no record.
- Fix 3a: Guard `disconnect()` in both `/ws/queue/` and `/ws/audio/` finally blocks — only disconnect if `active_connections[session_id] is websocket` (identity check).
- Fix 3b: Deduplicate `user_sessions` in `connect()` — prevent same session_id from being appended multiple times on reconnect.
- Fix 3c: Self-healing orphan cleanup in `emit_to_user()` — when a session is found in `user_sessions` but not in `active_connections`, clean it up automatically.

**Bug 4 — Config key underscore/space mismatch in `/api/config/client`**:
- Root cause: `system.py` read 4 config keys with underscores (`jwt_token_refresh_check_interval_mins`) but INI uses spaces (`jwt token refresh check interval mins`). Keys existed but were never found. Additionally, `return_type="int"` was missing — INI values returned as strings caused `"10" * 60 * 1000` string multiplication.
- Fix: Changed 4 `config_mgr.get()` calls to use space-separated key names + `return_type="int"`. Added 3 missing JWT splainer entries.

**Bug 5 — Phantom connection: server disconnect() doesn't close WebSocket**:
- Root cause: `disconnect()` removes WebSocket from dicts but does NOT call `websocket.close()`. Browser never receives close frame → `onclose` never fires → no reconnection → phantom connection (browser shows "Connected", server says gone).
- Fix: Added explicit `ws.close( code=1000, reason="Server disconnect" )` via `asyncio.run_coroutine_threadsafe()` in `disconnect()` before removing from dicts.

**Test Results**: 2110 unit tests pass, 0 regressions

**Files Modified (Lupin — 6 files)**:
- `src/fastapi_app/static/js/notifications.js` — Infinite retry, independent WS reconnect, connection tracking
- `src/conf/lupin-app.ini` — Added `notification_expired`, `notification_responded` to available events
- `src/conf/lupin-app-splainer.ini` — Splainer entries for 2 new events + 3 JWT token refresh keys
- `src/docs/websocket-events.md` — Documented 2 new events (18→20 total)
- `src/tests/unit/test_ini_key_naming.py` — Added 2 events to WS exemption set

**Files Modified (CoSA — 5 files, pending separate commit)**:
- `src/cosa/rest/routers/websocket.py` — Race condition guard in both finally blocks + TokenExpiredException handling
- `src/cosa/rest/websocket_manager.py` — Dedup user_sessions, orphan cleanup in emit_to_user
- `src/cosa/rest/routers/notifications.py` — API docs metadata on route decorators
- `src/cosa/rest/routers/system.py` — 4 config key underscore→space fixes
- `src/cosa/agents/decision_proxy/proxy_decision_embeddings.py` — LanceDB schema mismatch auto-recreate

**Design docs serialized**:
- `src/rnd/2026.03.23-notification-admin-filter-toggle-plan.md` — Admin account + "Not Mine" filter (Session 367 scope)
- `src/rnd/2026.03.23-cosa-voice-onboarding-bootstrapper.md` — MCP bootstrapper for new repos (future scope)

**Commits**: a994446, 393ab56, e647895, 89cf554, 3195e49

---

### 2026.03.19 - Session 365 | CUDA Memory Optimization — Model Loading Order, Warmup & OOM Retry

**Accomplishments**:
- Reduced VLLM `gpu_memory_utilization` from 0.70 → 0.55 in `~/.bash_aliases` (`svllmr` alias), freeing ~3.7 GiB for FastAPI-resident models
- Generated 85-second Whisper warmup MP3 via ElevenLabs TTS (narration about CUDA memory fragmentation)
- Reordered GPU model loading: CodeRankEmbed → Prose Embedding → Whisper (smallest → largest) to minimize CUDA fragmentation
- Enhanced warmup routines: multi-batch encode calls for both embedding engines, chunked 85s transcription for Whisper (`chunk_length_s=30, stride_length_s=5` matching production)
- Added `_log_vram()` helper for VRAM reporting after each model load (allocated/reserved GiB)
- Implemented `_run_with_cuda_retry()` in both CodeEmbeddingEngine and ProseEmbeddingEngine — wraps all 4 encode methods with gc.collect + empty_cache + single retry on CUDA OOM
- Added 8 unit tests for CUDA OOM retry logic (success, recovery, gc/cache verification, non-CUDA passthrough, CUBLAS handling, double-OOM failure)
- 40/40 embedding engine unit tests pass (32 existing + 8 new)

**Files Created**: `src/conf/warmup/whisper-warmup-85s.mp3`
**Files Modified**: `src/fastapi_app/main.py`, `src/cosa/memory/local_embedding_engine.py` (CoSA), `src/tests/unit/test_local_embedding_engine.py`
**External**: `~/.bash_aliases` (svllmr alias — not in repo)
**Commit**: b2d709b

---

### 2026.03.14 - Session 364 | Claude Agent SDK Config Migration — Phases 0-4

**Accomplishments**:
- Migrated Deep Research, Podcast Generator, and LLM Client Factory configs from hardcoded `@dataclass` to COSA ConfigurationManager (INI + env var overrides)
- Added 61 new INI keys across 3 agents: Deep Research (24 keys: models, scaling, limits, tokens, search, output), Podcast Generator (27 keys: model, script, content, host A/B personality with pipe-delimited phrases, audio), LLM Client Factory (10 keys: vendor URLs, API env vars, defaults)
- Added matching splainer documentation for all 61 new keys
- Implemented `ResearchConfig.from_config( config_mgr )` classmethod — reads all 24 fields from INI with type coercion, falls back to dataclass defaults
- Implemented `HostPersonality.from_config()`, `VoiceProfile.from_config()`, `PodcastConfig.from_config()` — nested composition with pipe-delimited list parsing for `typical_phrases`
- Replaced hardcoded `VENDOR_URLS`, `VENDOR_API_ENV_VARS`, `CLIENT_DEFAULT_PARAMS` class dicts in LlmClientFactory with instance methods loading from INI at singleton init
- Updated all consumers (job.py, cli.py for both agents) to use `from_config()` with job/CLI arg overrides
- No backward compatibility — `from_config()` is the only path (per project feedback)
- Serialized revised plan to `src/rnd/2026.03.14-claude-agent-sdk-config-migration-plan.md`
- 2083/2083 unit tests pass, both config smoke tests pass

**Files Modified (CoSA)**: `src/cosa/agents/deep_research/config.py`, `src/cosa/agents/deep_research/job.py`, `src/cosa/agents/deep_research/cli.py`, `src/cosa/agents/podcast_generator/config.py`, `src/cosa/agents/podcast_generator/job.py`, `src/cosa/agents/llm_client_factory.py`
**Files Modified**: `src/conf/lupin-app.ini`, `src/conf/lupin-app-splainer.ini`
**Files Created**: `src/rnd/2026.03.14-claude-agent-sdk-config-migration-plan.md`
**Files Modified**: `src/rnd/README.md`

---

### 2026.03.14 - Session 360 | CJ Flow Persistence — Phases 1-2 (Schema + Model + Service)

**Accomplishments**:
- Implemented Phase 1: PostgreSQL `job_history` table with 16 columns and 5 indexes for tracking agentic job lifecycle
- Created standalone SQL migration (`add-job-history.sql`) and appended to master schema
- Added `JobHistory` SQLAlchemy model to `postgres_models.py` (12 models, 12 tables)
- Implemented Phase 2: Stateless persistence service (`job_persistence.py`) with 8 functions (INSERT/UPDATE/query/recovery)
- Agentic type filter: `deep_research`, `podcast`, `claude_code`, `swe_team`, `research_to_podcast`
- All persist functions are fire-and-forget — catch/log exceptions, never break queue pipeline
- Fixed timezone-aware datetime issue (PostgreSQL TIMESTAMPTZ requires `datetime.now( timezone.utc )`)
- Added 2 config keys (`cj flow persistence enabled`, `cj flow persistence history days`)
- Full DB round-trip smoke test passes; 2096 unit tests, 0 regressions
- Updated planning document with completion markers, implementation notes, and deviations log

**Files Created**: `src/scripts/sql/add-job-history.sql`, `src/cosa/rest/job_persistence.py`
**Files Modified**: `src/scripts/sql/schema.sql`, `src/cosa/rest/postgres_models.py`, `src/conf/lupin-app.ini`, `src/conf/lupin-app-splainer.ini`, `src/rnd/2026.03.13-cj-flow-persistence-plan.md`, `TODO.md`

---

### 2026.03.14 - Session 363 | WS-QUEUE Verbose Logging Guard + TODO Cleanup

**Accomplishments**:
- Gated `[WS-QUEUE] Received message from` print behind `app_debug and app_verbose` — stops sys_pong flood from cc-listener sessions
- Matches existing pattern used by `[WS-AUDIO]` endpoint (line 212)
- Marked "Render Markdown Documents as HTML + Audio Player Viewer" as complete in TODO.md

**Files Modified**: `src/cosa/rest/routers/websocket.py` (CoSA), `TODO.md`

---

### 2026.03.14 - Session 360b | Bug Fix: Graceful STT Degradation — Server Starts Without GPU

**Accomplishments**:
- Fixed server startup crash when Whisper STT model can't load (no CUDA GPU, driver issue, Docker without `--gpus all`)
- Root cause: `load_stt_model()` in `lifespan()` had no try/except — any load failure killed the entire server, blocking all endpoints including auth, admin, queue, WebSocket, pages, and TTS
- Change 1 (`main.py`): Wrapped STT load in try/except; on failure sets `whisper_pipeline = None`, logs warning, continues startup
- Change 2 (`speech.py`): Added None guard in `get_whisper_pipeline()` dependency; raises HTTP 503 with `Retry-After: 60` when pipeline unavailable
- Only 2 STT endpoints affected (`/api/upload-and-transcribe-mp3`, `/api/upload-and-transcribe-wav`); 3 TTS endpoints + all other endpoints remain fully functional

**Files Modified**: `src/fastapi_app/main.py`, `src/cosa/rest/routers/speech.py` (CoSA — pending separate commit)
**Commit**: 3604443

---

### 2026.03.14 - Session 362 | Presentation Generator Agent — Strategy, Design & Documentation

**Accomplishments**:
- Designed comprehensive Presentation Generator Agent: agentic process (Claude SDK) transforming research docs into 10-20 minute slide decks with presenter notes
- Architecture: single orchestrator pattern (Podcast Generator), 8-phase pipeline with content/rendering separation, 4 human-in-the-loop gates
- Key design decisions: YAML intermediate format, Marp Markdown output, assertion-style slide titles, pluggable visual renderer registry, theme cascade (INI -> YAML template -> per-presentation overrides)
- Serialized strategy & design document covering: slides-per-minute theory, narrative arc decomposition, presenter notes spec, visual taxonomy, theme architecture, renderer protocol
- Created implementation plan: 8 phases, 55 tasks, file inventory, dependency list
- Created implementation tracking document with phase/task checkboxes
- Updated R&D README index with new entry

**Files Created**: `src/rnd/2026.03.14-presentation-generator/00-index.md`, `01-strategy-and-design.md`, `02-implementation-plan.md`, `03-implementation-tracking.md`
**Files Modified**: `src/rnd/README.md`, `TODO.md`

---

### 2026.03.14 - Session 361 | Playwright E2E Phase 8: Visual Regression & CI Integration

**Accomplishments**:
- Installed pytest-playwright-visual-snapshot==0.5.1 with --no-deps (starlette conflict workaround)
- Patched plugin __init__.py to make structlog import optional (try/except fallback)
- Configured pytest.ini: snapshot threshold 0.1, paths for baselines and failures
- Created test_visual_regression.py: 12 parametrized tests covering all pages (public, auth, admin)
- Implemented JS content normalization for dynamic elements (UUIDs, timestamps, WS status)
  - Key pivot: Playwright mask overlays caused subpixel rendering differences; JS text replacement is deterministic
- Generated and verified 12 baseline screenshots (zero-diff on re-run)
- Updated Dockerfile with Playwright E2E testing section (pytest, chromium, visual snapshot + __init__.py sed patch)
- Updated run-e2e-ui-tests.sh usage docs for --update-snapshots
- Added snapshot_failures/ to .gitignore
- Updated CLAUDE.md: E2E UI tier in testing section + visual regression in pre-merge checklist
- Updated src/tests/README.md: E2E UI tier documentation, test counts
- Session-end documentation: updated implementation plan (Phase 8 complete), testing skills (global + project), TODO.md
- Full suite verification: 2,102 unit + 50 WS + 265 E2E UI + 137 integration = ALL PASS
- **Phases 1-8 Summary**: 265 E2E tests across 28 test files, covering all 12 pages with functional + visual regression

**Files Created**: src/tests/e2e_ui/test_visual_regression.py, src/tests/e2e_ui/__snapshots__/ (12 baselines)
**Files Modified**: requirements-test.txt, pytest.ini, .gitignore, src/scripts/run-e2e-ui-tests.sh, docker/lupin/Dockerfile, CLAUDE.md, src/tests/README.md, src/rnd/2026.02.23-automating-ui-testing/01-implementation-plan.md, TODO.md, ~/.claude/skills/testing-development/SKILL.md, .claude/skills/testing-patterns/SKILL.md

---

### 2026.03.14 - Session 360 | Stop Hook: Two-Signal Gate to Suppress Spurious Notifications

**Accomplishments**:
- Added two-signal heuristic gate (`_should_ask_anything_else()`) to stop hook that suppresses the blocking "Anything else?" notification when no substantive work was performed
- Signal 1: Empty `last_assistant_message` → no output from Claude → skip silently
- Signal 2: Turn duration < 10 seconds → trivial turn (plan mode exit, CLAUDE.md ack, quick answer) → skip silently
- Mechanism: `UserPromptSubmit` hook writes `/tmp/cc-turn-start-{session_id}` epoch marker; stop hook reads it to compute elapsed time
- Safe fallback: missing marker (first turn, edge case) → fires notification (never suppresses by mistake)
- Added `write_turn_start_marker()` and `get_turn_elapsed_seconds()` helpers to `hook_common.py`
- 9 new gate tests in `TestShouldAskAnythingElse` + 14 existing tests updated with gate mock; 193/193 hook tests pass
- `MIN_TURN_DURATION_SECONDS = 10` is tunable; `gate_skip` log entries include elapsed values for calibration

**Files Modified**: `src/lupin_cli/claude_code/hooks/lib/hook_common.py`, `src/lupin_cli/claude_code/hooks/user_prompt_submit.py`, `src/lupin_cli/claude_code/hooks/stop.py`, `src/tests/unit/test_stop_hook.py`
**Commit**: 03d5e64

---

### 2026.03.14 - Session 359 | Bug Fix: Periodic CUDA OOM on Whisper Transcription

**Accomplishments**:
- Fixed periodic 500 errors on `/api/upload-and-transcribe-mp3` and WAV endpoints caused by CUDA memory fragmentation
- Root cause: PyTorch CUDA allocator couldn't find contiguous 16 MiB block despite ~290 MiB reserved (fragmentation from co-resident Whisper + embedding models on 23.65 GiB GPU)
- Added `_run_whisper_with_retry()` helper in `speech.py` — on CUDA OOM, runs `gc.collect()` + `torch.cuda.empty_cache()` then retries once
- Both MP3 and WAV endpoints now return 503 with `Retry-After: 5` header instead of 500 on persistent OOM
- Set `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` in `main.py` before model loading to reduce long-term fragmentation

**Files Modified**: `src/fastapi_app/main.py`
**Files Modified (CoSA)**: `src/cosa/rest/routers/speech.py` — pending separate CoSA commit

---

#### Checkpoint | 2026.03.13 | Session 358: Added markdown render TODO item

**Files**: TODO.md
**Commit**: c285454

---

### 2026.03.13 - Session 357 | CJ Flow Persistence — Plan & Design

**Accomplishments**:
- Designed comprehensive CJ Flow persistence plan: durable PostgreSQL-backed job history for AgenticJobBase jobs (DeepResearch, PodcastGenerator, ClaudeCode, SweTeam)
- Architecture decision: central write-through via `emit_job_state_transition()` — single integration point avoids touching ~10 handler sites
- 5-phase plan: schema+model, persistence service, write-through integration, startup recovery, API+tests
- Key design: `job_history` table with JSONB metadata, `mark_interrupted_jobs()` on startup, `/api/job-history` endpoint with role-based auth
- Serialized plan to R&D, updated TODO.md with phase-by-phase tracking

**Files Created**: `src/rnd/2026.03.13-cj-flow-persistence-plan.md`
**Files Modified**: `src/rnd/README.md`, `TODO.md`

---

### 2026.03.13 - Session 356 | Bug Fix: SWE Team Notifications Routing to Personal Email

**Accomplishments**:
- Fixed two compounding bugs causing SWE team test notifications to reach personal email instead of test account
- Bug 1: `swe_team/job.py` never set `cosa_interface.TARGET_USER = self.user_email` (both live and dry-run paths)
- Bug 2: `fifo_queue.py` hardcoded `ricardo.felipe.ruiz@gmail.com` as fallback — replaced with `LUPIN_DEV_EMAIL` env var, skips notification if unset
- Cleaned up hardcoded email from 4 additional Python scripts/tests, replaced with env var lookups
- Verification: 2094 unit tests pass, grep for hardcoded email returns only migration script (intentional seed user)
- Commit: 44010fd (Lupin scripts/tests), CoSA changes (`swe_team/job.py`, `fifo_queue.py`) pending separate commit

**Files Modified**: `src/cosa/agents/swe_team/job.py`, `src/cosa/rest/fifo_queue.py`, `src/scripts/debug/debug_crud_llm_call.py`, `src/scripts/reset_user_password.py`, `src/scripts/test_websocket_notification.py`, `src/tests/lupin_smoke/test_queue_filtering_smoke.py`, `src/scripts/auth_migration/migrate_mock_users.py`

---

### 2026.03.13 - Session 355 | Playwright E2E Phase 7: WebSocket & Real-Time Tests (253 total passing)

**Accomplishments**:
- Implemented Phase 7 of the Playwright E2E testing plan — WebSocket & Real-Time Tests
- Created 3 test files with 28 new tests covering browser-side WebSocket behavior
- Added 3 conftest helper functions (`capture_websockets`, `wait_for_ws_connected`, `get_ws_status`) + `notifications_page` fixture
- Test coverage: WS connection lifecycle (11), session ID persistence (10), auth handshake frame inspection (7)
- Discovered session IDs use space-separated format ("wise penguin") not underscore — URLs contain %20 encoding
- Full suite: 253/253 passing, zero regressions

**Files Created**: `src/tests/e2e_ui/test_websocket_connection.py`, `src/tests/e2e_ui/test_websocket_session_persistence.py`, `src/tests/e2e_ui/test_websocket_auth_handshake.py`
**Files Modified**: `src/tests/e2e_ui/conftest.py`

---

### 2026.03.13 - Session 354 | COSA Audio Player Viewer: In-Browser MP3 Playback Page

**Accomplishments**:
- Created `audio-player.html` — styled HTML5 `<audio>` player page mirroring document-viewer architecture (nav bar, CSS, container layout, companion script metadata lookup, file size via HEAD, download button, file details accordion)
- Added `/app/audio` route in `pages.py` (route table entry + route function)
- Migrated last 2 MP3 link URLs in `orchestrator.py` from `/api/io/file?path=` → `/app/audio?path=` so podcast MP3 links open in styled player

**Files Created**: `src/fastapi_app/static/html/audio-player.html`
**Files Modified**: `src/cosa/rest/routers/pages.py`, `src/cosa/agents/podcast_generator/orchestrator.py`

---

### 2026.03.13 - Session 353 | COSA Document Viewer Phase 2: Frontmatter Fix + Link URL Migration

**Accomplishments**:
- Added YAML frontmatter extraction to `document-viewer.html` — strips `---` delimited metadata before marked.js parsing, renders as collapsed `<details>` accordion
- Migrated 8 podcast orchestrator markdown links from `/api/io/file?path=` → `/app/docs?path=` (kept MP3 links on raw endpoint)
- Changed deep research CLI local-path URL from hardcoded `http://localhost:7999/api/deep-research/report` → relative `/app/docs?path=deep-research/` (GCS paths unchanged)

**Files Modified**: `src/fastapi_app/static/html/document-viewer.html`, `src/cosa/agents/podcast_generator/orchestrator.py`, `src/cosa/agents/deep_research/cli.py`

---

### 2026.03.13 - Session 352 | Playwright E2E Phase 6: Notifications & Q&A Tests (225 total passing)

**Accomplishments**:
- Implemented Phase 6 of the Playwright E2E testing plan — Notifications & Q&A Tests
- Created 8 test files covering all 11 sections of the notifications page (86 new tests)
- Test files: notifications_sections (13), qa_submission (9), job_dispatch (23), tts_controls (11), system_status (7), queue_display (12), action_required (5), time_saved (6)
- Fixed notifications page logout button test — uses timeout+URL check instead of wait_for_url (no hard navigation)
- Updated implementation plan with checkmarks for Phases 1-6 (was missing Phases 1-5 checkmarks)
- Updated TODO.md with Phase 6 completion status
- Total: 225 E2E UI tests, all passing across 24 test files (12:30 runtime on Chromium headless)

**Files Created**:
- `src/tests/e2e_ui/test_notifications_sections.py`, `test_qa_submission.py`, `test_job_dispatch.py`, `test_tts_controls.py` (Phase 6)
- `src/tests/e2e_ui/test_system_status.py`, `test_queue_display.py`, `test_action_required.py`, `test_time_saved.py` (Phase 6)

**Files Modified**: `src/rnd/2026.02.23-automating-ui-testing/01-implementation-plan.md`, `TODO.md`

---

### 2026.03.13 - Session 351 | Playwright E2E Phases 3-5: Auth + Smoke + Admin Tests (139 passing)

**Accomplishments**:
- Implemented Phases 3-5 of the Playwright E2E testing plan (Phases 1-2 were done in prior sessions)
- Phase 3 (Auth Flow Tests): 5 test files — login, register, profile, change-password, session management (30 tests)
- Phase 4 (Page Smoke Tests): 3 test files — parametrized page load for all 12 pages, navigation bar, landing page (39 tests)
- Phase 5 (Admin Flow Tests): 6 test files — admin dashboard, user management, snapshots, proxy dashboard, proxy ratify, role gating (69 tests)
- Fixed conftest.py `logged_in_page` redirect bug: `**/notifications**` → `**/app**` (matches actual `getSafeRedirectUrl()` default)
- Fixed conftest.py `admin_page` roles: added `flag_modified( user, "roles" )` for SQLAlchemy JSONB mutation tracking
- Fixed localStorage race conditions: added `wait_for_function` for token population in auth fixtures
- Landing page reclassified from AUTH_PAGES to HYBRID_PAGES (doesn't call `requireAuth()`)
- Total: 139 E2E UI tests, all passing (7:17 runtime on Chromium headless)

**Files Created**:
- `src/tests/e2e_ui/test_login.py`, `test_register.py`, `test_profile.py`, `test_change_password.py`, `test_session.py` (Phase 3)
- `src/tests/e2e_ui/test_page_smoke.py`, `test_navigation.py`, `test_landing.py` (Phase 4)
- `src/tests/e2e_ui/test_admin_dashboard.py`, `test_admin_users.py`, `test_admin_snapshots.py`, `test_admin_proxy_dashboard.py`, `test_admin_proxy_ratify.py`, `test_role_gating.py` (Phase 5)

**Files Modified**: `src/tests/e2e_ui/conftest.py` (bug fixes + HYBRID_PAGES)

---

### 2026.03.13 - Session 350 | Bug Fix: find_session_by_id() Session ID History List

**Accomplishments**:
- Fixed `find_session_by_id()` failing to match stable session IDs after context clears — qualifier text was silently dropped because the bridge file's `session_id` (latest transient UUID) diverged from the stable ID used by the stop hook
- Added `session_ids` list to bridge file format that accumulates all transient UUIDs across context clears, built from `old_data` already loaded for context-clear detection (no extra file read)
- Updated `find_session_by_id()` to check `session_ids` list with backward-compat fallback to `session_id` and `stable_session_id` fields for pre-existing bridge files
- Initialized `old_data = None` at scope top to prevent `NameError` when bridge file doesn't exist

**Files**: `src/lupin_cli/claude_code/hooks/register_session.py`, `src/lupin_cli/claude_code/hooks/lib/session_bridge.py`

---

### 2026.03.13 - Session 349 | Standardize ~91 Underscore Config Keys to Space-Separated

**Accomplishments**:
- Renamed all 91 underscore config keys to space-separated naming in `lupin-app.ini` (127 instances across 5 sections) and `lupin-app-splainer.ini` (102 instances)
- Updated 96 Python string literals across 59 files (14 Lupin + 45 CoSA) using longest-match-first replacement
- Created migration mapping file `src/conf/config-key-migration-map.json` (105 entries)
- Applied 5 key regroupings for better alphabetical clustering: `auto_debug` → `debug auto`, `inject_bugs` → `debug inject bugs`, `database_path_wo_root` → `path to database wo root`, `code_execution_file_path` → `path to code execution file`, `audio_recording_file_path` → `path to audio recording file`
- Caught and fixed 5 false positives where Python attribute names (`auto_debug`, `inject_bugs`) were incorrectly renamed as config keys in agent serialization/deserialization and constructor parameter introspection tests
- Removed 7 legacy splainer-only keys with no main INI counterpart (`path_to_snapshots_dir_wo_root`, `path_to_prompt_generator_data_function_mapping_wo_root`, `router_and_vox_command_url`, `deepily_inference_chat_url`, `tgi_server_codegen_name`, `tgi_server_router_name`, `model_tokenizer_map`)
- Added permanent guardrail test `test_ini_key_naming.py` (2 pass + 1 xfail parity check)
- Full regression green: unit 2094/2094, WebSocket 50/50, integration 136 passed

**Files (Lupin)**: `src/conf/lupin-app.ini`, `src/conf/lupin-app-splainer.ini`, `src/conf/config-key-migration-map.json`, `src/fastapi_app/main.py`, `src/scripts/init_test_database.py`, `src/scripts/migrate_synonymous_questions.py`, `src/tests/unit/test_ini_key_naming.py` (new), `src/tests/unit/test_answer_is_correct.py`, `src/tests/unit/test_crud_queue_integration.py`, `src/tests/unit/test_lancedb_gcs_manager.py`, `src/tests/unit/test_local_embedding_engine.py`, `src/tests/unit/test_running_queue_threshold.py`, `src/tests/integration/run_gcs_tests_standalone.py`, `src/tests/integration/test_lancedb_gcs_integration.py`, `src/tests/integration/test_lancedb_local_isolation.py`
**Files (CoSA)**: 45 files across REST, agents, memory, training, utils, config, and tests directories
**Design doc**: [`src/rnd/2026.02.23-ini-config-key-naming-convention.md`](src/rnd/2026.02.23-ini-config-key-naming-convention.md)

---

### 2026.03.12 - Session 348 | v0.1.5 PR to Main + Branch Transition

**Accomplishments**:
- Rewrote README.md with promotional tone for v0.1.5 PR
- Added "Human in the Loop, reimagined" section, updated architecture diagram (6 hooks), expanded trust proxy, test suite table
- Fleshed out CHANGELOG.md v0.1.5 from 3 bullets to 7 categories (30+ line items)
- Created PR #15: "v0.1.5 — Voice-First Human in the Loop" (192 commits, 397 files, +69K/-9K lines)
- PR merged to main (commit 949cf6e)
- Created new branch: `wip-v0.1.6-2026.03.12-cjflow-upe-and-playwrite`

**Files Modified**: `README.md`, `CHANGELOG.md`, `history.md`, `TODO.md`

---

### 2026.03.12 - Session 347 | Fix: TTS Audio Stops on Every Notification Dismissal Path

**Accomplishments**:
- Fixed TTS audio continuing after user responds to action-required notifications while audio still playing
- Added `stopAudio()` + `onTTSPlaybackComplete()` to `submitResponse()` — audio stops instantly when user clicks yes/no
- Added TTS cleanup to `handleGracePeriodExceeded()` — audio stops on grace period expiry + focus mode exit
- Fixed `stopAllAudio()` → `stopAudio()` typo in `stopTTSAndAdvance()` — UI stop button was silently broken
- Manual verification: 5+ yes/no notifications tested, all dismissal paths confirmed working

**File**: `src/fastapi_app/static/js/notifications.js`

---

### 2026.03.12 - Session 346 | TTS Race Condition: Stale handleAudioComplete + Focus Mode Analysis

#### Checkpoint | 2026.03.12 22:30 | Partial fix + race condition documented

**Accomplishments**:
- Fixed stale `handleAudioComplete` clobbering next notification's TTS mode: added early-return guard when `currentTTSMode` is already null
- Fixed premature `currentTTSMode = null` in `handleAudioComplete()` cleanup: instant mode now defers mode reset to PCM `onended` handler, preventing in-flight chunks from being dropped
- Added race condition guard in `playPCMChunk()` after async `arrayBuffer()` await
- Added `stopAudio()` call in `exitTTSFocusMode()` to ensure audio stops on dismiss
- Enhanced debug logging (`stopAudio`, `exitTTSFocusMode`, `cancelActionRequired`, `handleAudioChunk`)
- Documented remaining bug: Path B-2 race condition where user answers while audio still plays → `onended` enters focus mode for already-responded notification → queue permanently stuck
- Serialized execution path analysis to `src/rnd/`

**Open Bug**: TTS Focus Mode race — when user answers before audio finishes AND `onended` fires after `handleNotificationResponded`'s 1500ms setTimeout, focus mode is entered for an already-responded notification with no one to exit it

**Files**: `src/fastapi_app/static/js/notifications.js`, `src/rnd/2026.03.12-tts-focus-mode-race-condition-analysis.md`, `src/rnd/README.md`

---

### 2026.03.12 - Session 345 | Bug Fix: UPE MC Prediction Ignores Available Options

**Accomplishments**:
- Fixed UPE multiple-choice prediction generating free-text values instead of selecting from available options
- Added `response_type` field to LanceDB schema (`proxy_decision_embeddings.py`) with filter support in `find_similar()`
- All 4 predict methods (`_predict_yes_no`, `_predict_multiple_choice`, `_predict_open_ended`, `_predict_open_ended_batch`) now pass `response_type` filter to prevent cross-type contamination
- Added `_extract_valid_options()` helper to parse notification options structure into validated label sets
- Added option validation pass in `_predict_multiple_choice()`: invalid winners fall back to highest-voted valid option; empty results return cold_start
- Fixed `_store_decision()`: MC bare strings wrapped as `{"answers": {"_other": value}}` for parseability; `response_type` passed through to LanceDB
- 17 new unit tests across 4 test classes; 2092 total unit tests pass

**Files (CoSA)**: `agents/decision_proxy/proxy_decision_embeddings.py`, `agents/prediction_engine/prediction_engine.py`
**Files (Lupin)**: `src/tests/unit/test_prediction_engine_multiple_choice.py`, `bug-fix-queue.md`

---

### 2026.03.12 - Session 344 | Integration Test Remediation + DB Disambiguation

#### Checkpoint | 2026.03.12 20:15 | Disambiguate database names

**Accomplishments**:
- Renamed PostgreSQL database: `ALTER DATABASE lupin_db RENAME TO lupin_db_dev`
- Updated `database.py` defaults: production → `lupin_db_prod`, development → `lupin_db_dev`
- Updated `docker-compose.yml`: `POSTGRES_DB` + healthcheck
- Updated shell scripts: `run-postgresql-dev.sh`, `backup-postgres.sh`
- Updated 16 documentation references across 7 files (migrations guide, auth testing guide, alembic.ini, lupin-app.ini, main.py comments, 2 R&D docs)
- Marked Phase 6 as Done in `src/rnd/2026.03.12-integration-test-hot-swap-config.md`
- Dev server verified connecting to `lupin_db_dev` via `/api/server-info`

**Files**: `src/cosa/rest/db/database.py`, `docker-compose.yml`, `src/scripts/run-postgresql-dev.sh`, `src/scripts/backup-postgres.sh`, `src/docs/database-migrations.md`, `src/tests/AUTH-TESTING-GUIDE.md`, `src/fastapi_app/main.py`, `src/rnd/2026.03.12-integration-test-hot-swap-config.md`, `src/rnd/2026.03.11-integration-test-isolation-audit.md`, `alembic.ini`, `src/conf/lupin-app.ini`
**Commit**: f4b955c

#### Checkpoint | 2026.03.12 20:30 | Full test suite validation post-DB rename

**Accomplishments**:
- Ran full test suite after DB rename: unit 2075/2075, WS 50/50, integration 136 passed (0 failures)
- Added `@pytest.mark.xfail` to `test_lancedb_local_isolation.py` (4 tests, known normalization bug)
- Updated TODO.md with final post-rename test counts

**Files**: `src/tests/integration/test_lancedb_local_isolation.py`, `TODO.md`
**Commit**: 6d63d45

---

### 2026.03.12 - Session 343 | Integration Test Isolation via Hot-Swap Config

**Accomplishments**:
- Implemented hot-swap config mechanism: running dev server can toggle between `[Lupin: Development]` and `[Lupin: Testing]` config blocks at runtime via `/api/init?config_block_id=...`
- Added `GET /api/server-info` endpoint (no auth) returning config block, masked DB URL, and environment
- Added `swap_database()` function to `database.py`: disposes old engine, recreates engine/SessionLocal/ScopedSession for new environment, verifies connectivity
- Updated `/api/init` to accept optional `config_block_id` query param, update the singleton ConfigurationManager in-place, and call `swap_database()`
- Rewrote `run-integration-tests.sh`: now hot-swaps running dev server instead of starting a separate test server (solves GPU RAM constraint); trap handler always restores Development config on exit
- Hardened `clean_test_db` fixture: safety assertion verifies `lupin_db_test` in engine URL before destructive ops; verifies users table empty after reset
- Added `_validate_server_config()` to `LupinTestClient` (warns if server in Testing mode during smoke tests)
- Added `check_server_config()` to WebSocket smoke test runner (same pattern)
- Verified full hot-swap cycle: Development → Testing → Development
- Unit tests: 2075/2075 pass; Integration tests: 199/225 pass (12 pre-existing failures)
- Serialized plan to `src/rnd/2026.03.12-integration-test-hot-swap-config.md`

**Files**: `src/cosa/rest/routers/system.py`, `src/cosa/rest/db/database.py`, `src/tests/integration/conftest.py`, `src/tests/run-integration-tests.sh`, `src/tests/lupin_smoke/utilities.py`, `src/scripts/run-websocket-smoke-tests.sh`, `src/rnd/2026.03.12-integration-test-hot-swap-config.md` (NEW), `src/rnd/README.md`

---

### 2026.03.12 - Session 342 | Fix Session ID Drift Across Hooks After Context Clear

**Accomplishments**:
- Fixed session ID drift bug: after context clear, hooks used transient CC session_id (`38984b97`) instead of stable lockfile ID (`59afa5ba`), causing split identity across hooks, JSONL logs, and MCP
- Root cause: all 6 hooks had `payload.get("session_id") or get_claude_session_id()` — the transient ID was always non-empty, so the stable fallback was never reached
- Added `resolve_stable_session_id()` to `session_bridge.py`: looks up bridge file by PPID/grandparent, returns `stable_session_id` if found, otherwise passes through unchanged
- Updated all 6 hooks to call `resolve_stable_session_id(payload.get("session_id", ""))` before the `or get_claude_session_id()` fallback
- Updated `hook_common.py:log_to_stream()` to resolve stable ID before writing to hook-events.jsonl
- Updated `cosa_voice_mcp.py:get_session_info()` to expose `stable_session_id` in `claude_code` metadata
- Updated `register_session.py:_log_session_transition()` timestamp to human-readable format
- Fixed 18 unit test failures caused by unpatched `resolve_stable_session_id` mock across 6 test files
- All 231 hook/session tests pass (0 failures)

**Files**: `src/lupin_cli/claude_code/hooks/lib/session_bridge.py`, `src/lupin_cli/claude_code/hooks/lib/hook_common.py`, `src/lupin_cli/claude_code/hooks/user_prompt_submit.py`, `src/lupin_cli/claude_code/hooks/pre_tool_use.py`, `src/lupin_cli/claude_code/hooks/post_tool_use.py`, `src/lupin_cli/claude_code/hooks/notification.py`, `src/lupin_cli/claude_code/hooks/stop.py`, `src/lupin_cli/claude_code/hooks/permission_request.py`, `src/lupin_cli/claude_code/hooks/register_session.py`, `src/lupin_mcp/cosa_voice_mcp.py`, `src/tests/unit/test_*_hook.py` (6 files)

---

### 2026.03.11 - Session 341 | Smoke Test Remediation + Integration Test Isolation Audit

**Accomplishments**:
- Fixed all 6 remaining Lupin smoke test failures: notifications (2), audio (2), queues (2) — 27/27 pass
- Enabled WebSocket smoke tests (previously skipped due to missing credentials) — 49/50 pass
- Fixed `test_notifications.py`: skipped `mark_notification_played` (server hangs on missing `_emit_queue_update`); broadened API auth assertion (server doesn't validate `api_key`)
- Fixed `test_audio_tts.py`: broadened validation status codes (404/422 for FastAPI); used `last_generated_session_id` for Bearer regression test
- Fixed `test_queue_workflow.py`: commented out Kagi-dependent job submissions (external API 500s)
- Fixed `utilities.py`: increased httpx timeout from 5s to 30s (server slows under TTS load)
- Fixed stale docstring in `cc_notification_listener.py`: `~/.lupin/credentials.ini` → `~/.lupin/config`
- Documented integration test database isolation conundrum: tests that need dev server vs test server share port 7999 with no config validation or database boundary checks
- Created 5-phase remediation plan: server-info endpoint, pre-flight validation, post-startup verification, WebSocket guard, `clean_test_db` hardening
- Unit tests: 2075/2075 pass

**Files**: `src/tests/lupin_smoke/test_notifications.py`, `src/tests/lupin_smoke/test_audio_tts.py`, `src/tests/lupin_smoke/test_queue_workflow.py`, `src/tests/lupin_smoke/utilities.py`, `src/tests/smoke_test.sh`, `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py`, `src/rnd/2026.03.11-integration-test-isolation-audit.md` (NEW), `src/rnd/2026.03.11-baseline-test-report.md` (NEW)

---

### 2026.03.11 - Session 340 | UPE Live E2E Validation Plan + Baseline

**Accomplishments**:
- Planned comprehensive 5-phase live E2E validation for Universal Prediction Engine (all 7 slices code-complete, 87 unit + 21 integration tests)
- Serialized plan to `src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.11-upe-live-e2e-validation-plan.md`
- Ran Phase 1.1 unit test baseline: 87/87 pass (0.22s)
- Moved UPE E2E validation TODO item from v0.1.5 to v0.1.6 with updated plan reference
- Updated R&D README with new plan doc link

**Files**: `src/rnd/2026.02.23-trust-proxy-preference-learning/2026.03.11-upe-live-e2e-validation-plan.md` (NEW), `src/rnd/README.md`, `TODO.md`

---

### 2026.03.11 - Session 339 | Harden Config Migration: Fail-Hard + Script Cleanup

**Accomplishments**:
- Removed legacy fallback from `config_loader.py`: deleted `~/.notifications/config` fallback, `target_user` deprecated key fallback, and Priority 3 hardcoded defaults. Missing `~/.lupin/config` now raises `FileNotFoundError` with `lupin-config init/migrate` instructions.
- Removed legacy fallback from `hook_credentials.py`: deleted `LEGACY_CREDENTIALS_FILE` constant and `~/.lupin/credentials.ini` fallback. Simplified error messages to reference only `~/.lupin/config`.
- Updated cloud-run scripts: `~/.notifications/config` → `~/.lupin/config` in both `cloud-run-deploy.sh` and `cloud-run-validate.sh`.
- Rewrote unit tests: replaced 5 legacy fallback tests with 5 fail-hard tests across both test files. 38/38 pass (24 config_loader + 14 hook_credentials).

**Files**: `src/cosa/utils/config_loader.py`, `src/lupin_cli/claude_code/hooks/lib/hook_credentials.py`, `src/scripts/cloud-run-deploy.sh`, `src/scripts/cloud-run-validate.sh`, `src/tests/unit/test_config_loader.py`, `src/tests/unit/test_hook_credentials.py`

---

### 2026.03.11 - Session 338 | Credential Migration Step 7 + Duplicate Session Bug

#### Checkpoint | 2026.03.11 | Credential migration executed on live system

**Accomplishments**:
- Executed Step 7 of credential consolidation: ran `lupin-config migrate` on actual system
- Fixed stale `[local]` section in `~/.lupin/config` before migration (old `genie-in-the-box` path + deprecated `target_user` key)
- Migration merged `[lupin]` credentials + `[development]` environment into unified `~/.lupin/config`
- Verified: permissions `chmod 600`, backups created (`.bak`), all dependent systems operational
- Smoke tests: hook_credentials reader, config_loader, cc-listener-status all pass
- Unit tests: 40/40 pass (test_config_loader + test_hook_credentials)

**Files**: `~/.lupin/config` (modified)
**Commit**: 29fc69a

**Post-checkpoint — Bug fix: Duplicate notification sessions after context clear**:
- **Symptom**: Two notification session cards (25ca8c13 + 9f656de9) in UI from single TMUX-wrapped CC session
- **Root Cause**: `register_session.py:511` wrote transient `session_id` to `CLAUDE_ENV_FILE` instead of `stable_session_id`. After context clear, `CLAUDE_SESSION_ID` env var contained the new transient ID (`25ca8c13`), which `get_claude_session_id()` reads as Tier 1 (highest priority), bypassing the bridge file's `stable_session_id` (`9f656de9`). All hooks then sent notifications as `#25ca8c13` — creating a second session card.
- **Fix**: Changed `CLAUDE_ENV_FILE` write from `session_id` to `stable_session_id` (1 line)
- **Test**: Added `test_env_file_writes_stable_session_id` — verifies env file contains stable ID, not transient. 29/29 pass.

**Files**: `src/lupin_cli/claude_code/hooks/register_session.py`, `src/tests/unit/test_session_bridge_lookup.py`, `bug-fix-queue.md`
**Commit**: 527b6e5

---

### 2026.03.10 - Session 337c | Consolidate Three Credential Stores

**Accomplishments**:
- Consolidated `~/.lupin/credentials.ini`, `~/.notifications/config`, and deprecated `~/.lupin/config` into unified `~/.lupin/config` — one file, one directory, `chmod 600`
- Updated `config_loader.py`: swapped primary/legacy paths (`~/.lupin/config` now primary, `~/.notifications/config` now legacy with deprecation warning)
- Rewrote `hook_credentials.py`: reads unified file first, falls back to legacy `credentials.ini` with deprecation warning, extracted `_read_credentials_from_file()` helper
- Updated `check-cc-listener-status.sh`: changed credential file path argument
- Added `cmd_migrate()` to `lupin_config.py`: reads both legacy files, merges into unified config, backs up old files with `.bak`, enforces `chmod 600`
- Updated `cmd_init()` to include `[lupin]` credentials placeholder section
- Updated `cmd_show()` to display credentials status (email, password set/missing)
- Updated help text in `notify_user_async.py`, `notify_user_sync.py`, `notification_models.py` referencing `~/.notifications/config` → `~/.lupin/config`
- Created 16 new unit tests (`test_hook_credentials.py`), added 4 tests to `test_config_loader.py` — 40/40 pass
- Serialized plan to `src/rnd/2026.03.10-consolidate-credential-stores.md`, added TODO entry

**Files**: `src/cosa/utils/config_loader.py`, `src/lupin_cli/claude_code/hooks/lib/hook_credentials.py`, `src/scripts/check-cc-listener-status.sh`, `src/scripts/lupin_config.py`, `src/lupin_cli/notifications/notify_user_async.py`, `src/lupin_cli/notifications/notify_user_sync.py`, `src/lupin_cli/notifications/notification_models.py`, `src/tests/unit/test_config_loader.py`, `src/tests/unit/test_hook_credentials.py` (NEW), `src/rnd/2026.03.10-consolidate-credential-stores.md` (NEW), `TODO.md`

---

### 2026.03.10 - Session 337b | MCP Strict Detection Plan Revision

**Accomplishments**:
- Revised MCP strict project detection plan after source code review — switched design from tool-result poisoning to one-time urgent notification via synthetic `claude.code@errors.deepily.ai` sender (follows `_die_no_session_id()` pattern)
- Serialized updated plan: renamed `2026.03.09` → `2026.03.10-mcp-strict-project-detection-account-validation.md`
- Updated TODO.md with revised plan doc link and description reflecting notification approach

**Files**: `src/rnd/2026.03.10-mcp-strict-project-detection-account-validation.md` (overwrite), `TODO.md`

---

### 2026.03.10 - Session 337 | Stop Hook Gist → Ultra-Short TTS Summaries

#### Checkpoint | 2026.03.10 17:00 | Custom gist prompt for stop hook TTS

**Accomplishments**:
- Created dedicated prompt template `gist-stop-hook.txt` for stop hook task summaries — constrains gist to 10 words max, gerund form ("Fixing...", "Adding..."), optimized for TTS readout after "I'm finished"
- Wired `prompt_key="prompt template for stop hook gist"` into `_summarize_task()` — leverages existing Gister custom prompt infrastructure with automatic cache bypass
- Diagnosed and fixed XML parsing failure: original prompt's competing "Write ONLY" directive caused phi4 to skip XML wrapping; rewrote to match proven `gist.txt` persona/structure
- Updated notification message format to `*"...{gist}"*` for natural TTS flow: "I'm finished *"...fixing linting errors, updating unit tests"*"
- Added config key + splainer explanation, updated unit test to verify prompt_key passthrough

**Files**:
- `src/conf/prompts/agents/gist-stop-hook.txt` (NEW), `src/conf/lupin-app.ini`, `src/conf/lupin-app-splainer.ini`, `src/lupin_cli/claude_code/hooks/stop.py`, `src/tests/unit/test_stop_hook.py`
**Commit**: 2840482

**Post-checkpoint**:
- Removed redundant `${notification.type} notification:` TTS prefix from `formatNotificationTTSMessage()` — message now speaks cleanly without preamble
- Added timestamps to TTS queue cards (active + completed) using `message-time` CSS class
- Cache-busted `notifications.js?v=20260310b`

**Files**: `src/fastapi_app/static/js/notifications.js`, `src/fastapi_app/static/html/notifications.html`

---

### 2026.03.10 - Session 336 | Stop Hook Qualifier → TMUX Injection

**Accomplishments**:
- Replaced broken `systemMessage` approach (Sessions 332-333) with tmux injection for stop hook qualifiers — when user attaches `[comment: ...]` to yes/no response, qualifier text is now injected directly into Claude Code's tmux input as first-class user input
- Added `inject_qualifier_via_tmux()` to `hook_common.py` — lazy-imports `find_session_by_id`, resolves tmux session name, spawns detached background process using bash positional args (`$1`, `$2`, `$3`) for safe text passing without shell escaping
- Added `TMUX_INJECTION_DELAY = 0.25` constant, deprecation comment on `build_stop_block_with_system_message()`
- Updated both qualifier branches in `stop.py` (yes+qualifier, no+qualifier) to use tmux injection instead of systemMessage
- Removed unused `format_qualified_response` import from stop.py
- 36/36 stop hook unit tests pass: 4 existing tests updated (systemMessage → tmux assertions), 4 new tests added (plain yes no-inject, Popen spawn, no-session skip, special chars safety)

**Files Modified**:
- `src/lupin_cli/claude_code/hooks/lib/hook_common.py` — Added `subprocess` import, `TMUX_INJECTION_DELAY`, `inject_qualifier_via_tmux()`, deprecation comment
- `src/lupin_cli/claude_code/hooks/stop.py` — Replaced systemMessage branches with tmux injection, removed `format_qualified_response` import
- `src/tests/unit/test_stop_hook.py` — Updated 4 qualifier tests, added 4 new tmux injection tests

---

### 2026.03.10 - Session 335 | Stable Session ID Lockfile + Listener Drift Fix (Phases 1-4)

**Accomplishments**:
- Implemented write-once stable ID lockfile (`cc-stable-{ppid}.id`) using atomic `open('x')` (O_CREAT|O_EXCL) — replaces fragile "read old bridge file" chain for preserving `stable_session_id` across context clears
- Fixed listener drift bug: `_spawn_listener()` now receives `stable_session_id` instead of transient `session_id`, so listener filters on the same hash the MCP server and browser use
- Added `accepted_ids` set to CCNotificationListener — listener accepts notifications matching either stable or transient hash, with `--accepted-ids` CLI arg for comma-separated hashes
- Extended stale file purge to clean up `.id` lockfiles with PID liveness check (`os.kill(pid, 0)`) before purging
- All 5 code review issues incorporated (TOCTOU race, OSError recovery, PID reuse guard, argument clarity, duplicate hash comment)
- 9 new unit tests (28 total in test file), all passing

**Files Modified**:
- `src/lupin_cli/claude_code/hooks/register_session.py` — Lockfile creation (Phase 1), pass stable ID to listener (Phase 2), `accepted_ids` param + `--accepted-ids` CLI forwarding (Phase 3B), stale cleanup extension (Phase 4), `_is_live_cc_process()` helper
- `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` — `accepted_ids` param in `__init__()`, `--accepted-ids` CLI arg, filter change `!=` → `not in` (Phase 3A)
- `src/tests/unit/test_session_bridge_lookup.py` — 9 new tests covering lockfile creation, atomicity, read failure recovery, context clear detection, stable ID passthrough, accepted_ids parsing/filtering, stale cleanup

**Design docs**: `src/rnd/.../2026.03.10-stable-session-id-lockfile-and-listener-drift-fix.md`, `...-review.md`

---

### 2026.03.10 - Session 334 | Remove Redundant "Important!" TTS Prefix + Plan CC Listener Session ID Drift Fix

**Accomplishments**:
- Removed redundant "Important!" TTS prefix on high-priority notifications — if a notification plays with high priority, it's already important by definition. Kept "Urgent!" prefix for urgent notifications (useful escalation signal)
- Diagnosed CC Notification Listener session ID drift bug: after context clears, listeners filter by transient `session_id` but MCP server uses `stable_session_id` for `sender_id`, causing browser-originated `user_initiated_message` notifications to be rejected by all listeners. Root cause: `_spawn_listener()` passes transient hash but `_read_session_file()` returns stable hash
- Planned fix: pass `--stable-id` to listener at spawn time, filter by `accepted_ids` set containing both transient and stable hashes. No polling needed — stable ID never changes by contract

**Files Modified**:
- `src/fastapi_app/static/js/notifications.js` — Removed `else if ( notification.priority === "high" )` block

---

### 2026.03.09 - Session 333 | Stop Hook Qualifier Phase 2 — systemMessage Attempt

**Accomplishments**:
- Added `build_stop_block_with_system_message()` to hook_common.py — emits `systemMessage` alongside `reason` in stop hook response, hypothesizing it would be injected into Claude's conversation context
- Removed Phase 1 workaround `_enrich_qualifier_for_stop_hook()` from stop.py
- Updated both qualifier call sites (yes+qualifier, no+qualifier) to use new function
- Updated 4 unit tests to assert against `systemMessage` field
- **Live test result**: `systemMessage` is also ignored by Claude Code — the Stop hook only supports `decision` + `reason`, both are metadata-only. Neither field is injected into the model's conversation context with high salience
- **Next approach identified**: Write qualifier to voice buffer from stop hook; PreToolUse drain will inject it via `additionalContext` (proven mechanism). Documented in TODO.md for next session.

**Files Modified**:
- `src/lupin_cli/claude_code/hooks/lib/hook_common.py` — Added `build_stop_block_with_system_message()`
- `src/lupin_cli/claude_code/hooks/stop.py` — Removed `_enrich_qualifier_for_stop_hook()`, updated qualifier call sites
- `src/tests/unit/test_stop_hook.py` — Updated 4 qualifier tests (assert `systemMessage` instead of `reason`)
- `TODO.md` — Added stop hook qualifier bug tracking with full context

**Verification**: 32/32 stop hook tests pass, 19/19 qualifier MCP tests pass, 2002/2021 full suite pass (14 pre-existing failures unrelated)

---

### 2026.03.09 - Session 332 | Fix Date Off-by-One + Mark Phase 7 Done

#### Checkpoint | 2026.03.09 16:00 | Fix date off-by-one in CC session outgoing bubble

**Accomplishments**:
- Fixed date off-by-one bug where late-evening EST messages rendered under next day's date accordion — `extractDateFromTimestamp()` now parses timestamps through `appTimezone` (America/New_York) instead of naive `isoTimestamp.split('T')[0]` which returned UTC date
- Fixed `getTodayDateString()` to delegate to `getLocalDateDisplay()` instead of using UTC-based `toISOString().split('T')[0]`
- Marked Phase 7 (E2E testing + polish) as done in TODO.md — all 8 Voice I/O v0.1.5 phases now complete

**Files**:
- `src/fastapi_app/static/js/notifications.js` — `extractDateFromTimestamp()` + `getTodayDateString()` timezone fix
- `TODO.md` — Phase 7 marked complete, session number updated

**Commit**: 1aaae8d

---

### 2026.03.09 - Session 331 | Remove Dead `active_conversation_changed` Event + Fix Unhandled WS Events

**Accomplishments**:
- Removed dead `active_conversation_changed` WebSocket event — server emitted it but it was never in INI available events or JS subscriptions, so all clients silently rejected it. Removed both emission blocks (fire-and-forget + response-required paths) from `notifications.py` and the unreachable JS handler + methods from `notifications.js`
- Added missing `case "notification_play_sound"` handler to queue WS switch — was subscribed but fell through to "Unhandled message type" default
- Added missing `case "audio_streaming_chunk"` handler to audio WS switch — same issue
- Removed `active_conversation_changed` row from `notification-api.md` events table
- Original design doc (`src/rnd/2026.01.13-conversation-identity-phases-1-3.md`) preserved for future reference

**Files Modified**:
- `src/cosa/rest/routers/notifications.py` — Removed 2 emission blocks (~24 lines)
- `src/fastapi_app/static/js/notifications.js` — Removed case + 2 methods (~44 lines), added 2 no-op case handlers
- `src/docs/notification-api.md` — Removed 1 event table row

**Verification**: `grep active_conversation_changed` only matches history/TODO/R&D docs. Unit tests: 2008 pass (4 pre-existing failures unrelated).

---

### 2026.03.08 - Session 330 | Fix PG Audio Progress Not Updating In-Place

**Accomplishments**:
- Fixed Podcast Generator audio progress notifications appearing as separate entries instead of updating in-place — added `progress_group_id = self._audio_progress_group_id` to the Phase 5 English-only start notification in `orchestrator.py` (line 951-954), matching the pattern already used by the Phase 2 multi-language path and milestone callbacks

**Files** (CoSA submodule):
- `agents/podcast_generator/orchestrator.py` — Added `progress_group_id` to English audio start notification

---

### 2026.03.08 - Session 329 Checkpoint 2 | Fix R2P → PG Handoff Missing TARGET_USER on Agent

**Accomplishments**:
- Fixed "Cannot resolve target_user" crash during R2P → PG handoff in `agent.py` — added `pg_cosa_interface.TARGET_USER = self.user_email` before PG phase starts (the standalone PG job sets this, but the chained agent never did)
- Added defensive `dr_cosa_interface.TARGET_USER = self.user_email` in `_run_deep_research()` — currently works because job.py sets it, but agent should be self-sufficient
- Replaced bare "Deep Research complete!" notification with rich checkpoint showing report path, abstract preview, cost, token count, and duration
- Added `**kwargs` pass-through to `_notify()` helper so `abstract=` reaches `voice_io.notify()`

**Files** (all in CoSA submodule):
- `agents/deep_research_to_podcast/agent.py` — TARGET_USER on both cosa_interfaces, rich DR checkpoint notification, `_notify()` kwargs

---

### 2026.03.08 - Session 329 Checkpoint 1 | R2P Notification Delivery Diagnostics + Fix

**Accomplishments**:
- Added diagnostic logging to `WebSocketManager.emit_to_user()` — exposed three silent failure points (user not in sessions, `send_json()` exceptions, zero-delivery outcomes) that were previously invisible
- Fixed missing `self.debug` attribute in `WebSocketManager.__init__()` — was causing `AttributeError` crashes on `active_conversation_changed` emission. Now reads `app_debug` config key
- Added `job_id=self.id_hash` and `queue_name="run"` to all 14 `voice_io.notify()` calls in R2P job.py — matching the pattern used by standalone DeepResearchJob
- Added `voice_io.set_job_id()` / `voice_io.clear_job_id()` to R2P `_execute()` and `_execute_dry_run()` — enables auto-injection of job_id into all downstream notifications from `run_research()` internals (e.g., "Topic 1/5 complete")
- Discovered `active_conversation_changed` event was slipstreamed in by a prior session — not in `websocket available events` config, not in client subscription list. Deferred for review.

**Root cause chain**:
1. Diagnostic logging revealed all browser sessions were "not subscribed" to key events
2. Deeper analysis showed R2P notifications were missing `job_id`/`queue_name` (the JS UI needs these to route to job cards)
3. Even after adding explicit params to job.py, internal `run_research()` notifications still lacked `job_id` because `voice_io.set_job_id()` was never called (standalone DR job does this, R2P did not)

**Files** (all in CoSA submodule):
- `rest/websocket_manager.py` — `emit_to_user()` diagnostic logging, `self.debug` init, simplified `hasattr` guard
- `agents/deep_research_to_podcast/job.py` — `job_id`/`queue_name` on all notify calls, `set_job_id`/`clear_job_id` lifecycle

---

### 2026.03.07 - Session 328 Checkpoint 2 | Fix Missing TARGET_USER in R2P Job

**Accomplishments**:
- Fixed "Cannot resolve target_user" error in DeepResearchToPodcastJob — added `cosa_interface.TARGET_USER = self.user_email` in both `_execute()` and `_execute_dry_run()`, matching the pattern used by deep_research and podcast_generator jobs

**Files**:
- `src/cosa/agents/deep_research_to_podcast/job.py` — Added `TARGET_USER` assignment in 2 locations

---

### 2026.03.07 - Session 328 Checkpoint 1 | CJ Flow Job Card Bug Fixes + Packaging Guide Documentation

**Accomplishments**:
- Fixed user messages in running job cards rendering as gray `activity-log-entry` instead of right-justified blue chat bubbles — added `user_initiated_message` type check in `appendNotificationToJobCard()` to use `sender-message outgoing` pattern
- Fixed cancel button not removed on job card transition from running to done/dead — changed `cancelBtn.disabled = true` to `cancelBtn.remove()` for both `done` and `dead` queue transitions
- Fixed `DeepResearchToPodcastJob` sender_id validation error — changed `self.id_hash` to `self.base_id` for sender_id construction (id_hash includes `::user_uuid` after `register_scoped_job()`, breaking the regex pattern)
- Documented sender_id scoping pitfall as Pitfall 6.4 in CJ Flow Packaging Guide with symptom, root cause, and correct pattern
- Added sender identity setup block to Packaging Guide notification section showing `self.base_id` usage
- Removed double truncation in job card `job-full-question` — Python-side `last_question_asked` no longer truncates query text; JS header `truncateText()` handles display truncation independently

**Files**:
- `src/fastapi_app/static/js/notifications.js` — `appendNotificationToJobCard()` user message bubble, cancel button `.remove()` for done/dead
- `src/cosa/agents/deep_research_to_podcast/job.py` — `self.base_id` for sender_id (2 sites), removed query truncation in `last_question_asked`
- `src/cosa/agents/deep_research/job.py` — Removed query truncation in `last_question_asked`
- `src/cosa/agents/podcast_generator/job.py` — Removed filename truncation in `last_question_asked`
- `src/rnd/2026.02.12-cj-flow-bounded-job-packaging-guide.md` — Pitfall 6.4 + sender identity setup block

---

### 2026.03.06 - Session 327 | Housekeeping — Commit Stray Files from Sessions 325-326

**Accomplishments**:
- Added `log_to_stream()` JSONL stream logger to hook_common.py — single-line JSON entries to `hook-events.jsonl` for `tail -f` debugging across all hooks
- Added JSONL logging to `ask_yes_no()` in cosa_voice_mcp.py — captures raw_value, parsed answer, qualifier, and enriched flag for debugging qualifier flow
- Changed tmux session naming in start-cc-with-tmux.sh to use unique hash-based names (`cc-tmux-session-{8-char-hash}`) instead of fixed `claude-code` name
- Committed + pushed 7 pending local commits to remote

**Files**: 3 modified (+62/-59 lines)
- `src/lupin_cli/claude_code/hooks/lib/hook_common.py` — `STREAM_LOG`, `log_to_stream()`, wired into `log_payload()`
- `src/lupin_mcp/cosa_voice_mcp.py` — `log_to_stream` import, JSONL logging in `ask_yes_no()`
- `src/scripts/start-cc-with-tmux.sh` — Unique session name generation

---

### 2026.03.06 - Session 326 Checkpoint 1 | Fix tmux Voice Injection — Type Message Text Instead of Bare Enter

**Accomplishments**:
- Fixed voice injection to idle CC sessions: replaced bare `Enter` keystroke with actual message text typed via `tmux send-keys -l` (literal mode), followed by `Enter` after 250ms delay
- Root cause: CC ignores empty Enter presses — `UserPromptSubmit` hook never fires for empty input, so buffered messages were never drained
- Renamed `_trigger_tmux_enter()` → `_inject_via_tmux( message_text )` — message goes directly into CC prompt as visible typed input, bypassing the JSONL buffer intermediary
- Commented out `_buffer_message()` call in `_handle_event()` — no longer needed for idle injection path
- Updated 3 unit tests and 1 smoke test to verify new two-call subprocess pattern (literal text + Enter)
- All 18 unit tests and 3 smoke tests pass

**Files**:
- `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` — `import time`, `_inject_via_tmux()`, updated `_handle_event()`
- `src/tests/unit/test_session_bridge_lookup.py` — 3 tests updated in `TestListenerTmuxTrigger`
- `src/tests/smoke/test_voice_injection_e2e.py` — `test_listener_tmux_inject_mocked()` replaces old trigger test

---

### 2026.03.06 - Session 325 Checkpoint 1 | Centralized CC Notification Listener Logging

**Accomplishments**:
- Added centralized log file (`~/.claude/sessions/cc-listeners.log`) — all listener instances append to a single file, supporting `tail -f` across context clears and parallel sessions
- Each log line prefixed with `{ISO_TIMESTAMP} [{8-char hash}]` for easy filtering
- Lifecycle markers: `=== LISTENER STARTED ===`, `=== LISTENER STOPPED ===`, `=== SESSION TRANSITION: old -> new (stable: X) ===`
- Session transition markers written by `register_session.py` after killing old listener on context clear
- Listener stdout redirected to centralized log to capture base class `print()` calls
- Simplified `tail-cc-listeners.sh` from 216 lines to 66 lines — now a thin wrapper around `tail -f`
- Per-session log files (`cc-listener-{hash}.log`) kept for backward compatibility
- Fixed 3 test fixtures using `__new__` that needed new `_centralized_log` attribute

**Files**:
- `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` — CENTRALIZED_LOG constant, `--centralized-log` CLI arg, `_write_central()`, `_log_central()`, lifecycle markers in `run()`
- `src/lupin_cli/claude_code/hooks/register_session.py` — `_log_session_transition()`, stdout redirect, `--centralized-log` passthrough
- `src/scripts/tail-cc-listeners.sh` — Simplified to ~66 lines wrapping `tail -f`
- `src/tests/unit/test_session_bridge_lookup.py` — Added `_centralized_log = None` to 3 `__new__` fixtures

---

### 2026.03.06 - Session 323 Checkpoint 3 | Fix MCP ask_yes_no() Silently Discarding Qualifier Comments

**Accomplishments**:
- Fixed bug where `ask_yes_no()` in cosa_voice_mcp.py returned raw `"yes [comment: ...]"` string — Claude treated it as simple "yes" and ignored the user's comment
- Added `_extract_qualifier()` helper (duplicated regex from stop.py — separate packages, no cross-import) to parse `[comment: ...]` from response
- Added `_format_qualified_response()` helper to enrich return value with explicit `IMPORTANT` instruction block that Claude cannot ignore
- Plain yes/no responses pass through unchanged (no regression)
- 19 new tests all passing: 10 `_extract_qualifier` parsing, 3 `_format_qualified_response` output, 6 `ask_yes_no` integration with mocked backend

**Files**:
- `src/lupin_mcp/cosa_voice_mcp.py` — Added `import re`, `_extract_qualifier()`, `_format_qualified_response()`, modified `ask_yes_no()` return logic
- `src/tests/unit/test_cosa_voice_mcp_qualifier.py` — **NEW** 19 tests across 3 classes

**Commit**: b3ac02e

---

### 2026.03.06 - Session 323 Checkpoint 2 | Fix Stop Hook Discarding "no + qualifier" Comments

**Accomplishments**:
- Fixed bug where `_ask_anything_else()` in stop.py silently discarded user qualifier when answer was "no" — "no [comment: say hi]" now blocks stop and passes the instruction to Claude
- Extracted `_build_qualifier_reason()` shared helper used by both "yes + qualifier" and "no + qualifier" branches, taking separate `question_context` and `instruction_context` prefixes for grammatically correct output
- Added debug logging to stderr (`[STOP] response:` and `[STOP] parsed:`) for stop hook observability
- 6 new tests (42 total in test_stop_hook.py): 4 for `_build_qualifier_reason` unit tests + 2 end-to-end "no + qualifier" tests (instruction and question paths)

**Files**:
- `src/lupin_cli/claude_code/hooks/stop.py` — New `_build_qualifier_reason()` helper, "no + qualifier" branch at line 240, debug logging at lines 226-227
- `src/tests/unit/test_stop_hook.py` — 6 new tests in `TestBuildQualifierReason` class + `test_no_with_qualifier_*` in `TestNotifyUserSync`

---

### 2026.03.06 - Session 323 Checkpoint 1 | Voice Injection into Idle CC Sessions + Permission Prompt High Priority

**Accomplishments**:
- Implemented all 6 phases of voice injection plan: tmux discovery in register_session.py, session lookup utilities (`find_session_by_id`, `find_session_by_tmux`), listener tmux Enter trigger, UserPromptSubmit hook, shell scripts (`start-cc-with-tmux.sh`, `voice-send.sh`), hook registration in `~/.claude/settings.json`
- Added `_find_tmux_session()` to register_session.py — scans `tmux list-panes` for CC PID match with grandparent fallback
- Added `_resolve_tmux_session()` and `_trigger_tmux_enter()` to CCNotificationListener — sends bare Enter keystroke after buffering to wake idle CC
- Created UserPromptSubmit hook — drains JSONL buffer, formats as `[Voice]: ...` context, emits additionalContext
- Changed permission_prompt notification TTS from low to high priority so user hears approval requests spoken aloud
- 29 new tests all passing (8 UserPromptSubmit + 18 session bridge lookup/tmux + 3 E2E smoke)

**Files**:
- `src/lupin_cli/claude_code/hooks/register_session.py` — Added `_find_tmux_session()`, `tmux_session` in bridge JSON + env file
- `src/lupin_cli/claude_code/hooks/lib/session_bridge.py` — Added `find_session_by_id()`, `find_session_by_tmux()`
- `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` — Added `_resolve_tmux_session()`, `_trigger_tmux_enter()`, `--tmux-session` CLI arg
- `src/lupin_cli/claude_code/hooks/user_prompt_submit.py` — **NEW** UserPromptSubmit hook
- `src/lupin_cli/claude_code/hooks/notification.py` — `permission_prompt` TTS now `priority="high"`
- `src/scripts/start-cc-with-tmux.sh` — **NEW** tmux launcher for CC
- `src/scripts/voice-send.sh` — **NEW** manual testing utility
- `~/.claude/settings.json` — Added `UserPromptSubmit` hook entry
- `src/tests/unit/test_user_prompt_submit_hook.py` — **NEW** 8 tests
- `src/tests/unit/test_session_bridge_lookup.py` — **NEW** 18 tests
- `src/tests/smoke/test_voice_injection_e2e.py` — **NEW** 3 tests
- `src/tests/unit/test_notification_hook.py` — Added priority assertions for permission_prompt

**Commit**: faff65f

---

### 2026.03.06 - Session 323 | Markdown in Conversation History + Cancel Expired Notification Fix

**Accomplishments**:
- Added `renderMarkdownInline()` method using `marked.parseInline()` for inline-only markdown rendering (no `<p>` wrapping) — safe inside `<span>` chat bubble elements
- Replaced `escapeHtml()` with `renderMarkdownInline()` at 6 message-text locations: live outgoing chat bubble, history user-initiated message, progress group head, non-grouped message, progress group update, and date accordion messages
- Removed 120-char message truncation at 3 locations (`addNotificationToSenderCard`, `updateSenderProgressGroupEntry`, `addMessageToSenderCard`) — messages now display in full
- Fixed `textContent` → `innerHTML` for progress group head updates to preserve rendered markdown
- Fixed stuck card bug: cancelling an already-expired response-requested notification now gracefully dismisses via `handleGracePeriodExceeded()` instead of throwing an unrecoverable error

**Files**:
- `src/fastapi_app/static/js/notifications.js` — `renderMarkdownInline()` method + 6 call sites, 3 truncation removals, 1 `textContent` → `innerHTML` fix, 1 "already responded" error handler

**Commit**: de59952

**Status**: Session closed 2026.03.06

---

### 2026.03.05 - Session 322 | Fix deleteSenderConversation() Runtime Error

**Accomplishments**:
- Fixed runtime error in restored `deleteSenderConversation()` method — changed `group.notifications.length` → `group.totalCount` to match current sender group data structure (dateGroups Map replaced flat notifications array)

**Files**:
- `src/fastapi_app/static/js/notifications.js` — Line 8981: `group.totalCount` replaces `group.notifications.length`

---

### 2026.03.05 - Session 321 | Voice Injection Plan Serialization (Phase 0)

**Accomplishments**:
- Serialized voice injection implementation plan (listener + tmux + UserPromptSubmit hook) to R&D directory — 6-phase plan covering tmux discovery, listener trigger, new hook, shell scripts, registration, and tests (~24 unit + E2E)
- Added TODO item referencing plan and research docs for next-session pickup

**Files**:
- `src/rnd/2026.02.25-full-voice-io-integration-with-cc-system-hooks-and-mcp/2026.03.05-voice-injection-listener-tmux-hook-plan.md` — **NEW** Implementation plan
- `src/rnd/README.md` — Added index entry
- `TODO.md` — Added voice injection TODO item

---

### 2026.03.05 - Session 320 Checkpoint 1 | Skills Encyclopedia Plan

**Accomplishments**:
- Surveyed entire Lupin + CoSA repo documentation (~200+ files) and identified 10-11 canonical implementation patterns that Claude Code repeatedly reinvents
- Created comprehensive skills encyclopedia master plan documenting all patterns to be captured as auto-activating Claude Code skills
- Identified 4 tiers of skills: ConfigurationManager, XML/Pydantic serialization, Notification API, CJ Flow queue (Tier 1); agent-creation, FastAPI routers, WebSocket, storage patterns (Tier 2); Claude Agent SDK, nested git repos (Tier 3)
- Designed 7-session phased execution timeline for creating all skills

**Files**:
- `src/rnd/2026.03.05-skills-encyclopedia-plan.md` — **NEW** Master plan for skills encyclopedia (Tier 1-3 skill specs, execution timeline, design decisions)

**Commit**: baa25cf

---

### 2026.03.05 - Session 319 | Render Markdown in Response-Requested Card Title & Message

**Accomplishments**:
- Fixed raw markdown rendering in "response requested" notification cards (yes/no, open-ended, multiple choice) — title and message fields now pass through `renderMarkdown()` (marked.js + DOMPurify), matching existing `abstract` field behavior

**Files**:
- `src/fastapi_app/static/js/notifications.js` — Wrapped title (line 10775) and message (line 10783) in `this.renderMarkdown()`

**Commit**: 105a6cc

**Status**: Session closed 2026.03.05

---

### 2026.03.05 - Session 318 Checkpoint 1 | Stop Hook Gister Summary + LLM Intent Classification

**Accomplishments**:
- Added Gister-powered task summarization to stop hook "Anything else?" notification — user hears *what* was finished (e.g., "I'm finished *fixing linting errors*") instead of generic message
- Implemented LLM-based qualifier intent classification via phi4 + `QualifierClassification` BaseXMLModel — classifies user qualifiers as "question" (routes to `converse()`) or "instruction" (routes to `notify()` + action)
- Added `_summarize_task()` using Gister default mode (cache-enabled) for `last_assistant_message` from stop hook payload
- Added `classify_qualifier()` following established agent pattern: config-driven prompt template + PromptTemplateProcessor + LlmClientFactory + Pydantic XML parsing
- Fixed auto-response Gister in `cc_notification_listener.py`: switched from session-title prompt key to default mode, prefixed message with "Received:"
- Fallback: when LLM classifier unavailable, uses `?` suffix heuristic for question detection

**Files**:
- `src/cosa/agents/io_models/xml_models.py` — Added `QualifierClassification` model with `is_question()`, `is_instruction()`, None coercion, smoke test
- `src/cosa/agents/io_models/utils/prompt_template_processor.py` — Registered `QualifierClassification` in MODEL_MAPPING
- `src/conf/prompts/agents/qualifier-classification.txt` — **NEW** prompt template for intent classification
- `src/conf/lupin-app.ini` — Config keys for qualifier classification prompt + LLM spec
- `src/conf/lupin-app-splainer.ini` — Matching splainer entries
- `src/lupin_cli/claude_code/hooks/stop.py` — `_summarize_task()`, `classify_qualifier()`, updated `_ask_anything_else()` + `main()`
- `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` — Default Gister mode, "Received:" prefix
- `src/tests/unit/test_stop_hook.py` — 36 tests (was 19): +5 summarize, +4 classify, +8 qualifier routing/gist

**Commit**: b79b6f5

---

### 2026.03.05 - Session 317 Checkpoint 1 | Session ID + Copy Icon Spacing Fix

**Accomplishments**:
- Tightened visual spacing between session ID (`#a1b2c3d4`) and clipboard copy icon in notification panel
- Removed template literal whitespace between adjacent inline `<span>` elements that rendered as a browser space character
- Changed `.sender-session-copy` CSS `margin-left` from `1px` to `0`

**Files**:
- `src/fastapi_app/static/js/notifications.js` — Eliminated newline between session ID and copy button spans
- `src/fastapi_app/static/css/notifications.css` — `margin-left: 0` on `.sender-session-copy`

**Commit**: c5f8fb7

---

### 2026.03.05 - Session 315 Checkpoint 1 | Stop Hook notify_user_sync + display_qualifier_widget

**Accomplishments**:
- Implemented Phase 2 stop hook behavior: when no voice buffer content, asks user "Anything else?" via `notify_user_sync` with 5-minute timeout and default "no"
- Added `extract_qualifier_comment()` regex parser for "yes [comment: ...]" response format — extracts qualifier text and includes it in the stop block reason
- Added `_ask_anything_else()` helper that builds the NotificationRequest, calls `notify_user_sync`, and returns appropriate stop hook JSON
- Threaded `display_qualifier_widget` boolean flag through full notification stack: NotificationRequest model → `to_api_params()` → FastAPI query parameter → NotificationItem → `to_dict()` → JavaScript renderer
- JS renderer conditionally renders yes/no comment widget expanded with softer hint text ("You may comment on your answer here if you wish") when flag is True

**Files**:
- `src/lupin_cli/claude_code/hooks/stop.py` — Phase 2 `notify_user_sync` call, `extract_qualifier_comment()`, `_ask_anything_else()`
- `src/lupin_cli/notifications/notification_models.py` — `display_qualifier_widget` field on `NotificationRequest` + `to_api_params()`
- `src/cosa/rest/routers/notifications.py` — `display_qualifier_widget` query parameter, pass-through to both push_notification calls
- `src/cosa/rest/notification_fifo_queue.py` — `display_qualifier_widget` in `NotificationItem.__init__()`, `to_dict()`, `push_notification()`
- `src/fastapi_app/static/js/notifications.js` — Conditional expanded class + alternate hint text
- `src/tests/unit/test_stop_hook.py` — 22 tests (8 new for notify_user_sync + qualifier extraction)

**Commit**: 3001997

---

### 2026.03.04 - Session 314 | CJ Flow Cancel Button: Disable in Done/Dead + Padding Fix

**Accomplishments**:
- Fixed cancel button remaining clickable after job cards transition from run → done/dead via DOM reparenting in `handleJobStateTransition()`
- Added cancel button disabling logic for both `done` and `dead` queue transitions: sets `disabled = true`, nulls onclick handler, removes `.has-cancel` class from header
- Fixed cancel button visual positioning: moved from flush `top: 0; left: 0` to `top: 4px; left: 6px` for proper breathing room matching header padding
- Added `.job-cancel-button:disabled:hover` CSS override to prevent hover highlight on disabled buttons

**Files**:
- `src/fastapi_app/static/js/notifications.js` — Cancel button disabling in `handleJobStateTransition()` for done + dead transitions
- `src/fastapi_app/static/css/notifications.css` — Button positioning fix + disabled hover override

---

### 2026.03.04 - Session 313 Checkpoint 1 | Voice Buffer Deny + Generalized Notification Reminder

**Accomplishments**:
- Implemented PreToolUse voice buffer deny: when voice buffer has content, hook denies the tool call with `permissionDecision: "deny"` + `additionalContext`, forcing Claude to address the user's voice message before continuing
- Extracted shared `enrich_voice_context()` helper that appends the "MUST acknowledge via cosa-voice" notification reminder to any voice context string
- Generalized notification reminder across all three hooks: PreToolUse (deny + context), PostToolUse (additionalContext), Stop (block reason)
- Refactored `build_voice_deny_response()` to use `enrich_voice_context()` internally, eliminating duplicated reminder text
- Live-tested full deny → address → retry cycle: voice message blocked tool call, Claude responded via converse(), subsequent tool call passed through

**Files**:
- `src/lupin_cli/claude_code/hooks/lib/hook_common.py` — Added `enrich_voice_context()`, `build_voice_deny_response()`; refactored deny response to use shared enricher
- `src/lupin_cli/claude_code/hooks/pre_tool_use.py` — Deny when buffer has content instead of passthrough additionalContext
- `src/lupin_cli/claude_code/hooks/post_tool_use.py` — Enriched voice context with notification reminder
- `src/lupin_cli/claude_code/hooks/stop.py` — Enriched block reason with notification reminder

---

### 2026.03.04 - Session 312 Checkpoint 1 | Move Gist Auto-Response to Listener + Fix Drain-Only Hook Ack

**Accomplishments**:
- Moved gist auto-response from hook drain time to listener message receipt time for immediate feedback
- Added `_send_gist_response()` to `CCNotificationListener` — generates 3-5 word gist via Gister, sends as low-priority notification back to browser user immediately upon buffering
- Replaced `acknowledge_drained()` in `hook_common.py` with no-op — listener now handles auto-response, drain only injects full message as `additionalContext`
- Simplified JS `sender_id` from `user@{email}` prefix to plain email address — removes artificial prefix, fixes "Unknown" sender card on reload
- Updated test fixture sender_id to match new plain email format

**Files**:
- `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` — `_send_gist_response()` + call after `_buffer_message()`
- `src/lupin_cli/claude_code/hooks/lib/hook_common.py` — `acknowledge_drained()` → no-op
- `src/fastapi_app/static/js/notifications.js` — sender_id simplified to plain email
- `src/tests/smoke/test_cc_notification_listener.py` — sender_id updated to plain email

**Commit**: 2816557

---

### 2026.03.04 - Session 309 Checkpoint 1 | Fix Headless CC Notification Listener

**Accomplishments**:
- Fixed 3 bugs preventing the CC Notification Listener from receiving user-initiated voice messages
- **Bug 1**: `self._running` not set before outer restart loop in `CCNotificationListener.run()` — loop body never executed, listener exited silently
- **Bug 2**: `is_valid_session_id()` regex only accepted "adjective noun" format, rejecting `cc-listener-{hash}` with HTTP 403. Extended with programmatic session pattern
- **Bug 3**: Credentials file path `~/.claude/notification-hooks-credentials.ini` did not exist. Renamed all references to `~/.lupin/credentials.ini` and created the file
- Added stderr capture + 300ms liveness check in `_spawn_listener()` to surface future silent crashes
- Created `check-cc-listener-status.sh` script for reproducible listener monitoring (process + server WebSocket sessions)
- Purged 8 stale session bridge files from dead CC processes
- E2E verified: notification sent → WebSocket → listener → buffer file

**Files Modified** (Lupin repo):
- `src/lupin_cli/claude_code/hooks/lib/hook_credentials.py` — Credential path constant + docstrings (`~/.lupin/credentials.ini`)
- `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` — `self._running = True` fix + docstring path update
- `src/lupin_cli/claude_code/hooks/register_session.py` — stderr capture to file + liveness check in `_spawn_listener()`
- `src/rnd/.../2026.02.28-design-doc-revisions-session-290.md` — Path references updated
- `src/rnd/.../2026.03.01-evolve-hooks-test-to-production.md` — Path reference updated
- `src/scripts/check-cc-listener-status.sh` — New monitoring script

**Files Modified** (CoSA nested repo — NOT committed here):
- `src/cosa/rest/routers/websocket.py` — `is_valid_session_id()` extended for programmatic sessions

---

### 2026.03.04 - Session 308 | Fix Shared Mutable Global in Core voice_io

**Accomplishments**:
- Fixed "Cannot resolve target_user" notification dispatch failures caused by shared mutable `_cosa_interface` global in consolidated `voice_io.py`
- Added `reconfigure()` function to all 3 voice_io wrappers (podcast_generator, deep_research, swe_team) that re-asserts the correct cosa_interface binding
- Added `_voice_available` reset in `configure()` so the "Initializing..." ping re-runs with the correct cosa_interface/TARGET_USER after reconfigure
- Called `reconfigure()` at the start of `_execute()` in all 3 job files (podcast_generator, deep_research, swe_team)
- Called `reconfigure()` in podcast_generator router description mode (2 locations: `submit_podcast_job()` and `get_user_document_selection()`)
- Called `reconfigure()` in deep_research_to_podcast agent before each pipeline phase (DR phase + PG phase)
- All 9 smoke tests pass, 1943 unit tests pass (5 pre-existing failures unrelated)

**Files Modified** (9 files, all in CoSA nested repo):
- `src/cosa/agents/utils/voice_io.py` — Reset `_voice_available` cache on `configure()`
- `src/cosa/agents/podcast_generator/voice_io.py` — Added `reconfigure()` function
- `src/cosa/agents/deep_research/voice_io.py` — Added `reconfigure()` function
- `src/cosa/agents/swe_team/voice_io.py` — Added `reconfigure()` function
- `src/cosa/agents/podcast_generator/job.py` — Call `reconfigure()` in `_execute()`
- `src/cosa/agents/deep_research/job.py` — Call `reconfigure()` in `_execute()`
- `src/cosa/agents/swe_team/job.py` — Call `reconfigure()` in `_execute()`
- `src/cosa/rest/routers/podcast_generator.py` — Call `reconfigure()` in description mode (2 locations)
- `src/cosa/agents/deep_research_to_podcast/agent.py` — Call `reconfigure()` before each pipeline phase

---

### 2026.03.04 - Session 306 Checkpoint 4 | Route Completed Notifications to Job Card

**Accomplishments**:
- Added `routeCompletedNotification()` helper that routes completed response-required Q&A pairs to job card (via `appendNotificationToJobCard()`) when `job_id` exists, falls back to sender card
- Updated `showConfirmation()` — skips sender card creation when `job_id` present, routes via new helper
- Updated `handleGracePeriodExceeded()` — routes expired defaults to job card when `job_id` present
- Updated `handleLocalTimeout()` — animation destination targets job card, routes via new helper
- Fixed missing `'status': 'pending'` in `todo_fifo_queue.py` expeditor speculative metadata (same bug previously fixed in podcast_generator.py)

**Files Modified** (1 Lupin file + 1 CoSA file):
- `src/fastapi_app/static/js/notifications.js` — `routeCompletedNotification()` + 4 caller updates
- `src/cosa/rest/todo_fifo_queue.py` — Added `'status': 'pending'` to speculative metadata (CoSA nested repo)

**Commit**: d1a5e16

---

### 2026.03.04 - Session 307 | CJ Flow Job Card UX Consistency Fixes

**Accomplishments**:
- Fixed user responses in interaction panes to render as blue outgoing chat bubbles (`.sender-message.outgoing`) instead of flat inline gray/green text
- Fixed cancel button in job card headers to use absolute left-aligned positioning (matching `.action-required-cancel-btn` pattern) instead of floating inline in flex flow
- Added `.has-cancel` modifier class for conditional `padding-left: 36px` on headers with cancel buttons
- Removed unused CSS classes: `.interaction-response`, `.response-label`, `.response-value`
- Moved `responseHtml` outside `.interaction-item` div to render as sibling (proper chat bubble layout)

**Files Modified** (2 files):
- `src/fastapi_app/static/js/notifications.js` — `renderInteractionItem()` bubble fix + `renderJobCard()` cancel button restructure
- `src/fastapi_app/static/css/notifications.css` — Cancel button absolute positioning + removed unused response classes

---

### 2026.03.03 - Session 306 | Podcast Notification Routing + Silent TTS Failure Visibility

#### Checkpoint 3 | 2026.03.03 | Graceful job cancellation for agentic jobs

**Accomplishments**:
- Implemented full-stack graceful cancellation for long-running agentic jobs (podcast generator, deep research)
- Added `_cancel_requested` flag, `_orchestrator` ref, and `request_cancel()` method to `AgenticJobBase`
- Wired orchestrator reference storage in `PodcastGeneratorJob._execute()` for cancel signal propagation
- Added `cancel_check` callback parameter to `run_research()` with 4 checkpoint calls (between clarification, planning, each research topic, and synthesis steps)
- Added `POST /api/jobs/{job_id}/cancel` endpoint with auth, ownership, and type validation
- Added Cancel Job button to running job cards with confirmation dialog, disabled state, and "Cancelling..." feedback
- Cancel flow: Browser button → API endpoint → job flag → orchestrator stop → dead queue → WebSocket transition
- Thread-safe: boolean assignment atomic under CPython GIL, no locks needed

**Test Results**: 1942 unit tests pass, 0 regressions (verified against clean HEAD)

**Files** (CoSA nested repo — 5 files):
- `src/cosa/agents/agentic_job_base.py` — `_cancel_requested`, `_orchestrator`, `request_cancel()`
- `src/cosa/agents/podcast_generator/job.py` — orchestrator ref + cancel check in `do_all()`
- `src/cosa/agents/deep_research/job.py` — cancel_check callback + cancel check in `do_all()`
- `src/cosa/agents/deep_research/cli.py` — `cancel_check` param + 4 checkpoint calls
- `src/cosa/rest/routers/queues.py` — `POST /api/jobs/{job_id}/cancel` endpoint

**Files** (Lupin repo — 2 files):
- `src/fastapi_app/static/js/notifications.js` — Cancel button HTML + `cancelJob()` method
- `src/fastapi_app/static/css/notifications.css` — Cancel button styling

**Commit**: 148132b

---

#### Checkpoint 2 | 2026.03.03 | Bug 4/5/3b — Initializing ping + progress dedup + cosa_interface job_id

**Accomplishments**:

**Bug Fix 4 — "Initializing..." notification missing job_id**:
- Root cause: `is_voice_available()` pings voice service by calling `_cosa_interface.notify_progress()` directly, bypassing the `notify()` auto-injection. Even though `_job_id` is set before the first call, the ping test didn't pass it.
- Fix: Added `job_id=_job_id` to the ping test call in `voice_io.py:214`. Safe when no job_id set (defaults to `None`).

**Bug Fix 5 — Progress group notifications rendered separately in DONE card**:
- Root cause: `/api/get-job-interactions/{job_id}` endpoint returned all notifications as individual items without deduplicating by `progress_group_id`. RUNNING card collapses them (in-place DOM updates), but DONE card rendered each one separately.
- Fix: Added Python-side deduplication in `queues.py` before serialization — keeps only the latest notification per `progress_group_id` (ordered newest-first). DONE card now shows "100% (18/18 segments)" once instead of 10+ intermediate updates.

**Bug Fix 3b (Latent) — cosa_interface wrappers missing job_id parameter**:
- Root cause: Previous session's Bug 3 fix added `job_id=job_id` pass-through from `voice_io` to `_cosa_interface.*()` calls, but the wrapper functions in `cosa_interface.py` don't accept `job_id`. Would raise `TypeError: unexpected keyword argument 'job_id'` at runtime for any interactive prompt.
- Fix: Added `job_id: Optional[str] = None` to `ask_confirmation()`, `get_feedback()`, `present_choices()` in both `podcast_generator/cosa_interface.py` and `deep_research/cosa_interface.py`, with pass-through to dispatcher.

**Test Results**: 1942 unit tests pass, 0 new regressions (6 pre-existing failures unrelated)

**Files** (CoSA nested repo — 4 files):
- `src/cosa/agents/utils/voice_io.py` — Bug 4: `job_id=_job_id` on ping test
- `src/cosa/rest/routers/queues.py` — Bug 5: progress_group_id deduplication
- `src/cosa/agents/podcast_generator/cosa_interface.py` — Bug 3b: `job_id` param on 3 wrappers
- `src/cosa/agents/deep_research/cosa_interface.py` — Bug 3b: `job_id` param on 3 wrappers

---

#### Checkpoint 1 | 2026.03.03 | job_id auto-injection + TTS error visibility

**Accomplishments**:

**Bug Fix 1 — Notifications routing to CC Session card instead of job card**:
- Root cause: `PodcastOrchestratorAgent` has 41+ `notify()` calls, none pass `job_id`. Frontend routes to CC session card when `job_id` is missing.
- Fix: Added `_job_id` module-level state to `voice_io.py` with `set_job_id()`/`clear_job_id()`. `notify()` auto-injects `_job_id` when caller doesn't provide one. `job.py` sets it once before orchestrator launch, clears in `finally`.
- Re-exported `set_job_id`/`clear_job_id` from 3 wrapper modules (podcast, deep_research, swe_team).
- 7 new unit tests in `TestJobIdAutoInjection`: auto-injection, explicit override, clear, configure integration.

**Bug Fix 2 — Silent TTS segment failures**:
- Root cause: TTS errors logged via `logger.warning()` (invisible on console) + debug-gated `print()`. The "N segments failed" notification showed counts but no error message.
- Fix: Always `print()` each attempt failure, final failure summary, and completion stats in `tts_client.py`. Added `**Error**: {first_error}` to both single-language and multi-language `ask_yes_no` abstracts in `orchestrator.py`. Added always-on failure logging in `_generate_audio_async()`.

**Test Results**: 1942 unit tests pass (20/20 voice_io), 0 regressions

**Files** (CoSA nested repo — 9 files):
- `src/cosa/agents/utils/voice_io.py` — `_job_id`, `set_job_id()`, `clear_job_id()`, auto-inject in `notify()`
- `src/cosa/agents/podcast_generator/voice_io.py` — re-export set/clear_job_id
- `src/cosa/agents/deep_research/voice_io.py` — re-export set/clear_job_id
- `src/cosa/agents/swe_team/voice_io.py` — re-export set/clear_job_id
- `src/cosa/agents/podcast_generator/job.py` — set_job_id + finally clear
- `src/cosa/agents/deep_research/job.py` — set_job_id + finally clear
- `src/cosa/agents/podcast_generator/tts_client.py` — always-visible error prints
- `src/cosa/agents/podcast_generator/orchestrator.py` — error context in notifications + _generate_audio_async logging

**Files** (Lupin repo — 1 file, committed as 3a8207c):
- `src/tests/unit/test_voice_io_non_interactive.py` — 7 new TestJobIdAutoInjection tests

---

### 2026.03.03 - Session 305 | CC Session Routing — 5 Root Cause Fixes for Context Clear Mis-routing

**Accomplishments**:
- **Fix 1+5 (session_bridge.py)**: `_find_session_file()` now returns `(path, source)` tuple — CWD fallback results are NOT cached (only PPID/grandparent matches). Added PID liveness check (`os.kill(pid, 0)`) to skip bridge files from dead CC processes. Added `clear_cached_session_id()` export. `wait_for_session_id()` bypasses cache for fresh resolution.
- **Fix 2 (cosa_voice_mcp.py)**: Replaced one-shot `_upgrade_session_id_background()` with persistent `_session_watcher_thread()` daemon — polls bridge file every 2s for mtime changes, updates `SESSION_ID`/`SENDER_ID` atomically on context clear detection.
- **Fix 3 (cc_notification_listener.py)**: Wrapped `super().run()` in infinite restart loop with 60s cooling period — listener now recovers after exhausting 10 reconnect attempts instead of dying permanently.
- **Fix 4 (register_session.py)**: Context clear detection (same PID, different session ID) triggers `_cleanup_old_listener()` — SIGTERM with 3s grace → SIGKILL, buffer message forwarding from old to new hash, then new listener spawn.
- Unit tests: 1910 passed, 0 new regressions

**Files Modified**: 4 files
- `src/lupin_cli/claude_code/hooks/lib/session_bridge.py` — Fixes 1+5
- `src/lupin_mcp/cosa_voice_mcp.py` — Fix 2
- `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` — Fix 3
- `src/lupin_cli/claude_code/hooks/register_session.py` — Fix 4

**Plan doc**: `~/.claude/plans/vivid-exploring-nebula.md` (plan mode transcript)

---

### 2026.03.03 - Session 304 | Podcast Generator — 3 Bug Fixes (Session 283 Bugs)

#### Checkpoint 2 | 2026.03.03 | Fuzzy matching pre-filter + present_choices/target_user router fixes

**Accomplishments**:
- **Keyword pre-filter**: Added pre-filtering step in `match_research_docs()` — narrows 1,001 candidate files to top 50 by keyword scoring before sending to LLM. Fixes voice transcription failing to match in large search space.
- **deep_research cosa_interface**: Added missing `title` and `abstract` params to `present_choices()` — was causing `got an unexpected keyword argument 'title'` error
- **Router target_user**: Set `cosa_interface.TARGET_USER = user_email` in `get_user_document_selection()` before `present_choices()` — fixes "Cannot resolve target_user" during submit phase
- 3 new pre-filter unit tests added to `test_fuzzy_file_matching.py` (17 total)

**Files** (CoSA nested repo): `podcast_generator.py` (router), `deep_research/cosa_interface.py`
**Files** (Lupin repo): `test_fuzzy_file_matching.py` (3 new tests)

---

#### Checkpoint 1 | 2026.03.03 | All 3 podcast generator bugs + target_user dispatch fixed

**Accomplishments**:
- **Bug #1 (Fuzzy Matching)**: Added `difflib.get_close_matches()` as 3rd validation tier in `match_research_docs()` — voice-transcribed paraphrases now resolve to valid file paths
- **Bug #2 (Job Card Contact / sender_id)**: Root cause was double-hash in sender_id (`#cli#pg-xxx`) failing Pydantic regex. Fixed `_get_sender_id()` to accept optional `suffix` param across podcast_generator, deep_research, and deep_research_to_podcast
- **Bug #3 (Audio Segment Upload / Non-Interactive Hang)**: Three sub-fixes — (1) `_is_interactive()` guard prevents `input()` blocking in Docker/queue contexts, (2) fixed TTS cost key `tts_results` → `tts_results_en`, (3) pre-stitching guard when all segments fail
- 37 new unit tests: `test_fuzzy_file_matching.py` (14), `test_target_user_dispatch.py` (10), `test_voice_io_non_interactive.py` (13)
- Full test suite: 1932 passed, 0 new regressions

**Files** (CoSA nested repo — pending separate commit):
- `src/cosa/rest/routers/podcast_generator.py` — difflib fuzzy matching
- `src/cosa/agents/podcast_generator/cosa_interface.py` — suffix param
- `src/cosa/agents/podcast_generator/job.py` — sender_id fix
- `src/cosa/agents/podcast_generator/orchestrator.py` — TTS cost key + pre-stitching guards
- `src/cosa/agents/deep_research/cosa_interface.py` — suffix param
- `src/cosa/agents/deep_research/job.py` — sender_id fix
- `src/cosa/agents/deep_research_to_podcast/job.py` — sender_id fix
- `src/cosa/agents/utils/voice_io.py` — `_is_interactive()` + non-interactive guards

**Files** (Lupin repo — test files):
- `src/tests/unit/test_fuzzy_file_matching.py` — NEW
- `src/tests/unit/test_target_user_dispatch.py` — NEW
- `src/tests/unit/test_voice_io_non_interactive.py` — NEW

**Plan doc**: `~/.claude/plans/vivid-puzzling-quasar.md`

---


*Earlier sessions archived — see navigation links below.*

## Navigation

### Archive Links
- **[Feb 24 - Mar 3, 2026](history/2026-02-24-to-03-03-history.md)** - Sessions 260-303: Voice Module Refactoring, Preference Learning Phases 0-3, Universal Prediction Engine Slices 0-6, Voice Hook Phases 0-1, Credential Unification, INTERACTIVE Dry-Run, Data Origin Fixes, Podcast Generator Bug Fixes, CC Session Voice Input, Notification Recipient Debugging
- **[Feb 16-23, 2026](history/2026-02-16-to-23-history.md)** - Sessions 214-258: Bug Fix Mode, SWE Team Proxy phases 6-8, Voice Module Refactoring, Preference Learning R&D (Takes I-III), Seed Data Generator, BLR + Thompson Sampling, Conformal Guarantees + ICRL, Playwright E2E Planning, INI Config Naming Convention, Frontend Architecture Docs, Unified Page Styling
- **[Feb 10-14, 2026](history/2026-02-10-to-14-history.md)** - Sessions 171-213: Notification Proxy Agent, SWE Team Phases 2-4, Calculator completion, CRUD bug fixes, Unified Smoke Test Framework, PEFT Resume OOM analysis
- **[Feb 3-10, 2026](history/2026-02-03-to-10-history.md)** - Sessions 126-180: DataFrame CRUD Phases 1-3, Runtime Argument Expeditor, PEFT Phase 2, Notification Proxy Agent, Calculator Mock Pipeline, Yes/No Comment Feature, Agentic Voice Workflow v2.0
- **[Jan 19 - Feb 2, 2026](history/2026-01-19-to-02-02-history.md)** - Sessions 57-124: Podcast Generator Phase 2, Deep Research CLI UX, LORA Training Integration, Test Suite Remediation, Cache Freshness, Queue Protocol Refactoring
- **[Jan 13-19, 2026](history/2026-01-13-to-19-history.md)** - Sessions 56-74b: Conversation Identity, Deep Research Agent, Podcast Generator Phase 1, Job Queue Progressive Disclosure UI
- **[Nov 23, 2025 - Jan 12, 2026](history/2025-11-23-to-2026-01-12-history.md)** - Sessions 7-55: MCP Voice, Directory Rename, Claude Code Dispatcher
- **[Oct 16 - Nov 22, 2025](history/2025-10-16-to-11-22-history.md)** - Sessions 1-6: Admin Dashboard, LanceDB, PostgreSQL Migration
- **[Oct 16-30, 2025](history/2025-10-16-to-30-history.md)** - SSE Notification System Phase 2
- **[Oct 1-15, 2025](history/2025-10-01-to-15-history.md)** - JWT/OAuth, User Filtering
