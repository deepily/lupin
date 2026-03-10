# Lupin Project History

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
