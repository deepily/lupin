# Bug Fix Queue

**Format Version**: 2.0
**Last Updated**: 2026-02-06T09:00:00

---

### Active Sessions

| Session ID | Started | Last Activity | Status |
|------------|---------|---------------|--------|
| 0266f064 | 2026-02-07T09:00:00 | 2026-02-08T00:30:00 | closed |
| 2417c2b5 | 2026-02-06T21:00:00 | 2026-02-07T00:15:00 | closed |
| 41d2e575 | 2026-02-06T09:00:00 | 2026-02-06T17:00:00 | closed |
| 662576da | 2026-02-05T09:00:00 | 2026-02-05T14:45:00 | closed |
| bcd6e830 | 2026-02-04T08:30:00 | 2026-02-04T10:00:00 | closed |
| bb3a5d21 | 2026-02-03T14:50:00 | 2026-02-03T19:45:00 | closed |
| d7da6d0d | 2026-02-03T13:15:00 | 2026-02-03T13:35:00 | stale |
| 590273af | 2026-02-03T10:00:00 | 2026-02-03T14:30:00 | stale |
| 4949b964 | 2026-02-02T18:00:00 | 2026-02-02T23:05:00 | closed |

---

### Queued

(Available for any session to claim)


---

### In Progress

(Claimed by a specific session)

*None currently*

---

### Completed

- [x] **No way to copy WebSocket session IDs from System Status** (ad-hoc) → pending commit | By: 0266f064
- [x] **Cancel button on open-ended notifications fails with "Response cannot be empty"** (ad-hoc) → commit: 65658ba | By: 0266f064
- [x] **DataFrameGroupBy.apply DeprecationWarning in peft_trainer.py:597** (ad-hoc) → commit: afbfa7d (docs), CoSA pending | By: 2417c2b5
- [x] **PEFT Trainer False Positive Error Detection** (ad-hoc) → commit: 9b0e6a7 (docs), CoSA pending | By: 662576da
- [x] **ask_yes_no() missing priority parameter** (ad-hoc) → commit: 6b41a24 | By: 41d2e575

---

## Archive: Previous Sessions

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
- [x] sender_id regex rejects job ID format → pending commit (CoSA) | By: b9faa342
