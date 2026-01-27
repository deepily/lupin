# Bug Fix Queue

## Session: 2026.01.27 (Session 103)
**Owner**: claude.code@lupin.deepily.ai#8cc66d0d
**Status**: Active

### Queued
- [ ] LanceDB nprobes warning suppression
  - **Error**: `[WARN lance::dataset::scanner] nprobes is not set because nearest has not been called yet`
  - **Source**: LanceDB Rust library (repeated 8+ times in logs)
  - **Impact**: Warning noise in logs
  - **Potential fix**: Set nprobes parameter before search or suppress at logging level

### Completed (Session 103)
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
