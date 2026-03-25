# Bug Fix Queue

**Format Version**: 2.0
**Last Updated**: 2026-03-25T13:30:00

---

### Active Sessions

| Session ID | Started | Last Activity | Status |
|------------|---------|---------------|--------|
| 6d82cf6e | 2026-02-10T12:00:00 | 2026-02-10T23:30:00 | closed |
| 04aad364 | 2026-02-09T23:00:00 | 2026-02-10T09:30:00 | closed |
| 0266f064 | 2026-02-07T09:00:00 | 2026-02-08T00:30:00 | closed |
| 2417c2b5 | 2026-02-06T21:00:00 | 2026-02-07T00:15:00 | closed |
| 41d2e575 | 2026-02-06T09:00:00 | 2026-02-06T17:00:00 | closed |
| 662576da | 2026-02-05T09:00:00 | 2026-02-05T14:45:00 | closed |
| bcd6e830 | 2026-02-04T08:30:00 | 2026-02-04T10:00:00 | closed |
| bb3a5d21 | 2026-02-03T14:50:00 | 2026-02-03T19:45:00 | closed |
| d7da6d0d | 2026-02-03T13:15:00 | 2026-02-03T13:35:00 | stale |
| 590273af | 2026-02-03T10:00:00 | 2026-02-03T14:30:00 | stale |
| 649565dd | 2026-02-13T17:00:00 | 2026-02-14T23:59:00 | closed |
| 0a2fa054 | 2026-02-14T16:00:00 | 2026-02-14T16:30:00 | closed |
| 4949b964 | 2026-02-02T18:00:00 | 2026-02-02T23:05:00 | closed |
| 07b80074 | 2026-02-16T10:00:00 | 2026-02-16T10:00:00 | stale |
| a118cc5e | 2026-02-19T00:00:00 | 2026-02-20T00:00:00 | closed |
| ff1fffd0 | 2026-02-21T00:00:00 | 2026-02-21T00:00:00 | stale |
| e7bfdd1d | 2026-02-23T12:00:00 | 2026-02-23T21:20:00 | closed |
| e10e0f35 | 2026-02-24T00:00:00 | 2026-02-24T20:15:00 | closed |
| 7f9787a4 | 2026-02-26T12:20:00 | 2026-02-26T12:30:00 | closed |
| b6e79902 | 2026-02-27T09:00:00 | 2026-02-27T09:00:00 | stale |
| 10ff1e2a | 2026-02-28T10:00:00 | 2026-02-28T14:30:00 | closed |
| 0e73eb8e | 2026-02-28T21:00:00 | 2026-02-28T22:00:00 | closed |
| 98958f70 | 2026-02-28T23:00:00 | 2026-02-28T23:45:00 | closed |
| 9f656de9 | 2026-03-11T10:00:00 | 2026-03-12T17:30:00 | closed |
| 59afa5ba | 2026-03-12T17:25:00 | 2026-03-12T18:15:00 | committed |
| 135a6b16 | 2026-03-18T12:00:00 | 2026-03-18T12:00:00 | stale |
| 7d02176c | 2026-03-19T12:00:00 | 2026-03-19T13:00:00 | committed |
| cd0fd61a | 2026-03-23T16:30:00 | 2026-03-23T17:00:00 | committed |
| 0015f34e | 2026-03-24T12:00:00 | 2026-03-24T12:15:00 | committed |
| f52e3261 | 2026-03-24T15:00:00 | 2026-03-24T15:30:00 | committed |
| 1e9b946f | 2026-03-25T13:00:00 | 2026-03-25T13:30:00 | committed |

---

### Queued

(Available for any session to claim)

- [x] ~~**target_user "Cannot resolve" error in Docker**~~ → Session 304 | By: 05faae8b
- [x] ~~**Fuzzy matching via voice**~~ → Session 304 | By: 05faae8b
- [x] ~~**Job card contact failure**~~ → Session 304 | By: 05faae8b
- [x] ~~**Audio segment upload**~~ → Session 304 | By: 05faae8b
- [x] ~~**History archive needed** — history.md at 18,951 tokens (75.8%). Archive sessions older than 14 days to stay below 17k threshold.~~ (MEDIUM) → Completed 2026-03-11
- [x] ~~**TTS focus mode safety timeout** — Prevent permanent stuck state when TTS queue items fail to play. Implemented pause-aware safety timeout derived from notification's own `timeout_seconds` + 30s buffer.~~ → Completed 2026-03-11 | By: 9f656de9
- [x] ~~**Lupin/Notifications configuration** the use of `~/.notifications/config` and `~/.lupin/config` is ambiguous. Resolve.~~ → Session 337c | By: e8036972
- [x] ~~**Session ID drift across hooks after context clear** — After context clear, hooks used transient CC session_id instead of stable lockfile ID, causing split identity in hook-events.jsonl, listener log, and MCP metadata.~~ → Session 342 | By: 59afa5ba
---

### In Progress

(Claimed by a specific session)

(none)

---

### Completed

- [x] **set_session_topic() not propagating to notification UI header** → commit: f2420ed (Lupin), CoSA pending | By: 1e9b946f (Session 372b)
  - **Symptom**: MCP `set_session_topic()` writes to bridge file but UI `sender-session-name` span never updates
  - **Root Cause**: `session_name` field existed in model but server pipeline never plumbed it through `/api/notify` → `NotificationItem` → WebSocket
  - **Fix**: Added `SESSION_TOPIC` notification type, plumbed `session_name` through full pipeline, frontend intercept with anti-feedback
  - **Files**: `notification_models.py`, `notification_fifo_queue.py`, `notifications.py`, `cosa_voice_mcp.py`, `notifications.js`

- [x] **Action-required card stuck + WS send-after-close crash** → commit: d3ad8bf (Lupin), CoSA pending | By: f52e3261 (Session 371b)
  - **Symptom**: Notification card refuses dismissal (spinner cursor), FastAPI console spams RuntimeError on every WS disconnect
  - **Fix**: cancelActionRequired/submitResponse cleanup guards, audio WS timeout state cleanup, WebSocketDisconnect exception handling
  - **Files**: `notifications.js`, `websocket.py`

- [x] **Stop hook "Continue Session?" lacks project/task context** → commit: 47a3f8a | By: 0015f34e (Session 369b)
  - **Symptom**: Notification card shows generic "Continue Session?" with no project badge or session topic. User can't tell which session is asking.
  - **Fix**: Project badge from sender_id on all action-required cards, session topic pipeline (UI → listener → bridge → stop hook abstract), MCP tool
  - **Files**: `notifications.js`, `stop.py`, `cc_notification_listener.py`, `session_bridge.py`, `cosa_voice_mcp.py`

- [x] **WS queue crash (`app_verbose` undefined) + TTS focus mode crash (`state` undefined)** → commit: d7f00b5 | By: 0015f34e (Session 369)
  - **Symptom**: WebSocket queue handler crashes on every message receive, killing connection. Notifications stop until page refresh. TTS focus mode also crashes on playback complete.
  - **Root Cause 1**: `websocket_queue_endpoint()` extracts `app_debug` but omits `app_verbose` from `main_module` — NameError at line 488
  - **Root Cause 2**: `enterTTSFocusMode()` uses `state.timeoutSeconds` instead of `guardState.timeoutSeconds` — ReferenceError at line 10664
  - **Fix**: Added `app_verbose = main_module.app_verbose` (CoSA); changed `state.` → `guardState.` (Lupin)
  - **Files (CoSA)**: `websocket.py` — 1 line added
  - **Files (Lupin)**: `notifications.js` — 1 word changed

- [x] **WebSocket reconnection gives up after 5 failures + missing notification events** → pending commit | By: cd0fd61a (Session 366)
  - **Symptom**: Notifications stop rendering until force page refresh. Has been broken ~2 days.
  - **Root Cause**: `scheduleReconnect()` gave up after 5 retries; `Promise.all` coupled both WS reconnects; `notification_expired`/`notification_responded` silently filtered from subscriptions
  - **Fix**: Infinite retry with backoff, independent WS reconnection, added 2 events to INI config
  - **Files (Lupin)**: `notifications.js`, `lupin-app.ini`, `lupin-app-splainer.ini`, `websocket-events.md`, `test_ini_key_naming.py`

- [x] **LanceDB proxy_decisions schema mismatch (non-fatal)** → CoSA pending commit | By: cd0fd61a (Session 366)
  - **Symptom**: `find_similar failed: No field named response_type` on every proxy prediction
  - **Root Cause**: Session 345 added `response_type` to schema but existing table predates the change
  - **Fix**: Schema validation in `_ensure_table()` — drop+recreate on mismatch
  - **Files (CoSA)**: `proxy_decision_embeddings.py`

- [x] **Race condition: old WS handler disconnect() kills new connection** → pending commit | By: cd0fd61a (Session 366)
  - **Symptom**: Browser shows connected but server says `not in active_connections`. Notifications lost.
  - **Root Cause**: Reconnect with same session_id → old handler's `finally` calls `disconnect()` deleting the NEW connection
  - **Fix**: Identity guard in finally blocks, dedup user_sessions, orphan cleanup in emit_to_user
  - **Files (CoSA)**: `websocket.py`, `websocket_manager.py`

- [x] **Config key underscore/space mismatch in `/api/config/client`** → pending commit | By: cd0fd61a (Session 366)
  - **Symptom**: 4 config keys not found, falling back to defaults with ¿WUH? warnings
  - **Root Cause**: `system.py` used underscores, INI uses spaces
  - **Fix**: 4 `config_mgr.get()` calls fixed + 3 JWT splainer entries added
  - **Files (CoSA)**: `system.py`; **(Lupin)**: `lupin-app-splainer.ini`

- [x] **Periodic CUDA OOM on Whisper transcription** → pending commit | By: 73bf201f (Session 359)
  - **Symptom**: Periodic 500 errors on `/api/upload-and-transcribe-mp3` — CUDA OOM despite ~290 MiB reserved (fragmentation)
  - **Root Cause**: PyTorch CUDA allocator fragmentation from co-resident Whisper + embedding models; can't find contiguous 16 MiB block
  - **Fix**: `_run_whisper_with_retry()` with `gc.collect()` + `torch.cuda.empty_cache()` + retry; `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`; 503 with Retry-After instead of 500
  - **Files (Lupin)**: `main.py`; **(CoSA)**: `speech.py`

- [x] **CUDA Memory Optimization — loading order, warmup & embedding OOM retry** → commit: b2d709b | By: 7d02176c (Session 365)
  - **Follow-up to Session 359**: Reduced VLLM 0.70→0.55, reordered model loading (smallest→largest), added multi-batch warmup + 85s chunked Whisper warmup, added `_run_with_cuda_retry()` to both embedding engines
  - **Files (Lupin)**: `main.py`, `whisper-warmup-85s.mp3`; **(CoSA)**: `local_embedding_engine.py`; **(Tests)**: `test_local_embedding_engine.py` (8 new)

- [x] **find_session_by_id() fails after context clear — qualifier silently dropped** → commit: 98c0072 | By: 638212c2 (Session 350)
  - **Symptom**: Stop hook qualifier dropped with `qualifier_tmux_inject_skip reason: "no session found"` for stable ID when bridge file has different transient `session_id`
  - **Root Cause**: `find_session_by_id()` only checked `data["session_id"]` (latest transient UUID), not the stable ID passed by the stop hook
  - **Fix**: Added `session_ids` accumulator list to bridge file; `find_session_by_id()` checks full list + backward-compat fallback
  - **Files**: `register_session.py`, `session_bridge.py`

- [x] **TTS audio not stopped on notification dismissal** → commit: e861b46 | By: a0d314eb (Session 347)
  - **Symptom**: TTS audio keeps playing after user responds to action-required notification; queue can't advance until audio naturally finishes
  - **Root Cause**: `submitResponse()` never called `stopAudio()`; `handleGracePeriodExceeded()` had no audio cleanup; `stopTTSAndAdvance()` called nonexistent `stopAllAudio()`
  - **Fix**: Added `stopAudio()` + `onTTSPlaybackComplete()` to `submitResponse()` and `handleGracePeriodExceeded()`; fixed typo `stopAllAudio()` → `stopAudio()` in `stopTTSAndAdvance()`
  - **Tests**: Manual verification — 5+ yes/no notifications, all dismissal paths confirmed
  - **File**: `src/fastapi_app/static/js/notifications.js`

- [x] **UPE multiple-choice prediction ignores available options** → CoSA pending commit | By: 23f6d6de (Session 345)
  - **Symptom**: MC predictions return free-text values like "Commit Scope: commit my files (76%)" instead of selecting from available options [Push, Done, Cancel, Other]
  - **Root Cause**: (1) No `response_type` field in LanceDB schema → cross-type contamination, (2) `_predict_multiple_choice()` ignores `options` param, (3) bare MC strings stored unparseable
  - **Fix**: Added `response_type` to LanceDB schema/filter, option validation in `_predict_multiple_choice()`, bare string wrapping for MC type, `response_type` filter in all 4 predict methods
  - **Tests**: 17 new unit tests (2092 total pass), 48 in MC test file
  - **Files (CoSA)**: `proxy_decision_embeddings.py`, `prediction_engine.py`; **(Lupin)**: `test_prediction_engine_multiple_choice.py`

- [x] **Session ID drift across hooks after context clear** → commit: b7b1120 | By: 59afa5ba (Session 342)
  - **Symptom**: After context clear, 3 different session IDs appear — hooks use transient `38984b97`, MCP/listener use stable `59afa5ba`
  - **Root Cause**: `payload.get("session_id")` always returns non-empty transient ID, so `get_claude_session_id()` (stable) was never reached
  - **Fix**: Added `resolve_stable_session_id()` to session_bridge.py; all 6 hooks + hook_common.py resolve transient→stable before use
  - **Tests**: 18 test updates across 6 test files, 231/231 pass
  - **Files**: `session_bridge.py`, `hook_common.py`, 6 hook files, `cosa_voice_mcp.py`, `register_session.py`

- [x] **Podcast Generator — 3 Bugs + target_user dispatch** → CoSA pending commit | By: 05faae8b (Session 304)
  - **Bug #1 — Fuzzy matching via voice**: Added `difflib.get_close_matches()` 3rd tier in `match_research_docs()`. File: `podcast_generator.py` router
  - **Bug #2 — Job card contact / sender_id double-hash**: Fixed `_get_sender_id()` suffix param. Files: `cosa_interface.py` + `job.py` (podcast_generator, deep_research, deep_research_to_podcast)
  - **Bug #3 — Audio segment upload / non-interactive hang**: Added `_is_interactive()` guard in `voice_io.py`, fixed TTS cost key, pre-stitching guards in `orchestrator.py`
  - **Tests**: 37 new unit tests (`test_fuzzy_file_matching.py`, `test_target_user_dispatch.py`, `test_voice_io_non_interactive.py`)

- [x] **History archive needed** — history.md at 18,951 tokens, archived to stay below 17k threshold → Completed 2026-03-11
- [x] **TTS focus mode safety timeout** → pending commit | By: 9f656de9
  - **Symptom**: Focus mode stays active forever if exit events never fire (server crash, network disconnect, stale WebSocket)
  - **Root Cause**: No runtime timeout — only a staleness check on page restore (Session 164)
  - **Fix**: Pause-aware `setTimeout`/`clearTimeout` safety timer, duration = `notification.timeout_seconds + 30s buffer` (fallback 150s). Timer pauses/resumes with notification pause button. Page restore recomputes remaining time.
  - **File**: `src/fastapi_app/static/js/notifications.js` (7 touchpoints: constructor, enter/exit focus mode, save/restore state, pause/resume)

- [x] **Duplicate notification sessions after context clear** → commit: 527b6e5 | By: 9f656de9
  - **Symptom**: Two session cards in notifications UI from single CC session after context clear
  - **Root Cause**: `register_session.py` wrote transient session_id (not stable) to CLAUDE_ENV_FILE → hooks sent notifications as `#25ca8c13` instead of `#9f656de9`
  - **Fix**: Changed env file write from `session_id` to `stable_session_id` (1 line)
  - **Test**: `test_env_file_writes_stable_session_id` (29/29 pass)
  - **Files**: `register_session.py`, `test_session_bridge_lookup.py`

- [x] **Session ID cross-project contamination** → commit: 495cdfd | By: 0e73eb8e
  - **Symptom**: Two CC instances (Lupin + planning-is-prompting) both reported same session ID `#0e73eb8e`, breaking parallel session isolation
  - **Root Cause**: 3 compounding failures — PPID mismatch (bash wrapper vs claude PID), unsafe "most recent file" fallback, hooks project-local
  - **Fix**: (1) Grandparent PID walk in hook, (2) CWD-scoped fallback in session bridge, (3) Soft fallback for hookless projects, (4) Global hooks
  - **Files**: `test_register_session.py`, `session_bridge.py`, `cosa_voice_mcp.py`, `~/.claude/settings.json`, `.claude/settings.local.json`

- [x] **Orphaned session ID race in COSA Voice MCP server** → commit: f4d73d7 | By: 10ff1e2a
  - **Symptom**: MCP tool calls during 1-10s startup window used random fallback session ID, causing orphaned notifications
  - **Fix**: `threading.Event` gate blocks tool calls until real session ID resolves; fail-loud `os._exit(1)` if fallback only
  - **File**: `src/lupin_mcp/cosa_voice_mcp.py`

- [x] **SWE Team output path uses underscores instead of dashes** → pending commit | By: 7f9787a4
  - **Symptom**: Artifacts written to `io/swe_team/` but Lupin convention uses dashes for non-Python files/dirs
  - **Fix**: `orchestrator.py:853` path string, `state_files.py:9` docstring, filesystem rename `io/swe_team/` → `io/swe-team/`
  - **Files (CoSA)**: `src/cosa/agents/swe_team/orchestrator.py`, `src/cosa/agents/swe_team/state_files.py`

- [x] **QueryLogTable gist embedding dimension mismatch (ArrowInvalid)** → commit: 922f503 (docs), CoSA pending | By: e10e0f35
  - **Root Cause**: Schema kept 768-dim `embedding_gist` after gist embeddings jettisoned (38f9704)
  - **Fix**: Removed `embedding_gist`, `cache_hit_gist` from schema, row data, analytics, smoke test
  - **File (CoSA)**: `src/cosa/memory/query_log_table.py`

- [x] **Auto-focus confirm button in delete modal for keyboard-driven workflow** → commit: debb307 | By: e7bfdd1d

- [x] **Add delete functionality to proxy ratification page** → commit: 33b4122 | By: e7bfdd1d

- [x] **Profile page button relocation: Change Password to header, remove redundant Go to Notifications** → commit: dd62985 | By: e7bfdd1d

- [x] **High-priority toggle not functional + conversation UX** → commit: 34807f0 | By: ff1fffd0

- [x] **Calculator→MathAgent snapshot replay: missing `prompt_response_dict` copy** → FIXED | By: 07b80074
  - **Symptom**: "What's 4+4?" works first time but fails on cache replay — snapshot saved with `code=[""]`
  - **Root Cause**: `_delegate_to_math_agent()` copied only 3 attrs back from MathAgent, missing `prompt_response_dict` which `SolutionSnapshot.create()` reads for `code`
  - **Fix**: Added `self.prompt_response_dict = math_agent.prompt_response_dict` in copy-back block
  - **Files (CoSA)**: `calculator/agent.py`; **(Tests)**: `test_calculator_mock_pipeline.py` (4 tests updated)
- [x] **Calculator "unitless" bug — "2 unitless is about 2.00 unitless"** → FIXED, verified 1170 tests pass | By: 07b80074
  - **Symptom**: "What's 2 + 2?" returns "2 unitless is about 2.00 unitless" instead of routing to MathAgent
  - **Root Cause**: 3-layer bug chain: (1) prompt has no arithmetic op so LLM picks `convert`, (2) LLM invents "unitless" as unit, (3) formatter always uses `.2f`
  - **Fix**: (1) Added prompt rule 6 for empty unit fields, (2) Added unit validation guard in `run_code()` that falls back to MathAgent, (3) Added whole-number check in `_format_convert_for_voice()`
  - **Files (CoSA)**: `calculator/agent.py`, `calculator/dispatcher.py`; **(Lupin)**: `src/conf/prompts/agents/calculator.txt`
- [x] **vLLM max_tokens overflow in PEFT validation** (ad-hoc) → CoSA pending | By: 4d6d238f
  - **Symptom**: `ValueError: maximum context length is 1024 tokens. However, you requested 1403 tokens`
  - **Root Cause**: `xml_coordinator.py:1266` dropped `max_new_tokens` param — `llm_client.run( prompt )` never received it
  - **Fix**: `llm_client.run( prompt, max_tokens=max_new_tokens )` — threads 128 tokens through to CompletionClient
  - **File (CoSA)**: `src/cosa/training/xml_coordinator.py:1266`
- [x] **Resume button references stale `window.freshQueueUI`** (ad-hoc) → pending commit | By: 6d82cf6e
- [x] **Double-click-to-expand bug on CJ flow job cards** (ad-hoc) → pending commit | By: 04aad364
- [x] **No way to copy WebSocket session IDs from System Status** (ad-hoc) → pending commit | By: 0266f064
- [x] **Cancel button on open-ended notifications fails with "Response cannot be empty"** (ad-hoc) → commit: 65658ba | By: 0266f064
- [x] **DataFrameGroupBy.apply DeprecationWarning in peft_trainer.py:597** (ad-hoc) → commit: afbfa7d (docs), CoSA pending | By: 2417c2b5
- [x] **PEFT Trainer False Positive Error Detection** (ad-hoc) → commit: 9b0e6a7 (docs), CoSA pending | By: 662576da
- [x] **ask_yes_no() missing priority parameter** (ad-hoc) → commit: 6b41a24 | By: 41d2e575
- [x] **Make semantic-similarity confirmation step configurable at runtime** (ad-hoc) → implemented by 649565dd, verified by 07b80074 | By: 649565dd
  - Config key `similarity_confirmation_enabled` in `lupin-app.ini`, runtime check in `todo_fifo_queue.py:500`, REST toggle in `system.py`
- [x] **Cache re-execution of non-executable code ("N/A" bug)** → FIXED by c4619072, verified by 07b80074 | By: c4619072
  - Fix: Changed code fallback from `"N/A"` to `[ "" ]`, added empty-code guard in `run_code()`, `try/except ValueError` in caller
  - Files (CoSA): `solution_snapshot.py`, `running_fifo_queue.py`
- [x] **`test_crud_agent_emits_job_state_transition`** → FIXED, verified by 07b80074 (1170 tests pass)
  - Fix: 3 MagicMock lines in `_create_queue_and_agent()` — `do_all()`, `code_ran_to_completion()`, `formatter_ran_to_completion()`
- [x] **`test_crud_agent_pushed_to_done_queue`** → FIXED, verified by 07b80074 (1170 tests pass)
  - Same root cause and fix as above

---

## Archive: Previous Sessions

### 2026.02.19 - Session a118cc5e (2 items)
- [x] **Bug #5: Unify Job-User-Session Association** → commit: aece71f (Lupin), CoSA pending
- [x] **CoSA submodule uncommitted changes (Sessions 219-234)** → already committed: 4510eb7, 7a7ea21

### 2026.02.04 - Session bcd6e830 (3 items)
- [x] **MathAgent QueueableJob protocol check** → commit: 34f4874 (docs-only)
- [x] **Notifications UI: Claude Code submission layout cleanup** → commit: 425568a
- [x] **CJ flow compliance** → Verified working (no changes)

### 2026.02.03 - Session bb3a5d21 (2 fixes)
- [x] **Job cards disappear after queue refresh** → commit: c8a77ef
- [x] **loadUserQueues called instead of refreshAllQueues** → commit: 0329bf4

### 2026.02.03 - Session 590273af (1 fix)
- [x] **Remove deprecated get_html() and queue_*_update events** → commit: 5c5467b

### 2026.02.03 - Session d7da6d0d (1 fix)
- [x] **Directory Analyzer "Other" Classification** → commit: be0afa6

### 2026.02.02 - Session 4949b964 (1 fix)
- [x] **Cache Hit Behavior**: Re-execute cached code → commit: 3cff850

### 2026.02.02 - Session 49a88ad2 (1 fix)
- [x] **Dry-run completion messages too verbose for TTS** → Fixed

### 2026.02.02 - Session 8594147a (3 smoke tests)
- [x] Deep Research dry-run → All tests PASSED
- [x] Podcast Generator dry-run → All tests PASSED, commit: eab45bf
- [x] Research→Podcast dry-run → All tests PASSED

### 2026.01.31 - Session 42b5bbd7 (1 fix)
- [x] Podcast Generator recording button stuck in recording mode → commit: f4f6cc8
  - **Root Cause**: `handleSTTButtonClick()` missing toggle logic
  - **Fix**: Added toggle check, converted duplicate handlers to thin wrappers
  - **File (Lupin)**: `src/fastapi_app/static/js/notifications.js`

### 2026.01.31 - Session d9d74b04 (documentation-only)
- [x] **Documentation-only session**: Verified dry-run bug fix already applied, smoke test already created
  - Bug fix (`SessionSummary` dataclass in `job.py:396-401`) was already implemented
  - Smoke test (`test_deep_research_dry_run_smoke.py`) was already created
  - Test execution deferred to next session

### 2026.01.30 - Sessions 110-112 (4 fixes)
- [x] **Deep Research QueueableJob protocol compliance** → commit: 0e0ecfc (Lupin), COSA pending | By: bd42074b
- [x] **user_email injection refactoring** → commit: 7243a31 (Lupin), COSA pending | By: bd42074b
- [x] **Unknown badge for dynamically created objects** → commit: f8e3bda (Lupin), COSA pending | By: bd42074b
- [x] Math Agent TTS - job_id pattern validation → commit: 9b86ddc | By: bd42074b

### 2026.01.29 - Session 21a62c05 (1 fix)
- [x] Job card styling inconsistency (WebSocket vs server-fetched) | By: 21a62c05
  - **Symptom**: Done queue job cards look different when dynamically inserted (WebSocket) vs fetched from server
  - **Root Cause**: `insertJobMetadata()` used completely different HTML structure than `renderJobCard()`
  - **Fix**: Extracted helper functions (`renderAbstractSection()`, `renderReportLinkSection()`) and unified rendering
  - **Files (Lupin)**: `src/fastapi_app/static/js/notifications.js`
  - **Debug Utility Added**: `window.notificationsUI.debugDumpJobCard(jobId)` for DOM comparison

### 2026.01.28 - Session b9faa342 (2 fixes)
- [x] Job card field parity bug → commit: 57a9fbb (Lupin) | By: b9faa342
- [x] sender_id regex rejects job ID format → FIXED, CoSA commit: 4510eb7 | By: b9faa342
