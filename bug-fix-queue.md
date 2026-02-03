# Bug Fix Queue

**Format Version**: 2.0
**Last Updated**: 2026-02-03T14:50:00

---

### Active Sessions

| Session ID | Started | Last Activity | Status |
|------------|---------|---------------|--------|
| bb3a5d21 | 2026-02-03T14:50:00 | 2026-02-03T14:50:00 | active |
| d7da6d0d | 2026-02-03T13:15:00 | 2026-02-03T13:35:00 | active |
| 590273af | 2026-02-03T10:00:00 | 2026-02-03T14:30:00 | active |
| 4949b964 | 2026-02-02T18:00:00 | 2026-02-02T23:05:00 | closed |

---

### Queued

(Available for any session to claim)

- [ ] **MathAgent fails QueueableJob protocol check on /api/push**
  - **Symptom**: Push endpoint returns 500 error with "Job must implement QueueableJob protocol, got MathAgent"
  - **Stack Trace**:
    - `queues.py:197` → `todo_queue.push_job( question, websocket_id, user_id, user_email )`
    - `todo_fifo_queue.py:660` → `self.push( agent )`
    - `todo_fifo_queue.py:861` → `super().push( item )`
    - `fifo_queue.py:151` → raises `TypeError`
  - **Root Cause (suspected)**: `push_job()` creates a `MathAgent` instance and passes it to `push()`, but base `FifoQueue.push()` now enforces `QueueableJob` protocol compliance
  - **Impact**: All math questions fail to queue
  - **Files to investigate**:
    - `src/cosa/rest/todo_fifo_queue.py:660` (push_job creates agent)
    - `src/cosa/rest/fifo_queue.py:151` (protocol enforcement)
    - `src/cosa/agents/math_agent.py` (may need protocol compliance)

---

### In Progress

(Claimed by a specific session)

---

### Completed

- [x] **loadUserQueues called instead of refreshAllQueues after Claude Code submit** → pending commit | By: bb3a5d21
  - **Symptom**: After submitting a Claude Code job, only todo queue refreshed, not all queues
  - **Root Cause**: `handleClaudeCodeSubmit()` called `loadUserQueues()` instead of `refreshAllQueues()`
  - **Fix**: Changed line 2783 from `this.loadUserQueues()` to `this.refreshAllQueues()`
  - **File**: `src/fastapi_app/static/js/notifications.js:2783`

- [x] **Remove deprecated get_html() and queue_*_update events** → commit: 5c5467b | By: 590273af
  - Frontend uses metadata exclusively; get_html() never rendered
  - queue_*_update broadcasts total counts (all users), replaced by job_state_transition
  - Deleted dormant queue.js/queue.html (last modified 2025-08-15)
  - Unit tests: 195/195 PASS

- [x] **Directory Analyzer "Other" Classification**: 97.58% of files classified as "Other" → commit: be0afa6 | By: d7da6d0d
  - **Symptom**: Running directory analyzer on Lupin showed 46M lines (97.58%) as "Other"
  - **Root Cause**: LanceDB files (.lance, .manifest, .txn) + Flutter SDK not excluded, .dart not mapped
  - **Fix**: Added exclusions and mappings to `src/cosa/repo/directory_analyzer/default_config.yaml`
  - **Result**: "Other" dropped to 3.57% (12k lines), files scanned 59,471 → 1,223

- [x] **Cache Hit Behavior**: Re-execute cached code for fresh results → commit: 3cff850 | By: 4949b964
  - **Symptom**: Cache hits returned stale `answer_conversational` for time-sensitive queries
  - **Fix**: Added code re-execution in `_format_cached_result()` before returning cached result
  - **File**: `src/cosa/rest/running_fifo_queue.py:689-699`
  - **Test**: Smoke 9/9 PASS, Unit imports verified
  - **Trade-off**: Math queries re-execute unnecessarily (~100ms) but correctness > performance

- [x] **Dry-run completion messages too verbose for TTS** → Fixed | By: 49a88ad2
  - **Symptom**: Dry-run completion messages included full file paths with emails, UUIDs, slashes
  - **Fix**: Simplified return messages to voice-friendly summaries (paths remain in `abstract`)
  - **Files (COSA)**:
    - `src/cosa/agents/podcast_generator/job.py:336`
    - `src/cosa/agents/deep_research_to_podcast/job.py:341`
    - `src/cosa/agents/deep_research/job.py:420`
  - **Smoke tests**: All 3 modules pass

- [x] Run Deep Research dry-run smoke test → All 5 tests PASSED | By: 8594147a
  - Job ID: dr-6aa5d16d
  - Completed in: ~10s
  - Cost: $0.00 (dry-run confirmed)
- [x] Podcast Generator dry-run API smoke test → All tests PASSED | By: 8594147a
  - Job ID: pg-dd026977
  - Completed in: ~10s
  - Cost: $0.00 (dry-run confirmed)
  - **Bug fixed**: push_job() → push() with user_job_tracker association
  - **Bug fixed**: get_position() → size()
  - **Commit**: eab45bf (Lupin), CoSA pending
- [x] Research→Podcast dry-run API smoke test → All tests PASSED | By: 8594147a
  - Job ID: rp-221fe28e
  - Completed in: ~14s
  - Cost: $0.00 (dry-run confirmed)
  - **Bug fixed**: Same push_job() → push() fix as Podcast Generator
  - **Smoke test created**: test_research_to_podcast_dry_run_smoke.py

---

## Archive: Previous Sessions

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
- [x] sender_id regex rejects job ID format → pending commit (CoSA) | By: b9faa342
