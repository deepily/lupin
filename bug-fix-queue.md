# Bug Fix Queue

## Session: 2026.01.29 (Session 109 - Bug Fix Mode)
**Owner**: claude.code@lupin.deepily.ai#0bd32185
**Status**: Active

### Queued
(No bugs remaining)

### Completed
- [x] Math Agent TTS - job_id pattern validation → commit: 9b86ddc
  - **Symptom**: Math agents produced no TTS; Pydantic validation error on compound hash job_id
  - **Fix**: Updated regex in `notification_models.py` to accept `SHA256::UUID` compound format
  - **File (COSA)**: `src/cosa/cli/notification_models.py`
  - **Verified**: TTS now works for math questions via /api/push

---

## Previous Session: 2026.01.29 (Session 108 - Bug Fix Mode)
**Owner**: claude.code@lupin.deepily.ai#21a62c05
**Status**: Closed

### Completed (Session 108)
- [x] Job card styling inconsistency (WebSocket vs server-fetched) → this commit
  - **Symptom**: Done queue job cards look different when dynamically inserted (WebSocket) vs fetched from server
  - **Root Cause**: `insertJobMetadata()` used completely different HTML structure than `renderJobCard()`
  - **Fix**: Extracted helper functions (`renderAbstractSection()`, `renderReportLinkSection()`) and unified rendering
  - **Files (Lupin)**: `src/fastapi_app/static/js/notifications.js`
  - **Debug Utility Added**: `window.notificationsUI.debugDumpJobCard(jobId)` for DOM comparison

---

## Previous Session: 2026.01.28 (Session 107 - Bug Fix Mode)
**Owner**: claude.code@lupin.deepily.ai#b9faa342
**Status**: Closed

### Queued
(No bugs remaining)

### Completed (Session 107)
- [x] Job card field parity bug → commit: 57a9fbb (Lupin)
  - **Symptom**: WebSocket-created cards missing fields present in server-fetched cards
  - **Fix**: Added 5 missing fields (completed_at, status, error, has_interactions, duration_seconds) to JS job object in handleJobStateTransition()
  - **Files (Lupin)**: `src/fastapi_app/static/js/notifications.js`
  - **Note**: Server-side fix (6 fields in running_fifo_queue.py) is in CoSA submodule - needs separate commit

### Completed (Session 105)
- [x] Job cards not rendering when queue collapsed → commit: f13a8f1 (Lupin)
  - **Symptom**: Badge count updates but cards don't appear when expanding collapsed section
  - **Fix**: Reset `state.loaded = false` when data arrives, not just when expanded
  - **Files (Lupin)**: `src/fastapi_app/static/js/notifications.js`

- [x] sender_id regex rejects job ID format → pending commit (CoSA)
  - **Symptom**: `Failed to send progress notification: 1 validation error... String should match pattern`
  - **Fix**: Added `[a-z]+-[a-f0-9]{8}` pattern for job IDs like `dr-a0ebba60`
  - **Files (CoSA)**: `src/cosa/cli/notification_models.py`
  - **Note**: CoSA submodule change - needs separate commit in CoSA context

- [x] Agentic job progress notifications route to sender cards instead of job cards → pending commit (Lupin)
  - **Symptom**: Progress notifications go to Claude Code sender card, not CJ Flow job card
  - **Root cause**: job_id embedded in sender_id suffix, but not passed as separate job_id param
  - **Fix**: Extract job_id from sender_id suffix in frontend routing logic
  - **Files (Lupin)**: `src/fastapi_app/static/js/notifications.js`

### Completed (Session 103)
- [x] LanceDB nprobes warning suppression → **Already fixed** (Session 7, commit 24b463b)
  - Fix implemented Nov 2025: `warnings.filterwarnings()` + logger levels
  - Configurable via `suppress lancedb warnings = true` (enabled by default)
  - nprobes value configurable: `solution snapshots lancedb nprobes = 20`
- [x] LanceDB gist_cache.lance corruption - missing file → commit: 0b8c915 (Lupin docs) + pending CoSA
  - **Symptom**: `Object at location .../gist_cache.lance/data/<uuid>.lance not found`
  - **Fix**: Added `_is_table_corrupted()` + auto-recovery in `__init__`
  - **Files (CoSA)**: `src/cosa/memory/gist_cache_table.py`
  - **Tests**: 8 smoke tests (including corruption detection + auto-recovery)

---

## Previous Session: 2026.01.26 (Session 100-101)
**Owner**: claude.code@lupin.deepily.ai#514f7e7a
**Status**: Closed - 4 fixes completed, 2 bugs carried over

### Completed
- [x] clearAllNotifications TypeError - Cannot read properties of undefined (reading 'length') at notifications.js:7490 (ad-hoc) → marked fixed by user
- [x] Boolean configuration parsing case-sensitive bug (ad-hoc)
  - Fixed: `configuration_manager.py:817-822` - now handles `true`/`True`/`TRUE` variants
  - CoSA change: needs separate commit in CoSA context

### Completed
- [x] LanceDB embedding cache corruption recovery (ad-hoc) → commit: 77ab971 (Lupin unit tests)
  - CoSA changes: `embedding_cache_table.py` needs separate commit in CoSA context
  - Added `_is_table_corrupted()` method with data scan detection
  - Auto-recovery: drops and recreates table when corruption detected
  - Unit tests: 9 tests covering mocked and real corruption scenarios

---

## Previous Session: 2026.01.23 (Session 95)
**Owner**: claude.code@lupin.deepily.ai#6fa77d02
**Status**: Completed - 4 fixes

- [x] cosa-voice MCP project detection order bug - CoSA detected as Lupin (ad-hoc) - Fixed prior to session
- [x] LanceDB/PostgreSQL permissions issue - database recreation blocked by wrong ownership/permissions (from Session 94 TODO)
  - Fixed: `lupin.lancedb` ownership changed from root:root to rruiz:rruiz
  - Fixed: `postgresql-dev-data` permissions changed from 700 to 750 (group r-x added)
- [x] Podcast Generator - English audio generated when not requested (ad-hoc)
  - Fixed: Conditional English inclusion in `orchestrator.py:441-462`
  - Change in CoSA repo (needs separate commit)
- [x] Podcast Generator - English audio notifications missing language identifier (ad-hoc)
  - Fixed: Added "English" to `do_audio_only_async()` notifications → commit: 329ad9b (COSA)

---

## Previous Session: 2026.01.22 (Session 92)
**Owner**: claude.code@lupin.deepily.ai#40d6e532
**Status**: Carried over 1 bug to next session

---

## Previous Session: 2026.01.21 (Session 89)
- [x] Gist enhancement with abstract fields → commit: f24337f (ad-hoc)
