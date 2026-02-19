# Bug Fix Queue

**Format Version**: 2.0
**Last Updated**: 2026-02-19T00:00:00

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
| 07b80074 | 2026-02-16T10:00:00 | 2026-02-16T10:00:00 | active |
| a118cc5e | 2026-02-19T00:00:00 | 2026-02-19T00:00:00 | committed |

---

### Queued

(Available for any session to claim)

(none)

---

### In Progress

(Claimed by a specific session)

(none)

---

### Completed

- [x] **Bug #5: Unify Job-User-Session Association** → commit: f0fc016 (Lupin), CoSA pending | By: a118cc5e
  - **Symptom**: Dual-bookkeeping — `UserJobTracker` side-table duplicated user/session info already on job objects
  - **Root Cause**: Tracker was added before `user_id` was on all job types; now `QueueableJob` protocol guarantees it
  - **Fix**: 5-phase refactor: JWT fix, `register_scoped_job()` atomic method, universal scoped IDs, direct `job.user_id` reads, dead code removal
  - **Verification**: 1,447 unit tests pass, 13 new tests added
- [x] **CoSA submodule uncommitted changes (Sessions 219-234)** → FIXED, already committed to CoSA repo | By: a118cc5e
  - **Symptom**: Accumulated uncommitted CoSA changes across Sessions 225-234 (identified as Bug #2 in session summary)
  - **Root Cause**: Technical debt — CoSA edits made during Lupin sessions were not batch-committed to the CoSA repo
  - **Resolution**: Already resolved via two batch commits: `4510eb7` (Sessions 226-234, 2026-02-18), `7a7ea21` (Sessions 219-225, 2026-02-17)
  - **Verification**: `cd src/cosa && git status --short` returns clean (0 uncommitted changes)
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
