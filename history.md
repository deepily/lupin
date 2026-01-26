# Lupin Project History

> **✅ SESSION 100 COMPLETE**: Agentic Job UI Cards - Phases 0-2 + Bug Fix 4 + Expertise Level (2026.01.26)
> **Owner**: claude.code@lupin.deepily.ai#63cce923
> **Plan**: `/home/rruiz/.claude/plans/federated-prancing-lagoon.md`
>
> ### Accomplishments
> **Phase 0 - Consolidated voice_io Modules** (CoSA):
> - Created `agents/utils/voice_io.py` - unified implementation with all features
> - Updated `agents/deep_research/voice_io.py` - thin wrapper using consolidated module
> - Updated `agents/podcast_generator/voice_io.py` - thin wrapper with new features
>
> **Phase 1 - DeepResearchToPodcastAgent Wrapper** (CoSA):
> - Created `agents/deep_research_to_podcast/` package with `agent.py` and `state.py`
>
> **Phase 2 - CLI Entry Point** (CoSA):
> - Created `agents/deep_research_to_podcast/__main__.py`
> - Usage: `python -m cosa.agents.deep_research_to_podcast --query "..." --user-email ...`
>
> **Bug Fix 4 - run_research() Missing user_email**:
> - Fixed wrapper agent to pass `user_email=self.user_email` to `run_research()`
>
> **Expertise Level / Target Audience Configuration** (NEW):
> - Added `target_audience` (beginner/general/expert/academic) and `audience_context` to ResearchConfig
> - Added config keys to `lupin-app.ini` and `lupin-app-splainer.ini` (Lupin commit: bcf386a)
> - Added `--audience` and `--audience-context` CLI flags to Deep Research CLI
> - Created AUDIENCE_GUIDELINES dictionaries in 3 prompt files:
>   - `prompts/planning.py` - decomposition guidelines per audience level
>   - `prompts/subagent.py` - source selection guidelines per audience level
>   - `prompts/synthesis.py` - writing style guidelines per audience level
> - Wired audience params through `cli.py` → all prompt functions
> - Added `--audience` and `--audience-context` to wrapper agent CLI (`__main__.py`)
> - Updated wrapper `agent.py` to pass audience config to ResearchConfig
> - **All smoke tests passing**: config, planning, subagent, synthesis modules
>
> ### Remaining Work (Phases 3-6)
> - Phase 3: PodcastGeneratorJob class for queue integration
> - Phase 4: API endpoints (`/api/podcast-generator/submit`, `/api/chained-job/submit`)
> - Phase 5: UI cards in notifications.html
> - Phase 6: Router registration in main.py
>
> **Note**: CoSA submodule changes need separate commit
>
> ---

> **✅ SESSION 99 COMPLETE**: Bug Fix Mode - LanceDB Corruption Recovery (2026.01.25)
> **Owner**: claude.code@lupin.deepily.ai#454f9eca
>
> ### Fixes
> - **Fix 1**: LanceDB embedding cache corruption auto-recovery (ad-hoc)
>   - **Symptom**: `get_cached_embedding()` failed with "Not found" error when internal data fragment files missing
>   - **Root Cause**: LanceDB stores data in UUID-named `.lance` fragments; manual deletion or crash leaves manifest referencing missing files
>   - **Fix**: Added `_is_table_corrupted()` method that performs actual data scan (not just `count_rows()` which only reads metadata)
>   - **Auto-Recovery**: On corruption detection, drops and recreates table with fresh schema (acceptable data loss - it's a cache)
>   - **Files (CoSA)**: `src/cosa/memory/embedding_cache_table.py` - needs separate commit
>   - **Files (Lupin)**: `src/tests/unit/test_embedding_cache_corruption.py` (313 lines, 9 tests)
>   - **Tests**: 6 unit tests (mocked scenarios), 3 integration tests (real LanceDB corruption)
>   - **Commit**: 77ab971 (Lupin unit tests only)
>
> ### Session Summary
> - **Total Fixes**: 1
> - **Files Changed**: embedding_cache_table.py (CoSA), test_embedding_cache_corruption.py (Lupin)
> - **Commits**: 77ab971 (Lupin)
> - **Note**: CoSA submodule changes require separate commit in CoSA context
>
> **Status**: Session closed 2026.01.25
>
> ---

> **✅ SESSION 98 COMPLETE**: TTS Migration Completion + Phase 7 Browser Testing Done (2026.01.25)
> **Owner**: claude.code@lupin.deepily.ai#194f142f
>
> ### Accomplishments
> - **Bug Fix: Cache Hit ID Mismatch** (`running_fifo_queue.py:530-533`)
>   - Root cause: When cache hit occurs, `for_current_user()` creates copy with cached snapshot's `id_hash`
>   - But user association in `user_job_tracker` uses running job's `id_hash`
>   - Result: `get_jobs_for_user()` returned 0 jobs for cache hits
>   - Fix: Added `done_queue_entry.id_hash = original_job.id_hash` after copy creation
> - **Migrated 3 remaining `emit_speech_callback` calls** in `todo_fifo_queue.py`
>   - Line ~640: Unimplemented command case → `_notify()`
>   - Line ~655: After agent creation → `_notify(msg, job=agent)`
>   - Line ~772: Queue size announcement → `_notify(msg, job=job)`
> - **Bug Fix: Phase 6 TTS Routing** (`notifications.js:3728-3745`)
>   - Problem: Job-card routed notifications had no TTS playback (cached results silent)
>   - Problem: Regular notifications used verbose "Important! task notification:" prefix
>   - Fix: Added TTS queuing to Phase 6 with direct message (no prefix)
>   - Result: Answers now play clean (e.g., "14" not "Important! task notification: 14")
> - **✅ Phase 7 Browser Testing - COMPLETE**
>   - Job Queue Progressive Disclosure UI verified working
>   - Spinning indicator, duration timer, job cards all functional
>   - TTS playback for both fresh and cached results confirmed
> - **Smoke Tests**: All 4 passed (fifo_queue, running_fifo_queue, todo_fifo_queue, notification_models)
>
> ### Session Summary
> Completed TTS migration from legacy `_emit_speech` WebSocket system to notification service. Fixed critical cache hit bug that prevented done queue jobs from appearing for users. Fixed Phase 6 TTS routing for clean answer playback. Phase 7 Browser Testing marked complete.
>
> **Note**: Queue code changes are in CoSA submodule - require separate commit in CoSA context.
>
> ---

> **✅ SESSION 97 COMPLETE**: TTS Migration Phase 0-3 (2026.01.25)
> **Owner**: claude.code@lupin.deepily.ai#454f9eca
>
> ### Accomplishments
> - **Phase 0**: Added `suppress_ding` field to NotificationRequest and AsyncNotificationRequest
> - **Phase 0**: Added retry parameters (`retry_on_timeout`, `max_attempts`, `backoff_multiplier`) to `notify_user_sync()`
> - **Phase 0**: Updated `job_id` pattern to accept SHA256 hashes: `^([a-z]+-[a-f0-9]{8}|[a-f0-9]{64})$`
> - **Phase 1**: Added `_notify()`, `_get_notification_job_id()`, `_get_target_user_email()` to FifoQueue base class
> - **Phase 1**: Added user_service lookup for email resolution in `_get_target_user_email()`
> - **Phase 2**: Migrated all 7 `_emit_speech` calls in `running_fifo_queue.py` to `_notify()`
> - **Phase 2**: Migrated blocking query (line 480) in `todo_fifo_queue.py` to `notify_user_sync()` with retry
> - **Phase 3**: Commented out legacy `_emit_speech()` in `fifo_queue.py`
> - **Phase 3**: Set `emit_speech_callback=None` in `main.py` queue initialization
>
> ### Session Summary
> Major TTS migration implementing the plan from Session 96. Replaced legacy WebSocket-based `_emit_speech` with notification service. Added `suppress_ding=True` for conversational TTS without notification sounds. Job cards now receive TTS via job_id routing.
>
> ---

> **✅ SESSION 96 COMPLETE**: TODO Review + TTS Investigation Planning (2026.01.23)
> **Owner**: claude.code@lupin.deepily.ai#2adf6d65
>
> ### Accomplishments
> - Reviewed all outstanding TODO items from Session 95
> - Marked as DONE: Podcast Generator Full Audio Test, Job Queue Progressive Disclosure UI
> - Added new future TODO: TTS Consolidation Investigation
> - Began TTS consolidation research - investigated `_emit_speech` (5 callers in queue code) vs notification service
> - **Key user correction**: MCP is facade over notification service; latency assumptions need re-evaluation
> - Created investigation plan: `/home/rruiz/.claude/plans/modular-wondering-fox.md`
>
> ### Session Summary
> Light session focused on TODO management and initial TTS architecture investigation. Investigation deferred to tomorrow pending deeper analysis of notification service capabilities (not just MCP facade).
>
> ---

> **✅ SESSION 95 COMPLETE**: Bug Fix Mode (2026.01.23)
> **Owner**: claude.code@lupin.deepily.ai#6fa77d02
>
> ### Fixes
> - **Fix 1**: cosa-voice MCP project detection order bug (CoSA detected as Lupin) - Fixed prior to session start
> - **Fix 2**: LanceDB/PostgreSQL permissions issue (from Session 94 TODO #1)
>   - Root cause: `lupin.lancedb` owned by root, `postgresql-dev-data` had 700 permissions (no group access)
>   - Fixed: Changed ownership and permissions via sudo chown/chmod
>   - Impact: Database recreation and embedding cache errors in smoke tests now resolved
> - **Fix 3**: Podcast Generator - English audio generated when not requested
>   - Root cause: `scripts_by_language` unconditionally initialized with English (`orchestrator.py:441-442`)
>   - Fixed: Conditional English inclusion - only add to dict if `"en" in self.target_languages`
>   - Updated notification message for non-English-only generation
>   - File: `src/cosa/agents/podcast_generator/orchestrator.py` (lines 441-462)
>   - Smoke Tests: 10/10 PASSED
> - **Fix 4**: Podcast Generator - English audio notifications missing language identifier
>   - Root cause: `do_audio_only_async()` used generic messages without language specification
>   - Fixed: Added "English" to notification messages (matching `do_all_async()` pattern)
>   - File: `src/cosa/agents/podcast_generator/orchestrator.py` (lines 917-919, 943)
>   - Commit: 329ad9b (COSA repo)
>
> ### Session Summary
> - **Total Fixes**: 4
> - **Files Changed**: orchestrator.py, lupin.lancedb permissions, postgresql-dev-data permissions
> - **Commits**: 9df9149 (Lupin), 329ad9b (COSA)
>
> **Status**: Session closed 2026.01.23
>
> ---

> **✅ SESSION 94 COMPLETE**: Queue System Class Hierarchy Unification (2026.01.22)
> - **Goal**: Unify naming conventions across AgentBase, SolutionSnapshot, and AgenticJobBase
> - **Phase 1**: Cleared LanceDB database for schema-free refactoring (fresh start)
> - **Phase 2**: Added unified properties to all three classes:
>   - `AgenticJobBase`: Added `question`, `answer`, `job_type`, `created_date` properties
>   - `SolutionSnapshot`: Added `job_type` property (maps to `agent_class_name`)
>   - `AgentBase`: Added `job_type` (class name), `created_date` properties
> - **Phase 3**: Created `QueueableJob` Protocol (`src/cosa/rest/queue_protocol.py`) documenting unified interface
> - **Phase 4**: Simplified `queues.py` - replaced `getattr()` chains with direct attribute access using `job.job_type`
> - **Files Created**: `src/cosa/rest/queue_protocol.py` (~180 lines)
> - **Files Modified**: `agentic_job_base.py`, `agent_base.py`, `solution_snapshot.py`, `queues.py`
> - **Smoke Tests**: All PASSED (AgenticJobBase, SolutionSnapshot, AgentBase, QueueableJob Protocol)
> - **Benefit**: Clean code, type safety via Protocol, consistent `job_type` across all job types, IDE autocomplete works
>
> ---
>
> **📋 IMMEDIATE TODO**:
> 1. **Deep Research UI Card**: Simple UI for creating new deep research tasks
> 2. **Podcast Generator UI Card**: Simple UI for creating new podcast generation tasks
>
> **📋 FUTURE TODO**:
> 1. **Deep Research Phase 8**: COSA Router Integration for natural language job submission
> 2. **Podcast Generator Phase 3**: COSA Router Integration for natural language podcast generation
>
> **✅ Recently Completed**:
> - Conversation Identity Phases 4-5 (Session 101)
>
> **✅ COMPLETED (Session 98)**:
> - ~~🔊 TTS Consolidation Investigation~~ - Migrated to notification service
> - ~~🧪 Phase 7 Browser Testing~~ - Job Queue Progressive Disclosure UI verified
> - ~~🔬 Deep Research Queue Integration - BROWSER TESTING~~ - Phase 6 frontend notification routing working
>
> **✅ SESSION 93 COMPLETE**: Podcast Generator Multi-Language Translation Support (2026.01.22)
> - **Feature**: Added support for generating podcasts in multiple languages (English default, Spanish opt-in)
> - **ISO Codes**: en, es, es-ES (Castilian), es-MX (Mexican), es-AR (Argentinian)
> - **Native Generation**: Claude generates scripts directly in target language (not post-translation)
> - **Phase 4b Loop**: After English approval, generates/reviews each additional language with full user approval flow
> - **TTS Support**: Language-aware voice lookup with multilingual model fallback (eleven_multilingual_v2)
> - **Prosody Validation**: Verifies prosody markers preserved across translations
> - **CLI**: Added `--languages` / `-l` argument (e.g., `--languages en,es-MX`)
> - **Files Created/Modified**: config.py, tts_client.py, prompts/script_generation.py, state.py, orchestrator.py, __main__.py, lupin-app.ini, lupin-app-splainer.ini
> - **Smoke Tests**: 10/10 PASSED
>
> ---
>
> **📋 TODO FOR NEXT SESSION (Session 94)**:
> 1. **🏗️ DESIGN: Unify SolutionSnapshot/AgenticJobBase Interface**: Queue system mixes `SolutionSnapshot` (legacy COSA) and `AgenticJobBase` (new agentic jobs) without shared interface. Current `getattr()` hack in `queues.py:508-517` needs principled design. Options: Protocol/Interface, Adapter Pattern, Attribute Alignment.
> 2. **🧪 Phase 7 Browser Testing**: Continue verification - spinning indicator, live duration timer, abstract/report link, cost summary, error display.
> 3. **🔬 Deep Research Queue Integration - BROWSER TESTING**: Test Phase 6 frontend notification routing.
> 4. **🎙️ Podcast Generator - FULL AUDIO GENERATION TEST**: Ready for full 20-segment test.
> 5. **⏰ Job Queue Progressive Disclosure UI - MANUAL TESTING**: See plan: `/home/rruiz/.claude/plans/cheeky-leaping-scone.md`
> 6. **Deep Research Phase 8 (PENDING)**: COSA Router Integration for natural language job submission
> 7. **Conversation Identity Phases 4-5 (FUTURE)**: Phase 1 complete. Remaining: Phase 4 = AgentBase History, Phase 5 = Lifecycle.
> 8. Voice discovery/configuration for notification TTS UI still pending
> 9. **Future TODO**: Config mapping female/male voices, consolidate voice_io.py, evaluate config.py dataclasses, migrate /api/deep-research/report
>
> **🔧 SESSION 91 COMPLETE**: Phase 7 Browser Testing - Bug Fixes in get_job_interactions Endpoint
> - **BUG #1**: Wrong import path in `queues.py:484` - changed `cosa.rest.db.models.notification` to `cosa.rest.postgres_models`
> - **BUG #2**: AttributeError - `MockAgenticJob` missing `agent_class_name`, `question`, `answer`, `created_date` attributes
> - **TEMP FIX**: Used `getattr()` with safe defaults in `queues.py:508-517` (marked as needing proper design)
> - **DESIGN TODO**: Need principled interface contract for queue items (SolutionSnapshot vs AgenticJobBase)
> - **Files Modified**: `src/cosa/rest/routers/queues.py` (2 edits)
>
> **✅ SESSION 90 COMPLETE**: Podcast Generator Notification Enhancements + Bug Discovery
> - **Implemented**: Clickable links (script, audio, research) and audio cost tracking in all 3 notification methods
> - **Changes**: Added `character_count` to `TTSSegmentResult`, `ELEVENLABS_COST_PER_1K_CHARS` constant, fixed `do_all_async`/`do_review_only_async`/`do_audio_only_async` notifications
> - **Bug Found**: Research link shows "edit-mode" in audio-only mode - needs fix (see TODO #1)
> - **Smoke Tests**: 10/10 PASSED
> - **Files**: `tts_client.py` (+2 lines), `orchestrator.py` (+60 lines)
>
> **✅ SESSION 89 COMPLETE**: Bug Fix Mode - Gist Enhancement
> - **Fix 1**: Enhance Session Gist Generation with Abstract Fields (commit: f24337f)
> - **Details**: Frontend now collects both messages and abstracts; backend prioritizes first 5 abstracts + first 5 messages for richer gist generation; CSS width increased from 180px to 225px
> - **Files**: notifications.js, notifications.py, notifications.css
>
> **✅ SESSION 88 COMPLETE**: Bug Fix Day - Multiple notification/UI bugs fixed in single session.
> - **Fix 1**: Clear-All-Notifications bulk delete endpoint (notifications.py, notification_repository.py, notifications.js)
> - **Fix 2**: PostgreSQL Backup Integration via pg_dump (backup-postgres.sh, backup.sh, rsync-exclude.txt)
> - **Status**: All fixes complete and tested.
>
> **🧪 SESSION 87 COMPLETE**: Phase 7 Browser Testing + Mock Job User Association Bug Fix. CURL testing complete, browser UI testing ongoing.
>
> **✅ SESSION 86 COMPLETE**: Podcast Generator Phase 2 Bug Fixes + Progress Enhancement. See details below.
>
> **🧪 SESSION 85 AWAITING BROWSER TESTING**: Phase 7 - Unified Queue View + MockAgenticJob Test Harness. See details below.
>
> **✅ SESSION 84 COMPLETE**: Notification UI Tweaks - System Status Refresh Button. See details below.
>
> **✅ SESSION 83 COMPLETE**: Deep Research API Testing + Phase 5-6 Implementation. See details below.
>
> **✅ SESSION 82 COMPLETE**: Podcast Generator Phase 2 Enhancements - Audio-Only Flag, Smoke Tests & Progress Notifications. See details below.
>
> **✅ SESSION 81 COMPLETE**: Docker Path Bug Fixes. See details below.

> **🎯 CURRENT**: 2026.01.21 (Session 87) - PHASE 7 BROWSER TESTING + MOCK JOB BUG FIX! Testing Phase 7 Unified Queue View with MockAgenticJob. **BUG DISCOVERED**: Mock jobs weren't appearing in user's queue view despite being pushed to the queue. Jobs showed in WebSocket events but API returned empty arrays with `filtered_by: user_id`. **ROOT CAUSE**: `mock_job.py` called `todo_queue.push(job)` directly, bypassing the `UserJobTracker.associate_job_with_user()` call that happens in `TodoFifoQueue.push_job()`. Jobs were in the queue but not associated with the submitting user. **FIX**: Added import for `user_job_tracker` and two association calls after push: `user_job_tracker.associate_job_with_user(job.id_hash, user_id)` and `user_job_tracker.associate_job_with_session(job.id_hash, session_id)`. **CURL TESTING COMPLETE**: (1) `failure_probability: 0` - Jobs correctly flow through todo → running → done queues ✅, (2) `failure_probability: 1` - Jobs correctly flow through todo → running → dead queues ✅. **FILES MODIFIED**: `src/cosa/rest/routers/mock_job.py` (+3 lines: import + 2 association calls). **STATUS**: CURL testing complete, browser UI testing in progress. 🧪🔄
>
> **🎯 PREVIOUS**: 2026.01.20 (Session 86) - PODCAST GENERATOR PHASE 2 BUG FIXES + PROGRESS ENHANCEMENT! Manual end-to-end testing session that discovered and fixed 4 bugs, plus implemented a progress reporting enhancement. **PART 1 - MAX-SEGMENTS FLAG**: Added `--max-segments` / `-m` CLI flag to limit TTS generation to first N segments (cost control during testing). Modified `__main__.py` (+15 lines), `orchestrator.py` (+15 lines: `max_segments` parameter in `__init__` and `from_saved_script()`, segment slicing in `_generate_audio_async()`). **PART 2 - BUG #1: WRONG USER_ID IN OUTPUT PATH**: Output path used default `user@example.com` instead of actual user. **FIX**: Added `extract_user_id_from_path()` function that parses email from paths like `io/podcasts/{email}/script.md`. Auto-extracts when `--user-id` not explicitly provided. **PART 3 - BUG #1b: DUPLICATE "PODCAST" IN FILENAME**: Audio filename template `{topic}-podcast.mp3` combined with topic "untitled-podcast" created "untitled-podcast-podcast.mp3". **FIX**: Changed template in `config.py` from `{timestamp}-{topic}-podcast.mp3` to `{timestamp}-{topic}.mp3`. **PART 4 - BUG #2/3: CLICKABLE LINKS IN NOTIFICATIONS**: MP3 and script paths were plain text, not clickable. **FIX**: Created new generic file serving endpoint `/api/io/file` in `src/cosa/rest/routers/io_files.py` (~170 lines). Supports .md, .mp3, .pdf, .wav, .txt, .json with proper content-type detection. Security: path validation, directory traversal prevention. Updated `orchestrator.py` completion notification to use markdown links: `[View Script](/api/io/file?path=...)`, `[Download MP3](/api/io/file?path=...)`. Registered router in `main.py`. **PART 5 - BUG #4: DURATION SHOWS 0.0 MINUTES**: Script loaded with `Duration: ~0.0 minutes`. **ROOT CAUSE**: Claude may not provide `estimated_duration_minutes` in response, and fallback was missing. **FIX**: Added `calculated_duration_minutes` property to `PodcastScript` in `state.py` that calculates from word count (~150 words/minute speaking rate) when estimate is 0. Updated orchestrator notifications to use `calculated_duration_minutes`. **PART 6 - PROGRESS ENHANCEMENT**: Changed progress reporting from "every 10 segments" to "every 10% milestone". **BEFORE**: Notifications at segment 10, 20, 30... (variable count). **AFTER**: Notifications at 10%, 20%, 30%... 100% (consistent ~10 notifications). Added `_reported_milestones` set tracking in orchestrator, updated `_audio_progress_callback()` to calculate percentage milestones. **FILES CREATED**: `src/cosa/rest/routers/io_files.py` (~170 lines). **FILES MODIFIED**: `src/cosa/agents/podcast_generator/__main__.py` (+50 lines), `src/cosa/agents/podcast_generator/orchestrator.py` (+50 lines), `src/cosa/agents/podcast_generator/config.py` (1 line), `src/cosa/agents/podcast_generator/state.py` (+20 lines), `src/fastapi_app/main.py` (+2 lines). **SMOKE TESTS**: 10/10 PASSED. **ENDPOINT VERIFIED**: `curl "http://localhost:7999/api/io/file?path=..."` returns correct content. **STATUS**: All bug fixes complete, tested with `--max-segments 3`, ready for full audio generation test. 🎙️🔧✅

> **🎯 PREVIOUS**: 2026.01.20 (Session 85) - PHASE 7: UNIFIED QUEUE VIEW + MOCKAGENTICJOB TEST HARNESS! Implemented comprehensive Phase 7 for Deep Research background job integration. **PART 1 - MOCKAGENTICJOB TEST HARNESS**: Created zero-cost testing infrastructure for the queue system at `src/cosa/agents/test_harness/`. `MockAgenticJob` class simulates long-running agentic jobs without inference costs. Features: configurable iteration count (random or fixed), configurable sleep duration between phases, configurable failure probability for testing dead queue, real notifications via cosa-voice MCP with `job_id` routing, mock artifacts (report_path, abstract, cost_summary) for UI testing. **API ENDPOINT**: `POST /api/mock-job/submit` accepts parameters: `iterations_min/max`, `sleep_min/max`, `failure_probability`, `fixed_iterations`, `fixed_sleep`, `description`. Returns job_id, queue_position, and config summary. **PART 2 - BACKEND QUEUE API ENHANCEMENTS**: Modified `src/cosa/rest/routers/queues.py` to expose job artifacts in metadata. Done queue now includes: `report_path`, `abstract`, `cost_summary`, `started_at`, `completed_at`, `duration_seconds`, `status`, `error`. Todo/Run queues now return `*_jobs_metadata` arrays (previously HTML only). Auto-detection of AgenticJobBase vs SolutionSnapshot objects. **PART 3 - COSA-VOICE JOB_ID PARAMETER FIX**: Updated `voice_io.py` and `cosa_interface.py` to accept and pass through `job_id` parameter for notification routing to job cards. **PART 4 - FRONTEND JAVASCRIPT ENHANCEMENTS**: Modified `notifications.js` with ~150 new lines. Added `durationTimers` Map for tracking running job timers. Enhanced `renderJobCard()` to show: (1) Running jobs: spinning status indicator, live duration timer with auto-update every second, (2) Done jobs: abstract section with green left border, "View Full Report" button, cost summary grid (cost/duration/tokens), completion badge (✓/✗), (3) Dead jobs: error display section with red styling, failed badge. New functions: `formatDuration()` (seconds → "Xm Ys"), `startDurationTimer()`, `stopDurationTimer()`, `stopAllDurationTimers()`. **PART 5 - CSS STYLING**: Added ~150 lines to `notifications.css` for new components: `.status-indicator.spinning` with rotation animation, `.completion-badge.success/failed`, `.job-duration-line` with blue background, `.job-abstract` with green left border, `.report-link-btn` with hover state, `.job-cost-summary` with yellow grid, `.job-error` with red styling. **FILES CREATED**: `src/cosa/agents/test_harness/__init__.py`, `src/cosa/agents/test_harness/mock_job.py` (~340 lines), `src/cosa/agents/test_harness/README.md` (~180 lines), `src/cosa/rest/routers/mock_job.py` (~130 lines). **FILES MODIFIED**: `src/fastapi_app/main.py` (router registration), `src/cosa/rest/routers/queues.py` (~80 lines), `src/cosa/agents/deep_research/voice_io.py` (+job_id param), `src/cosa/agents/deep_research/cosa_interface.py` (+job_id param), `src/fastapi_app/static/js/notifications.js` (~150 lines), `src/fastapi_app/static/css/notifications.css` (~150 lines). **VERIFICATION**: Python syntax checks PASSED, JavaScript syntax check PASSED, MockAgenticJob smoke test PASSED. **PLAN FILE**: `/home/rruiz/.claude/plans/tidy-doodling-pizza.md` (Phase 7 status: AWAITING BROWSER TESTING). **STATUS**: Code implementation complete, awaiting browser testing and debugging. 🧪🔬

> **🎯 PREVIOUS**: 2026.01.20 (Session 84) - NOTIFICATION UI TWEAKS - SYSTEM STATUS REFRESH BUTTON! Quick enhancement session adding a refresh button to the System Status section in the notifications page. **FEATURE**: Added ↻ refresh button to "System Status" section header that refreshes all status information without full page reload. Clicking triggers: (1) WebSocket connection state evaluation (readyState mapping), (2) Auth verification via token check with auto-refresh if expired, (3) Session ID display updates, (4) Health monitor status refresh via existing `checkWebSocketHealth()`. **VISUAL FEEDBACK**: Button spins during refresh using existing `@keyframes spin` animation, disables to prevent double-clicks. **FILES MODIFIED**: (1) `notifications.html:361-370` - Added refresh button wrapped in `.section-header-actions` div with `event.stopPropagation()` to prevent section collapse, (2) `notifications.css:121-150` - Added styles for `.section-header-actions` (flexbox container), `.refresh-link` (button base), hover/disabled/spinning states, (3) `notifications.js:1071-1188` - Added 4 methods: `refreshAllStatus()` (main orchestrator), `refreshWebSocketStatus()` (evaluates queueWS/audioWS readyState), `refreshAuthStatus()` (token validation with refresh), `refreshSessionDisplay()` (updates session ID spans). **PATTERN**: Matches existing "↻ Reload" button in Config section. **STATUS**: Implementation complete. 🔄✅
>
> **🎯 PREVIOUS**: 2026.01.20 (Session 83) - DEEP RESEARCH API TESTING + PHASE 5-6 IMPLEMENTATION! Multi-part session implementing auth testing documentation and Deep Research notification routing. **PART 1 - AUTH TESTING QUICK-REFERENCE**: Created `src/tests/AUTH-TESTING-GUIDE.md` (~120 lines) documenting the critical distinction between destructive (integration) and non-destructive (smoke/unit/manual) testing contexts. Includes Python and CURL patterns for authenticated API testing with environment variable-based credentials (security best practice). **PART 2 - DEEP RESEARCH SUBMIT SMOKE TEST**: Created `src/tests/smoke/test_deep_research_submit_smoke.py` (~115 lines) to test `POST /api/deep-research/submit` endpoint. 5-step test: login, submit job, verify response structure, verify expected values (status=queued, job_id format), check queue access. Ran test successfully with `ricardo.felipe.ruiz@gmail.com` - job `dr-c0ed19ef` queued at position 1. **PART 3 - PHASE 5: cosa-voice MCP ENHANCEMENT**: Added `job_id: Optional[str]` parameter to notification system for job-based routing. **Files modified**: (1) `src/cosa/cli/notification_models.py` - Added `job_id` field with regex validation `^[a-z]+-[a-f0-9]{8}$` to both `NotificationRequest` and `AsyncNotificationRequest`, updated `to_api_params()` methods. (2) `src/lupin_mcp/cosa_voice_mcp.py` - Added `job_id` parameter to all 4 tools: `notify()`, `ask_yes_no()`, `converse()`, `ask_multiple_choice()`. Backward compatible: `job_id=None` uses existing routing. **PART 4 - PHASE 6: NOTIFICATION ROUTER (FRONTEND)**: Implemented job-based notification routing in UI. **Files modified**: (1) `src/fastapi_app/static/js/notifications.js` (+150 lines) - Added `registeredJobs` Map for tracking active jobs (todo/running), `updateJobRegistration()` called when queues load, modified `handleNotificationUpdate()` to check for `job_id` and route to job card, added `appendNotificationToJobCard()`, `createJobActivityLog()`, `createActivityLogEntry()` methods. (2) `src/fastapi_app/static/css/notifications.css` (+45 lines) - Activity log styling with priority-based border colors. **ROUTING FLOW**: `response_requested=true` → Action Required card (unchanged), `job_id + registered` → Job card activity log (NEW), else → Sender card (unchanged). **FILES CREATED**: `src/tests/AUTH-TESTING-GUIDE.md`, `src/tests/smoke/test_deep_research_submit_smoke.py`. **FILES MODIFIED**: `src/cosa/cli/notification_models.py`, `src/lupin_mcp/cosa_voice_mcp.py`, `src/fastapi_app/static/js/notifications.js`, `src/fastapi_app/static/css/notifications.css`. **PLAN FILE**: `/home/rruiz/.claude/plans/tidy-doodling-pizza.md` (Phases 5-6 now complete). **STATUS**: Implementation complete, awaiting browser testing to verify Phase 6 notification routing. 🔬📋✅
>
> **🎯 PREVIOUS**: 2026.01.20 (Session 82) - PODCAST GENERATOR PHASE 2 ENHANCEMENTS! Continuation session implementing progress notification improvements and audio-only CLI mode for the Podcast Generator. **PART 1 - SMOKE TEST RUNNER UPDATES**: Added `tts_client` and `audio_stitcher` modules to the smoke test runner in `__main__.py`. Module count increased from 8 to 10. All 10 smoke tests passing. **PART 2 - AUDIO-ONLY CLI FLAG**: Added `--generate-audio` / `-a` flag to generate audio from an existing script (skips script generation and review phases). New `run_audio_generation()` async function loads script via `from_saved_script()`, calls new `do_audio_only_async()` method that jumps directly to Phase 5 (GENERATING_AUDIO) → Phase 6 (STITCHING_AUDIO) → COMPLETED. **PART 3 - PROGRESS NOTIFICATION ENHANCEMENTS**: (1) **ETA Tracking**: Added timing tracking in `generate_all_segments()` - calculates average segment duration and estimates remaining time. Progress callback signature updated to include `eta_seconds: float`. Notifications now show "Audio progress: 20/47 segments (42%), ~45s remaining". (2) **Retry Notifications**: Added `retry_callback` parameter to `PodcastTTSClient`. When a segment fails and will be retried, sends low-priority notification: "Segment 15 (Nora) failed, retrying (2/3)...". (3) **Callback Methods**: Added `_audio_retry_callback()` method to orchestrator, updated `_audio_progress_callback()` to accept and display ETA. **NOTIFICATION PRIORITY CLARIFICATION**: Progress and retry notifications use "low" priority (ding only, no TTS). Partial failure prompts use blocking `ask_yes_no()` which gets high priority (spoken via TTS). **FILES MODIFIED**: `src/cosa/agents/podcast_generator/__main__.py` (+70 lines: run_audio_generation, --generate-audio arg, smoke test modules), `src/cosa/agents/podcast_generator/orchestrator.py` (+80 lines: do_audio_only_async, _audio_retry_callback, updated _audio_progress_callback with ETA), `src/cosa/agents/podcast_generator/tts_client.py` (+40 lines: retry_callback parameter, timing tracking, ETA calculation). **SMOKE TESTS**: 10/10 PASSED (config, state, prompts.script_generation, prompts.personality, cosa_interface, voice_io, api_client, tts_client, audio_stitcher, orchestrator). **CLI USAGE**: `python -m cosa.agents.podcast_generator --generate-audio path/to/script.md --cli-mode --debug`. **PLAN FILE**: `/home/rruiz/.claude/plans/elegant-fluttering-narwhal.md`. **STATUS**: Implementation complete, awaiting manual end-to-end testing. 🎙️📊✅
>
> **✅ SESSION 79 BRIEF**: API Testing Setup - Server health verified, authentication approach discussed. User will provide credentials in Session 80 for Deep Research API testing.
>
> **✅ SESSION 78 COMPLETE**: Deep Research CLI UX Improvements + Docker Path Bug Fixes. See details below.
>
> **✅ SESSION 77 COMPLETE**: Multiple-Choice TTS Verification Testing. See details below.
>
> **✅ SESSION 76 COMPLETE**: Podcast Generator Save Timing & Version Suffix Fixes. See details below.
>
> **✅ SESSION 75 COMPLETE**: Podcast Generator Bugs 7 & 8 Fixed (iterative review + filename preservation). See details below.

> **🎯 CURRENT**: 2026.01.19 (Session 80) - PODCAST GENERATOR PHASE 2 PLANNING! Created comprehensive implementation plan for TTS audio generation feature. **SCOPE**: Convert approved podcast scripts into spoken MP3 files using ElevenLabs multi-voice synthesis. **ARCHITECTURE DECISIONS**: (1) Use pydub library for audio processing (PCM→MP3, silence insertion, concatenation), (2) ElevenLabs PCM 24000 output format (matches existing speech.py pattern), (3) Memory buffer storage during generation (write only final MP3), (4) Per-segment progress notifications. **FILES TO CREATE**: (1) `tts_client.py` (~250 lines) - ElevenLabs WebSocket batch generation with TTSSegmentResult dataclass, voice mapping, retry logic, (2) `audio_stitcher.py` (~150 lines) - pydub-based concatenation with 300ms silence on speaker changes. **FILES TO MODIFY**: (1) `orchestrator.py` (+80 lines) - Add Phase 5 (GENERATING_AUDIO) and Phase 6 (STITCHING_AUDIO) after script approval, (2) `requirements.txt` - Add pydub==0.25.1. **KEY PATTERNS**: WebSocket logic extracted from `speech.py:863-993`, voice mapping (Alex→Sarah voice, Jordan→Arnold voice), error handling with 3x retry and partial failure recovery. **VERIFICATION**: Smoke tests per module, manual integration test with real ElevenLabs API (~$2.40/podcast). **PLAN FILE**: `/home/rruiz/.claude/plans/compressed-marinating-tarjan.md`. **STATUS**: Planning complete, ready for implementation in next session. 🎙️📝✅
>
> **🎯 PREVIOUS**: 2026.01.19 (Session 78) - DEEP RESEARCH CLI UX IMPROVEMENTS + DOCKER PATH BUG FIXES! Multi-part session implementing planned UX improvements and fixing discovered bugs. **PART 1 - MULTIPLE-CHOICE CLARIFICATION UX**: Implemented plan from previous session to improve query clarification UX. When Deep Research CLI needs clarification, it now presents structured multiple-choice options instead of free-text input. **CHANGES**: (1) `prompts/clarification.py` - Added `options` array to JSON schema with 2-4 label/description pairs, updated all examples. (2) `voice_io.py` - Updated `choose()` to accept `Union[List[str], List[dict]]` with `allow_custom` parameter, CLI fallback shows descriptions. (3) `cli.py` - Uses `voice_io.choose()` when ≥2 options provided, falls back to `get_input()` otherwise. **PART 2 - REPORT VIEWER BROKEN LINK**: User reported 404 error when clicking "View Report" link after Deep Research completion. **ROOT CAUSE**: CLI sent absolute path (`/mnt/DATA01/.../io/deep-research/user@email/file.md`) but API expected relative path (`user@email/file.md`). **FIX**: `cli.py` now extracts relative path from `io/deep-research` base before URL encoding. **PART 3 - DOCKER VOLUME MOUNT MISMATCH**: Report viewer still returned 404 even with relative path fix. **ROOT CAUSE**: Docker container mounted `io/` to `/var/io` but code expected `/var/lupin/io`. **DIAGNOSIS**: `get_project_root()` returns `/var/lupin`, so code looks in `/var/lupin/io/deep-research/`. But Docker mount was `-v .../io:/var/io` (wrong destination). **FIXES**: (1) Created symlink inside container: `ln -s /var/io /var/lupin/io` (immediate fix). (2) Updated `lupin_client.py` - Changed 4 hardcoded `/var/io/` paths to `/var/lupin/io/`. (3) Updated `start-docker-lupin.sh` - Changed line 358 from `-v "$LUPIN_ROOT/io:/var/io"` to `-v "$LUPIN_ROOT/io:/var/lupin/io"` (permanent fix). **FILES MODIFIED**: `src/cosa/agents/deep_research/prompts/clarification.py`, `src/cosa/agents/deep_research/voice_io.py`, `src/cosa/agents/deep_research/cli.py`, `src/lib/clients/lupin_client.py`, `$DEEPILY_PROJECTS_DIR/scripts/server/start-docker-lupin.sh`. **SMOKE TESTS**: clarification.py ✓, voice_io.py ✓, CLI dry-run ✓. **STATUS**: All fixes complete and verified. 🔧✅🐳✅

> **🎯 PREVIOUS**: 2026.01.19 (Session 77) - MULTIPLE-CHOICE TTS VERIFICATION TESTING! Verification session to confirm Sessions 71-72 fixes still work correctly. **TESTS PERFORMED**: (1) Ran smoke tests for `notification_utils`, `deep_research/cosa_interface`, and `podcast_generator/cosa_interface` - all passed. (2) Sent live `ask_multiple_choice()` notifications to verify TTS behavior. (3) Confirmed options are NOT read aloud in TTS (UI-only display working). (4) Confirmed multi-select hint ("You can select multiple options") works correctly. (5) Noted: high/urgent priority required for TTS to speak. **KEY FINDING**: Session 71-72 fixes remain functional - no regressions detected. **FILES VERIFIED**: `src/cosa/utils/notification_utils.py`, `src/cosa/agents/deep_research/cosa_interface.py`, `src/cosa/agents/podcast_generator/cosa_interface.py`. **STATUS**: Verification complete, no changes needed. ✅🔊
>
> **🎯 PREVIOUS**: 2026.01.19 (Session 76) - PODCAST GENERATOR SAVE TIMING & VERSION SUFFIX FIXES! Fixed two issues from manual testing of `--edit-script` mode. **ISSUE 1 - PREMATURE SAVE**: Script was being saved at the TOP of the review loop BEFORE user made any decision - debug output showed "Script saved to: ..." before presenting review choices. **ROOT CAUSE**: Both `do_all_async()` and `do_review_only_async()` called `_save_script_async()` immediately when entering the review `while` loop. **FIX**: Moved save to AFTER user approves (final save) or AFTER revision is generated (versioned save). Now shows "Will save to:" preview path instead of actually saving. **ISSUE 2 - NO VERSION SUFFIX**: Revised scripts overwrote the original file instead of creating versioned copies. User expected: original preserved, revisions as `-v2.md`, `-v3.md`. **ROOT CAUSE**: `_save_script_async()` always reused `self._original_script_path` without version suffix. **FIX**: Added `is_revision: bool = False` parameter to `_save_script_async()`. When `is_revision=True`, generates versioned path: `stem-v{revision_num}.md`. Example: `2026.01.19-153550-voice-script.md` → `2026.01.19-153550-voice-script-v2.md`. **FILES MODIFIED**: `src/cosa/agents/podcast_generator/orchestrator.py` (~60 lines: save timing in both review methods + version suffix in _save_script_async). **SMOKE TESTS**: 8/8 PASSED. **PLAN FILE**: `/home/rruiz/.claude/plans/humble-dancing-beacon.md`. **STATUS**: Implementation complete, awaiting manual verification. 🎙️🔧✅
>
> **🎯 PREVIOUS**: 2026.01.19 (Session 75) - PODCAST GENERATOR BUGS 7 & 8 FIXED! User reported two critical bugs from manual testing of the `--edit-script` feature. **BUG 7 - NON-DESCRIPTIVE FILENAME**: Revised scripts were saved as `2026.01.19-160333-untitled-podcast-script.md` instead of preserving the original filename. Root cause: `_save_script_async()` generated a NEW filename each time based on current `script.title`. **FIX**: Added `_original_script_path` attribute to track original filename across revisions. Updated `from_saved_script()` to store original path, modified `_save_script_async()` to check and reuse original path for all subsequent saves. **BUG 8 - REVIEW NOT ITERATIVE (CRITICAL)**: After providing revision feedback and LLM regenerating the script, the process immediately EXITED instead of looping back to show the updated script for further review. User expected: review → feedback → regenerate → review again → repeat until explicit approval. Root cause: No `while` loop around review phase - code fell through to `script_approved = True` after revision. **FIX**: Wrapped entire review phase in `while not script_approved:` loop in BOTH `do_all_async()` and `do_review_only_async()` methods. Loop structure: (1) Save current draft (overwrites previous), (2) Present script preview with file path, (3) Handle choice - "Approve" exits loop, "Revise" or "Other" triggers regeneration and loops back, "Cancel" cleans up and returns None. **KEY CODE CHANGES**: (1) Added `self._original_script_path: Optional[str] = None` in `__init__`, (2) Store path in `from_saved_script()` with `agent._original_script_path = script_path`, (3) Modified `_save_script_async()` to reuse original path or generate new one only on first save, (4) Rewrote Phase 4 review section with iterative loop pattern. **FILES MODIFIED**: `src/cosa/agents/podcast_generator/orchestrator.py` (~80 lines: filename tracking + iterative review loop in both methods). **SMOKE TESTS**: 8/8 PASSED (config, state, prompts.script_generation, prompts.personality, cosa_interface, voice_io, api_client, orchestrator). **PLAN FILE**: `/home/rruiz/.claude/plans/mellow-chasing-tiger.md`. **STATUS**: Bug fixes complete, awaiting manual verification. 🎙️🐛✅
>
> **✅ SESSION 74 COMPLETE**: Podcast Generator Bug Fixes + Script Resume Feature. See details below.
>
> **✅ SESSION 74b COMPLETE**: Progressive Narrowing Test Harness - Isolated testing module for Deep Research theme clustering. See details below.
>
> **✅ SESSION 73 COMPLETE**: Notification UI bug fixes and updates. See details below.
>
> **✅ SESSION 72 COMPLETE**: Unified `_format_questions_for_tts()` implementations into shared utility. See details below.
>
> **✅ SESSION 71 COMPLETE**: Fix duplicate multiple-choice option rendering in agent interfaces. See details below.
>
> **✅ SESSION 70 COMPLETE**: Podcast Generator Agent Phase 1 - Script generation infrastructure. See details below.
>
> **✅ SESSION 69b COMPLETE**: Deep Research Background Job Integration - Phases 1-4 Backend Implementation. See details below.
>
> **✅ SESSION 69 COMPLETE**: Robust right-justification for sender stats in notification UI. See details below.
>
> **✅ SESSION 68 COMPLETE**: Reduce TTS verbosity for ask_multiple_choice - options now UI-only, not spoken. See details below.
>
> **✅ SESSION 67 COMPLETE**: Fix Sender ID and Session Name Separation for Deep Research CLI. See details below.
>
> **✅ SESSION 66 COMPLETE**: Fixed literal `\n` in abstract field breaking markdown rendering. See details below.
>
> **✅ SESSION 65 COMPLETE**: Markdown rendering for abstract field with XSS protection. See details below.
>
> **✅ SESSION 64 COMPLETE**: Deep Research Agent - Semantic Session IDs + Rate Limit Error Handling. See details below.
>
> **✅ SESSION 63 COMPLETE**: MCP Documentation Fix - `abstract` parameter. See details below.
>
> **✅ SESSION 62 COMPLETE**: Grace Period Message Bug Fix. See details below.
>
> **✅ SESSION 61 COMPLETE**: History Filter Race Condition Fix + Dropdown UX + UI Reorder. See details below.
>
> **✅ SESSION 60 COMPLETE**: Notifications UI Minor Tweaks - Action-required auto-expand, TTS queue empty state, Config reload button. See details below.
>
> **✅ SESSION 59 COMPLETE**: Deep Research Agent Voice-First CLI Testing + Notification Identity Implementation. See details below.
>
> **✅ SESSION 58 COMPLETE**: Gist Button UX, Recording Toggle Bug, Session Title Generation + Stop Token Sentinel Pattern. See details below.
>
> **✅ SESSION 57 COMPLETE**: Job Queue Progressive Disclosure UI - Full 6-phase implementation. See details below.
>
> **✅ COMPLETED**: Conversation Identity Architecture Phases 1-3 (Session 56) - parallel Claude Code sessions now distinguishable in notification UI. New sender_id format: `claude.code@{project}.deepily.ai#{session_id}`.

## Navigation

### Archive Links
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
- **Current Focus**: Cold Call Flow Path 1 - Claude Code UI Card Testing
- **Path 1 Plan**: `src/rnd/2026.01.08-cold-call-path-1-ui-card-plan.md`
- **Cold Call Flow Planning (updated)**: `src/rnd/2025.12.31-claude-code-via-mcp-and-cosa-vox/2026.01.02-03-cold-call-flow-planning.md`
- **Session 47 Plan File**: `/home/rruiz/.claude/plans/expressive-plotting-charm.md`
- **Project Status Overview**: `/home/rruiz/.claude/plans/clever-napping-clover.md`

### Quick Navigation
- **Run FastAPI server**: `src/scripts/run-fastapi-lupin.sh` (port 7999)
- **Run GUI client**: `src/scripts/run-lupin-gui.sh`
- **Integration tests**: `./src/tests/run-integration-tests.sh -v`
- **Smoke tests**: `src/scripts/run-websocket-smoke-tests.sh`

### Current Development Areas
- Directory Rename (COMPLETE - genie-in-the-box → lupin, Sessions 36-40)
- MCP Voice Integration (COMPLETE - Phases 1-5)
- Option A Dispatcher (COMPLETE - ClaudeCodeDispatcher working)
- Cold Call Flow Path 1 (IMPLEMENTED - UI Card needs testing, Session 47)
- Cold Call Flow Path 2 (DEFERRED - Intent parsing after Path 1 proven)
- Notifications UI (ONGOING - polish and improvements)
