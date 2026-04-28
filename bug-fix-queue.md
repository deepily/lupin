# Bug Fix Queue

**Format Version**: 2.0
**Last Updated**: 2026-04-22T16:50:00-04:00

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
| e3c3bab8 | 2026-03-25T18:02:00 | 2026-03-25T18:35:00 | committed |
| 5b508f0e | 2026-03-26T15:50:00 | 2026-03-26T16:30:00 | committed |
| 5329e0ea | 2026-03-27T14:00:00 | 2026-03-27T16:15:00 | closed |
| a312ee22 | 2026-04-08T11:00:00 | 2026-04-08T15:45:00 | committed |
| 1b8c1cc0 | 2026-04-10T09:30:00 | 2026-04-10T11:00:00 | closed |
| 5a620729 | 2026-04-14T14:20:00 | 2026-04-14T23:00:00 | closed |
| eb50bd56 | 2026-04-16T22:30:00 | 2026-04-17T00:30:00 | closed |
| 8ed95029 | 2026-04-18T13:20:00 | 2026-04-18T13:30:00 | stale |
| b802e633 | 2026-04-21T00:00:00 | 2026-04-21T01:00:00 | closed |
| 9b840935 | 2026-04-22T14:55:15 | 2026-04-22T16:50:00 | closed |
| 52a71953 | 2026-04-24T15:50:00 | 2026-04-24T17:42:00 | closed |
| 2026-04-26-card-render-stall | 2026-04-26T11:00:00 | 2026-04-26T13:50:00 | closed |
| 49c27830 | 2026-04-27T11:30:00 | 2026-04-27T11:45:00 | active |

---

### Queued

(Available for any session to claim)

- [ ] **`POST /api/notify/response` ERR_CONNECTION_RESET + audio WebSocket connect failure** (possibly related to session 9b840935's notification fixes — filed 2026-04-22, USER-REPORTED while manually testing)
  - **Browser console traces**:
    - `POST http://localhost:7999/api/notify/response net::ERR_CONNECTION_RESET` at `notifications.js:962` (`authedFetch`) → propagated from `submitResponse` (line 13572) ← `submitYesNoWithComment` (line 15050) ← inline handler (line 12666). `TypeError: Failed to fetch` caught and logged as `[Notifications ERROR] Failed to submit response`.
    - `WebSocket connection to 'ws://localhost:7999/ws/audio/slow%20zebra' failed:` (trailing colon, no reason) at `connectAudioWebSocket` (line 2136). Session-name "slow zebra" URL-encodes correctly; not a URL-encoding issue at first glance.
    - Queue WebSocket not shown failing in the snippet — only audio WebSocket.
  - **Symptom correlation**: `ERR_CONNECTION_RESET` on an HTTP POST + near-simultaneous WebSocket connect failure usually means the server dropped the connection mid-request OR briefly became unresponsive. Uvicorn auto-reload during session 9b840935's `notifications.js` edits could have caused a transient window; worth confirming with fresh repro that isn't timed near a code-reload.
  - **Open questions**: (1) is this still reproducible after :7999 has been stable for several minutes? (2) does the queue WebSocket also break or only audio? (3) does a non-space session name (`foolish-goat` vs `slow zebra`) change behavior? (4) any server-side exception in the :7999 log at the timestamp of the ERR_CONNECTION_RESET?
  - **Possibly-related files**: `src/cosa/rest/routers/notifications.py` (`/notify/response` endpoint), `src/cosa/rest/routers/websocket.py` (`/ws/audio/{session_id}` endpoint), `src/fastapi_app/static/js/notifications.js:962 / :13572 / :2136 / :2142`.
  - **Update 2026-04-22 15:26 EDT**: a second ERR_CONNECTION_RESET observed on `POST /auth/login` (totally unrelated route). Direct Python probe to the SAME endpoint at the same time returned a clean `401 Invalid email or password` in 14ms — server is healthy. Strongly suggests stale HTTP keep-alive TCP sockets in the browser after uvicorn auto-reload dropped connections during this session's `notifications.js` edits.
  - **Repro gate before investing investigation time**: (a) hard-refresh the page (Ctrl+Shift+R), (b) let :7999 sit idle with no source edits for 60+ seconds, (c) retry. If ERR_CONNECTION_RESET still appears → real bug, investigate. If not → close as "transient stale-keepalive artifact from auto-reload", no code bug.
  - **Deferred until**: session 9b840935's main fix is wrapped + committed, then revisit with the repro gate above.

- [x] ~~**DRY refactor: extract emission helper on NotificationFifoQueue**~~ → claimed by 9b840935 on 2026-04-22 (moved to In Progress)
- [x] ~~**Phase 2 pool: 2 bugs surfaced by 2026-04-24 Live API probe on :7999**~~ → **ROOT-CAUSED + FIXED** in same session (616112aa, 2026-04-24). Root cause: `_process_job(job)` at `running_fifo_queue.py:148` did `running_job = self.head()` instead of using the passed `job` parameter. Pre-Phase-2 (serial agentic processing), `self.head()` coincidentally == the newly-pushed job because agentic jobs always drained the running queue before the next push arrived. Phase 2 submits agentic jobs to a pool and returns immediately, so the running queue can hold MULTIPLE in-flight jobs — `self.head()` then returns the OLDEST job, not the one the consumer just pushed. Consequence: (a) newly-pushed job orphaned in run queue (Bug 2A phantom), (b) older job re-submitted to pool every time a new job arrives (Bug 2B duplicate done-queue entries, one per re-submit). Fix: `running_job = job` (explicit parameter use). Regression test `test_process_job_uses_passed_job_not_queue_head` added to `test_agentic_pool.py` (Session 616112aa). Post-fix Live API probe on :7999 (2026-04-24 14:34) submitted 1 DR dry-run → landed in done queue with exactly 1 copy, run queue clean, no dead-letters, pool-status terminal (inflight=0). Both bugs eliminated.
  - **Fix + regression test** will ride the Phase 2 commit reshoot (Phase 2 ship-path re-opened).

- [ ] ~~superseded (keep for context)~~ **Phase 2 pool: 2 bugs surfaced by 2026-04-24 Live API probe on :7999** (Session 616112aa, post-Phase-2 commit `9adfc26`, ROOT-CAUSED + FIXED above — original writeup preserved below).
  - **Setup**: :7999 bounced 13:50 EDT, my Phase 2 code live. Probe at 14:00:21 submitted 2 DR dry-runs back-to-back (dr-978e4aa4, dr-709f5f84). Pool confirmed `max_agentic_workers=3`.
  - **Bug 2A — phantom job in running queue**: `dr-709f5f84` submitted 14:00:21.873; at 14:04:27 (4+ min later) pool-status showed `inflight_agentic_jobs=0` but the job was still in the `run` queue with `status=pending`. The future popped from `_agentic_futures` (so callback ran) but `_transition_to_done` either crashed or didn't complete the queue transition. **This is exactly the ghost-job scenario Phase 3's ghost-sweeper is designed to catch** — but the fact that it reproduces EASILY on just 2 back-to-back submissions, without any injected failure, suggests a regression in my Phase 2 callback path, not a rare race. Need to investigate whether `_transition_to_done` raises silently (caught by outer `except BaseException`) under concurrent DR completion.
  - **Bug 2B — duplicate done-queue entries**: `dr-978e4aa4` appears 3 times in the `done` queue metadata, all with identical `id_hash` and identical `created_date` timestamp (14:00:21.673). `FifoQueue.push(item)` always `append`s to `queue_list` regardless of duplicate id_hash (dict is overwrite-only), so 3 entries means `jobs_done_queue.push(dr-978e4aa4)` was called 3 times. Enumerated all 6 `jobs_done_queue.push` call sites: line 529 (my `_transition_to_done`, Phase 2), lines 817/879 (`_handle_agentic_job` legacy, now unreachable per dispatcher switch), lines 1174/1257/1473 (fast-lane paths, irrelevant for agentic jobs). Given my dispatcher routes agentic → `_submit_agentic_job` + return, ONLY line 529 should fire for DR jobs. Three fires means either (a) the pool fired 3 separate futures for the same job object (→ 3 callbacks → 3 transitions), or (b) `_transition_to_done` was called 3x for one callback, or (c) the legacy `_handle_agentic_job` is reachable via some path I missed.
  - **Confidence**: Bug 2A and 2B are likely related (both stem from the callback path). Bug 2B's 3-fire pattern points at a DOUBLE-SUBMIT race in `_submit_agentic_job` OR something pre-Phase-2 in the consumer thread.
  - **Repro strategy**: submit one DR dry-run to a clean :7999; observe done-queue count. If 1 → multi-submit race; if 3+ → single-submit repeats the bug and rules out consumer-thread doubling.
  - **Files under suspicion**: `src/cosa/rest/running_fifo_queue.py` (my Phase 2 code), `src/cosa/rest/queue_consumer.py` (consumer loop), `src/cosa/rest/routers/deep_research.py:179` (the single submit point).
  - **Out of scope**: Phase 3 ghost-sweeper would catch Bug 2A symptomatically, but we should fix the ROOT in Phase 2 before shipping.
  - **Status**: BLOCKS Phase 2 ship. Do not bounce :8000 to validate Phase 2 until these are resolved.

- [ ] **Receptionist agent: multiple issues** (filed 2026-04-24, USER-REPORTED from :8000 dead-queue card for admin2@notself.com, id_hash `1ef2b359...::96e7cb88...`, timestamp 2026-04-24 11:48 EDT). **Observed error**: `BadRequestError 400: "This model's maximum context length is 8192 tokens. However, you requested 8250 tokens (4154 in the messages, 4096 in the completion)"`. **Issues bundled**:
  - (1) **Receptionist prompt/response is overflowing 8192-token context window.** 4154 tokens in messages + 4096 reserved for completion = 8250 > 8192. Either the prompt template grew, someone injected long conversation history, or the model is wired to an 8k-context vLLM (Ministral 8B) while the completion-reservation `max_tokens=4096` is way oversized for a receptionist handoff. Need to trace: (a) the Receptionist prompt template size + dynamic content, (b) the `max_tokens` config it passes to vLLM, (c) which model endpoint it's configured against.
  - (2) **BFE correctly rejected the job** per current config (`auto fix eligible job types = presentation, deep_research, podcast, test_suite` in `[Lupin: Baseline]` at `lupin-app.ini:979` — doesn't include ANY fast-lane AgentBase type). `dead_queue_watchdog.is_eligible_for_auto_fix()` returned `(False, "Job type 'ReceptionistAgent' not in eligible types: [...]")`. **Question to confirm with user**: is this the INTENDED design (BFE handles only agentic jobs) or a gap (fast-lane agents silently die without repair)? If the former, close the question. If the latter, extend eligibility list.
  - (3) **Classifier miss**: "maximum context length" + "context_length_exceeded" don't match any of the `_INFRA_PATTERNS` in `dead_queue_watchdog.py:34-56`, so the error falls through to `FailureCategory.UNKNOWN` — the conservative fallback that triggers BFE. But BFE cannot fix a context-overflow error (that's prompt-template or model-config, not code). Suggest adding `INFRA_PROMPT_TOO_LONG` category with pattern `maximum\s+context\s+length|context_length_exceeded|token\s+limit`, and marking it `"requires manual intervention"` in the eligibility check (same treatment as `INFRA_OOM` + `INFRA_ENVIRONMENT`).
  - **Files likely involved**: `src/cosa/agents/receptionist_agent.py` (prompt + model wiring), `src/conf/lupin-app.ini` (receptionist's LLM spec key), `src/cosa/rest/dead_queue_watchdog.py:34-56` (classifier regex set), `src/cosa/rest/dead_queue_watchdog.py:176-180` (eligibility decision branch).
  - **Not a regression from Phase 1/Phase 2** — the dead-queue entry is from 11:48 EDT on :8000, which ran pre-bounce code (Phase 1 code loaded at 11:16). Phase 2 pool work landed on :7999 only, via 13:50 bounce. This is an existing Receptionist/BFE-config issue, filed as a separate ticket.

- [ ] **TFE/BFE post-resume proposal-review UX — cluster + propose-fixes presentation lacks context for end-user decision** (filed 2026-04-27, USER-REPORTED). After clicking "Resume from checkpoint" on `tfe-66aab80b`, the user was presented with a series of proposed fixes at the voice gate but lacked the information needed to make a proper accept/reject determination, leading them to cancel the resumed job. **Concrete asks** (per user feedback):
  - Surface WHY each fix is being proposed — what failure trace, what file, what test
  - Group/cluster related proposals visibly so user can see "these 3 changes all address the same root cause"
  - Show the diff per proposal (or at least the touched files)
  - Differentiate confidence levels — "this fix has been tried successfully on similar failures" vs. "speculative one-shot"
  - Make "skip this proposal" a first-class action distinct from "cancel the entire resume"
  - **Files likely involved**: `src/cosa/agents/test_fix_expediter/orchestrator.py` (proposal generation), `src/fastapi_app/static/js/notifications.js` (action-required card rendering for voice-gate notifications), and the prompt template that emits the proposal payload. `_isResumableWithOverrides` + `renderResumeOverrideControls` (notifications.js:7281+) are nearby.
  - **Out of scope of this entry**: the resume MECHANISM itself works (clickable link rehydrated the job, voice gate fired); this is purely a presentation/UX gap.

- [ ] **Repair pre-existing CoSA unit test failures unrelated to notification fifo** — surfaced while running adjacent tests during session 9b840935. After accurate diagnosis on 2026-04-26 the original "9 cosmetic failures" item splits into:
  - `test_fifo_queue.py::TestFifoQueue::test_websocket_emission` (1 test) — expects `_emit_queue_update` on parent `FifoQueue`; parent was refactored to not have it. Either restore `_emit_queue_update` on parent with inline emission, or update the test to match current behavior (push is bare append, emission is per-subclass).
  - `test_notifications_router.py::TestNotificationsRouter::test_get_local_timestamp_success` (1 test) — was config-key drift `"app_timezone"` (underscore) vs production `"app timezone"` (space). **FIXED 2026-04-26 by Phase 1 of CJ Flow card-rendering unification** (test asserts `"app timezone"` now).
  - `test_notifications_router.py::TestNotificationsRouter::*` (7 tests: `test_notify_user_*`) — **NOT** config-key drift as originally diagnosed. Tests patch `cosa.rest.routers.notifications.email_to_system_id` (returning a UUID), but production code now imports `get_user_by_email` from `cosa.rest.user_service` and reads `user_data["id"]` for the system ID. Different mock target, different return shape. Genuinely a separate refactor — out of scope for the 2026-04-26 unification work.
- [x] ~~**`/plan-bug-fix-mode-wrap` skill not triggered — session-end invoked instead**~~ → fixed commit 5f2713a | By: eb50bd56 | 2026-04-16


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

- [x] **Notification dispatch unification — extracted `WebSocketManager.emit_to_user_or_listener_sync` helper, migrated 5 dispatch sites** → pending commit + pending :7999 bounce | By: 49c27830 | 2026-04-27
  - **Background**: Today's narrow fix (entry below) patched ONE dispatch site. A comprehensive audit revealed the same dispatch pattern existed in 6 places across `notifications.py`, `queues.py`, and `notification_fifo_queue.py`, with subtly different and inconsistent behavior. Two sites (`notification_expired` and `notification_responded` lifecycle broadcasts) were missing the cross-user listener fallback entirely. The next contributor adding a 7th dispatch site would have repeated the bug.
  - **Approach**: Extracted a single canonical method `WebSocketManager.emit_to_user_or_listener_sync(user_id, job_id, event, data) -> dict` that encapsulates the "always emit to user + always emit to cc-listener-{job_id} if active" pattern. Returns `{user_delivered, listener_delivered, any_delivered}`. Mirrors the precedent set by `emit_to_user_and_admins_sync` (canonical dual-emit for queue/job state events, RnD doc 2026-04-11).
  - **Migrations** (all 5 sites collapsed onto the helper):
    1. `notify_user` fire-and-forget branch (`notifications.py:504-575` → ~50 lines collapsed to ~30 with the helper)
    2. `notification_expired` SSE timeout broadcast (`notifications.py:806`) — gained the listener fallback (was emit_to_user only)
    3. `notification_responded` response-submission broadcast (`notifications.py:1019`) — gained the listener fallback (was emit_to_user only)
    4. `send_job_message` (`queues.py:966-1004` → 40 lines collapsed to ~20)
    5. `_emit_notification_added` in `notification_fifo_queue.py:407-421` — collapsed targeted-user + listener emits onto the helper; broadcast branch retained for the user_id=None case
  - **Files (CoSA, user commits separately)**:
    - `src/cosa/rest/websocket_manager.py` — added `emit_to_user_or_listener_sync` (~95 lines incl. docstring)
    - `src/cosa/rest/routers/notifications.py` — Migrations 1, 2, 3
    - `src/cosa/rest/routers/queues.py` — Migration 4
    - `src/cosa/rest/notification_fifo_queue.py` — Migration 5
  - **Files (Lupin)**:
    - `src/tests/unit/test_websocket_manager_dispatch.py` — NEW, 9 unit tests covering the 6-row behavior contract matrix + 3 failure-isolation cases
    - `src/tests/unit/test_notify_cc_listener_fallback.py` — UPDATED. Existing 5 tests still pass via helper-based path. Added 2 structural-check tests for `notification_responded` and `notification_expired` (verify source code uses the helper, not the legacy `emit_to_user`)
  - **Tests**:
    - `pytest src/tests/unit/test_websocket_manager_dispatch.py` → **9/9 pass**
    - `pytest src/tests/unit/test_notify_cc_listener_fallback.py` → **7/7 pass** (5 existing + 2 new structural)
    - `pytest src/tests/unit/` → **3672 passed, 1 xfailed, 0 failed** (was 3638 → +34 tests over Phases A-E)
    - `pytest src/tests/unit/ src/cosa/tests/unit/rest/test_notification_fifo_queue.py` → **3677 passed, 1 xfailed, 0 failed**
    - `bash src/scripts/run-websocket-smoke-tests.sh` → **50/50 pass** (regression sanity)
  - **Audit**: `grep emit_to_session_sync` in 3 migrated routers → ZERO matches (all dispatch routes through the helper now). `grep emit_to_user_or_listener_sync` → 7 call sites across 4 files (1 helper definition + 6 callers). `grep emit_to_user_sync` in migrated files → 1 match: `queues.py:1028` (the user-only echo acknowledgment, intentionally NOT migrated — listener already received the original message).
  - **Out-of-scope follow-ups documented in plan**: (1) wire CC listeners to ANSWER response-required notifications (no callback wiring exists today); (2) migrate `queue_util.emit_job_state_transition` callers to `emit_to_user_and_admins_sync` (separate RnD plan from 2026-04-11); (3) refactor `agent_notification_dispatcher._resolve_routing` operator-fallback into a shared utility; (4) investigate the `:7999` uvicorn StatReload watcher recovery (watcher hasn't fired in ~24h despite source touches).
  - **Plan**: `~/.claude/plans/dazzling-napping-frost.md`
  - **Deploy status — NOT YET LIVE on :7999**: same as today's narrow fix entry below — uvicorn StatReload watcher hasn't fired. Held off bouncing per user's "rebuilding v1.0.0 image" request. The migrations are backwards-compatible — `_emit_notification_added` and `send_job_message` previously had inline dual-emits; the helper preserves that behavior. So even on the unmigrated running bytecode, the fire-and-forget path's narrow fix from earlier today is what the user actually depended on.

- [x] **UI Claude Code Notifications Panel → CC console — `notify_user` missing cross-user `cc-listener-{job_id}` fallback** → pending commit + pending :7999 bounce | By: 49c27830 | 2026-04-27 (SUPERSEDED by the unification entry above — this narrow fix was rolled INTO the helper as Migration 1)
  - **USER-REPORTED**: 3 user-initiated messages sent from the LookML CC notifications panel UI targeting CC session `b2ce9133` were persisted to PostgreSQL with `state='created'` but NEVER reached the Claude Code console.
  - **Messages** (13:46-47 EDT):
    - "Testing testing, is this thing on?"
    - "Hello, anybody home?"
    - "Okay let's contemplate what the output from the last run of the evaluation harness ..."
  - **Root cause** (from server log OFFLINE DIAG):
    - `target_user=claude.code@lookml.deepily.ai` resolves to UUID `f71f5b8a-...`
    - `is_user_connected(f71f5b8a-...)` returns `False` — that user has zero active sessions
    - HOWEVER, `cc-listener-b2ce9133` IS in `ws_manager.active_connections` — registered under user `931e9dae-...` (`claude.code@lupin.deepily.ai`, the SHARED CC service account)
    - `notify_user` at `notifications.py:478-520` short-circuits with `status="user_not_available"` based on `is_user_connected(target_system_id)` alone, never trying the listener fallback
    - The sibling endpoint `send_job_message` at `queues.py:986-1004` correctly emits to `cc-listener-{job_id}` as a cross-user fallback. `notify_user` was missing the equivalent.
  - **Fix**: Added cross-user CC-listener fallback to `notify_user` (CoSA-side). When `not is_connected and job_id and f"cc-listener-{job_id}" in ws_manager.active_connections`: emit `notification_queue_update` to that listener session via `emit_to_session_sync`, mark state as `delivered`, return `status="delivered_via_listener"`. Mirrors the pattern in `send_job_message`. Best-effort state update (non-fatal if it fails). Listener emit failure cleanly falls through to existing `user_not_available` (DB row remains for forensic recovery).
  - **Files (CoSA, user commits separately)**: `src/cosa/rest/routers/notifications.py` (~70 lines added in `notify_user` offline branch)
  - **Files (Lupin)**: `src/tests/unit/test_notify_cc_listener_fallback.py` — NEW, 5 unit tests:
    1. `test_cc_listener_fallback_fires_when_target_offline_and_listener_active` — primary regression repro
    2. `test_user_not_available_when_listener_also_absent` — preserves existing offline behavior
    3. `test_normal_user_path_still_fires_when_target_connected` — connected-user path takes precedence
    4. `test_no_job_id_no_listener_attempt` — guard: must not try listener without job_id
    5. `test_listener_emit_failure_falls_through_to_user_not_available` — graceful degradation
  - **Verification**: `pytest src/tests/unit/test_notify_cc_listener_fallback.py` → **5/5 pass**. Full Lupin unit suite → **3638 passed, 1 xfailed, 0 failed** (was 3633 pre-fix).
  - **Deploy status — NOT YET LIVE on :7999**: uvicorn StatReload watcher has not fired in ~24h despite source touch (last reload was for `tests/unit/test_agentic_pool.py` yesterday). Live probe of the new fallback path returned `user_not_available` → confirms running bytecode is still pre-fix. The fix needs a `:7999` bounce to take effect. **Held off bouncing** because (a) user is rebuilding v1.0.0 image, (b) LookML CC session `b2ce9133` is actively running on :7999. User should bounce when convenient.

- [x] **7 self-inflicted E2E test regressions from 2026-04-26 :8000 sweep** → pending commit | By: 2026-04-26-card-render-stall | 2026-04-27
  - **Trigger**: 2026-04-26 18:45 EDT scheduled :8000 sweep (`ts-f180a14d`) returned 30 failures + 7 errors. After accurate triage, **7 of 37 were mine** (the rest were pre-existing infra: CUDA OOM, no-docker-in-container, no-PEFT, argparse SystemExit, live-agent contention, websocket suite hot-swap config-block mismatch).
  - **Group G — my own new test file out of sync with my own follow-up Q1 fix (3 tests)**: `test_history_card_parity.py` looked for `[id^='job-cancel-history-']` (the small ✕ button DOM id). The Q1 fix removed `'history'` from the small-✕ gate at `notifications.js:6992` AFTER the test file was authored, so the tests were probing a DOM element that no longer exists. **Fix**: rewrote 3 tests to target the prominent splice button via `.history-action-buttons .delete-btn`; added explicit regression-guard assertion that the small ✕ is GONE on history; renamed `test_history_card_delete_button_uses_dispatch` → `test_history_card_delete_button_routes_to_history_endpoint` (semantic correction — the splice button calls `deleteHistoryJob` directly, not via the `_dispatchDelete` chokepoint).
  - **Group H — CSS-class drift from queueName='history' architectural change (4 tests)**: `test_job_history_ui.py::test_failed_job_has_dead_styling` + `test_repair_loop_ui.py × 3` asserted `status-dead` / `status-done` on history cards. Pre-Phase-2, history cards used the status→queueName mapping which produced those classes. After my Phase 2 change to pass `queueName='history'` directly, `notifications.js:6835` derives `statusClass = \`status-${queueName}\``, so the outer class is uniformly `status-history` — the failed/completed signal is now carried by the inner `.completion-badge.failed` (✗) / `.completion-badge.success` (✓) element. **Fix**: updated 4 test assertions to expect `status-history` outer + the appropriate inner completion-badge — preserves the tests' INTENT (verify the card visually represents failed-state vs completed-state) under the new outer/inner class split.
  - **Files (Lupin)**: `src/tests/e2e_ui/test_history_card_parity.py`, `src/tests/e2e_ui/test_job_history_ui.py`, `src/tests/e2e_ui/test_repair_loop_ui.py`
  - **Verification (:7999-eligible)**: `pytest --collect-only` on all 3 files → 47 tests collect cleanly, 0 errors. `pytest src/tests/unit/` → 3633 passed, 1 xfailed, 0 failed (regression sanity).
  - **Verification (:8000 — STAGED)**: actual E2E execution requires a scheduled :8000 sweep, deferred while user is rebuilding the v1.0.0 image (per user 2026-04-27).

- [x] **TFE/agentic voice-gate stall persistence regression — Phase 2 pool path drops checkpoint, persists status='completed'** → pending commit | By: 2026-04-26-card-render-stall | 2026-04-26
  - **USER-REPORTED**: TFE job `tfe-99595e2c` on :8000 history showed "TFE stalled at voice gate. 3 proposals await your review. Resume when ready." in `response_text` but had `status='completed'` and **no `checkpoint` in metadata_json**, hiding the inline `▶ Resume from Checkpoint` button on the history card. User had previously resumed jobs like this — implying a regression.
  - **Root cause**: CJ Flow Phase 2 (commit `9adfc26`-area, 2026-04-23) introduced the pool-based agentic dispatcher. The new pool callback `_on_agentic_complete()` at `src/cosa/rest/running_fifo_queue.py:427-489` calls `_transition_to_done()` unconditionally — it does NOT check `if job.state == JobState.STALLED:`, the way the legacy serial path `_handle_agentic_job()` did at line ~898 (Bug 11, 2026-04-15). So every agentic job that goes through the pool — whether it actually stalled or completed normally — got persisted as `RUNNING → COMPLETED` with `_transition_to_done`'s metadata blob, which has NO `checkpoint` field. Persistence dispatch at `queue_util.py:96` then routed `to_state=COMPLETED` to `persist_job_completed_from_metadata`, writing `status='completed'` to the row and stripping the would-be-stall metadata.
  - **Confirmation that everything else is wired**: `JobState.STALLED` exists in `job_state.py`; `persist_job_stalled_from_metadata()` exists at `job_persistence.py:275`; the dispatch site at `queue_util.py:99` correctly routes `to_state == JobState.STALLED` to it; the resume endpoint at `agentic_job_factory.py:resume_job` reads `metadata_json.checkpoint` and `original_args` to rehydrate. TFE's `do_all()` at `test_fix_expediter/job.py:165` correctly sets `self.state = JobState.STALLED` and stashes the checkpoint into `self.artifacts['checkpoint']`. Only the pool-callback dispatch was missing the branch.
  - **Fix**: Added `_transition_to_stalled(job, formatted_output)` helper to `running_fifo_queue.py` (mirrors `_transition_to_done` but emits `JobState.STALLED` with `checkpoint` + `plan_path` in metadata). Updated `_on_agentic_complete` to gate on `job.state == JobState.STALLED` before falling through to `_transition_to_done`. Single-file change in CoSA.
  - **Backfill caveat**: Existing pre-fix history rows (like `tfe-99595e2c`) remain `status='completed'` with no checkpoint — the fix doesn't repair them. They're not resumable via the inline button. The standalone "🔄 Resume Stalled TFE Job" form on the notifications page may still find them via plan-doc path if `metadata_json.report_link` points at one. Filing a separate one-shot data-migration job is OUT OF SCOPE for this fix.
  - **Files (CoSA, user commits separately)**: `src/cosa/rest/running_fifo_queue.py` (~10-line guard in `_on_agentic_complete`, ~75-line new `_transition_to_stalled` helper)
  - **Files (Lupin)**: `src/tests/unit/test_agentic_pool.py` — NEW `TestStallTransition` class with 5 unit tests
  - **Tests**: `pytest src/tests/unit/test_agentic_pool.py` → **31 passed** (5 new + 26 existing). Full Lupin unit `pytest src/tests/unit/` → **3633 passed, 1 xfailed, 0 failed** (was 3628 before this session). All 5 new tests verify: (1) STALLED state routes to `_transition_to_stalled`, (2) stalled job lands in done queue (not dead), (3) `emit_job_state_transition` called with `RUNNING→STALLED`, (4) metadata blob includes `checkpoint` + `plan_path`, (5) regression — non-stalled completions still go through `_transition_to_done`.
  - **Live deploy status**: Container source mount confirmed (`docker exec lupin-rest-test grep -c '_transition_to_stalled' /var/lupin/src/cosa/rest/running_fifo_queue.py` → 2 matches). However the test container runs as `python3 -m fastapi_app.main` (no `--reload`), so :8000 needs another bounce to pick up the new bytecode. **Bounce required before user can validate the fix on :8000.**

- [x] **CJ Flow accordion: history bucket renders inconsistently with done bucket (third unification attempt)** → pending commit | By: 2026-04-26-card-render-stall | 2026-04-26
  - **USER-REPORTED**: history-pane cards missing 💬 interaction indicator + "📋 Notification Conversation" section showing a "Loading..." spinner that never resolved. Diagnosed as the **third unification attempt** in the rendering pipeline — Sessions 21a62c05 (2026-01-29) and 1b8c1cc0 (2026-04-10, commit `3faec04`) had each declared "single source of truth via renderJobCard()" but left residual gaps. This session closes them.
  - **Three-axis cleanup (A1 + B + C)**:
    - **A1 (Backend)**: `/api/job-history` returns the same FLAT shape as `/api/get-queue/done`. Was: top-level `id_hash, job_type, status, ...` + `metadata_json` JSONB blob holding the rich fields. Now: 31 top-level keys including `job_id, agent_type, response_text, abstract, report_path, cost_summary, scheduled_at, monopolize, has_interactions, paused, …` (matching done-bucket field set verbatim). `metadata_json` retained for backward compat (additive change, no removed fields). Aliases `report_link` → `report_path` for naming alignment.
    - **B (Frontend)**: Eliminated the `_isHistory` boolean flag (was set in `renderHistoryCard` line 6065, read in `renderJobCard` lines 6850 + 6976). Replaced with `DELETE_HANDLERS` lookup table keyed by `queueName` and a single `_dispatchDelete(jobId, queueName)` chokepoint. DOM-id namespacing now uses `queueName === 'history' ? 'history-${jobId}' : jobId`. Added `'history'` to renderJobCard's queueName-driven branches for completion badges (✓/✗), interactions indicator (💬), and the "Notification Conversation" section gate.
    - **C (Backend)**: `has_interactions` is now an accurate count from a bulk SQL query against the indexed `notifications.job_id` column, NOT the prior `bool(job.session_id)` proxy that gave false positives. Added `count_by_job_ids(job_ids: list[str]) -> dict[str, int]` to `notification_repository.py`. Single batched query per page; sub-100ms expected.
  - **Adapter collapse (Phase 3, Option A — conservative)**: `renderHistoryCard()` shrunk from ~50 lines to ~10 — dropped all metadata_json fallback unpacking (Phase 1 makes it unnecessary), kept the splice of `renderHistoryActions()` to preserve the prominent "🗑 Delete" / "↻ Retry" buttons placement. **Option B (full deletion)** deferred — the splice removal would change UX placement.
  - **Q1 follow-up (same session)**: User reported two delete buttons on history cards (small ✕ in header + prominent 🗑 Delete in footer). Diagnosed as pre-Phase-2 redundancy I'd carried forward when adding `'history'` to the small-✕ gate. Removed `'history'` from the gate at `notifications.js:6992` — small ✕ now renders for live buckets only (`[ 'todo', 'done', 'dead' ]`); history cards rely solely on the prominent splice buttons.
  - **Files (CoSA, user commits separately)**:
    - `src/cosa/rest/db/repositories/notification_repository.py` — added `count_by_job_ids()` (~37 lines)
    - `src/cosa/rest/job_persistence.py` — added `_count_notifications_for_jobs()`, `_unpack_metadata_json()`, `_build_history_row()` helpers; rewrote `query_job_history()` row builder
    - `src/cosa/rest/routers/queues.py` — added `_count_interactions_for_jobs()`; replaced `bool(job.session_id)` proxy at done-bucket handler line 477 and dead-bucket handler line 540
    - `src/cosa/tests/unit/rest/test_notifications_router.py` — fixed 1 timezone-config-key test (`app_timezone` → `app timezone`)
  - **Files (Lupin)**:
    - `src/fastapi_app/static/js/notifications.js` — DELETE_HANDLERS + `_dispatchDelete`; `_isHistory` flag removed; `renderHistoryCard` shrunk; queueName-driven branches expanded for `'history'`; small-✕ gate restricted to live buckets
    - `src/fastapi_app/static/html/notifications.html` — cache-bust `v=20260422b` → `v=20260426b` (two bumps in same session)
    - `src/tests/unit/test_job_persistence.py` — +20 tests (TestUnpackMetadataJson + TestBuildHistoryRow + TestCountNotificationsForJobs)
    - `src/tests/unit/test_notification_repository_count.py` — NEW, 5 tests
    - `src/tests/integration/test_job_history_shape_parity.py` — NEW, 5 tests (staged for :8000)
    - `src/tests/e2e_ui/test_history_card_parity.py` — NEW, 7 tests (staged for :8000)
    - `src/rnd/v0.1.7/2026.04.26-cj-flow-card-rendering-unification/` — 9 R&D docs (01-design-overview, 02-api-shape-normalization, 03-has-interactions-accuracy, 04-frontend-flag-removal, 05-adapter-collapse, 06-testing-strategy, 90-phase1-execution-log, 91-phase2-execution-log, 92-phase3-execution-log)
  - **Tests (:7999 — AI-discretionary, ran)**: Lupin unit `pytest src/tests/unit/` → **3633 passed, 1 xfailed, 0 failed**; WebSocket smoke `bash src/scripts/run-websocket-smoke-tests.sh` → **50/50 PASS**; live shape probes on `/api/job-history` confirmed 31 top-level keys + accurate `has_interactions` (8/10 True, 2/10 False on real data — vs the prior all-True proxy)
  - **Tests (:8000 — staged, NOT run)**: integration shape parity (5 tests in `test_job_history_shape_parity.py`); E2E UI parity (7 tests in `test_history_card_parity.py`); visual regression. **Need user-confirmed scheduled_at slot via `/api/test-suite/submit` to run.**
  - **Live deploy status**: :7999 picks up changes via auto-reload + cache-bust. :8000 was bounced early in this session (`docker rm -f lupin-rest-test && docker compose up -d lupin-rest-test`) so Phase 1 backend changes + Phase 2 frontend changes are live. The Q1 small-✕ fix and the TFE stall fix landed AFTER that bounce, so the test server still serves the pre-fix bytecode for those two — needs another bounce.

- [x] **cosa-voice MCP misidentifies nested repos as "lupin" + UI shows [UNKNOWN] for hyphenated projects** → commit: f549b20 (Lupin), CoSA submodule files committed by user separately | By: 52a71953 | 2026-04-24
  - **Bug #1 (CoSA)**: `detect_project()` substring matching collapsed `/lupin/src/cosa/`, `/lupin/src/lupin-mobile/`, `/lupin/src/lupin-plugin-firefox/` all to `"lupin"`. Replaced with git-repo-boundary walk-up. Extended `KNOWN_PROJECTS` for the two new nested repos.
  - **Bug #2 (Lupin)**: `notifications.js` regexes at lines 8590 + 8618 used `[a-z]+` for project segment, rejecting hyphens. Both bumped to canonical `[a-z][a-z0-9]*(?:-[a-z0-9]+)*` matching the Python pattern in `cosa_voice_mcp.py:205` and `notification_models.py:216,629`. Surfaced as `[UNKNOWN]` sender label after Bug #1 made hyphenated projects representable end-to-end.
  - **Files (Lupin)**: `src/fastapi_app/static/js/notifications.js`, `src/tests/unit/test_sender_id.py` (rewrite, +7 tests), `src/rnd/v0.1.7/2026.04.24-cosa-voice-nested-repo-detection-fix.md` (NEW R&D companion doc).
  - **Files (CoSA, user-commits)**: `src/cosa/agents/utils/sender_id.py`, `src/cosa/utils/notification_utils.py`.
  - **Tests**: 23 unit tests in `test_sender_id.py` (all green) + V2.5 real-FS detect from 4 cwds + V3 live MCP module-load from 4 cwds (subprocess banner capture) + V4 full unit regression 3590 pass / 1 xfail. User-confirmed live MCP from `/src/lupin-mobile/` reports correct `lupin-mobile` identity.

- [x] **DRY refactor: extract `_emit_notification_added` helper on NotificationFifoQueue** → commit: cd4e5e6 | By: 9b840935 | 2026-04-22
  - Collapsed ~44 lines of near-identical emission code (push lines 244-267 + push_notification lines 343-365) into a single shared helper. Both call sites now `self._emit_notification_added(notification)`. Unified debug-print strings (dropped the "priority" qualifier). Verified no behavior change via CoSA unit 5/5, Lupin integration 3/3, Lupin notification unit 27/27, module smoke (priority + mark_played paths).
- [x] **NotificationFifoQueue `_emit_queue_update` 500 + Chrome `/played` silence** → commit: cd4e5e6 | By: 9b840935 | 2026-04-22
  - **Fix 1 (CoSA, user commits from CoSA session)**: added `_emit_queue_update()` method to `NotificationFifoQueue` at `src/cosa/rest/notification_fifo_queue.py`. Broadcasts `notification_queue_update` with `queue_name`, `value`, `unplayed_count`. Silent no-op when `websocket_mgr=None` or `emit_enabled=False`. 5 new unit tests in `src/cosa/tests/unit/rest/test_notification_fifo_queue.py` (all pass). Module smoke test still green.
  - **Fix 2 (Lupin)**: `playNotificationAudio` in `src/fastapi_app/static/js/notifications.js:10509` now fires fire-and-forget `POST /api/notifications/{id}/played` after successful playback. `notifications.html` cache-bust bumped to `v=20260422a`. 3 new in-process TestClient regression tests in `src/tests/integration/test_notifications_integration.py::TestMarkPlayedEndpoint` (all pass).
  - **Verification**: CoSA unit 5/5, Lupin integration 3/3, Lupin notification units 27/27, module smoke OK, live probe on :7999 confirmed endpoint reachable + updated JS served. User manually confirmed Chrome path works end-to-end after browser restart.
- [x] **Refine job-id chip truncation — preserve compound prefixes** → commit: 0f67635 | By: b802e633 | 2026-04-21
  - Fix 2's `length>8` rule over-truncated short non-compound ids (`foo-a1b2c9b2`) and reasonable BFE prefixes (`bfe-a1b2c3d4::<uuid>` → `bfe-a1b2c3d4` should stay). New rule in `notifications.js:6835`: `idPrefix = jobId.split("::")[0]`; truncate only if `idPrefix.length > 16`. Effectively restores `8ed95029`'s original `::`-split (5b3e305) plus a safety fallback for 64-char sha prefixes. Cache-bust `v=20260421c`.
- [x] **DELETE /api/queue/{name}/all returned 404 on test server** → commit: 82243e4 | By: b802e633 | 2026-04-21
  - `DELETE /api/queue/done/all` (and the latent `/job-history/all` sibling) returned 404 because the parameterized `/{job_id}` route was declared BEFORE the literal `/all` route in `src/cosa/rest/routers/queues.py` — FastAPI matched `/{job_id}`, bound `job_id="all"`, failed to find a job by that id, and raised 404. Same shadowing defect existed for the job-history pair, so the history bulk-delete was broken too (user hadn't hit it yet). Reorder fix lives in the CoSA submodule (deferred to CoSA session); Lupin-side pieces committed here — Fix History appended to `src/rnd/v0.1.6/2026.04.16-cj-flow-delete-all-buttons.md`, plus new `src/tests/integration/test_queue_delete_all.py` (6 lock-in cases). HTTP probe against `:7999` confirms 8/8 regression assertions.
- [x] **CJ Flow accordion — enormously long job-ids overflow header chip** → commit: 82243e4 | By: b802e633 | 2026-04-21
  - Cards displayed full id_hash strings (64-char sha + `::` + UUID). Truncated the header chip in `renderJobCard()` (`notifications.js:6832`) to first 8 chars + `"..."`; full `jobId` stays in `data-job-id`, `title` tooltip, clipboard-on-click, and the expanded `<code>` details block — every API call and DOM lookup unaffected. Cache-bust v=20260420a → v=20260421a. **Follow-up bug filed above**: the simple length>8 rule over-truncates short non-compound ids (see In Progress).
- [x] **CJ Flow badge — BFE compound IDs overflow `.job-id-chip`** → commit: 5b3e305 | By: 8ed95029 | 2026-04-18
  - `bfe-XXXXXXXX::<uuid>` (60+ chars) blew out the badge while `tfe-XXXXXXXX` fit fine. Truncated visible text at `::` in `renderJobCard` (`notifications.js:6829,6980`); tooltip now reveals the full compound ID on hover, and `data-job-id`, DOM ids, and clipboard copy still carry the full scoped form. Mirrors backend `AgenticJobBase.base_id` pattern. User live-confirmed working after hard-refresh.

- [x] **PQW HTTP 500 — peer-queue auth env vars not set on dev server** → no-code fix | By: eb50bd56 | 2026-04-16
  - Container predated env var additions to docker-compose.yml. Fix: `docker rm -f lupin-rest-dev && docker compose up -d lupin-rest-dev`. Watcher confirmed running post-fix.

- [x] **History archive — history.md at 38,821 tokens (155% of 25k limit)** → commit: 2879cbf | By: eb50bd56 | 2026-04-16
  - Archived 23 sessions (2026-04-08 to 2026-04-14) to `history/2026-04-08-to-14-history.md`. Retained 4 sessions, 10,008 tokens.

- [x] **Seed account protection — companions wiped by E2E/integration test teardown** → commit: this session | By: eb50bd56 | 2026-04-16
  - 3-layer protection: `is_protected` column on `User` model; `seed_test_companions.py` marks companions `TRUE` on every upsert; E2E + integration `clean_test_db` switched to row-level `DELETE WHERE NOT is_protected` + TRUNCATE; `admin_delete_user()` API guard rejects deletion of protected accounts. DEV + TEST DBs migrated. 4 unit tests in `test_admin_protected_accounts.py`. Zero lockout windows for operator or PQW during test runs.
  - **CoSA files** (user commits from `src/cosa/`): `postgres_models.py`, `admin_service.py`

- [x] **CJ Flow — Delete All button for 5 queue panes** → commit: 29a6fd4 | By: eb50bd56 | 2026-04-16
  - Added 🗑️ Delete All to each of todo/run/done/dead/history pane headers. Non-admins delete own jobs; admins clear entire queue. History respects time-window filter.
  - **Backend** (CoSA — user commits separately): `DELETE /api/queue/{name}/all`, `DELETE /api/job-history/all?days=N`, `delete_job_history_bulk()`.
  - **Frontend** (Lupin): `notifications.html` (5 buttons), `notifications.js` (`deleteAllQueueJobs()`), `notifications.css` (`.queue-delete-all-btn`).
  - **Plan**: `src/rnd/v0.1.6/2026.04.16-cj-flow-delete-all-buttons.md`

- [x] **BFE & TFE job cards lack interactions and results documents** → Session 5a620729 | Live validated 2026-04-14
  - **Symptom**: Notification Conversation showed "No interactions recorded" on BFE/TFE done cards; no report-link artifact rendered.
  - **RC-1**: `voice_io.notify()` gate conflated voice availability with persistence dispatch. `is_voice_available()` cached-False from a probe error caused silent drops of every subsequent notify. Fix: decoupled — `notify()` always dispatches via `cosa_interface.notify_progress()` when configured; TTS decision moved to voice-bridge subscriber.
  - **RC-2**: Neither agent wrote a final report (only an intermediate plan via PlanWriter). Fix: new `src/cosa/agents/shared/report_writer.py` + `_write_final_report()` hooks on BFE (5 exits: dry-run dead-not-found, live dead-not-found, happy, stall, generic exception) and TFE (3 exits: happy, stall, generic exception). Populates `artifacts["report_path"]` → UI renderReportLinkSection fires.
  - **Test-harness gaps discovered and fixed**: E2E scripts blocked by missing `websocket_id` on `/api/push` and no BFE fixture. Solved via NEW `POST /api/push-agentic` endpoint (explicit routing_command + args, bypasses runtime-argument-expeditor for unattended callers) + `push_job_agentic()` method on TodoFifoQueue. Scripts patched; fixture created.
  - **Live validation**: `dr-eb1b680e` (deep_research dry-run, force_failure_mode=code_bug) → dead queue → DeadQueueWatchdog dispatched `bfe-f91fd115` → BFE breadcrumbs landed in `lupin_db_test.notifications` with correct compound job_id + sender_id. 15 rows persisted. Chain fully green.
  - **Plan**: `src/rnd/v0.1.6/2026.04.14-bfe-tfe-interactions-and-reports.md`.
  - **Commits (Lupin)**: `62a85e1` (CP4 — initial fix + ReportWriter + unit tests), plus CP5 (session-end commit with push-agentic endpoint wiring + E2E script patches).
  - **CoSA-side changes (user commits separately)**: `src/cosa/agents/utils/voice_io.py`, `src/cosa/agents/shared/report_writer.py`, `src/cosa/agents/bug_fix_expediter/job.py`, `src/cosa/agents/test_fix_expediter/job.py`, `src/cosa/rest/routers/queues.py` (new endpoint), `src/cosa/rest/todo_fifo_queue.py` (new method), `src/cosa/rest/routers/peer.py` (from CP2/CP3), `src/cosa/rest/routers/pages.py` (peer-queue-watch route), `src/cosa/rest/routers/admin.py` (refresh-source from CP1).

- [x] **Done bucket job card render parity** → commit: 3faec04 | By: 1b8c1cc0
  - **Symptom 1**: Dynamically-inserted done cards (WS transition) showed an irrelevant pause button and lacked a trash button
  - **Symptom 2**: Reload-loaded done cards lacked the scheduled (🕐) and monopolize (🔒) badges that dynamic cards displayed
  - **Symptom 3**: History-tab cards lacked the trash button (`_isHistory` gate) and the scheduled/monopolize badges
  - **Root Cause**: 4 defects across 2 files — backend `/api/get-queue/done` omitted 3 fields; `renderJobCard` gated scheduled badge to `queueName==='todo'`; `handleJobStateTransition` surgically morphed cards on transition instead of re-rendering; `renderHistoryCard` omitted same 3 fields and stamped `_isHistory:true`
  - **Fix**: Single source of truth via `renderJobCard()` — fed it complete data from every path; ungated the scheduled badge; switched terminal-state (done/dead) WS transitions to full re-render via `renderJobCard`; normalized history card fields; dropped the unused `_isHistory` gate
  - **Files (Lupin)**: `notifications.js`, `src/rnd/v0.1.6/2026.04.10-done-card-render-parity.md`
  - **Files (CoSA, separate commit)**: `routers/queues.py`

- [x] **Queue badge counts stale + process owner badge missing** → commit: a149363 | By: a312ee22
  - **Bug 1**: Badge counts used DOM element counting on collapsed (empty) containers. Fixed with local counter tracker.
  - **Bug 2**: `user_email` not propagated to frontend. Added to API responses + all WebSocket metadata dicts + UI badge.

- [x] **Timezone UTC→EST + queue job delete button** → commit: 7e71e1a | By: a312ee22
  - **Bug 3**: `datetime.now().isoformat()` produced naive UTC strings. Added `get_current_datetime_iso()` utility, replaced ~65 call sites across 20 files.
  - **Bug 4**: No delete for stuck/done jobs. Added `DELETE /api/queue/{name}/{id}` + 🗑 button + `job_removed` WS event.

- [x] **Agentic job factory scattered imports** → commit: 18ff764 (docs), CoSA pending | By: 65e3162f
  - **Symptom**: 9 imports scattered across function body — 4 at top, 5 inline in `elif` branches
  - **Fix**: Consolidated into single alphabetically-sorted, vertically-aligned block
  - **File (CoSA)**: `agentic_job_factory.py`

- [x] **SentenceTransformer contacts HuggingFace Hub on every startup** → CoSA pending | By: 28f07da3 (Session 383)
  - **Root Cause**: Missing `local_files_only=True` — every load checked Hub for updates
  - **Fix**: Added `local_files_only=True` to `SentenceTransformer()` constructor
  - **Files**: `local_embedding_engine.py` (CoSA)

- [x] **Main container max-width too narrow (800px → 1000px)** → commit: 5c2ba91 | By: 28f07da3 (Session 383)
  - **Root Cause**: `.container` and `.profile-container` both set `max-width: 800px`
  - **Fix**: Changed to `1000px` in both CSS files + toolbar `calc()` updated
  - **Files**: `notifications.css`, `auth/css/auth.css`

- [x] **Config manager visual grouping broken by space-separated keys** → commit: 94044ab (docs), CoSA pending | By: 2098634b (Session 382b)
  - **Root Cause**: `key.split( "_" )[ 0 ]` returns entire key when no underscores present
  - **Fix**: Changed to `key.split()[ 0 ]` — splits on whitespace
  - **Files**: `configuration_manager.py`

- [x] **set_session_topic() UI propagation + notify retry** → commit: d9cd6f0 | By: 5329e0ea (Session 380b)
- [x] **Job interactions 404 for compound IDs** → commit: d9cd6f0 | By: 5329e0ea (Session 380b)
- [x] **Stack trace not captured on dead jobs** → commit: d9cd6f0 | By: 5329e0ea (Session 380b)
- [x] **Cost summary missing from PresentationGenerator + DeepResearch** → commit: d9cd6f0 | By: 5329e0ea (Session 380b)
- [x] **Job History missing "1 day" time window filter** → commit: d83882f | By: 5329e0ea (Session 380b)
- [x] **FastAPI startup crash — missing Field import in podcast_generator** → commit: 8f0b214 (docs), CoSA pending | By: 5329e0ea (Session 380b)

- [x] **Presentation Generator dry-run sends zero progress notifications** → commit: 8b749b0 | By: 5b508f0e (Session 376)
  - **Symptom**: Dry run completes but UI shows no breadcrumb notifications
  - **Root Cause**: `_execute_dry_run()` was dead code; orchestrator path lacked identity setup → `is_voice_available()` cached False
  - **Fix**: Wired `_execute_dry_run()` with identity setup (matching podcast pattern) + added breadcrumb docs to agentic workflow skill
  - **Files**: `job.py`, `agentic-voice-workflow.md`, `SKILL.md`

- [x] **session_name max_length=50 silently rejects long session topics** → commit: 0cadd52 | By: 5b508f0e (Session 376)
  - **Symptom**: `set_session_topic()` returns OK but UI never updates for topics > 50 chars
  - **Fix**: Truncate to 64 chars before `_notify_impl()`, bump `max_length` to 64, surface failures in logs
  - **Files**: `cosa_voice_mcp.py`, `notification_models.py`

- [x] **set_session_topic() FunctionTool not callable (second root cause)** → commit: ab2cf50 | By: e3c3bab8 (Session 373)
  - **Symptom**: Session 372b pipeline fix worked, but `set_session_topic()` still never sent the notification
  - **Root Cause**: FastMCP 2.14.2 `@mcp.tool` converts functions to `FunctionTool` objects — not callable as Python functions. `except Exception: pass` swallowed the TypeError.
  - **Fix**: Extracted `_notify_impl()` private function, both MCP tool and internal callers use it directly
  - **Files**: `cosa_voice_mcp.py`

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
