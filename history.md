# Lupin Project History

> **🎁 CURRENT**: 2025.10.16 (Session 2) - JWT Token Proactive Refresh Planning COMPLETE! Analyzed JWT token freshness gap during idle periods (>1 hour), designed hybrid proactive refresh system with dual mechanisms (periodic 10-min monitor + heartbeat-triggered checks every 30s). Created comprehensive 800+ line implementation document covering architecture, configuration management (server-driven with explicit unit naming _ms/_secs/_mins), testing strategy (unit/smoke/integration), deployment plan. Eliminates 401 errors after idle, enables high-priority notifications to play immediately after >90 min inactivity. Ready to implement! 📋

> **✅ PREVIOUS**: 2025.10.16 (Session 1) - SSE Phase 2 Design Questions Captured! Identified critical architectural gaps preventing Phase 2 implementation: notification persistence (no DB serialization), response-required notifications (yes/no + open-ended STT), timeout handling, return value propagation to Claude Code. Created comprehensive design questions document (98-notification-design-draft.md) with 9 areas: data model, response types, timeout/expiration, SSE/WebSocket integration, bash return values, UI/UX, existing system integration, MVP scope, conceptual questions. Ready for design session to resolve 8 key decision points before implementation! 📋

> **✅ PREVIOUS**: 2025.10.15 (Session 4) - SSE Conceptual Deep Dive! Created comprehensive Q&A document (99-sse-conceptual-qna.md) clarifying async/sync terminology and cooperative multitasking patterns. Resolved confusion about blocking vs non-blocking event loops, documented production patterns for heartbeats with real work (asyncio.create_task). Added TODO for Phase 2 architecture discussion - design still TBD before implementation. Documentation: 2k+ lines capturing conceptual insights. ✅

> **✅ PREVIOUS**: 2025.10.15 (Session 3) - SSE Notification System Phase 1 COMPLETE! Built standalone PoC for synchronous notifications using Server-Sent Events. Created FastAPI SSE server (port 8000), Python streaming client, and bash wrapper script. All 5 tasks completed: server, client, wrapper, testing, documentation. Happy path test passed (10.42s processing). Ready for Phase 2 production integration (port 7999)! ✅

> **✅ PREVIOUS**: 2025.10.15 (Session 2) - JWT Token Expiration Auto-Refresh Fix! Diagnosed and fixed 401 Unauthorized errors caused by expired tokens (95% diagnostic confidence). Implemented ensureValidToken() helper with automatic token refresh across 4 API endpoints. Added comprehensive client/server debugging. Performance: ~1-2ms validation (fast path), ~50-200ms refresh (slow path). TTS now works indefinitely without authentication failures! ✅

> **✅ PREVIOUS**: 2025.10.15 (Session 1) - Fresh Queue TTS Mode & Performance Enhancements! Fixed high priority notification TTS mode bypass bug, implemented cache key consistency for instant replay, added time-to-first-playback metrics (⚡294ms instant, ~900ms reliable), fixed reliable mode authentication (missing X-Session-ID header). All TTS modes fully functional with performance instrumentation! ✅

> **EARLIER**: 2025.10.14 (Session 2) - Test Harness Update + Complete Bearer Token Fix! Implemented 2 regression tests for Oct 14 bugs (UUID format, Bearer token). Discovered incomplete Oct 14 fix - fixed 3 additional Bearer token instances. Fixed reliable TTS race condition (state initialization timing). All authentication working! ✅

> **EARLIER**: 2025.10.14 (Session 1) - Notification & TTS Authentication Fixes COMPLETE! Fixed two critical JWT authentication bugs: notification delivery (user ID format mismatch UUID vs email-hash) and TTS streaming (missing Bearer prefix). Added comprehensive WebSocket debugging infrastructure. All systems operational! ✅

> **⚠️ PREVIOUS**: 2025.10.08 - v0.1.0 Pre-Release Cleanup. Deprecated file-based snapshot manager (removed 46 JSON files), added developer workflow utilities (session-start slash command, backup sync script). Two clean commits advancing toward v0.1.0 release.

> **🎉 EARLIER**: 2025.10.06 - JWT Auth Database User Recovery. Restored authentication access after database wipe, created password reset utility with LUPIN_ROOT bootstrap pattern. Fixed root ownership issue preventing database writes.

> **Prior**: 2025.10.04 (Session 5) - Path Manipulation Cleanup COMPLETE! Eradicated fragile path manipulation across 20 files (75% reduction), implemented LUPIN_ROOT bootstrap pattern, enhanced global CLAUDE.md with comprehensive bootstrap guidance. All tests passing with canonical pattern.

> **Earlier**: 2025.10.04 (Session 3) - Configuration Block-Based Test Mode (PARTIAL). Implemented triple safety but discovered architecture blocker. 15/43 tests passing. Led to breakthrough simplification in Session 4.

> **More**: 2025.10.04 - JWT/OAuth 10/10 PHASES COMPLETE (100%)! 🚀 WebSocket JWT authentication fixed, all 8/8 integration tests passing, Phase 10 documentation complete (7 comprehensive docs, 4,500+ lines). System is production-ready!

> **Earlier**: 2025.10.03 - User-Filtered Queue Views PHASE 1 COMPLETE! Implemented role-based queue filtering backend with 32/32 unit tests passing (100%). Multi-tenant isolation with admin override capability.

> **More**: Integration Test Analysis & Remediation PHASE 1 COMPLETE! Fixed 4 test failures, achieved 7/8 passing (87.5%). Email service configuration-based fix implemented.

> **Prior Achievement**: 2025.10.01 - JWT/OAuth PHASE 9 CORE COMPLETE! Full authentication flow working: login, profile display, password change, re-authentication. Overall progress: 9/10 phases core complete (90%).

## Recent Activity (Last 7 Days)

### 🎯 October 2025 - Recent Sessions

#### 2025.10.16 (Session 2) - JWT Token Proactive Refresh Planning COMPLETE 📋

**Summary**: Comprehensive planning session for JWT token proactive refresh system to eliminate 401 errors during idle periods. Identified gap in current reactive-only refresh strategy (works for active users, fails after >30 min idle). Designed hybrid dual-mechanism solution with periodic background monitor + heartbeat-triggered checks. Created 800+ line implementation document with architecture, configuration management, testing strategy, and deployment plan. Ready for implementation (est. 6-8 hours).

**Problem Analysis**:

**Current Reactive-Only Refresh** ❌:
- `ensureValidToken()` only called BEFORE API requests
- Works: Active user (API calls every few minutes)
- Fails: Idle user (no API calls for >30 minutes)
- WebSocket stays connected (heartbeats continue) but token expires
- Result: First action after idle = 401 error + retry delay

**Idle Period Failure Scenario**:
```
T+0m:   User authenticates, token valid until T+30m
T+10m:  User goes idle (no clicks, no API calls)
T+30m:  Access token EXPIRES (WebSocket still connected)
T+90m:  📢 High-priority notification arrives
        → Notification delivered via WebSocket ✅
        → User clicks to play audio
        → API call with expired token → 401 Unauthorized ❌
        → ensureValidToken() recovers by refreshing
        → Second attempt succeeds ✅
        → Poor UX: double request, visible delay
```

**Solution: Hybrid Proactive Refresh** ✅:

**Dual Mechanism for Maximum Reliability**:

1. **Periodic Background Monitor** ⏰:
   - `setInterval` checks token every 10 minutes
   - Refreshes if < 5 minutes until expiry
   - Works: Tab active/foreground
   - Limitation: May throttle when tab backgrounded (browser optimization)

2. **Heartbeat-Triggered Check** 💓:
   - Piggybacks on existing WebSocket `sys_ping` (every 30 seconds)
   - Checks token freshness, refreshes if needed
   - Works: Even when tab backgrounded
   - Bypasses browser timer throttling

**Deduplication Logic**:
- Track `lastTokenRefresh_ms` timestamp
- Skip refresh if refreshed within last 60 seconds
- Prevents rapid-fire refreshes when both mechanisms fire

**Configuration-Driven Design**:

**Server-Side** (`lupin-app.ini`):
```ini
jwt token refresh check interval mins = 10   # Periodic monitor interval
jwt token refresh expiry threshold mins = 5  # When to trigger refresh
jwt token refresh dedup window secs = 60     # Prevent duplicates
```

**New Authenticated Endpoint** (`/api/config/client`):
- Returns timing parameters with unit conversions
- JWT authentication required (no public access)
- Falls back to hardcoded defaults if fetch fails

**Explicit Unit Naming Convention**:
- `_ms`: Milliseconds (JavaScript `Date.now()`, `setInterval`)
- `_secs`: Seconds (JWT `exp` claim, Unix timestamps)
- `_mins`: Minutes (Human-readable config, display)
- **Prevents bugs**: Can't accidentally compare milliseconds to seconds

**Implementation Plan**:

**Phase 1: Planning** ✅:
- Created comprehensive 800+ line design document
- Added to R&D README.md

**Phase 2: Server Changes** (Pending):
- Add JWT token refresh config to `lupin-app.ini`
- Implement `/api/config/client` endpoint in `system.py`

**Phase 3: Client Changes** (Pending - 9 tasks):
- Add token refresh properties to constructor
- Implement `fetchClientConfig()` method
- Implement `checkAndRefreshToken()` method
- Implement `start/stopTokenRefreshMonitor()` methods
- Modify `setupAuthentication()` to fetch config and start monitor
- Modify `handlePing()` to trigger heartbeat-based refresh
- Modify `handleAuthFailure()` and `logout()` to stop monitor
- Add window beforeunload cleanup handler

**Phase 4: Testing** (Pending - 3 test suites):
- Unit tests: Config endpoint, unit conversions, authentication
- Smoke tests: Config fetch, token refresh lifecycle
- Integration tests: 90-min idle scenario, deduplication, backgrounded tab

**Phase 5: Validation** (Pending):
- Run all tests and verify functionality

**Benefits**:
- ✅ Zero 401 errors during idle periods
- ✅ High-priority notifications play immediately after >1 hour idle
- ✅ No user-visible authentication failures
- ✅ Configuration-driven (easy to tune per environment)
- ✅ Dual redundancy (works in all tab states)
- ✅ No server changes to existing authentication endpoints

**Success Metrics**:
- **Before**: ~10-20 401 errors/day, 100% post-idle errors
- **Target**: 0 401 errors/day, 0% post-idle errors
- **Monitoring**: Token refresh frequency (~1 per 25 mins)

**Files Created**:
- `src/rnd/2025.10.16-jwt-token-proactive-refresh.md` (CREATED - 869 lines)
  - Executive summary & problem analysis
  - Dual-mechanism architecture with deduplication
  - Configuration management (server-driven, explicit units)
  - Implementation details (server + client ~150 lines)
  - Testing strategy (12 tests: 6 unit + 3 smoke + 3 integration)
  - Deployment plan & rollback strategy
  - Success metrics & monitoring queries
  - Future enhancements (adaptive timing, multi-tab coordination)

**Files Modified**:
- `src/rnd/README.md` (+1 line - added link to new document)
- `history.md` (this entry)

**Next Session TODO**:
- [ ] Implement Phase 2: Server changes (config + endpoint)
- [ ] Implement Phase 3: Client changes (~150 lines in queue-fresh.js)
- [ ] Implement Phase 4: Test suites (3 files, ~400 lines)
- [ ] Run all tests and validate functionality

---

#### 2025.10.16 (Session 1) - SSE Phase 2 Design Questions Captured 📋

**Summary**: Critical design session identifying architectural gaps preventing Phase 2 SSE implementation. User revealed fundamental missing pieces: notification persistence (no database serialization - lost on server shutdown), response-required notification types (yes/no buttons + open-ended STT), timeout/countdown UI, return value propagation to bash/Claude Code. Created comprehensive design questions document to capture all decision points before proceeding with implementation.

**Critical Gaps Identified**:

1. **Notification Persistence** 🗄️:
   - Current: All notifications in-memory - lost on server shutdown
   - Needed: Database serialization with unique ID (time + sender_id + recipient_id hash)
   - User preference: Explicit deletion vs auto-cleanup strategy

2. **Response-Required Notifications** 🎯:
   - Two types needed:
     - **Yes/No**: Click buttons OR microphone for free-text STT override
     - **Open-Ended**: Microphone icon for STT response
   - Animated countdown timer (updates every second, visual expiration indicator)
   - Timeout propagation: Return "no response/timeout" code to bash script → Claude Code

3. **Return Value Propagation** 📡:
   - bash script must return response to Claude Code caller
   - Exit codes + stdout format needs definition
   - Blocking behavior: notify-claude waits up to 120s for response

4. **Integration Questions** 🔄:
   - SSE vs WebSocket: Which protocol for which notification type?
   - Database schema: Lifecycle states, essential fields
   - UI placement: Separate "Action Required" section or inline?
   - Multi-device handling: What happens when user has multiple tabs open?

**Design Questions Document Created** (`98-notification-design-draft.md` - 600+ lines):

**9 Areas of Clarifying Questions**:
1. **Notification Persistence & Data Model**: Schema, lifecycle states, deletion semantics, unique ID strategy
2. **Response Types & UI Affordances**: Yes/No vs open-ended, extensibility (ratings, multiple choice), mixed modes
3. **Timeout & Expiration**: Duration, grace period, visual countdown format, color coding, audio alerts
4. **SSE vs WebSocket Architecture**: Dual connection model, delivery mechanism, endpoint design, complete notification flow
5. **Return Value Propagation**: Exit codes, response encoding (text vs JSON), Claude Code integration pattern
6. **Client UI/UX**: Display location, interactive elements placement, post-response behavior, multiple simultaneous notifications
7. **Existing System Integration**: Current notify-claude flow changes, database schema, WebSocket events, backward compatibility
8. **MVP Scope & Phasing**: Minimum viable product definition, what to defer to Phase 3/4
9. **Conceptual Questions**: Who sends response-required notifications, security/authorization, offline behavior, multi-device

**Key Decision Points** (8 areas requiring resolution):
1. Database schema for persistent notifications (exact fields)
2. Response types to support in MVP (just yes/no? or include open-ended?)
3. SSE architecture (per-notification stream? per-user stream? hybrid?)
4. Notification flow (complete sequence diagram from send → response → return)
5. Return value format for bash script (exit codes + stdout format)
6. UI placement for response-required notifications (separate section? inline?)
7. Timeout behavior (grace period? what happens to expired notifications?)
8. MVP scope (what's Phase 2 vs Phase 3 vs Phase 4?)

**Strawman MVP Proposed**:
- ✅ Database table for persistent notifications (basic schema)
- ✅ `response_required` boolean flag (start with just yes/no type)
- ✅ SSE endpoint for response-required notifications
- ✅ Client UI: Yes/No buttons + countdown timer
- ✅ Return value propagation to bash script
- ⏸️ Defer: Open-ended STT responses (Phase 3?)
- ⏸️ Defer: Deletion UI (just auto-cleanup after 7 days?)
- ⏸️ Defer: Multiple choice, ratings, etc.

**Files Created**:
- `src/rnd/sse-notifications/98-notification-design-draft.md` (CREATED - 617 lines)
  - 9 comprehensive areas of design questions
  - Summary of 8 key decision points
  - Strawman MVP scope proposal
  - Links to related SSE documentation

**Development Philosophy Applied**:
- Recognized architecture gaps before premature implementation
- Comprehensive question gathering for thorough design session
- Following "Planning is Prompting" pattern - design before code
- User insight: "Far too nebulous to begin implementation" - validated caution

**Next Session TODO**:
- [ ] Design session: Answer all questions in 98-notification-design-draft.md
- [ ] Document decisions in 03-decisions.md with rationale
- [ ] Update 02-architecture.md with persistent notification design
- [ ] Create Phase 2 implementation plan (update 01-implementation-current.md)
- [ ] Define database schema with exact field definitions
- [ ] Sketch complete notification flow sequence diagram
- [ ] Finalize MVP scope (Phase 2 vs Phase 3 boundary)
- [ ] Design notify-claude return value format and exit codes

**Key Insight**: Better to pause and clarify all architectural unknowns than to code with nebulous requirements. This session captured all the missing pieces in one comprehensive document, enabling a focused design session to resolve them systematically.

---

### 🎯 September 2025 - Recent Sessions (Sept 24-30)

#### 2025.09.30 - History Management Meta-Workflow System COMPLETE ✅

**Summary**: Created comprehensive, reusable history management meta-workflow to prevent history.md from exceeding 25k token limits. Implemented adaptive archival strategy with velocity forecasting, dual-channel notifications, and session-end integration.

**Problem Solved**: history.md reached 26,886 tokens (exceeded 25k limit). September's high-intensity development (38 sessions, ~1k tokens/day) broke the "30 days = 3k tokens" assumption.

**Solution Architecture**:
- **3-Location Strategy**: Canonical workflow (planning-is-prompting) + Project slash command + Optional reference copy
- **"Read and Execute" Pattern**: Minimal pointers instead of content duplication
- **Adaptive Archival**: Token thresholds (20k warning, 22k critical) + velocity-based forecasting
- **Natural Boundaries**: Split at milestones, week boundaries, or day boundaries
- **Visual Storytelling**: Multiple archives per month = intensity indicator

**Immediate Action Taken**:
- ✅ Archived Sept 3-23 content (26,886 → 4,647 tokens, 83% reduction)
- ✅ Created `history/2025-09-03-to-23-history.md` with metadata and navigation
- ✅ Archive naming convention: `YYYY-MM-DD-to-DD-history.md` (NO consolidation)

**Files Created/Modified**:
1. `/mnt/DATA01/include/www.deepily.ai/projects/planning-is-prompting/workflow/history-management.md` (533 lines) - Canonical workflow
2. `.claude/commands/history-management.md` (365 lines) - Lupin slash command
3. `src/rnd/prompts/history-management.md` (149 lines) - Reference copy with sync note
4. `.claude/commands/lupin-session-end.md` - Added Step 0.5 (History Health Check)
5. `/home/rruiz/.claude/CLAUDE.md` - Updated with minimal pointer approach

**Meta-Workflow Features**:
- **4 Operational Modes**: check, archive, analyze, dry-run
- **Velocity Forecasting**: 7-day rolling average predicts breach dates
- **Token Thresholds**: 🚨 CRITICAL (≥22k), ⚠️ WARNING (≥20k), ℹ️ MONITOR (breach <14d), ✅ HEALTHY
- **Adaptive Retention**: Keeps 8-12k tokens based on current size (7-14 days typical)
- **Session-End Integration**: Step 0.5 checks health before updating history
- **Dual Notifications**: CLI display + notify-claude alerts

**Adaptive Boundary Detection Algorithm** (Priority Order):
1. Most recent major milestone (✅ COMPLETE, 🎯 ACHIEVEMENT markers)
2. Most recent week boundary (Sunday date)
3. Most recent day boundary with <3 sessions
4. Token-based split keeping last 8-12k tokens

**Archive File Structure**:
```markdown
# Lupin Project History - September 3-23, 2025
> Archive Period, Archived Date, Reason, Token Reduction
> Parent Document link

## September 2025 Sessions (Sept 3-23)
### 🎯 Key Achievements This Period
[Auto-generated milestone summary]

[Full session content...]

## Navigation
### Archive Links
- Return to Main History
- Previous/Next archives (dynamic)
```

**Next Steps**:
- ⏳ Test `/history-management mode=dry-run` on current history.md (deferred to tomorrow)
- 📋 TODO: `[LUPIN] Test history-management dry-run mode on current history.md`

**Key Insights**:
- Archive naming tells visual story: Multiple files per month = high-intensity period
- "Read and execute" pattern prevents documentation bloat in config files
- Velocity-based forecasting enables proactive management vs. reactive crisis
- Step 0.5 integration prevents overflow during session-end ritual itself

---

**For October 1-15 sessions (24 sessions), see**: [history/2025-10-01-to-15-history.md](history/2025-10-01-to-15-history.md)

**For earlier September sessions (Sept 3-23), see**: [history/2025-09-03-to-23-history.md](history/2025-09-03-to-23-history.md)

---

## Implementation Documents

### Current Focus
- **JWT Token Proactive Refresh**: [src/rnd/2025.10.16-jwt-token-proactive-refresh.md](src/rnd/2025.10.16-jwt-token-proactive-refresh.md)
- **SSE Notifications Phase 2 Design**: [src/rnd/sse-notifications/98-notification-design-draft.md](src/rnd/sse-notifications/98-notification-design-draft.md)
- **WebSocket Events Documentation**: [src/docs/websocket-events.md](src/docs/websocket-events.md)
- **Fresh Queue UI**: Version 0.0.7 with envelope pattern and comprehensive list management

### Key Technical References
- **Audio Issues**: [Sequential Audio Analysis](src/rnd/2025.08.01-audio-chunk-sequential-playback-analysis.md)
- **Q&A Mystery**: [Audio Silence Investigation](src/rnd/2025.08.03-qa-audio-silence-mystery.md)
- **Testing Framework**: 50-test WebSocket smoke suite (92% success rate)

## Session Archives

### Monthly Archives
- **[October 2025 (Oct 1-15)](history/2025-10-01-to-15-history.md)** - Admin user management, queue filtering, JWT/OAuth completion, path cleanup
- **[September 2025 (Sept 3-23)](history/2025-09-03-to-23-history.md)** - Snapshot caching, Math Agent fixes, smoke test infrastructure, agent migration
- **[August 2025](history/2025-08-history.md)** - Audio/TTS enhancements, Pydantic XML migration, unit testing framework
- **[July 2025](history/2025-07-history.md)** - Progressive TTS streaming, user routing architecture
- **[June 2025](history/2025-06-history.md)** - Lupin renaming, notification system, WebSocket foundation
- **[May 2025 and Earlier](history/2025-05-and-earlier-history.md)** - PEFT training, agent migrations, Flask→FastAPI transition

### Project Context
- **Project Span**: December 2024 - Present (Lupin evolution from Genie-in-the-Box)
- **Current Branch**: `wip-v0.1.0-2025.10.07-at-09-00pm-pre-release-spit-and-polish`
- **Architecture**: FastAPI-only server (port 7999), WebSocket support, COSA framework integration
- **Status**: Production-ready WebSocket infrastructure with comprehensive testing framework

## Quick Navigation

### Development Commands
- Run FastAPI server: `src/scripts/run-fastapi-lupin.sh` (port 7999)
- Run WebSocket smoke tests: `src/scripts/run-websocket-smoke-tests.sh`
- Fresh Queue UI: http://localhost:7999/static/html/queue-fresh.html

### Current Development Areas
1. **JWT Token Proactive Refresh**: Eliminate 401 errors during idle periods (ready to implement)
2. **SSE Notifications Phase 2**: Response-required notifications (design in progress)
3. **Frontend Polish**: Fresh Queue UI with notification/job management
4. **Testing Infrastructure**: CoSA unit testing framework
