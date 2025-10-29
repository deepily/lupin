# SSE Phase 2 - Implementation Tracking

**Status**: Phase 2.0 Foundation - COMPLETE ✅
**Last Updated**: 2025.10.28
**Current Week**: Week 1 of 4 (COMPLETE)

## Related Documentation

- **[Index](00-index.md)**: Master navigation and project overview
- **[Phase 1 Implementation](01-implementation-current.md)**: Standalone PoC (COMPLETE)
- **[Architecture](02-architecture.md)**: SSE design patterns and system integration
- **[Decisions](03-decisions.md)**: Technical decisions and rationale
- **[Testing](04-testing-validation.md)**: Test strategy and validation plans
- **[Phase 2 Design Decisions](05-phase2-design-decisions.md)**: Complete design session results (9 areas, 40 questions)

---

## Overview

**Goal**: Implement Phase 2 SSE notification system with response-required capabilities

**Scope**: Response-required notifications with dual protocol (WebSocket + SSE), persistent storage, multi-modal UX

**Timeline**: 4 weeks (phased rollout with feature flags)

**Testing**: 40-50 tests (unit + smoke + integration)

**Key Design Principles**:
- Backward compatible (existing fire-and-forget notifications unchanged)
- Dual protocol architecture (WebSocket for delivery, SSE for blocking/waiting)
- In-memory event system (asyncio.Event) with future Redis migration path
- Voice-first UX with title/message separation
- Both response types in MVP (yes/no + open-ended)

---

## Phase 2.0: Foundation (Week 1)

**Status**: COMPLETE ✅
**Started**: 2025.10.28
**Completed**: 2025.10.28
**Goal**: Database schema, configuration keys, and test infrastructure

### Tasks

**Database Schema** (Priority: CRITICAL):
- [x] Task 1.1: Create `notifications` table with full schema ✓
  - All fields: id, sender_id, recipient_id, source_context, source_sender, title, message, type, priority
  - Response fields: response_requested, response_type, response_value, response_default, timeout_seconds
  - Timestamps: created_at, delivered_at, expires_at, responded_at, deleted_at
  - State machine: state (created/delivered/responded/expired/deleted)
  - Legacy compatibility: played, play_count, last_played
  - Indexes: recipient_id+state, recipient_id+created_at, expires_at
- [x] Task 1.2: Create table creation script `src/scripts/create_notifications_table.py` ✓
  - **Initial table creation** (notifications table does not currently exist)
  - Full Phase 2 schema with 23 fields (see design doc lines 136-174)
  - CREATE TABLE IF NOT EXISTS operation with 3 indexes
  - No data migration needed (current notifications are in-memory only)
  - Validation: check schema integrity, verify indexes
  - Database: `lupin-notifications.db` (new dedicated SQLite database)
- [x] Task 1.3: Verify database schema integrity ✓
  - Run table creation script
  - Verify all fields created correctly (23 fields total)
  - Verify indexes created (3 indexes: idx_recipient_state, idx_recipient_created, idx_expires_at)
  - Database file created: 24KB at `src/conf/long-term-memory/lupin-notifications.db`

**Configuration** (Priority: HIGH):
- [x] Task 2.1: Add config keys to `lupin-app.ini` ✓
  - `enable response required notifications = false`
  - `enable sse blocking = false`
  - `notification timeout default seconds = 120`
  - `notification grace period seconds = 30`
  - `notification offline immediate default = true`
  - Added explainer entries to `lupin-app-splainer.ini`
- [x] Task 2.2: Update `ConfigurationManager` to load new keys ✓
  - No code changes needed - ConfigurationManager loads keys dynamically from INI file
  - Tested: Configuration keys accessible via `config_mgr.get()` method
  - Follows existing pattern (websocket config keys)

**Test Infrastructure** (Priority: HIGH):
- [x] Task 3.1: Set up unit test framework for notifications ✓
  - Created `src/tests/unit/test_notifications_database.py` (10 tests, 100% passing)
  - Test fixtures for notification creation (pytest fixtures with temp database)
  - CRUD operations fully tested (CREATE, READ, UPDATE, DELETE/soft delete)
  - State machine transitions tested (created→delivered→responded, created→delivered→expired)
  - Query operations tested (by recipient_id, by state, expired notifications)
- [x] Task 3.2: Set up smoke test framework ✓
  - Created `src/tests/smoke/test_notifications_smoke.py` (quick sanity checks, ✓ passing)
  - Basic workflow validation (create → store → retrieve → update → delete)
  - State transition workflow tested (created → delivered → responded)
  - LLM interpretation helper placeholder (Phase 2.1 implementation)
  - Uses `cu.print_banner()` for professional output
- [x] Task 3.3: Set up integration test framework ✓
  - Created `src/tests/integration/test_notifications_integration.py` (test stubs for Phase 2.1+)
  - Test structure defined for SSE blocking flow (yes/no, open-ended, timeout, grace period)
  - Test structure defined for multi-device sync (Tab A → Tab B updates, duplicate prevention)
  - Test structure defined for offline detection (immediate default return)
  - Fixtures defined (test_database, websocket_test_client, sse_test_client)
  - All tests marked with `@pytest.mark.skip` until Phase 2.1 backend ready

### Success Criteria

- ✅ Database schema created with all 23 fields
- ✅ Table creation script tested and verified (idempotent, validated)
- ✅ Configuration keys added and loaded correctly (5 keys + explainers)
- ✅ Test infrastructure ready (unit: 10 tests passing, smoke: ✓ passing, integration: stubs ready)
- ✅ All unit tests passing (CRUD operations: 4/10, queries: 3/10, state transitions: 3/10)

### Estimated Effort

**Total**: 2-3 days

**Breakdown**:
- Database schema + table creation: 1 day
- Configuration: 0.5 day
- Test infrastructure: 1-1.5 days

---

## Phase 2.1: Backend Complete (Week 2)

**Status**: PLANNED
**Goal**: SSE endpoint, in-memory event system, offline detection

### High-Level Tasks

- [ ] Extend `/api/notify` endpoint for response-required notifications
- [ ] Create response submission endpoint `POST /api/notify/response`
- [ ] Implement SSE blocking flow with asyncio.Event
- [ ] Implement timeout scenario handling (use response_default)
- [ ] Implement offline detection (check WebSocket connection before blocking)
- [ ] Create in-memory event system (`pending_responses` dict)
- [ ] Extend WebSocket events (notification_queue_update, notification_responded, notification_expired)

### Success Criteria

- ✅ SSE blocking works end-to-end
- ✅ Offline detection returns default immediately
- ✅ WebSocket events broadcasting correctly
- ✅ Integration tests passing (full yes/no flow, timeout, offline)

### Estimated Effort

**Total**: 4-5 days

---

## Phase 2.2: Client UI (Week 3)

**Status**: PLANNED
**Goal**: "Action Required" section, multi-modal input, timer/progress bar

### High-Level Tasks

- [ ] Create "Action Required" section in Fresh Queue UI
- [ ] Implement Yes/No response type with buttons and keyboard shortcuts
- [ ] Implement open-ended response type with text input + mic
- [ ] Implement countdown timer (MM:SS format)
- [ ] Implement progress bar with color coding (green/yellow/red)
- [ ] Implement grace period intent tracking
- [ ] Implement post-response confirmation and transition
- [ ] Implement multi-device sync via WebSocket events

### Success Criteria

- ✅ Both response types working (yes/no, open-ended)
- ✅ Timer and progress bar functional with color coding
- ✅ Multi-modal input working (voice, keyboard, mouse)
- ✅ Multi-device sync operational (respond in one tab → all tabs update)
- ✅ Confirmation and transition UX working

### Estimated Effort

**Total**: 5-6 days

---

## Phase 2.3: CLI Integration (Week 4)

**Status**: PLANNED
**Goal**: notify-claude-sync command, return value propagation, documentation

### High-Level Tasks

- [ ] Create `notify-claude-sync` CLI command
- [ ] Implement SSE client in Python with timeout handling
- [ ] Implement return value propagation (exit codes + stdout)
- [ ] Implement LLM response interpretation (server-side)
- [ ] End-to-end integration tests (all 6 scenarios)
- [ ] Update architecture documentation
- [ ] Create CLI usage guide
- [ ] Create best practices guide
- [ ] Create troubleshooting guide
- [ ] Create in-app help text

### Success Criteria

- ✅ notify-claude-sync working end-to-end
- ✅ LLM interpretation working (free text → yes/no)
- ✅ All integration tests passing (6 scenarios)
- ✅ Documentation complete (architecture, CLI, best practices, troubleshooting)

### Estimated Effort

**Total**: 4-5 days

---

## Progress Notes

### 2025.10.28 - Database Schema Complete ✓

**Session Start**:
- Created Phase 2 implementation tracking document (06-phase2-implementation-tracking.md)
- Reviewed complete design decisions document (3,326 lines, 9 areas, 40 questions)
- Clarified "migration" terminology (this is table creation, not migration)

**Database Implementation**:
- ✅ Added `lupin-notifications.db` to `.gitignore`
- ✅ Created table creation script: `src/scripts/create_notifications_table.py`
  - Uses canonical path pattern (`cu.get_project_root()`)
  - Bootstrap pattern for standalone execution (LUPIN_ROOT)
  - Idempotent (CREATE TABLE IF NOT EXISTS, CREATE INDEX IF NOT EXISTS)
  - Schema validation (23 fields, 3 indexes)
  - Proper error handling with exit codes
- ✅ Executed script successfully
  - Database created: `src/conf/long-term-memory/lupin-notifications.db` (24KB)
  - Schema: 23 fields (id, routing, source, content, timestamps, response, state, legacy)
  - Indexes: 3 (idx_recipient_state, idx_recipient_created, idx_expires_at)
  - Validation passed: ✓ 23 fields, ✓ 3 indexes

**Design Decisions**:
- Database choice: SQLite (not LanceDB) - correct for relational CRUD operations
- Database location: New dedicated `lupin-notifications.db` (not in lupin-auth.db)
- Rationale: Notifications are relational data (state transitions, queries by recipient/state/expiration), not vector embeddings

**Configuration Implementation**:
- ✅ Added 5 configuration keys to `lupin-app.ini` (lines 355-360)
  - `enable response required notifications = false` (feature flag for Phase 2.1+)
  - `enable sse blocking = false` (feature flag for Phase 2.1+)
  - `notification timeout default seconds = 120` (2 minutes default)
  - `notification grace period seconds = 30` (accept late responses within 30s)
  - `notification offline immediate default = true` (return default immediately if offline)
- ✅ Added explainer entries to `lupin-app-splainer.ini` (lines 69-78)
  - Comprehensive explanations for each configuration key
  - Rationale and behavior documented
- ✅ Verified ConfigurationManager loads keys dynamically (no code changes needed)

**Test Infrastructure Implementation**:
- ✅ Unit Tests: `src/tests/unit/test_notifications_database.py`
  - 10 tests covering CRUD, queries, and state transitions
  - 100% passing (pytest: 10 passed in 0.12s)
  - Test categories: TestNotificationCRUD (4), TestNotificationQueries (3), TestStateTransitions (3)
- ✅ Smoke Tests: `src/tests/smoke/test_notifications_smoke.py`
  - 4 test scenarios (database verification, CRUD workflow, state transitions, LLM helper placeholder)
  - All passing (✓ Smoke test completed successfully)
  - Professional output with `cu.print_banner()` formatting
- ✅ Integration Tests: `src/tests/integration/test_notifications_integration.py`
  - 6 test stubs defined for Phase 2.1+ implementation
  - Test categories: TestSSEBlockingFlow (5), TestMultiDeviceSync (2), TestOfflineDetection (1)
  - All tests marked with `@pytest.mark.skip` until backend ready
  - Fixtures defined (test_database, websocket_test_client, sse_test_client)

**Files Created/Modified**:
- Created: `src/scripts/create_notifications_table.py` (table creation script)
- Created: `src/conf/long-term-memory/lupin-notifications.db` (SQLite database, 24KB)
- Created: `src/tests/unit/test_notifications_database.py` (10 unit tests)
- Created: `src/tests/smoke/test_notifications_smoke.py` (smoke test suite)
- Created: `src/tests/integration/test_notifications_integration.py` (integration test stubs)
- Modified: `.gitignore` (added lupin-notifications.db)
- Modified: `src/conf/lupin-app.ini` (5 config keys added)
- Modified: `src/conf/lupin-app-splainer.ini` (5 explainer entries)

**Next Steps (Phase 2.1 - Week 2)**:
- Extend `/api/notify` endpoint for response-required notifications
- Create response submission endpoint (`POST /api/notify/response`)
- Implement SSE blocking flow with asyncio.Event
- Implement timeout and grace period handling
- Implement offline detection
- Extend WebSocket events (notification_responded, notification_expired)

**User Review Requested**:
- User wants to review smoke test module: `src/tests/smoke/test_notifications_smoke.py`

---

## Blockers & Dependencies

**Current**: None

**Known Dependencies**:
- Phase 2.1 depends on Phase 2.0 completion (database schema required)
- Phase 2.2 depends on Phase 2.1 completion (backend API required)
- Phase 2.3 depends on Phase 2.2 completion (UI integration required)

**Risks**:
- LLM interpretation quality (mitigated by comprehensive testing in Phase 2.0)
- Multi-device sync complexity (mitigated by existing WebSocket infrastructure)
- Scaling limitation (in-memory events, single-worker only - documented for Phase 3+ Redis migration)

---

## Technical Notes

### Database Schema Design (from Design Doc Area 1)

**29 Fields Total**:
- Identity: id (UUID), sender_id, recipient_id
- Source: source_context, source_sender
- Content: title (terse/technical), message (prose/TTS-friendly), type, priority
- Response: response_requested, response_type, response_value, response_default, timeout_seconds, responded_at
- State: state (5 states), deleted_at
- Timestamps: created_at, delivered_at, expires_at
- Legacy: played, play_count, last_played

**State Machine**:
```
created → delivered → responded → deleted
         ↓
      expired (if timeout occurs)
```

**Indexes**:
- `idx_recipient_state ON (recipient_id, state)`
- `idx_recipient_created ON (recipient_id, created_at)`
- `idx_expires_at ON (expires_at) WHERE expires_at IS NOT NULL`

### Configuration Keys (from Design Doc Area 8)

All keys use spaces (Lupin config style), not underscores:
- `enable response required notifications = false` (feature flag for Week 1+)
- `enable sse blocking = false` (feature flag for Week 2+)
- `notification timeout default seconds = 120` (2 minutes default)
- `notification grace period seconds = 30` (accept late responses within 30s)
- `notification offline immediate default = true` (return default immediately if user offline)

### Testing Strategy (from Design Doc Area 8)

**Unit Tests** (~10-15 tests):
- Database CRUD operations
- Timeout/expiration calculations
- Grace period validation
- State machine transitions

**Smoke Tests** (~10-15 tests):
- Basic workflows (create → store → retrieve)
- LLM response interpretation ("sure" → "yes", "nope" → "no")
- Simple timeout scenarios

**Integration Tests** (~25-30 tests):
- Full yes/no flow: notify-claude-sync → WebSocket delivery → button click → SSE return
- Full open-ended flow: notification → STT response → interpretation → return
- Timeout scenario: notification expires → return default value
- Grace period: late response accepted
- Multi-device sync: respond in Tab A → Tab B updates
- Offline detection: user offline → immediate default return

**Total**: ~40-50 tests across all tiers

---

## Important: Why "Migration" Terminology Appears in Design Doc

**Clarification**: The Phase 2 design document (`05-phase2-design-decisions.md`) uses "migration" terminology, which can be confusing. Here's what it actually means:

### What "Migration" Means in the Design Doc

**Architectural Transition** (system-level):
- Moving from **in-memory notifications** → **database-backed notifications**
- The "migration" refers to the system architecture change, not database schema changes

**Current State**:
- ❌ No `notifications` table exists in the database
- ✅ Notifications currently use in-memory `NotificationItem` objects
- ✅ Notifications are ephemeral (fire-and-forget, delivered via WebSocket, then discarded)

**What We're Actually Doing**:
- **Operation**: `CREATE TABLE IF NOT EXISTS notifications (...)` (initial table creation)
- **NOT**: `ALTER TABLE` or data migration from existing table
- **No data to migrate**: Old notifications are ephemeral (disposable, not persisted)

### What "Soft Migration" and "Dual-Write" Mean

**"Soft Migration"** (from design doc):
- Refers to the **rollout strategy**, not database operations
- Both systems run in parallel temporarily during rollout:
  - Old system: In-memory notifications via WebSocket (fire-and-forget)
  - New system: Database-backed notifications with response-required capability
- Gradual cutover (not hard cutover)

**"Dual-Write"** (from design doc):
- During transition period, both notification systems coexist
- New notification code writes to database
- Old notification code writes to memory
- Clients gradually upgrade to use new API

### Terminology Correction in This Tracking Document

**This tracking document uses accurate terminology**:
- ✅ "Table creation script" (not "migration script")
- ✅ "Initial table creation" (not "schema migration")
- ✅ `create_notifications_table.py` (not `migrate_notifications_phase2.py`)

**Why the design doc uses "migration"**: Describes the architectural transition strategy, following common "migration script" naming convention in web frameworks (Django, Rails, etc.), even though it's technically initial creation.

**Bottom line**: This is **table creation**, not migration. There's nothing to migrate.

---

## References

- **Design Document**: `05-phase2-design-decisions.md` (lines 2986-3235 contain detailed Phase 2.0-2.3 implementation plan)
- **Database Schema**: `05-phase2-design-decisions.md` (lines 133-230, Area 1 Q1.3)
- **Configuration**: `05-phase2-design-decisions.md` (lines 3018-3025, Phase 2.0 Configuration)
- **Testing Strategy**: `05-phase2-design-decisions.md` (lines 2648-2682, Area 8 Q8.2)
- **"Migration" Clarification**: See design doc lines 1867-1947 (Area 7 Q7.2) for original "soft migration" explanation
