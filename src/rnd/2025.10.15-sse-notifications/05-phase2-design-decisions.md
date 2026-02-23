# SSE Phase 2 Design Decisions

**Document Purpose**: Record all architectural decisions from interactive design session for Phase 2 SSE notification system implementation

**Created**: 2025.10.17
**Updated**: 2025.10.27 (Session 3 - COMPLETE)
**Status**: ✅ DESIGN COMPLETE - Ready for Implementation
**Progress**: 9/9 areas completed (100%), 40 questions answered, implementation plan generated

---

## Navigation

**Related Documents**:
- [98-notification-design-draft.md](98-notification-design-draft.md) - Original design questions (this document contains the answers)
- [01-implementation-current.md](01-implementation-current.md) - Phase 1 PoC implementation (complete)
- [02-architecture.md](02-architecture.md) - Technical architecture (needs Phase 2 update)
- [03-decisions.md](03-decisions.md) - Architectural decisions log (will consolidate with this doc)

**Next Steps**:
1. Begin Phase 2.0 implementation (Foundation - Week 1)
2. Reference this document for all design decisions
3. Create tasks in TodoWrite for each phase
4. Follow 4-week phased rollout plan (see Implementation Plan section)

---

## Executive Summary

**Goal**: Design persistent, response-required notification system for Claude Code → User synchronous communication

**Key Decisions Made (Areas 1-7 complete)**:

**Database & Architecture** (Areas 1, 4, 7):
- ✅ Database schema with persistent storage (response_requested, response_default fields)
- ✅ Dual protocol architecture (WebSocket for delivery, SSE for blocking/waiting)
- ✅ In-memory event system with scaling documentation for future Redis migration
- ✅ Extend existing `/api/notify` endpoint (backward compatible, Accept header determines response type)
- ✅ Fresh schema with soft migration (no data loss, ephemeral fire-and-forget notifications)
- ✅ Extended `notification_queue_update` event + new `notification_responded` and `notification_expired` events
- ✅ Full backward compatibility (no API versioning needed)

**Response Types & Behavior** (Areas 2, 3, 5):
- ✅ LLM-based natural language response interpretation (user says "sure, why not?" → "yes")
- ✅ Multi-modal UX (voice, keyboard, mouse - accessibility first)
- ✅ Hybrid countdown timer (MM:SS + progress bar + color coding)
- ✅ Hybrid lazy server + active client expiration (asyncio.Event for single-worker)
- ✅ Intent-based grace period (30s if user started before expiration)
- ✅ Server-side interpretation, simple stdout output (exit 0=success, 1=error)

**Client UI/UX** (Area 6):
- ✅ Title/message split for voice-first UX (title: terse/technical, message: prose/TTS-friendly)
- ✅ Separate "Action Required" section in UI, buttons inline with timer + progress bar paired
- ✅ Confirmation flash (2.5s) + move to Recent Notifications after response
- ✅ Show all notifications with smart sorting (priority → expiration)

**Implementation Strategy (Areas 8-9)**:
- ✅ MVP scope: Both response types (yes/no + open-ended) in Phase 2
- ✅ Testing: 40-50 tests (unit + smoke + integration)
- ✅ Rollout: 4-week phased deployment with feature flags
- ✅ Security: No auth Phase 2 (localhost-only), add in Phase 3
- ✅ Offline: Immediate default return when user offline
- ✅ Multi-device: Real-time sync via WebSocket events

---

## 🗄️ AREA 1: DATABASE SCHEMA & PERSISTENCE ✅ COMPLETE

### Overview

**Problem**: Current system stores notifications in-memory only (lost on server shutdown)

**Solution**: Create dedicated `notifications` table with full lifecycle tracking

---

### Q1.1: Unique ID Strategy

**Question**: UUID vs composite key vs hybrid for notification IDs?

**Decision**: ✅ **UUID Primary Key** (Option A)

**Rationale**:
- Current `NotificationItem` already uses `uuid.uuid4()` - consistency with existing code
- Simple, guaranteed unique without coordination
- Sufficient for MVP - can add duplicate detection later if needed
- No need for composite keys or hash-based IDs initially

**Database Field**: `id TEXT PRIMARY KEY` (UUID string)

---

### Q1.2: Lifecycle States

**Question**: What states should notifications transition through?

**Decision**: ✅ **5-State Model with Boolean Flags**

**State Machine**:
```
created → delivered → responded → deleted
         ↓
      expired (if timeout occurs before response)
```

**States**:
- `created` - Notification inserted in database
- `delivered` - Sent via SSE/WebSocket to client
- `responded` - User provided response (for response-required notifications)
- `expired` - Timeout occurred, no response received
- `deleted` - User deleted or auto-cleanup removed

**Additional Flags** (not states):
- `played` - Boolean for fire-and-forget notifications (audio played)
- `read` - Tracked via timestamp, not separate state

**Rationale**:
- Clear progression for response-required flow
- Distinguishes expired (timeout) from deleted (user action)
- Backward compatible with existing `played` tracking
- Audit trail preserved (soft delete to `deleted` state)

**Database Field**: `state TEXT NOT NULL DEFAULT 'created'`

---

### Q1.3: Essential Fields

**Question**: What fields does the notifications table need?

**Decision**: ✅ **Comprehensive Schema with Source Split and Title/Message Separation**

**Full Database Schema**:

```sql
CREATE TABLE notifications (
    -- Identity
    id                      TEXT PRIMARY KEY,  -- UUID from uuid.uuid4()

    -- Routing
    sender_id               TEXT NOT NULL,     -- Specific user email-style ID (e.g., claude.code.cosa@deepily.ai)
    recipient_id            TEXT NOT NULL,     -- User UUID from auth database

    -- Source Context (NEW - splits old 'source' field)
    source_context          TEXT DEFAULT 'internal',  -- internal, external, claude_code, system
    source_sender           TEXT DEFAULT 'claude.code@deepily.ai',  -- Full email-style sender ID

    -- Content (NEW - title/message split)
    title                   TEXT NOT NULL,     -- Terse, technical, specific (e.g., "JWT Token Refresh Failed")
    message                 TEXT NOT NULL,     -- Prose, no acronyms/abbrevs, TTS-friendly
    type                    TEXT NOT NULL,     -- task, progress, alert, custom
    priority                TEXT NOT NULL,     -- urgent, high, medium, low

    -- Timestamps
    created_at              TEXT NOT NULL,     -- ISO timestamp with timezone
    delivered_at            TEXT,              -- When sent via SSE/WebSocket (NULL until delivered)
    expires_at              TEXT,              -- NULL for fire-and-forget, set for response-required

    -- Response-Required Fields
    response_requested      INTEGER DEFAULT 0, -- Boolean: 0 = no, 1 = yes
    response_type           TEXT,              -- NULL, 'yes_no', 'open_ended'
    response_value          TEXT,              -- JSON object (e.g., {"answer": "yes", "raw_utterance": "sure!", "confidence": "high"})
    responded_at            TEXT,              -- When user responded (NULL until responded)
    timeout_seconds         INTEGER,           -- Per-notification timeout (nullable, falls back to config max)
    response_default        TEXT,              -- 'yes', 'no', NULL (for pre-selecting button, accepting default with Enter)

    -- State Management
    state                   TEXT NOT NULL DEFAULT 'created',  -- created, delivered, responded, expired, deleted

    -- Legacy Compatibility (for fire-and-forget notifications)
    played                  INTEGER DEFAULT 0, -- Boolean: 0 = unplayed, 1 = played
    play_count              INTEGER DEFAULT 0, -- How many times audio played
    last_played             TEXT               -- Last playback timestamp
);

-- Indexes for common queries
CREATE INDEX idx_recipient_state ON notifications(recipient_id, state);
CREATE INDEX idx_recipient_created ON notifications(recipient_id, created_at);
CREATE INDEX idx_expires_at ON notifications(expires_at) WHERE expires_at IS NOT NULL;
```

**Key Design Decisions**:

**1. Source Field Split**:
- **Old**: Single `source` field (e.g., "claude_code")
- **New**: `source_context` + `source_sender`
- **Why**: Need to distinguish internal/external + specific sender identity
- **Example**:
  - `source_context = "internal"`
  - `source_sender = "claude.code.cosa@deepily.ai"`

**2. Title/Message Separation**:
- **title**: Terse, technical, acronyms OK (e.g., "JWT Token Refresh Failed")
- **message**: Prose-like, no acronyms, TTS-friendly (e.g., "The authentication token could not be refreshed. Please log in again.")
- **Why**: Voice-first UX - title shown in UI, message read aloud or shown on hover/click
- **UI Behavior**:
  - Title displayed with buttons in notification list
  - Message: First line with ellipsis, expand on hover/click

**3. Response Value as JSON**:
- **Field**: `response_value TEXT` (contains JSON object)
- **Why**: Structured metadata from day 1 - easier to extend later
- **Examples**:
  ```json
  {"answer": "yes", "method": "button_click", "timestamp": "2025-10-17T14:30:00Z"}
  {"answer": "yes", "method": "default_accepted", "timestamp": "..."}
  {"answer": "dismissed", "method": "keyboard_escape", "timestamp": "..."}
  {"answer": "custom", "method": "stt_override", "text": "maybe later", "raw_utterance": "maybe later", "timestamp": "..."}
  ```

**4. Per-Notification Timeout**:
- **Field**: `timeout_seconds INTEGER` (nullable)
- **Behavior**:
  - If NULL → use server config default (e.g., 120s)
  - If set → client requests specific timeout
  - Server validates: rejects if > config max (e.g., 300s)
- **Why**: Some decisions are urgent (10s), others can wait (5 minutes)
- **Example**: "Delete production database?" → 30s timeout (safety)

**5. Default Answer Support**:
- **Field**: `response_default TEXT` (values: 'yes', 'no', NULL)
- **Why**: Keyboard accessibility - user can hit Enter to accept pre-selected default
- **UI**: If `response_default = "yes"`, Yes button is pre-focused/highlighted
- **Example**: "Delete these 5 files?" → default="no" (safety first)

**Fields NOT Included** (and why):
- ❌ `solution_path_wo_root` - Not relevant for notifications (only for io_tbl conversation history)
- ❌ Composite unique constraint - UUID is sufficient, duplicate detection deferred to Phase 3

---

### Q1.4: Deletion Semantics

**Question**: Soft delete vs hard delete vs hybrid?

**Decision**: ✅ **Hybrid Approach** (Option C - Soft Delete + Auto-Cleanup)

**Behavior**:
1. **User Clicks Delete**:
   - Set `state = 'deleted'`
   - Set `deleted_at = NOW()` (add this timestamp field)
   - Keep row in database

2. **Nightly Cleanup Job**:
   - Hard-delete where `state = 'deleted' AND deleted_at < NOW() - 30 days`
   - Configurable retention period in `lupin-app.ini`

3. **Query Behavior**:
   - Default queries: `WHERE state != 'deleted'` (exclude deleted notifications)
   - Admin queries: Can include deleted for audit trail

**Rationale**:
- ✅ Audit trail for recent deletions (30 days)
- ✅ Can "undelete" within retention window if needed
- ✅ Database doesn't grow forever (cleanup after 30 days)
- ✅ Can analyze deletion patterns ("users delete 80% of low-priority notifications")

**Configuration**:
```ini
# lupin-app.ini
notification_deleted_retention_days = 30  # How long to keep deleted notifications
notification_cleanup_enabled = true       # Enable nightly cleanup job
```

**Additional Schema Field**:
```sql
deleted_at  TEXT,  -- Timestamp when user deleted (NULL if not deleted)
```

---

### Q1.A: Confirmation - Message Display UX

**Question**: How should message field be displayed in UI?

**Decision**: ✅ **First Line with Ellipsis + Expand on Hover/Click**

**Behavior**:
- **Collapsed** (default): Show first ~60 characters of message + "..."
- **Expand trigger**: Hover OR click on message text
- **Expanded**: Full message text displayed (tooltip, modal, inline expansion - TBD in Area 6)

**Rationale**:
- Keeps notification list compact
- Progressive disclosure - show details on demand
- Consistent with email inbox UX (subject line + preview)

---

### Q1.B: User Management CLI

**Question**: When do we build sender identity management?

**Decision**: ✅ **Phase 3** (Deferred)

**Planned Command**:
```bash
lupin-admin create-sender --email claude.code.cosa@deepily.ai \
                          --context internal \
                          --display-name "Claude Code (CoSA)"
```

**Why Defer**:
- MVP can use hardcoded sender IDs
- User management adds complexity (auth, permissions, UI)
- Focus Phase 2 on response-required core functionality

**Interim Solution**:
- Manually insert sender records in database
- Or use `source_sender = "system"` for all Phase 2 notifications

---

## 🎯 AREA 2: RESPONSE TYPES & UI AFFORDANCES ✅ COMPLETE

### Overview

**Goal**: Design intuitive, multi-modal UI for users to respond to notifications

**Principles**:
- **Voice-first**: Microphone icon is primary interaction
- **Keyboard accessible**: Tab navigation, Enter/Space/Escape shortcuts
- **Mouse/touch fallback**: Click buttons works too
- **Natural language**: User can say anything, LLM interprets intent

---

### Q2.1: Yes/No Response Type - Button Layout

**Question**: What buttons should appear for yes/no notifications?

**Decision**: ✅ **Three Buttons + Escape Key** (Modified Option D)

**Layout** (left to right):
```
[🎤 Mic] [Yes] [No]
```

**Interaction Modalities**:

**1. Voice (Primary)**:
- Click `🎤 Mic` button → STT captures utterance
- User says anything: "sure", "nah", "maybe later", "I don't care"
- **Press-to-talk only** (never always-on listening - prevents ambient false triggers)

**2. Keyboard**:
- `Tab` cycles through: Mic → Yes → No
- `Spacebar` or `Enter` activates focused button
- `Escape` = dismiss (no button needed - invisible interaction)

**3. Mouse/Touch**:
- Click any button

**Default Answer Support**:
- Sender can specify `response_default` field: `"yes"`, `"no"`, or `null`
- If set, corresponding button is pre-focused/highlighted
- User just hits `Enter` to accept default
- **Example Use Case**: "Delete these 5 files?" → default="no" (safety)

**Dismiss Behavior**:
- **No Dismiss Button** - cleaner UI
- `Escape` key = implicit dismiss
- STT can capture dismiss intent: "I don't care", "skip", "not answering"

**Rationale**:
- Voice-first (mic is leftmost, most prominent)
- Keyboard power users can navigate without mouse
- Default answer = minimal effort interaction (just hit Enter)
- Invisible dismiss (Escape) keeps UI clean while supporting power users

---

### Q2.1.A: Natural Language Response Interpretation

**Question**: How do we interpret free-form user responses like "sure, why not?"

**Decision**: ✅ **LLM-Based Classification via ConfirmationDialogue Pattern**

**Architecture**:
```
User Utterance (STT or typed)
  ↓
Server LLM Classification (ConfirmationDialogue.confirmed())
  ↓
Parsed Result: "yes" | "no" | "ambiguous"
  ↓
If ambiguous + no default → Ask user to clarify
```

**Implementation Reference**: `src/cosa/agents/confirmation_dialog.py`

**LLM Prompt Template**: `src/conf/prompts/agents/confirmation-yes-no.txt`
- Reduces utterance to: `yes`, `no`, or `ambiguous`
- Linguistics PhD student persona
- Step-by-step reasoning (chain of thought)
- Uses Pydantic XML parsing for structured output

**Example Mappings**:
| User Says              | LLM Interprets | Final Answer |
|------------------------|----------------|--------------|
| "Sure, why not?"       | yes            | yes          |
| "Nah, skip it"         | no             | no           |
| "I don't care"         | ambiguous      | dismissed (if that's the default) |
| "Maybe later?"         | ambiguous      | Use default_answer OR ask to clarify |
| "Absolutely"           | yes            | yes          |
| "Not right now"        | no             | no           |

**Response JSON Storage**:
```json
{
  "answer": "yes",
  "raw_utterance": "sure, why not?",
  "method": "stt_override",
  "confidence": "high",
  "timestamp": "2025-10-17T14:30:00Z"
}
```

**Server-Side Processing Flow**:
1. Client sends raw STT text: `{"raw_response": "sure, why not?"}`
2. Server POST `/api/notifications/{id}/classify` with utterance
3. Server runs `ConfirmationDialogue.confirmed(utterance, default=default_answer)`
4. Server stores result in `response_value` JSON field
5. Server updates notification: `state = 'responded'`

**STATUS**: ⚠️ **NEEDS CLARIFICATION** - Must design LLM classification endpoint before Phase 2 implementation

**Open Questions for Tomorrow**:
- Should classification endpoint be separate (`/api/classify-response`) or part of response submission?
- Should we cache LLM results for common utterances? ("yes", "no", "sure" seen 1000x)
- What happens if LLM call fails? Fallback to exact string matching?
- Should we allow user to override LLM interpretation? ("I said yes, not no!")

---

### Q2.2: Open-Ended Response Type

**Question**: What UI for free-form text responses?

**Decision**: ✅ **Microphone + Text Input Field** (Option B)

**Layout**:
```
[🎤 Mic] [________________________]
          Text input field
```

**Interaction**:
- **Voice**: Click mic → STT captures → populate text field
- **Keyboard**: Type directly into text field
- **Hybrid**: Speak first, then edit typed text
- **Submit**: Press `Enter` in text field OR click mic again (acts as submit if field has text)
- **Dismiss**: Press `Escape`

**Why No Dismiss Button**:
- Escape key handles it (consistent with yes/no)
- Cleaner UI - just mic + input
- Power users know Escape = dismiss

**Use Cases**:
- "Why are you deleting these files?" → "They're duplicates from the backup"
- "What should we name this feature?" → "ProactiveTokenRefresh"
- "Any feedback on the design?" → "Looks good, but consider adding a retry button"

**Accessibility**:
- ✅ Voice-first (mic prominent)
- ✅ Keyboard accessible (text input for noisy/private environments)
- ✅ Editing support (can correct STT errors)

**Response JSON**:
```json
{
  "answer": "open_ended",
  "text": "They're duplicates from the backup",
  "method": "stt_with_edit",  // or "keyboard_only"
  "timestamp": "2025-10-17T14:35:00Z"
}
```

---

### Q2.3: Future Response Types (Deferred to Phase 3+)

**Extensibility Design**:

The `response_type` field and `response_value` JSON structure support future types without schema changes:

**Potential Future Types**:
- `multiple_choice` - Radio buttons A/B/C/D
- `rating` - 1-5 stars or thumbs up/down
- `confirmation_with_reason` - Yes/No + "Why?" text field
- `slider` - Numeric range (1-100)

**Example `response_value` for Future Types**:
```json
// Multiple choice
{
  "answer": "C",
  "choices": ["A", "B", "C", "D"],
  "question": "Which approach is best?"
}

// Rating
{
  "answer": 4,
  "scale": "1-5 stars",
  "question": "How useful was this notification?"
}
```

**Decision**: ✅ **Design for extensibility, implement in Phase 3+**

---

## ⏱️ AREA 3: TIMEOUT & EXPIRATION BEHAVIOR ✅ COMPLETE

### Overview

**Goal**: Clear visual countdown and predictable timeout behavior

**Progress**: All 4 questions complete (Q3.1-Q3.4)

---

### Q3.1: Visual Countdown Timer Format ✅ COMPLETE

**Question**: How should countdown be displayed?

**Decision**: ✅ **Hybrid Multi-Modal Display** (Option D with enhancements)

**Visual Design**:
```
┌─────────────────────────────────────────┐
│ [🎤 Mic] [Yes] [No]      1:45 ⏱️        │  ← MM:SS timer
│ ████████████░░░░░░░░░░░░░░░░░░░░░░░░    │  ← Progress bar (58% full, yellow)
└─────────────────────────────────────────┘
```

**Components**:

**1. Numeric Timer (MM:SS)**:
- Format: `2:00` → `1:59` → `1:58` → ... → `0:05` → `0:04` → `0:00`
- Updates every second
- Precision for users who need exact time

**2. Progress Bar**:
- Horizontal bar that depletes left-to-right
- Visual urgency indicator
- Width represents time remaining percentage

**3. Color Coding** (applied to BOTH timer text and progress bar):
- **Green** (>50% time remaining): Plenty of time, no rush
- **Yellow** (20-50% remaining): Getting urgent, should respond soon
- **Red** (<20% remaining): Very urgent, about to expire

**4. Audio Alert** (TBD in Q3.3):
- Optional chime at T-minus 10 seconds
- Configurable per-user preference

**Rationale**:
- **Multiple perception modes**: Visual (progress bar), numeric (MM:SS), color (urgency)
- **Accessibility**: Color-blind users have progress bar + timer, deaf users have visual countdown
- **User preference**: Some users prefer precise numbers, others respond to visual cues
- **Gradual urgency**: Color transition creates psychological pressure without being annoying

**Example Timeline**:
```
T=120s (2:00) → Green progress bar, green timer, 100% full
T=90s  (1:30) → Green progress bar, green timer, 75% full
T=60s  (1:00) → Yellow progress bar, yellow timer, 50% full (transition point)
T=30s  (0:30) → Yellow progress bar, yellow timer, 25% full
T=20s  (0:20) → Red progress bar, red timer, 17% full (transition point)
T=10s  (0:10) → Red progress bar, red timer, 8% full + AUDIO CHIME (optional)
T=0s   (0:00) → EXPIRED
```

**User Quote**:
> "I like the multiple signal options you provided in your recommended option D, that is brilliant. This is precisely what I'm looking for: multiple ways of inputting and outputting information because different people have different perception strengths, weaknesses, and preferences."

---

### Q3.2: Server-Side Timeout Handling ✅ COMPLETE

**Question**: When does server mark notification as `expired`?

**Decision**: ✅ **Option C: Hybrid (Lazy Server + Active Client)**

**Implementation**:

**Client Behavior**:
1. Receives notification with `expires_at` timestamp
2. Shows countdown timer (MM:SS + progress bar + color coding)
3. At T=0, sends: `POST /api/notifications/{id}/expire`
4. Disables interactive elements (see UI behavior below)

**Server Behavior**:
1. Stores `expires_at` when notification created
2. Does NOT spawn active timer (no `asyncio.sleep()` tasks)
3. On client expire request: validates `expires_at < NOW()` and marks `state='expired'`
4. On all read queries: lazy expiration check
   ```sql
   SELECT * FROM notifications
   WHERE recipient_id = ?
     AND state != 'deleted'
     AND (state != 'delivered' OR expires_at > datetime('now'))
   ```
5. Optional: Periodic cleanup job (every 5 minutes) to catch orphaned notifications if client disconnects

**UI Behavior on Expiration**:
- ✅ **Disable interactive elements**: Mic button, Yes/No buttons (or text input) become grayed out/disabled
- ✅ **Visual indication**: Entire notification card gets subtle visual treatment (reduced opacity, grayed text)
- ✅ **Tooltip**: Hovering over disabled buttons shows: "This notification has expired and cannot be responded to"
- ✅ **Stay in place**: Notification remains in list at same position (no removal, no moving to different section)
- ✅ **Countdown stopped**: Timer shows "EXPIRED" (or "0:00") in red, progress bar empty/red

**Example Visual State**:
```
┌─────────────────────────────────────────────┐
│ 🚫 JWT Token Refresh Failed                 │  ← Subtle opacity/strikethrough
│ Message: The authentication token could...  │
│                                              │
│ [🎤 Mic] [Yes] [No]           EXPIRED ⚠️    │  ← Buttons disabled (grayed)
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░        │  ← Empty progress bar (red)
└─────────────────────────────────────────────┘
      ↑ Tooltip on hover: "This notification has expired and cannot be responded to"
```

**Rationale**:
- ✅ Client drives immediate UI feedback (no waiting for server round-trip)
- ✅ Server validates to prevent spoofing (client can't fake expiration before timeout)
- ✅ Lazy expiration catches edge cases (client offline, disconnected, crashed)
- ✅ No resource overhead of N active timers for N notifications
- ✅ Expired notifications remain visible for context (user can see what they missed)
- ✅ Disabled state prevents accidental interaction with expired notifications

---

### Q3.3: Audio & Visual Alerts ✅ COMPLETE

**Question**: Should we add audio/visual alerts as the timeout approaches?

**Decision**:
- ✅ **Audio Alerts**: Option C (No audio alerts during countdown)
- ✅ **Visual Alerts**: Option E (No additional visual alerts - color coding + timer sufficient)
- ✅ **Priority-Based Differentiation**: YES (already exists in system)
- ✅ **User Preference Settings**: YES (already tracking TTS preferences)

**Implementation**:

**Audio Behavior**:
- **On Receipt**: Priority-based audio alert (urgent = different beep, already implemented)
- **During Countdown**: No audio alerts at T-30s, T-10s, etc.
- **On Expiration**: No audio alert
- **Rationale**: Visual countdown (green → yellow → red) provides sufficient urgency cues

**Visual Behavior**:
- **Only**: Color-coded countdown timer + progress bar (already designed in Q3.1)
- **No**: Pulse/flash animations, shake effects, browser tab updates, desktop notifications
- **Rationale**: Keep UI calm and professional - color transition provides gradual psychological pressure without being annoying

**Priority-Based Differentiation** (existing system integration):
- **Receipt Alert**: Urgent/high priority already gets distinct audio beep (existing)
- **TTS Playback**: Currently only urgent/high priority notifications use TTS (existing user preference)
- **Response-Required Notifications**: Inherit same priority-based behavior

**User Preference Settings** (leverage existing):
- Current setting: "TTS for urgent/high priority only"
- Applies to response-required notifications same as fire-and-forget
- No new settings needed for MVP

**Rationale**:
- ✅ Consistent with existing notification system behavior
- ✅ Respects user's established TTS preferences
- ✅ Visual countdown is sufficient - no audio bombardment
- ✅ Simple, clean UX - not overwhelming
- ✅ Can add more alerts in Phase 3 if user feedback requests it

---

### Q3.4: Grace Period for Late Responses ✅ COMPLETE

**Question**: What happens if a user starts responding just before timeout but finishes after?

**Decision**: ✅ **Option C: Intent-Based Grace (Started Before Expiration)** with pragmatic server implementation

**Philosophy**: "Did the user genuinely try to respond before timeout?" → Accept it. This isn't high-frequency trading!

**Client-Side Intent Tracking**:

Track user interaction timestamps:
- **Mic button pressed**: `mic_pressed_at` timestamp
- **Text field focused**: `text_focused_at` timestamp
- **Text input started**: `first_keystroke_at` timestamp

**Client sends with response**:
```json
{
  "answer": "yes",
  "method": "stt_override",
  "raw_utterance": "sure, go ahead",
  "started_at": "2025-10-26T10:15:58Z",    // User clicked mic at T-2s
  "submitted_at": "2025-10-26T10:16:03Z",  // Response submitted at T+3s
  "timestamp": "2025-10-26T10:16:03Z"
}
```

**Server-Side Validation** (simple lazy check):

```python
# When response arrives via POST /api/notifications/{id}/respond
notification = get_notification(id)

# Check 1: Was intent shown before expiration?
if response['started_at'] < notification.expires_at:
    # User started responding before timeout - accept it
    accept_response(notification, response)
else:
    # User started responding AFTER timeout - reject it
    reject_response("Response started after notification expired")

# Check 2: Is response reasonably fresh? (optional safety check)
time_since_expiration = submitted_at - expires_at
if time_since_expiration > 30_seconds:
    # User took >30s after expiration - too stale, reject
    reject_response("Response submitted too long after expiration")
```

**Grace Period Window**: ~30 seconds after expiration (configurable)
- Covers STT processing latency (1-5 seconds)
- Allows slow typers to finish thought (10-20 seconds)
- Prevents abuse (can't respond 5 minutes later)

**Edge Case Handling**:

| Scenario | Started At | Submitted At | Accept? | Reason |
|----------|-----------|--------------|---------|--------|
| User clicks mic at T-2s, STT completes at T+3s | T-2s | T+3s | ✅ Accept | Intent before expiration, quick response |
| User typing at T-5s, submits at T+10s | T-5s | T+10s | ✅ Accept | Intent before expiration, reasonable delay |
| User hovers at T-1s, clicks at T+2s | T+2s | T+2s | ❌ Reject | No intent signal before expiration (hover ≠ click) |
| User clicks mic at T-2s, submits at T+45s | T-2s | T+45s | ❌ Reject | Too stale (>30s grace period) |
| User starts typing at T+5s (after expiration) | T+5s | T+10s | ❌ Reject | No intent before expiration |

**Client UX During Grace Period**:
- At T=0 (expiration), countdown shows "EXPIRED"
- If user has active interaction (mic recording, text field focused):
  - **Don't** disable buttons immediately
  - **Do** show warning banner: "⚠️ Notification expired, but you can still submit (started before timeout)"
  - **Allow** completion of current interaction
  - **Disable** after submission OR after 30s of inactivity

**Rationale**:
- ✅ User-friendly: Accepts genuine attempts to respond
- ✅ Simple server logic: Just compare `started_at < expires_at`
- ✅ Lazy validation fits our architecture (no active timers needed)
- ✅ SSE/WebSocket connection still open, response can arrive late
- ✅ Not time-critical (as you said - not stock trading!)
- ✅ 30-second grace window is generous but not abusable
- ✅ Prevents frustration from STT latency or slow typing

**Configuration** (lupin-app.ini):
```ini
# Grace period for late responses (if intent shown before expiration)
notification_grace_period_seconds = 30
```

---

## 📋 AREA 4: SSE VS WEBSOCKET ARCHITECTURE ✅ COMPLETE

### Overview

**Goal**: Define delivery architecture for response-required notifications

**Progress**: All 4 questions complete (Q4.1-Q4.4)

---

### Q4.1: Dual Connection Model vs Unified Approach ✅ COMPLETE

**Question**: Should we use SSE for response-required notifications, or leverage the existing WebSocket infrastructure?

**Decision**: ✅ **Option A: Dual Protocol (WebSocket + SSE)**

**Architecture**:

**Fire-and-Forget Notifications** (existing, unchanged):
- Command: `notify-claude-async` (renamed from `notify-claude`)
- Flow: POST `/api/notify` → WebSocket delivers to client → done
- No blocking, no response needed
- Uses existing WebSocket: `/ws/queue/{session_id}`

**Response-Required Notifications** (new):
- Command: `notify-claude-sync` (new SSE-based version)
- Flow: POST `/api/notify` with `response_requested=true` → SSE stream blocks → returns response
- Blocking behavior (script waits for user response or timeout)
- Uses SSE endpoint: POST returns SSE stream directly

**Unified Backend**:
- **Same POST endpoint**: `/api/notify` (add `response_requested` parameter)
- **Same database table**: `notifications` (with `response_requested` field)
- **Same WebSocket delivery**: Both notification types delivered to UI via WebSocket
- **SSE addition**: Only used for blocking/waiting behavior in notify-claude-sync

**Implementation Summary**:
```bash
# Fire-and-forget (existing behavior)
notify-claude-async "Task complete!" --type=task --priority=low
# → POST /api/notify (response_requested=false)
# → WebSocket pushes to client
# → Script exits immediately

# Response-required (new behavior)
notify-claude-sync "Delete 5 files?" --response-required yes_no --timeout 120
# → POST /api/notify (response_requested=true)
# → WebSocket pushes to client (shows UI with buttons)
# → SSE stream blocks until response
# → Script returns response and exits
```

**Rationale**:
- ✅ Keep existing fire-and-forget working (no changes needed)
- ✅ SSE only for blocking/waiting behavior (natural fit)
- ✅ WebSocket continues handling real-time delivery to UI
- ✅ Clear naming: async vs sync behavior explicit in command name
- ✅ Simple: One POST endpoint, different protocols for different use cases

---

### Q4.2: Notification Delivery Flow ✅ COMPLETE

**Question**: How does the complete notification flow work from POST to response?

**Decision**: ✅ **POST request returns SSE stream directly** (single connection model)

**Complete Flow**:

1. **notify-claude-sync script** → `POST /api/notify` with `Accept: text/event-stream`:
   ```json
   {
     "message": "Approve changes?",
     "response_requested": true,
     "response_type": "yes_no",
     "timeout_seconds": 120
   }
   ```

2. **Server** (POST handler):
   - Creates notification in database (UUID, state='created', expires_at, etc.)
   - Creates in-memory `asyncio.Event()` in global dict: `pending_responses[notification_id] = event`
   - Pushes notification via **WebSocket** to client UI
   - **Returns SSE stream** in POST response (connection stays open)
   - SSE stream awaits: `await event.wait()` (blocks until response arrives)

3. **Client** receives WebSocket event:
   - Renders notification UI (buttons, countdown timer)

4. **notify-claude-sync script** is blocked:
   - Reading SSE stream from original POST connection
   - Waiting for event

5. **User responds** (clicks Yes button):
   - Client → `POST /api/notifications/{notification_id}/respond` with `{"answer": "yes"}`

6. **Server** (respond handler):
   - Updates database: `state='responded'`, `response_value={"answer":"yes"}`
   - Looks up in-memory event: `pending_responses[notification_id]`
   - Stores response data: `pending_responses[notification_id]["response_data"] = response`
   - **Signals event**: `event.set()` ← **This wakes up the waiting SSE stream!**

7. **Server** (SSE stream from step 2):
   - Event is set, `await event.wait()` completes
   - Retrieves response data from `pending_responses[notification_id]["response_data"]`
   - Sends SSE event: `data: {"status": "responded", "answer": "yes"}\n\n`
   - Cleans up: `del pending_responses[notification_id]`
   - Closes SSE connection

8. **notify-claude-sync script** receives SSE event:
   - Closes connection
   - Prints to stdout: `yes`
   - Exits with code 0

9. **Claude Code** reads stdout and continues

**Inter-Request Communication**: In-Memory Event System (asyncio.Event)

```python
# Global state for pending responses
pending_responses = {}  # {notification_id: {"event": asyncio.Event(), "response_data": None}}

@app.post("/api/notify")
async def create_notification(data: NotificationCreate):
    # Create in database
    notification_id = str(uuid.uuid4())
    # ... insert into DB ...

    # Create in-memory event
    response_event = asyncio.Event()
    pending_responses[notification_id] = {
        "event": response_event,
        "response_data": None
    }

    # Push via WebSocket to client UI
    await websocket_manager.broadcast_to_user(user_id, notification)

    # SSE stream generator
    async def event_generator():
        try:
            # Wait for response (with timeout)
            await asyncio.wait_for(response_event.wait(), timeout=data.timeout_seconds)

            # Response received!
            response = pending_responses[notification_id]["response_data"]
            yield f"data: {json.dumps(response)}\n\n"

        except asyncio.TimeoutError:
            # Timeout occurred
            yield f"data: {json.dumps({'status': 'expired'})}\n\n"

        finally:
            # Cleanup
            if notification_id in pending_responses:
                del pending_responses[notification_id]

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/api/notifications/{notification_id}/respond")
async def respond_to_notification(notification_id: str, response: ResponseData):
    # Update database
    update_notification_response(notification_id, response)

    # Signal waiting SSE stream (if it exists)
    if notification_id in pending_responses:
        pending_responses[notification_id]["response_data"] = response
        pending_responses[notification_id]["event"].set()  # Wake up SSE stream!

    return {"status": "ok"}
```

**⚠️ SCALING LIMITATION - IMPORTANT DOCUMENTATION**

**Current Design Constraint**: Single-worker FastAPI only

**Why it works now**:
- Both POST requests (create notification, respond to notification) hit the same worker process
- In-memory `pending_responses` dict is shared within the single process
- `asyncio.Event()` signals work within the same event loop

**What breaks with multiple workers** (`uvicorn --workers 4`):
- Request A (create notification) might hit Worker 1
- Request B (respond to notification) might hit Worker 2
- Worker 2's `pending_responses` dict doesn't have Worker 1's event
- SSE stream in Worker 1 never receives signal
- notify-claude-sync times out even though user responded

**Migration Path for Scaling** (Phase 3+):

When scaling to multiple workers, choose one:

1. **Redis Pub/Sub** (recommended):
   - Replace `asyncio.Event()` with Redis pub/sub channels
   - Workers communicate via Redis: `PUBLISH notification:{id}:response`
   - Fast, production-grade, commonly used pattern

2. **Database Polling with Notifications**:
   - PostgreSQL: Use `LISTEN/NOTIFY` for real-time updates
   - SQLite: Fall back to polling (check DB every 500ms)

3. **Sticky Sessions** (workaround):
   - Load balancer ensures same user always hits same worker
   - Fragile, not recommended for production

**Documentation Location**: Add to `src/rnd/2025.10.15-sse-notifications/02-architecture.md`

**Configuration Flag** (future):
```ini
# lupin-app.ini
notification_response_backend = inmemory  # or: redis, postgres_notify
```

**Rationale**:
- ✅ Simple for MVP (single worker deployment)
- ✅ Clear upgrade path documented
- ✅ asyncio.Event is fast and reliable for single-process
- ✅ Scaling decisions deferred until needed

---

### Q4.3: SSE Endpoint Design ✅ COMPLETE

**Question**: Should we have a separate SSE endpoint, or return SSE stream from POST?

**Decision**: ✅ **Option A: Single Endpoint (POST returns SSE stream directly)**

**Endpoint**:
- `POST /api/notify` with `Accept: text/event-stream` header
- Returns SSE stream immediately in the POST response
- No separate GET `/sse/notification/{id}` endpoint needed

**Implementation**:
```bash
# notify-claude-sync (simplified)
curl -X POST /api/notify \
  -H "Accept: text/event-stream" \
  -H "Authorization: Bearer $token" \
  -d '{
    "message": "Approve changes?",
    "response_requested": true,
    "response_type": "yes_no",
    "timeout_seconds": 120
  }'
# → SSE stream opens, blocks until response or timeout
# → Returns: data: {"status": "responded", "answer": "yes"}
```

**Rationale**:
- ✅ Simpler (one request instead of two)
- ✅ Atomic operation (create + wait in single call)
- ✅ Matches Phase 1 PoC implementation
- ✅ No race condition (notification exists before SSE stream opens)

---

### Q4.4: WebSocket Events for Response-Required Notifications ✅ COMPLETE

**Question**: Should we add new WebSocket event types to distinguish response-required notifications from fire-and-forget?

**Decision**: ✅ **Option A: Unified Event (reuse existing `notification_queue_update`)**

**WebSocket Event Structure**:

```javascript
{
  "event": "notification_queue_update",
  "notification": {
    // Identity
    "id": "uuid-123",
    "sender_id": "claude.code@deepily.ai",
    "recipient_id": "user-uuid",

    // Content
    "title": "Approve Changes?",
    "message": "Claude Code wants to modify 5 files. Do you approve?",
    "type": "task",
    "priority": "high",

    // Response-Required Fields (NEW)
    "response_requested": true,        // ← Client checks this to render response UI
    "response_type": "yes_no",         // "yes_no" or "open_ended"
    "response_default": "yes",         // ← Pre-selected answer ("yes", "no", or null)
    "timeout_seconds": 120,            // Client uses this for countdown timer
    "expires_at": "2025-10-26T10:18:00Z",

    // Timestamps
    "created_at": "2025-10-26T10:16:00Z",
    "delivered_at": "2025-10-26T10:16:00Z",

    // State
    "state": "delivered"
  }
}
```

**Field Mapping** (Database → WebSocket):
- ✅ **Identical field names** - no translation needed
- DB: `response_requested` → WebSocket: `response_requested`
- DB: `response_default` → WebSocket: `response_default`
- All other fields: Same name everywhere

**Client Behavior**:

```javascript
// Client WebSocket handler
if (notification.response_requested) {
  // Render response UI with buttons/input
  renderResponseRequiredUI(notification);

  // Pre-select default if specified
  if (notification.response_default === "yes") {
    highlightYesButton();  // Focus Yes button, user can press Enter
  } else if (notification.response_default === "no") {
    highlightNoButton();   // Focus No button, user can press Enter
  }

  // Start countdown timer
  startCountdown(notification.timeout_seconds, notification.expires_at);
} else {
  // Fire-and-forget notification
  renderStandardNotification(notification);
}
```

**Rationale**:
- ✅ Backward compatible (existing clients ignore new fields)
- ✅ Single event type (simpler client logic)
- ✅ `response_default` enables keyboard accessibility (Enter = accept default)
- ✅ Client has all info needed to render appropriate UI
- ✅ Consistency across stack (database, API, WebSocket, client)

---

## 📡 AREA 5: RETURN VALUE PROPAGATION ✅ COMPLETE

### Overview

**Goal**: Define how not ify-claude-sync returns responses to Claude Code

**Progress**: All 3 questions complete (Q5.1-Q5.3)

---

### Q5.1: Script Exit Codes and Output Format ✅ COMPLETE

**Question**: How should notify-claude-sync communicate the response back to the calling bash/Claude Code?

**Decision**: ✅ **Option 1: Server Interprets, Returns Simple Value**

**Implementation**:

**Server-Side Logic** (SSE stream response):
```python
# When user responds
if user_clicked_yes:
    return {"answer": "yes"}
elif user_clicked_no:
    return {"answer": "no"}

# When timeout occurs
elif timeout_occurred:
    if response_default is not None:
        # Apply default answer
        return {"answer": response_default}  # "yes" or "no"
    else:
        # No default specified
        return {"answer": None}

# When user dismisses (Escape key)
elif user_dismissed:
    return {"answer": None}
```

**notify-claude-sync Script Output**:
```bash
# Server returned: {"answer": "yes"}
echo "yes"
exit 0

# Server returned: {"answer": "no"}
echo "no"
exit 0

# Server returned: {"answer": null} (timeout or dismissed)
echo ""
exit 0

# Infrastructure error (auth, network, server down)
echo "error: Connection failed" >&2
exit 1
```

**Claude Code Usage Pattern**:
```bash
# Example: Ask for approval with default=yes
answer=$(notify-claude-sync "Delete 5 files?" \
    --response-required yes_no \
    --default yes \
    --timeout 120)

if [ $? -ne 0 ]; then
    # Infrastructure error (exit 1)
    echo "Failed to send notification"
    exit 1
fi

if [ "$answer" = "yes" ]; then
    # User clicked Yes OR timeout with default=yes
    delete_files
elif [ "$answer" = "no" ]; then
    # User clicked No
    echo "User declined"
elif [ -z "$answer" ]; then
    # Empty string: timeout with no default OR user dismissed
    echo "No response received, skipping"
fi
```

**Exit Code Semantics**:
- `0` = Success (response received, timeout, or dismissed)
- `1` = Infrastructure error (auth failure, network error, server unavailable)

**Stdout Values**:
- `"yes"` = User approved OR timeout with default=yes
- `"no"` = User declined OR timeout with default=no
- `""` (empty) = Timeout with no default OR user dismissed

**Rationale**:
- ✅ Simple bash script (minimal interpretation logic)
- ✅ Server applies business logic (default_answer handling)
- ✅ Easy for Claude Code to consume
- ✅ Sufficient for MVP use cases
- ✅ Can add exit codes in Phase 3 if needed

---

### Q5.2: Open-Ended Response Handling ✅ COMPLETE

**Question**: For `response_type = "open_ended"`, what does notify-claude-sync output?

**Decision**: ✅ **Option A: Multi-line stdout (simple text output)**

**Implementation**:

**Server SSE Response**:
```python
# For open-ended responses
{
    "answer": "They're duplicates from the backup"  # User's text response
}
```

**notify-claude-sync Script Output**:
```bash
# Single-line response
echo "They're duplicates from the backup"
exit 0

# Multi-line response (newlines preserved)
echo "These files are duplicates.
They came from the backup restore.
Safe to delete."
exit 0

# Empty response (timeout or dismissed)
echo ""
exit 0
```

**Claude Code Usage**:
```bash
# Ask open-ended question
reason=$(notify-claude-sync "Why are you deleting these files?" \
    --response-required open_ended \
    --timeout 300)

if [ -n "$reason" ]; then
    echo "User provided reason: $reason"
    log_deletion_reason "$reason"
    delete_files
else
    echo "No reason provided"
fi
```

**Edge Cases**:
- **Multi-line text**: Preserved as-is (newlines included in stdout)
- **Special characters**: Output as-is (quotes, apostrophes, etc.)
- **Empty response**: Empty string (same as yes/no timeout/dismiss)
- **Very long text**: No truncation (full response returned)

**Rationale**:
- ✅ Simplest possible output format
- ✅ No parsing required in Claude Code
- ✅ Bash naturally handles multi-line strings
- ✅ Consistent with yes/no output format
- ✅ Metadata (method, timestamp) stored in DB but not needed by caller

---

### Q5.3: Command-Line Interface Design ✅ COMPLETE

**Question**: What should the notify-claude-sync command-line interface look like?

**Decision**: ✅ **Flag-based syntax with --response-required**

**Command Syntax**:
```bash
notify-claude-sync MESSAGE [OPTIONS]
```

**Options**:
```
--response-required TYPE    Response type: "yes_no" or "open_ended" (required)
--default ANSWER           Default answer: "yes" or "no" (optional, yes_no only)
--timeout SECONDS          Timeout in seconds (optional, default: 120)
--type TYPE                Notification type (optional, default: "task")
--priority PRIORITY        Priority level (optional, default: "medium")
--title TITLE              Short title (optional, defaults to MESSAGE)
```

**Usage Examples**:

```bash
# Yes/No with default and custom timeout
notify-claude-sync "Delete 5 files?" \
    --response-required yes_no \
    --default no \
    --timeout 60

# Open-ended question with longer timeout
notify-claude-sync "Why are you deleting these files?" \
    --response-required open_ended \
    --timeout 300

# Urgent approval request
notify-claude-sync "Approve production database migration?" \
    --response-required yes_no \
    --priority urgent \
    --type alert \
    --timeout 30

# With explicit title and message
notify-claude-sync "This will drop the users table and recreate it. Proceed?" \
    --response-required yes_no \
    --title "Database Migration Approval" \
    --default no \
    --timeout 120
```

**Validation Rules**:
- `--response-required` is mandatory (distinguishes from notify-claude-async)
- `--default` only valid with `--response-required yes_no`
- `--timeout` must be positive integer (server enforces max, e.g., 300s)
- `--type` validates against: task, progress, alert, custom
- `--priority` validates against: urgent, high, medium, low

**Error Handling**:
```bash
# Missing required flag
$ notify-claude-sync "Delete files?"
Error: --response-required is required
Usage: notify-claude-sync MESSAGE --response-required TYPE [OPTIONS]

# Invalid default with open_ended
$ notify-claude-sync "Why?" --response-required open_ended --default yes
Error: --default is only valid with --response-required yes_no
```

**Rationale**:
- ✅ Explicit and self-documenting
- ✅ Consistent with notify-claude-async flag style
- ✅ Easy to extend with new options
- ✅ Clear error messages for misuse

---

## 🎨 AREA 6: CLIENT UI/UX DESIGN (PARTIAL - 2/4 questions)

### Overview

**Goal**: Design how response-required notifications appear and behave in Fresh Queue UI

**Progress**: Q6.1-Q6.2 ✅ complete, Q6.3-Q6.4 pending for next session

---

### Q6.1: Notification Display Location ✅ COMPLETE

**Question**: Where in the Fresh Queue UI should response-required notifications appear?

**Decision**: ✅ **Option B: Separate "Action Required" Section**

**UI Layout**:

```
┌─────────────────────────────────────────────────┐
│  Fresh Queue                                    │
├─────────────────────────────────────────────────┤
│                                                 │
│  ⚡ ACTION REQUIRED                             │
│  ┌───────────────────────────────────────────┐ │
│  │ 🔔 Approve Database Migration?            │ │
│  │ This will drop the users table...         │ │
│  │ [🎤] [Yes] [No]              0:45 ⏱️      │ │
│  │ ████████████████░░░░░░░░░░░░              │ │
│  └───────────────────────────────────────────┘ │
│                                                 │
│  ┌───────────────────────────────────────────┐ │
│  │ 🔔 Delete 5 files?                        │ │
│  │ These files are duplicates...             │ │
│  │ [🎤] [Yes] [No]              1:30 ⏱️      │ │
│  │ ██████████████████████████░░░░            │ │
│  └───────────────────────────────────────────┘ │
│                                                 │
├─────────────────────────────────────────────────┤
│  📋 RECENT NOTIFICATIONS                        │
│  ┌───────────────────────────────────────────┐ │
│  │ ✓ Task complete                           │ │
│  │ 2 minutes ago                             │ │
│  └───────────────────────────────────────────┘ │
│                                                 │
│  ┌───────────────────────────────────────────┐ │
│  │ ℹ️ Build finished successfully            │ │
│  │ 5 minutes ago                             │ │
│  └───────────────────────────────────────────┘ │
│                                                 │
└─────────────────────────────────────────────────┘
```

**Section Behavior**:

**"Action Required" Section** (top):
- Only shows notifications with `response_requested = true`
- Sorted by priority (urgent first), then by expiration (soonest first)
- Always visible at top (doesn't scroll with recent notifications)
- Section header shows count: "⚡ ACTION REQUIRED (2)"
- When empty, section collapses or shows: "No actions required ✓"

**"Recent Notifications" Section** (bottom):
- Fire-and-forget notifications (existing behavior)
- Sorted by timestamp (newest first)
- Includes expired/responded notifications (moved down after completion)
- Scrollable if list is long

**Visual Distinction**:
- Action Required cards: Highlighted border, larger, interactive elements
- Recent Notifications: Standard card styling, non-interactive

**Expired Notification Behavior**:
- Once notification expires or user responds, moves from "Action Required" to "Recent Notifications"
- Shows status: "✓ Responded: Yes" or "⏱️ Expired (no response)"

**Rationale**:
- ✅ Clear separation: "Needs attention" vs "FYI"
- ✅ High visibility: Action items always at top
- ✅ Not blocking: User can still browse recent notifications
- ✅ Organized: Easy to see what requires action at a glance
- ✅ Clean: Expired items move out of action section

---

### Q6.2: Interactive Elements Layout ✅ COMPLETE

**Question**: Within a response-required notification card, how should the interactive elements be arranged?

**Decision**: ✅ **Modified Option B: Buttons inline, Timer + Progress Bar paired horizontally**

**Final Layout**:
```
┌─────────────────────────────────────────────┐
│ Title: Delete 5 files?                      │
│ Message: These files are duplicates...      │
│                                             │
│ [🎤] [Yes] [No]                             │
│                                             │
│ 1:30 ⏱️  ████████████████████░░░░░░░░      │
└─────────────────────────────────────────────┘
```

**Element Positioning**:
- **Row 1**: Title (bold, terse)
- **Row 2**: Message (prose, expandable on hover/click)
- **Row 3**: Interactive buttons (Mic, Yes, No OR Mic + text input)
- **Row 4**: Timer + Progress bar (horizontally aligned, visually paired)

**Rationale**:
- ✅ Timer and progress bar on same level (reinforces their relationship)
- ✅ Buttons separate from countdown (clear action vs status separation)
- ✅ Compact layout (4 rows total)
- ✅ Progress bar spans most of width (high visibility)

---

### Q6.3: After Response Submitted ✅ COMPLETE

**Question**: What happens to the notification after user responds?

**Decision**: ✅ **Option B: Confirmation Flash + Move to Recent**

**Implementation**:

**Step-by-Step Behavior**:
1. User clicks Yes/No button (or submits voice/text response)
2. Notification shows confirmation state immediately:
   - Green checkmark icon appears
   - Text overlay: "Response sent ✓"
   - Buttons become disabled (grayed out)
   - Timer stops (if still counting down)
3. After 2-3 second delay (configurable, default: 2.5s):
   - Notification fades out from "Action Required" section
   - Simultaneously fades into "Recent Notifications" section
   - Shows status in Recent: "✓ Answered: Yes" (or "No")
4. State update:
   - Database: `state = "responded"`
   - `responded_at` timestamp recorded
   - `response_value` JSON stored

**Visual Design**:
```
┌─────────────────────────────────────────────┐
│ ✅ Approve File Changes?                    │ ← Green checkmark replaces priority icon
│ Response sent ✓                             │ ← Confirmation text
│ [Yes ✓] [No]                                │ ← Selected button highlighted, both disabled
│ 🟢 ▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░ 01:45                 │ ← Timer frozen at response time
└─────────────────────────────────────────────┘
       ↓ (2.5 second fade transition)
┌─────────────────────────────────────────────┐
│ Recent Notifications                         │
│ ┌───────────────────────────────────────┐   │
│ │ ✓ Approve File Changes?               │   │
│ │ Answered: Yes • 10:47 AM              │   │
│ └───────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

**Technical Details**:

**Client-Side Transition**:
```javascript
async function handleResponseSubmit( notificationId, answer ) {
  // 1. Send response to server
  await fetch( `/api/notifications/${notificationId}/respond`, {
    method: "POST",
    body: JSON.stringify( { answer } )
  } );

  // 2. Update UI immediately (optimistic update)
  const notification = document.getElementById( `notif-${notificationId}` );
  notification.classList.add( "response-confirmed" );  // Show checkmark + "Response sent ✓"
  disableButtons( notification );
  stopTimer( notification );

  // 3. Wait 2.5 seconds
  await sleep( 2500 );

  // 4. Fade out from Action Required, fade into Recent
  notification.classList.add( "fade-out" );
  await sleep( 300 );  // CSS transition duration

  // 5. Move DOM element
  moveToRecentNotifications( notificationId, answer );
}
```

**Server-Side WebSocket Event** (broadcast to all user's devices):
```javascript
{
  "event": "notification_responded",
  "notification_id": "uuid-123",
  "answer": "yes",
  "responded_at": "2025-10-26T10:47:23Z"
}
```

**Multi-Device Sync**:
- When user responds in Tab 1, Tab 2 receives `notification_responded` event
- Tab 2 performs same UI transition (confirmation → Recent)
- All devices stay in sync

**Rationale**:
- ✅ Immediate feedback (user knows response was received)
- ✅ Clears Action Required quickly for next notification
- ✅ Preserves audit trail in Recent Notifications
- ✅ 2.5 second delay is enough for confirmation without being disruptive
- ✅ Mirrors common UX patterns (toast notifications, Gmail's "Message sent" confirmation)
- ✅ Multi-device synchronization ensures consistent state

**Edge Cases**:
- **Network error during response**: Show error state, keep in Action Required with retry button
- **Timeout occurs during 2.5s confirmation window**: Cancel transition, move to expired state instead
- **User switches tabs during confirmation**: Transition completes in background, user sees final state in Recent

---

### Q6.4: Multiple Simultaneous Notifications ✅ COMPLETE

**Question**: How does the UI handle multiple response-required notifications at once?

**Decision**: ✅ **Option D: Show All with Count Badge + Smart Sorting**

**Implementation**:

**UI Layout**:
```
┌─────────────────────────────────────────────┐
│ ⚠️ Action Required (5)                      │ ← Count badge shows total
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━│
│                                             │
│ ┌─────────────────────────────────────┐   │ ← Urgent, expires in 30s
│ │ 🔴 Approve Deletion?                │   │
│ │ Delete 5 production files           │   │
│ │ [Yes] [No]                          │   │
│ │ 🔴 ▓▓▓▓▓▓▓░░░░░░░░░░ 00:30          │   │
│ └─────────────────────────────────────┘   │
│                                             │
│ ┌─────────────────────────────────────┐   │ ← High, expires in 2:15
│ │ 🟠 Approve File Changes?            │   │
│ │ Claude Code wants to modify 5 files │   │
│ │ [Yes] [No]                          │   │
│ │ 🟢 ▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░ 02:15           │   │
│ └─────────────────────────────────────┘   │
│                                             │
│ ┌─────────────────────────────────────┐   │ ← High, expires in 2:45
│ │ 🟠 Install Dependencies?            │   │
│ │ npm install required packages       │   │
│ │ [Yes] [No]                          │   │
│ │ 🟢 ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░ 02:45           │   │
│ └─────────────────────────────────────┘   │
│                                             │
│ ┌─────────────────────────────────────┐   │ ← Medium, expires in 5:00
│ │ ⚪ Provide Feedback?                │   │
│ │ How should we handle this error?    │   │
│ │ [Yes] [No] 🎤                       │   │
│ │ 🟢 ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ 05:00          │   │
│ └─────────────────────────────────────┘   │
│                                             │
│ ┌─────────────────────────────────────┐   │ ← Medium, expires in 5:30
│ │ ⚪ Review Changes?                  │   │
│ │ Please review the updated code      │   │
│ │ [Yes] [No]                          │   │
│ │ 🟢 ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ 05:30          │   │
│ └─────────────────────────────────────┘   │
│                                             │
│ ↓ Scroll for more                          │ ← Scroll indicator if >5
└─────────────────────────────────────────────┘
```

**Sorting Algorithm**:

**Priority 1: Priority Level** (urgent → high → medium → low)
**Priority 2: Expiration Time** (soonest first within same priority)

```python
def sort_action_required( notifications ):
    """
    Sort response-required notifications for display in Action Required section.

    Sorting logic:
    1. Priority (urgent > high > medium > low)
    2. Expiration time (soonest first within same priority)
    """
    priority_order = { "urgent": 0, "high": 1, "medium": 2, "low": 3 }

    return sorted( notifications, key=lambda n: (
        priority_order.get( n["priority"], 99 ),  # Primary: priority
        n["expires_at"]                            # Secondary: soonest expiration
    ) )
```

**Example Sorting**:
```
Input (arrival order):
1. medium, expires 5:30
2. urgent, expires 0:30
3. high, expires 2:45
4. high, expires 2:15
5. medium, expires 5:00

Output (display order):
1. urgent, expires 0:30    ← Top (highest priority, soonest)
2. high, expires 2:15      ← High priority, expires sooner
3. high, expires 2:45      ← High priority, expires later
4. medium, expires 5:00    ← Medium priority, expires sooner
5. medium, expires 5:30    ← Medium priority, expires later
```

**Count Badge Behavior**:
- Shows total count: "⚠️ Action Required (5)"
- Updates dynamically as user responds
- Color coded:
  - Red badge if any urgent notifications present
  - Orange badge if high priority only
  - White badge if medium/low only

**Auto-Scroll Behavior**:
- New notification arrives → scroll to top (so user sees it)
- User responds → focus moves to next notification in list
- Expired notification → auto-removed, no scroll jump

**Visual Density Options**:

**Default Mode** (full expansion):
- All notifications fully visible as shown above
- Recommended for ≤5 notifications

**Compact Mode** (optional for Phase 3):
- Title + timer only, buttons hidden until hover
- Activates automatically when >5 notifications
- User can toggle back to full mode

**Technical Implementation**:

**Client-Side Rendering**:
```javascript
function renderActionRequiredSection( notifications ) {
  const sorted = sortActionRequired( notifications );
  const count = sorted.length;

  // Update section header with count
  const header = document.getElementById( "action-required-header" );
  header.innerHTML = `⚠️ Action Required (${count})`;
  header.className = getBadgeColor( sorted );  // red/orange/white

  // Render sorted notifications
  const container = document.getElementById( "action-required-container" );
  container.innerHTML = "";
  sorted.forEach( notification => {
    container.appendChild( renderNotification( notification ) );
  } );

  // Show scroll indicator if >5 notifications
  if ( count > 5 ) {
    showScrollIndicator();
  }
}

function getBadgeColor( notifications ) {
  if ( notifications.some( n => n.priority === "urgent" ) ) return "badge-red";
  if ( notifications.some( n => n.priority === "high" ) ) return "badge-orange";
  return "badge-white";
}
```

**Rationale**:
- ✅ Full transparency (user sees complete picture of pending work)
- ✅ Smart sorting ensures urgent items always at top
- ✅ Count badge provides at-a-glance status
- ✅ Simple implementation (no queueing/state management complexity)
- ✅ Scalable (handles 2-10 notifications gracefully)
- ✅ If >10 notifications becomes common, can add compact mode in Phase 3
- ✅ Auto-scroll to new notifications prevents "missed" items

**Edge Cases**:
- **0 notifications**: Hide "Action Required" section entirely, show "Recent Notifications" only
- **1 notification**: Show without scrollbar, singular label: "⚠️ Action Required (1)"
- **>10 notifications**: Consider this a product smell (too many approvals), but UI still handles it
- **All same priority**: Sort purely by expiration time (soonest first)

**Phase 3 Enhancement Ideas** (not for MVP):
- Collapsible priority groups: "▼ Medium Priority (3)" to hide lower priority items
- Keyboard navigation: Tab/Shift+Tab to move between notifications
- Bulk actions: "Approve all low priority" button

---

## 🔌 AREA 7: EXISTING SYSTEM INTEGRATION ✅ COMPLETE

### Overview

**Goal**: Integrate Phase 2 response-required notifications with existing fire-and-forget system

**Progress**: All 4 questions complete (Q7.1-Q7.4)

---

### Q7.1: Current notify-claude Flow Changes ✅ COMPLETE

**Question**: What changes to existing `/api/notify` endpoint? New endpoint for response-required? Backward compatibility?

**Decision**: ✅ **Extend Existing `/api/notify` Endpoint (Backward Compatible)**

**Implementation**:

**Server-Side Endpoint**:
```python
@router.post( "/api/notify" )
async def notify_user( request: Request ):
    """
    Universal notification endpoint - handles both fire-and-forget and response-required.

    Behavior based on `response_requested` field:
    - response_requested=False (or omitted) → Returns 201 immediately (fire-and-forget)
    - response_requested=True + Accept: text/event-stream → Returns SSE stream, blocks until response
    - response_requested=True + Accept: application/json → Returns 201 with notification_id (non-blocking)

    Backward compatibility: Requests without `response_requested` field default to fire-and-forget.
    """
    data = await request.json()

    # Check Accept header to determine response type
    accept_header = request.headers.get( "Accept", "application/json" )

    if data.get( "response_requested", False ):
        # Response-required notification
        if "text/event-stream" in accept_header:
            # SSE stream (blocking, waits for response)
            return await handle_response_required_sse( data )
        else:
            # Regular POST (non-blocking, return notification ID for polling)
            notification_id = await create_response_required_notification( data )
            return JSONResponse(
                status_code=201,
                content={ "status": "created", "notification_id": notification_id }
            )
    else:
        # Fire-and-forget notification (existing behavior)
        notification_id = await send_fire_and_forget_notification( data )
        return JSONResponse(
            status_code=201,
            content={ "status": "sent", "notification_id": notification_id }
        )
```

**Client Behavior**:
```bash
# Fire-and-forget (existing behavior - unchanged)
notify-claude "Task complete" --type=progress --priority=low
# → POST /api/notify with response_requested=False (default)
# → Returns 201 immediately

# Response-required with SSE (new, blocking)
answer=$(notify-claude-sync "Approve?" --response-required yes_no --timeout 120)
# → POST /api/notify with response_requested=True, Accept: text/event-stream
# → Blocks until user responds, returns answer via SSE stream

# Response-required with polling (alternative, non-blocking)
notify-claude "Approve?" --response-required yes_no --timeout 120 --async
# → POST /api/notify with response_requested=True, Accept: application/json
# → Returns notification_id immediately for status polling
```

**Request/Response Examples**:

**Fire-and-Forget (Existing Behavior)**:
```http
POST /api/notify
Content-Type: application/json

{
  "title": "Task complete",
  "message": "Processing finished",
  "type": "progress",
  "priority": "low"
  // NOTE: No response_requested field
}

Response: 201 Created
{
  "status": "sent",
  "notification_id": "uuid-123"
}
```

**Response-Required (SSE Stream)**:
```http
POST /api/notify
Content-Type: application/json
Accept: text/event-stream

{
  "title": "Approve Changes?",
  "message": "Claude Code wants to modify 5 files",
  "type": "task",
  "priority": "high",
  "response_requested": true,
  "response_type": "yes_no",
  "response_default": "yes",
  "timeout_seconds": 120
}

Response: 200 OK
Content-Type: text/event-stream

data: {"status": "delivered", "notification_id": "uuid-456"}

data: {"status": "responded", "answer": "yes", "responded_at": "2025-10-27T10:47:23Z"}
```

**Rationale**:
- ✅ Single endpoint (simpler client logic, no routing decisions)
- ✅ Backward compatible (existing calls work unchanged)
- ✅ Accept header determines response type (SSE vs JSON)
- ✅ No API versioning needed for MVP
- ✅ Optional async mode for non-blocking response-required notifications

---

### Q7.2: Database Migration ✅ COMPLETE

**Question**: Migrate existing notifications to new schema? Create migration script? Handle in-flight notifications during deployment?

**Decision**: ✅ **Fresh Schema with Soft Migration**

**Migration Strategy**:

**Phase 1: Create New Table**
1. Create new `notifications` table with full Phase 2 schema
2. Leave old in-memory `NotificationItem` system running temporarily
3. New code writes to new database table
4. Old fire-and-forget notifications in memory can be discarded (ephemeral by design)

**Phase 2: Dual-Write Period** (1-2 weeks)
- New notifications → database table
- Old notifications → still delivered via existing WebSocket
- Gradual client migration

**Phase 3: Remove Old System**
- Once all clients upgraded, remove in-memory notification code
- Single source of truth: database

**Migration Script**:
```python
# src/scripts/migrate_notifications_phase2.py

"""
Phase 2 Notifications Migration Script

Creates new notifications table with full schema for response-required notifications.
Does NOT migrate old in-memory notifications (they're ephemeral by design).
"""

import asyncio
from cosa.rest.database import get_db

async def migrate_to_phase2_schema():
    """
    Create Phase 2 notifications table.

    NOTE: Does NOT migrate old in-memory notifications (they're ephemeral).
    Old fire-and-forget notifications are delivered once and discarded.
    """
    db = await get_db()

    print( "Creating Phase 2 notifications table..." )

    # Create new table with full schema
    await db.execute( """
        CREATE TABLE IF NOT EXISTS notifications (
            -- Identity
            id                      TEXT PRIMARY KEY,

            -- Routing
            sender_id               TEXT NOT NULL,
            recipient_id            TEXT NOT NULL,

            -- Source Context
            source_context          TEXT DEFAULT 'internal',
            source_sender           TEXT DEFAULT 'claude.code@deepily.ai',

            -- Content
            title                   TEXT NOT NULL,
            message                 TEXT NOT NULL,
            type                    TEXT NOT NULL,
            priority                TEXT NOT NULL,

            -- Timestamps
            created_at              TEXT NOT NULL,
            delivered_at            TEXT,
            expires_at              TEXT,

            -- Response-Required Fields
            response_requested      INTEGER DEFAULT 0,
            response_type           TEXT,
            response_value          TEXT,
            responded_at            TEXT,
            timeout_seconds         INTEGER,
            response_default        TEXT,

            -- State Management
            state                   TEXT NOT NULL DEFAULT 'created',

            -- Legacy Compatibility (for fire-and-forget)
            played                  INTEGER DEFAULT 0,
            play_count              INTEGER DEFAULT 0,
            last_played             TEXT
        )
    """ )

    # Create indexes for common queries
    await db.execute( """
        CREATE INDEX IF NOT EXISTS idx_recipient_state
        ON notifications(recipient_id, state)
    """ )

    await db.execute( """
        CREATE INDEX IF NOT EXISTS idx_recipient_created
        ON notifications(recipient_id, created_at)
    """ )

    await db.execute( """
        CREATE INDEX IF NOT EXISTS idx_expires_at
        ON notifications(expires_at)
        WHERE expires_at IS NOT NULL
    """ )

    await db.commit()

    print( "✓ Phase 2 notifications table created" )
    print( "✓ Indexes created: idx_recipient_state, idx_recipient_created, idx_expires_at" )

if __name__ == "__main__":
    asyncio.run( migrate_to_phase2_schema() )
```

**Running Migration**:
```bash
# Run migration script
python src/scripts/migrate_notifications_phase2.py

# Verify table created
sqlite3 src/conf/lupin.db "SELECT name FROM sqlite_master WHERE type='table' AND name='notifications';"
```

**In-Flight Notifications During Deployment**:

**Scenario**: Server restart during deployment

**Before Restart**:
- Old fire-and-forget notifications in memory: Delivered via WebSocket
- Response-required notifications in database: Persistent, survive restart

**During Restart** (10-30 seconds downtime):
- Old in-memory notifications: Lost (acceptable for ephemeral fire-and-forget)
- Response-required notifications: Safe in database
- WebSocket connections: Dropped, clients auto-reconnect

**After Restart**:
- Clients reconnect to WebSocket
- Response-required notifications re-delivered from database
- Fire-and-forget notifications: New ones work normally

**Mitigation Strategy**:
- Deploy during low-traffic window (late evening/weekend)
- Use rolling deployment if multiple servers (Phase 3)
- Monitor for dropped WebSocket connections
- Fire-and-forget notifications are ephemeral by design (acceptable loss)

**Rationale**:
- ✅ Clean schema (no legacy baggage)
- ✅ Simple migration (no data to migrate from old system)
- ✅ Old system can run temporarily during rollout
- ✅ Fire-and-forget notifications are ephemeral anyway (acceptable to lose in-flight)
- ✅ Response-required notifications persisted from day 1 (no data loss)

---

### Q7.3: WebSocket Events ✅ COMPLETE

**Question**: New events? Update existing `notification_queue_update`?

**Decision**: ✅ **Extend Existing Event + Add New Events**

**Event Types**:

**1. `notification_queue_update` (EXTENDED)**

**Purpose**: Notify client of new notification (fire-and-forget OR response-required)

**Fire-and-Forget Notification (Existing Behavior)**:
```javascript
{
  "event": "notification_queue_update",
  "notification": {
    "id": "uuid-123",
    "sender_id": "claude.code@deepily.ai",
    "recipient_id": "user-uuid",
    "title": "Task complete",
    "message": "Processing finished",
    "type": "progress",
    "priority": "low",
    "created_at": "2025-10-27T10:45:00Z",
    "delivered_at": "2025-10-27T10:45:00Z",
    "state": "delivered",
    "response_requested": false,  // ← NEW field (defaults to false)
    // ... other fields
  }
}
```

**Response-Required Notification (NEW)**:
```javascript
{
  "event": "notification_queue_update",
  "notification": {
    "id": "uuid-456",
    "sender_id": "claude.code@deepily.ai",
    "recipient_id": "user-uuid",
    "title": "Approve Changes?",
    "message": "Claude Code wants to modify 5 files",
    "type": "task",
    "priority": "high",
    "created_at": "2025-10-27T10:46:00Z",
    "delivered_at": "2025-10-27T10:46:00Z",
    "expires_at": "2025-10-27T10:48:00Z",
    "state": "delivered",

    // Response-Required Fields (NEW)
    "response_requested": true,        // ← Client checks this to render response UI
    "response_type": "yes_no",         // "yes_no" or "open_ended"
    "response_default": "yes",         // ← Pre-selected answer ("yes", "no", or null)
    "timeout_seconds": 120,            // Client uses this for countdown timer

    // ... other fields
  }
}
```

**Client Rendering Logic**:
```javascript
// Client WebSocket handler
socket.on( "notification_queue_update", ( data ) => {
  const notification = data.notification;

  if ( notification.response_requested ) {
    // Render response-required UI
    renderActionRequired( notification );

    // Pre-select default if specified
    if ( notification.response_default ) {
      preselectButton( notification.response_default );
    }

    // Start countdown timer
    startCountdown( notification.timeout_seconds, notification.expires_at );
  } else {
    // Fire-and-forget notification (existing behavior)
    renderStandardNotification( notification );
  }
} );
```

---

**2. `notification_responded` (NEW)**

**Purpose**: Notify all user's devices that response was submitted

**Event Structure**:
```javascript
{
  "event": "notification_responded",
  "notification_id": "uuid-456",
  "answer": "yes",                           // "yes", "no", or custom text
  "responded_at": "2025-10-27T10:47:23Z",
  "method": "button_click"                   // "button_click", "keyboard", "voice", "default_accepted"
}
```

**Client Behavior**:
```javascript
socket.on( "notification_responded", ( data ) => {
  // Find notification in UI
  const notification = findNotification( data.notification_id );

  // Show confirmation state
  notification.showConfirmation( data.answer );

  // After 2.5s, move to Recent Notifications
  setTimeout( () => {
    moveToRecentNotifications( notification, data.answer );
  }, 2500 );
} );
```

**Multi-Device Sync**:
- User responds in Tab 1 → `notification_responded` event sent to Tab 2
- Tab 2 performs same UI transition (confirmation → Recent)
- All devices stay synchronized

---

**3. `notification_expired` (NEW)**

**Purpose**: Notify all user's devices that notification timed out

**Event Structure**:
```javascript
{
  "event": "notification_expired",
  "notification_id": "uuid-456",
  "expired_at": "2025-10-27T10:49:00Z",
  "default_answer": "yes"                    // or null if no default specified
}
```

**Client Behavior**:
```javascript
socket.on( "notification_expired", ( data ) => {
  // Find notification in UI
  const notification = findNotification( data.notification_id );

  if ( data.default_answer ) {
    // Show "Timeout - default applied: Yes"
    notification.showTimeoutWithDefault( data.default_answer );
  } else {
    // Show "Timeout - no response recorded"
    notification.showTimeoutNoDefault();
  }

  // Move to Recent Notifications after 2.5s
  setTimeout( () => {
    moveToRecentNotifications( notification, "expired" );
  }, 2500 );
} );
```

---

**Backward Compatibility**:

**Old Clients** (pre-Phase 2):
- Receive `notification_queue_update` events as before
- Ignore new fields (`response_requested`, `response_type`, etc.)
- Render as fire-and-forget notification (missing UI for response buttons)
- **Impact**: Old clients can't respond to response-required notifications, but don't crash

**New Clients** (Phase 2+):
- Check `response_requested` field to determine rendering
- Render fire-and-forget exactly as before
- Render response-required with new UI components

**Migration Path**:
- Deploy server with new fields (backward compatible)
- Deploy new client with response-required UI
- Old clients continue working until upgraded

**Rationale**:
- ✅ Backward compatible (`response_requested` defaults to false)
- ✅ Old clients ignore new fields without breaking
- ✅ New events enable multi-device sync
- ✅ Single `notification_queue_update` event simplifies client logic
- ✅ `notification_responded` and `notification_expired` events keep all devices in sync

---

### Q7.4: Backward Compatibility ✅ COMPLETE

**Question**: Do fire-and-forget notifications keep working exactly as before? Version the API?

**Decision**: ✅ **Full Backward Compatibility, No API Versioning**

**Guarantee**:
- Fire-and-forget notifications work **exactly** as before
- Existing clients see no breaking changes
- New fields are optional and ignored by old clients
- No API versioning needed (`/v1` vs `/v2`)

**Backward Compatibility Matrix**:

| Client Version | Fire-and-Forget | Response-Required |
|----------------|-----------------|-------------------|
| Old client     | ✅ Works        | ⚠️ Renders as fire-and-forget (no response UI) |
| New client     | ✅ Works        | ✅ Works          |

**API Contract**:

**Existing Behavior (Unchanged)**:
```bash
# Old clients POST without response_requested field
curl -X POST http://localhost:7999/api/notify \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Task complete",
    "message": "Processing finished",
    "type": "progress",
    "priority": "low"
  }'

# Response: 201 Created
# {"status": "sent", "notification_id": "uuid-123"}

# Delivered via WebSocket as before
```

**New Behavior (Additive)**:
```bash
# New clients POST with response_requested=true
curl -X POST http://localhost:7999/api/notify \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "title": "Approve Changes?",
    "message": "Claude Code wants to modify 5 files",
    "type": "task",
    "priority": "high",
    "response_requested": true,
    "response_type": "yes_no",
    "response_default": "yes",
    "timeout_seconds": 120
  }'

# Response: 200 OK (SSE stream, blocks until response)
# data: {"status": "delivered", "notification_id": "uuid-456"}
# data: {"status": "responded", "answer": "yes"}
```

**Testing Strategy**:

**Integration Tests**:
```python
# Test 1: Fire-and-forget unchanged
async def test_fire_and_forget_unchanged():
    """Verify old fire-and-forget behavior unchanged."""
    response = await client.post( "/api/notify", json={
        "title": "Task complete",
        "message": "Processing finished",
        "type": "progress",
        "priority": "low"
        # NOTE: No response_requested field (old behavior)
    } )

    assert response.status_code == 201
    assert response.json()["status"] == "sent"
    assert "notification_id" in response.json()
    # Should NOT block, should NOT create SSE stream

# Test 2: Old client receives response-required as fire-and-forget
async def test_old_client_receives_response_required():
    """Verify old clients can receive (but not respond to) response-required notifications."""
    # Send response-required notification
    await client.post( "/api/notify", json={
        "title": "Approve Changes?",
        "message": "Claude Code wants to modify 5 files",
        "type": "task",
        "priority": "high",
        "response_requested": true,
        "response_type": "yes_no",
        "timeout_seconds": 120
    } )

    # Old client receives via WebSocket
    ws_message = await websocket.receive_json()
    assert ws_message["event"] == "notification_queue_update"
    notification = ws_message["notification"]

    # Old client ignores new fields (renders as fire-and-forget)
    assert "response_requested" in notification  # Field exists
    # Old client doesn't render response UI (acceptable degradation)

# Test 3: New client handles both types
async def test_new_client_handles_both_types():
    """Verify new clients handle fire-and-forget and response-required."""
    # Fire-and-forget
    response1 = await client.post( "/api/notify", json={
        "title": "Task complete",
        "type": "progress",
        "priority": "low"
    } )
    assert response1.status_code == 201

    # Response-required
    response2 = await client.post( "/api/notify", json={
        "title": "Approve?",
        "type": "task",
        "priority": "high",
        "response_requested": true,
        "response_type": "yes_no"
    }, headers={"Accept": "text/event-stream"} )
    assert response2.status_code == 200
    assert response2.headers["content-type"] == "text/event-stream"
```

**No API Versioning Needed**:

**Why No Versioning**:
- All new fields are optional (default values provided)
- Behavior determined by request content, not URL path
- `/api/notify` handles both old and new requests intelligently
- Accept header determines response type (JSON vs SSE)

**Alternative Considered (Rejected)**:
```
/v1/notifications → Old fire-and-forget only
/v2/notifications → New response-required + fire-and-forget
```

**Why Rejected**:
- ❌ Adds complexity (two endpoints to maintain)
- ❌ Forces clients to choose endpoint (more decision logic)
- ❌ Requires routing configuration
- ❌ Version management overhead
- ✅ Single endpoint with optional fields is simpler

**Rationale**:
- ✅ Zero breaking changes to existing clients
- ✅ Gradual adoption (clients upgrade when ready)
- ✅ No version management overhead
- ✅ Simple deployment (single endpoint)
- ✅ Old clients continue working indefinitely
- ✅ Comprehensive test coverage for both old and new behavior

---

## 🚀 AREA 8: MVP SCOPE & PHASING ⏸️ PENDING

**Questions for Tomorrow's Session**:

### Strawman MVP (from original design draft):
- ✅ Database table for persistent notifications
- ✅ `response_required` boolean + `response_type` field
- ✅ SSE endpoint for response-required notifications (TBD which endpoint)
- ✅ Client UI: Yes/No buttons + mic + countdown timer
- ✅ Return value propagation to bash script
- ⏸️ Defer: Open-ended STT responses (Phase 3?)
- ⏸️ Defer: Deletion UI (auto-cleanup sufficient for MVP?)
- ⏸️ Defer: Multiple choice, ratings, etc. (Phase 3+)

**Questions**:
- Does this phasing make sense?
- What MUST be in Phase 2 MVP?
- What can wait for Phase 3?

---

## 🤔 AREA 9: CONCEPTUAL QUESTIONS ⏸️ PENDING

**Questions for Tomorrow's Session**:

### Q9.1: Who Sends Response-Required Notifications?
- Only Claude Code → Human?
- Human → Human too?
- Human → Claude Code? (Does Claude respond via SSE?)

### Q9.2: Security & Authorization
- Can any user send to any other user?
- Rate limiting?
- Permission levels?

### Q9.3: Offline Behavior
- User offline when notification arrives
- Notification times out while offline
- When user comes back online, what do they see?

### Q9.4: Multi-Device
- User has 2 browser tabs open
- Response-required notification arrives
- User responds in Tab 1
- What happens in Tab 2?

---

## 📊 AREA 10: COMPLETE NOTIFICATION FLOW ⏸️ PENDING

**To Create Tomorrow**: Sequence diagram showing complete end-to-end flow

**Flow to Document**:
```
1. Claude Code calls notify-claude with --response-required flag
2. POST /api/notify → Server creates notification in DB
3. Server... (WebSocket push? SSE stream? Both?)
4. Client receives notification → renders UI with countdown
5. User responds (button click or STT)
6. Client submits response → Server processes
7. Server updates DB (state=responded, response_value=...)
8. Server returns response to... (SSE stream? POST response?)
9. notify-claude script receives response
10. notify-claude exits with code + stdout
11. Claude Code reads exit code + stdout
12. Claude Code continues with user's answer
```

---

## 📝 AREA 11: DOCUMENTATION & DECISIONS LOG ⏸️ PENDING

**To Complete After Design Session**:

### Update Existing Documents
- `02-architecture.md` - Add Phase 2 persistent notification design
- `03-decisions.md` - Consolidate all decisions from this document

### Create New Documents
- Database migration script
- API endpoint specifications
- Client UI component specifications
- Testing strategy (unit + integration + smoke)

---

## Next Session Checklist

**Tomorrow's Agenda** (Resume at Area 3, Q3.2):

- [ ] **Area 3 (Continue)**: Q3.2-Q3.4 (timeout handling, grace period, audio alerts)
- [ ] **Area 4**: SSE vs WebSocket architecture (4 questions)
- [ ] **Area 5**: Return value propagation (4 questions)
- [ ] **Area 6**: Client UI/UX design (4 questions)
- [ ] **Area 7**: Existing system integration (4 questions)
- [ ] **Area 8**: MVP scope and phasing (define Phase 2 boundaries)
- [ ] **Area 9**: Conceptual questions (security, offline, multi-device)
- [ ] **Area 10**: Create complete notification flow sequence diagram
- [ ] **Area 11**: Update architecture docs and create implementation plan

**Estimated Time**: 2-3 hours for remaining 6.75 areas (assuming same pace as today)

---

## Design Session Statistics

**Session 1 (2025.10.17)**:
- Duration: ~90 minutes
- Areas Completed: 2.25 / 9 (25%)
- Questions Answered: 8 / ~36 (22%)
- Key Decisions: 13 major architectural choices
- Lines Written: ~1000 (this document)

**Progress**:
- ✅ Database schema complete (5 decisions)
- ✅ Response types complete (3 decisions + 1 flagged for clarification)
- ⏸️ Timeout behavior partial (1/4 questions)
- ⏸️ 6 areas remaining

**Status**: 🟢 On track - good progress, clear next steps, all decisions documented with rationale

---

## Appendix: Quick Reference

### Database Schema (Final)

```sql
CREATE TABLE notifications (
    -- Identity
    id                      TEXT PRIMARY KEY,

    -- Routing
    sender_id               TEXT NOT NULL,
    recipient_id            TEXT NOT NULL,

    -- Source
    source_context          TEXT DEFAULT 'internal',
    source_sender           TEXT DEFAULT 'claude.code@deepily.ai',

    -- Content
    title                   TEXT NOT NULL,
    message                 TEXT NOT NULL,
    type                    TEXT NOT NULL,
    priority                TEXT NOT NULL,

    -- Timestamps
    created_at              TEXT NOT NULL,
    delivered_at            TEXT,
    expires_at              TEXT,
    deleted_at              TEXT,

    -- Response-Required
    response_requested      INTEGER DEFAULT 0,
    response_type           TEXT,
    response_value          TEXT,
    responded_at            TEXT,
    timeout_seconds         INTEGER,
    response_default        TEXT,

    -- State
    state                   TEXT NOT NULL DEFAULT 'created',

    -- Legacy
    played                  INTEGER DEFAULT 0,
    play_count              INTEGER DEFAULT 0,
    last_played             TEXT
);

CREATE INDEX idx_recipient_state ON notifications(recipient_id, state);
CREATE INDEX idx_recipient_created ON notifications(recipient_id, created_at);
CREATE INDEX idx_expires_at ON notifications(expires_at) WHERE expires_at IS NOT NULL;
```

### UI Layouts (Final)

**Yes/No Notification**:
```
┌─────────────────────────────────────────────┐
│ Title: JWT Token Refresh Failed             │
│ Message: The authentication token could...  │
│                                              │
│ [🎤 Mic] [Yes] [No]              1:45 ⏱️    │
│ ████████████░░░░░░░░░░░░░░░░░░░░░░░░        │
└─────────────────────────────────────────────┘
```

**Open-Ended Notification**:
```
┌─────────────────────────────────────────────┐
│ Title: Why delete these files?              │
│ Message: Please provide a reason for...     │
│                                              │
│ [🎤 Mic] [_____________________________]    │
│ ████████████░░░░░░░░░░░░░░░░░░░░░░░░        │
└─────────────────────────────────────────────┘
```

### State Transitions

```
CREATED → DELIVERED → RESPONDED → DELETED
         ↓
       EXPIRED
```

### Response JSON Examples

```json
// Button click
{"answer": "yes", "method": "button_click", "timestamp": "2025-10-17T14:30:00Z"}

// Default accepted
{"answer": "yes", "method": "default_accepted", "timestamp": "..."}

// Dismissed
{"answer": "dismissed", "method": "keyboard_escape", "timestamp": "..."}

// STT custom
{"answer": "custom", "method": "stt_override", "text": "maybe later", "raw_utterance": "maybe later", "timestamp": "..."}

// Open-ended
{"answer": "open_ended", "text": "They're duplicates", "method": "stt_with_edit", "timestamp": "..."}
```

---

## 🚀 AREA 8: MVP SCOPE & PHASING ✅ COMPLETE

### Overview

**Problem**: Define minimum viable product scope and phased rollout strategy for Phase 2

**Solution**: 4-stage rollout with comprehensive testing and documentation

---

### Q8.1: Core MVP Features ✅ COMPLETE

**Question**: What features should be included in Phase 2 MVP vs deferred to later phases?

**Decision**: ✅ **Both Response Types in Phase 2 MVP** (yes/no + open-ended)

**Include in Phase 2:**
1. ✅ Persistent notifications table (with all fields from Area 1)
2. ✅ Response-required notifications with **both** yes/no AND open-ended types
3. ✅ Dual protocol architecture (WebSocket + SSE)
4. ✅ In-memory event system (asyncio.Event based)
5. ✅ Timeout/expiration with countdown timer + progress bar
6. ✅ Intent-based grace period (30s)
7. ✅ Client UI with "Action Required" section
8. ✅ Multi-modal input (voice + keyboard + mouse)
9. ✅ Return value propagation to bash
10. ✅ Basic backward compatibility

**Defer to Phase 3:**
- Authentication layer (JWT tokens, API keys)
- Rate limiting and permission models
- Redis/Postgres for multi-worker scaling

**Defer to Phase 4+:**
- Multiple choice / rating response types
- Agent-to-agent blocking notifications
- Advanced notification history/search
- Notification templates
- Rich media (images, attachments)

**Rationale**:
- Both response types already thoroughly designed (Areas 2, 6)
- Multi-modal UX handles both seamlessly
- Since complexity is solved, include both in MVP
- Authentication can be added incrementally in Phase 3

---

### Q8.2: Testing Strategy for Phase 2 ✅ COMPLETE

**Question**: What testing coverage is needed for Phase 2?

**Decision**: ✅ **All Three Testing Tiers** (comprehensive coverage)

**Unit Tests** (fast, isolated):
- Database CRUD operations (notifications table)
- Timeout/expiration calculations
- Grace period validation
- State machine transitions

**Smoke Tests** (quick sanity checks):
- Basic workflows (create → store → retrieve)
- **LLM response interpretation** ("sure" → "yes", "nope" → "no")
- Simple timeout scenarios
- ~10-15 tests total

**Integration Tests** (end-to-end workflows):
- Full yes/no flow: notify-claude-sync → WebSocket delivery → button click → SSE return
- Full open-ended flow: notification → STT response → interpretation → return
- Timeout scenario: notification expires → return default value
- Grace period scenario: late response accepted
- Multi-device sync: respond in one tab → other tab updates
- Offline detection: user offline → immediate default return
- ~25-30 tests total

**Total Testing**: ~40-50 tests across all tiers

**Rationale**:
- Synchronous blocking behavior requires high confidence
- Claude Code depends on correct return values
- Integration tests validate complete user flows
- LLM interpretation needs real LLM (smoke test, not unit test)

---

### Q8.3: Deployment & Rollout Strategy ✅ COMPLETE

**Question**: How should we deploy Phase 2 to minimize risk?

**Decision**: ✅ **4-Stage Phased Rollout**

**Phase 2.0: Foundation** (Week 1)
- Database schema migration (fresh schema with soft migration)
- API endpoint modifications (backward compatible)
- Unit tests + Smoke tests passing
- Configuration keys added: `enable response required notifications`, `enable sse blocking`

**Phase 2.1: Backend Complete** (Week 2)
- SSE blocking endpoint working (`Accept: text/event-stream`)
- In-memory event system operational (asyncio.Event)
- Integration tests passing
- Offline detection working

**Phase 2.2: Client UI** (Week 3)
- "Action Required" section in Fresh Queue UI
- Yes/No buttons + open-ended input field
- Timer + progress bar + color coding
- Multi-modal input (mic button, keyboard, mouse)
- Multi-device sync via WebSocket events

**Phase 2.3: CLI Integration** (Week 4)
- notify-claude-sync command working
- Return value propagation validated
- End-to-end Claude Code integration tests
- Documentation complete

**Feature Flags** (Configuration):
- `enable response required notifications` (default: false for Week 1)
- `enable sse blocking` (default: false until Phase 2.1 complete)
- Note: Keys use spaces (Lupin config style), not underscores

**Rationale**:
- Gradual rollout reduces risk
- Each phase has clear completion criteria
- Feature flags allow production testing with minimal exposure
- Can roll back individual phases if issues arise

---

### Q8.4: Documentation Requirements ✅ COMPLETE

**Question**: What documentation needs to ship with Phase 2?

**Decision**: ✅ **Comprehensive Documentation**

**For Developers:**
1. Updated architecture doc (02-architecture.md) - SSE + WebSocket dual protocol
2. Testing guide (how to run all 3 test tiers)
3. API reference (extended /api/notify endpoint with SSE support)

**For Claude Code Users (Us):**
1. notify-claude-sync CLI usage guide
   - Command syntax with --response-required flag
   - Response type options (yes_no, open_ended)
   - Return value handling (exit codes + stdout)
   - Timeout behavior and defaults
2. Best practices (when to use sync vs async notifications)
3. Troubleshooting guide (common issues, debugging)

**For End Users (UI):**
1. In-app help text for "Action Required" section
2. Tooltip explanations (timer, mic button, grace period)
3. Visual cues for expiration states

**Not Included** (per user request):
- ~~Database migration guide~~ (removed - not needed for developers)

**Rationale**:
- Comprehensive docs ensure smooth adoption
- CLI guide critical for Claude Code integration
- In-app help improves UX for response-required notifications
- API reference enables future extensions

---

## 🤔 AREA 9: CONCEPTUAL QUESTIONS ✅ COMPLETE

### Overview

**Problem**: Resolve broader design considerations around security, offline behavior, and multi-device sync

**Solution**: Phased security approach, intelligent offline handling, real-time multi-device sync

---

### Q9.1: Who Can Send Response-Required Notifications? ✅ COMPLETE

**Question**: Who should be allowed to send response-required (blocking) notifications?

**Decision**: ✅ **Claude Code → Human Only (Phase 2)**

**Scope**:
- **Phase 2**: Only Claude Code can send blocking notifications to humans
- **Phase 4+**: Agent-to-agent blocking notifications (future consideration)

**Not Supported in Phase 2**:
- Human → Human blocking notifications
- Human → Claude Code blocking notifications
- Agent → Agent blocking notifications

**Rationale**:
- Primary use case: Claude Code needs user decisions during execution
- Keeps MVP focused and simple
- Agent-to-agent communication requires additional considerations:
  - Authentication and authorization
  - Permission models (who can interrupt whom)
  - Rate limiting to prevent notification spam
  - Agent session management

---

### Q9.2: Security & Authorization ✅ COMPLETE

**Question**: How do we authenticate and authorize response-required notification senders?

**Decision**: ✅ **No Authentication in Phase 2, Add in Phase 3**

**Phase 2 Security Model - Localhost Trust**:
- `/api/notify` with `response_requested=true` requires **NO authentication**
- Assumption: API runs on localhost (port 7999), not publicly exposed
- Trust model: Anything that can reach localhost is trusted
- **Security Limitation**: Phase 2 is localhost-only

**Phase 3 Security Model - Authentication Layer**:
- JWT tokens for Claude Code sessions (reuse existing auth system)
- API keys for agent-to-agent communication
- Rate limiting per authenticated caller
- Permission model: Who can send blocking notifications to whom?
- Audit trail: Track who sent what notification

**Documentation Requirements**:
- ⚠️ **Phase 2 Security Warning**: Localhost-only deployment required
- ⚠️ **Do not expose port 7999 publicly** without authentication
- Document migration path: Phase 3 will add auth without breaking Phase 2 callers

**Where This Gets Documented**:
1. Area 9 (Q9.2) - Security decisions (this section)
2. Area 8 (MVP Scope) - Phase 3 as "Authentication & Authorization layer"
3. 02-architecture.md - Call out localhost-only security model for Phase 2
4. API Reference - Document unauthenticated endpoint with security warning
5. Phase 2.3 Testing - Verify localhost-only behavior (reject external requests)

**Rationale**:
- Simplifies MVP implementation (no auth plumbing)
- Localhost deployment is safe for single-user development environment
- Clear migration path to production-ready auth in Phase 3
- Allows rapid prototyping without compromising future security

---

### Q9.3: Offline Behavior ✅ COMPLETE

**Question**: What happens when the recipient is offline when a response-required notification arrives?

**Decision**: ✅ **Return Default Immediately + Show Expired Notifications**

**Offline Detection Strategy**:
- Server detects no active WebSocket connection for recipient
- Immediately return `response_default` value to caller
- Don't wait full timeout (e.g., 120 seconds) if user clearly offline
- Notification stored in DB with state=`expired`

**When User Returns Online**:
- Show expired notifications in "Recent Notifications" section
- Display with "Expired" badge and grayed-out state
- Include decision made (e.g., "Default: Yes was used")
- Provides audit trail of autonomous decisions

**Implementation**:
```python
async def send_notification_with_response( notification ):
    # Check if recipient has active WebSocket
    if not websocket_manager.has_active_connection( notification.recipient_id ):
        # User offline - return default immediately
        notification.state = "expired"
        notification.response_value = notification.response_default
        notification.responded_at = datetime.utcnow()
        await db.save( notification )
        return notification.response_default

    # User online - proceed with SSE blocking flow
    return await sse_blocking_flow( notification )
```

**Rationale**:
- Claude Code doesn't wait unnecessarily when user offline
- Faster autonomous decision-making
- Audit trail shows what happened while user away
- User has visibility into decisions made on their behalf

---

### Q9.4: Multi-Device Synchronization ✅ COMPLETE

**Question**: What happens when user has multiple browser tabs/devices open and responds in one?

**Decision**: ✅ **Immediate Sync via WebSocket**

**Multi-Device Scenario**:
1. User has 2 browser tabs open (Tab A and Tab B)
2. Claude Code sends response-required notification
3. Notification appears in both tabs (via `notification_queue_update` WebSocket event)
4. User responds in Tab A by clicking "Yes"
5. **Tab B updates immediately**

**Synchronization Flow**:
- Tab A sends response → POST to `/api/notify/response`
- Server broadcasts `notification_responded` WebSocket event to all user sessions
- Tab B receives event → Notification transitions to "Response sent ✓" state
- Shows confirmation for 2 seconds, then fades out to "Recent Notifications"
- Prevents duplicate responses

**WebSocket Event**:
```json
{
  "event": "notification_responded",
  "notification_id": "uuid-123",
  "answer": "yes",
  "method": "button_click",
  "responded_at": "2025-10-27T14:30:00Z"
}
```

**Duplicate Response Prevention**:
- If user tries to respond in Tab B after responding in Tab A:
  - Server checks notification state (already `responded`)
  - Returns error: `{"error": "Already responded", "existing_answer": "yes"}`
  - Client shows message: "Already responded in another session ✓"

**Cross-Device Support**:
- Same mechanism works across devices (laptop + phone)
- All active sessions receive `notification_responded` event
- All UIs update in real-time

**Rationale**:
- Leverages existing `notification_responded` event (designed in Area 7)
- Prevents confusion and duplicate work
- Clean UX with real-time feedback
- No polling or refresh needed

---

## Design Session Statistics

**Session 1 (2025.10.17)**:
- Duration: ~90 minutes
- Areas Completed: 2.25 / 9 (25%)
- Questions Answered: 8 / ~36 (22%)
- Key Decisions: 13 major architectural choices
- Lines Written: ~1000

**Session 2 (2025.10.26)**:
- Duration: ~2 hours
- Areas Completed: 3.75 / 9 (42% of remaining work)
- Questions Answered: 15 / ~36 (42% cumulative)
- Key Decisions: 19 additional architectural choices
- Lines Written: ~1400 (cumulative: ~2400)

**Session 3 (2025.10.27)**:
- Duration: ~90 minutes
- Areas Completed: 2 / 9 (Areas 8-9 complete, 100% TOTAL)
- Questions Answered: 8 / 40 (100% cumulative - all questions answered!)
- Key Decisions: 10 additional architectural choices
- Lines Written: ~600 (cumulative: ~3000+)

**Cumulative Progress**:
- ✅ **Area 1**: Database schema complete (5 questions)
- ✅ **Area 2**: Response types complete (3 questions)
- ✅ **Area 3**: Timeout behavior complete (4 questions)
- ✅ **Area 4**: SSE vs WebSocket complete (4 questions)
- ✅ **Area 5**: Return value propagation complete (3 questions)
- ✅ **Area 6**: Client UI/UX complete (4 questions)
- ✅ **Area 7**: Existing system integration complete (4 questions)
- ✅ **Area 8**: MVP scope & phasing complete (4 questions - NEW)
- ✅ **Area 9**: Conceptual questions complete (4 questions - NEW)

**Key Milestones Session 3**:
- Finalized Phase 2 MVP scope (both response types included)
- Comprehensive testing strategy (unit + smoke + integration)
- 4-stage phased rollout plan with feature flags
- Security model clarified (no auth Phase 2, add in Phase 3)
- Offline behavior optimized (immediate default return)
- Multi-device sync via WebSocket real-time events

**Final Status**: 🎉 **DESIGN COMPLETE** - 9/9 areas (100%), 40 questions answered, ready for implementation planning

**Final Statistics**:
- **Document**: `src/rnd/2025.10.15-sse-notifications/05-phase2-design-decisions.md`
- **Length**: 3,326 lines (comprehensive design + implementation plan)
- **Sessions**: 3 sessions across 3 days (Oct 17, Oct 26, Oct 27)
- **Areas Completed**: 9/9 (100%)
- **Questions Answered**: 40 total
- **Design Decisions**: 42 major architectural choices

---

## 📋 IMPLEMENTATION PLAN

### Overview

**Goal**: Implement Phase 2 SSE notification system with response-required capabilities

**Scope**: All 9 design areas implemented across 4 rollout phases

**Timeline**: 4 weeks (phased rollout with feature flags)

**Testing**: 40-50 tests (unit + smoke + integration)

---

### Phase 2.0: Foundation (Week 1)

**Goal**: Database schema, configuration, and test infrastructure

#### Tasks

**Database Schema** (Priority: CRITICAL):
1. Create `notifications` table with full schema (Area 1)
   - All fields: id, sender_id, recipient_id, title, message, type, priority
   - Response fields: response_requested, response_type, response_value, response_default, timeout_seconds
   - Timestamps: created_at, delivered_at, expires_at, responded_at, deleted_at
   - State machine: state (created/delivered/responded/expired/deleted)
   - Indexes: recipient_id+state, recipient_id+created_at, expires_at
2. Create migration script: `src/scripts/migrate_notifications_phase2.py`
   - Fresh schema approach (no data migration needed)
   - Soft migration: dual-write during rollout
   - Validation: check schema integrity

**Configuration** (Priority: HIGH):
1. Add config keys to `lupin-app.ini`:
   - `enable response required notifications = false`
   - `enable sse blocking = false`
   - `notification timeout default seconds = 120`
   - `notification grace period seconds = 30`
   - `notification offline immediate default = true`
2. Update `ConfigurationManager` to load new keys

**Test Infrastructure** (Priority: HIGH):
1. Set up unit test framework for notifications
   - Test fixtures for notification creation
   - Mock database for CRUD operations
2. Set up smoke test framework
   - LLM interpretation test helper
   - Basic workflow validation
3. Set up integration test framework
   - Test database with clean slate per test
   - WebSocket test client
   - SSE test client

**Estimated Effort**: 2-3 days
**Completion Criteria**: Database schema created, config keys added, test infrastructure ready, all unit tests passing

---

### Phase 2.1: Backend Complete (Week 2)

**Goal**: SSE endpoint, in-memory event system, offline detection

#### Tasks

**API Endpoint Modifications** (Priority: CRITICAL):
1. Extend `/api/notify` endpoint (Area 7)
   - Accept `response_requested`, `response_type`, `response_default`, `timeout_seconds` fields
   - Check `Accept: text/event-stream` header
   - Route to SSE blocking flow if `response_requested=true` + SSE header
   - Maintain backward compatibility (fire-and-forget unchanged)
2. Create response submission endpoint: `POST /api/notify/response`
   - Accept `notification_id`, `answer`, `method`, `text` (for open-ended)
   - Update notification state to `responded`
   - Signal asyncio.Event to wake SSE stream
   - Broadcast `notification_responded` WebSocket event

**SSE Blocking Flow** (Priority: CRITICAL):
1. Implement SSE endpoint logic (Area 4)
   - Create `pending_responses` dict: `{notification_id: asyncio.Event}`
   - Send initial SSE event: `{"status": "delivered", "notification_id": "..."}`
   - Wait on asyncio.Event with timeout
   - Return response via SSE: `{"status": "responded", "answer": "yes"}`
   - Clean up event from pending_responses dict
2. Handle timeout scenario (Area 3)
   - If asyncio.Event.wait() times out, use `response_default`
   - Update notification state to `expired`
   - Return SSE event: `{"status": "timeout", "answer": "yes", "method": "default_accepted"}`

**Offline Detection** (Priority: HIGH):
1. Implement offline check (Area 9, Q9.3)
   - Before SSE blocking, check `websocket_manager.has_active_connection(recipient_id)`
   - If offline, immediately return `response_default`
   - Update notification state to `expired`
   - Store in database for audit trail

**In-Memory Event System** (Priority: CRITICAL):
1. Create `pending_responses: Dict[str, asyncio.Event]` (Area 4)
2. POST `/api/notify` creates event, stores in dict
3. POST `/api/notify/response` sets event, removes from dict
4. Implement cleanup for abandoned events (>10 minutes old)

**WebSocket Events** (Priority: HIGH):
1. Extend `notification_queue_update` event (Area 7)
   - Add `response_requested`, `response_type`, `response_default`, `timeout_seconds`, `expires_at` fields
2. Create `notification_responded` event (Area 7, Area 9)
   - Broadcast to all user sessions when response submitted
   - Payload: `{notification_id, answer, method, responded_at}`
3. Create `notification_expired` event (Area 7)
   - Broadcast when notification times out
   - Payload: `{notification_id, response_default, expired_at}`

**Estimated Effort**: 4-5 days
**Completion Criteria**: SSE blocking works, offline detection works, WebSocket events broadcasting, integration tests passing

---

### Phase 2.2: Client UI (Week 3)

**Goal**: "Action Required" section, multi-modal input, timer/progress bar

#### Tasks

**UI Layout** (Priority: CRITICAL):
1. Create "Action Required" section in Fresh Queue UI (Area 6)
   - Separate from "Recent Notifications"
   - Badge with count: "⚠️ Action Required (3)"
   - Smart sorting: priority (urgent→high→medium→low), then expiration (soonest first)
   - Badge color: red (urgent present), orange (high only), white (medium/low)
2. Design notification card layout
   - Title (terse/technical)
   - Message (prose/TTS-friendly)
   - Buttons inline with timer + progress bar paired
   - Mic button for multi-modal input

**Yes/No Response Type** (Priority: CRITICAL):
1. Implement Yes/No buttons (Area 2, Area 6)
   - [🎤 Mic] [Yes] [No] layout
   - Button click → POST to `/api/notify/response` with `{answer: "yes", method: "button_click"}`
   - Mic button → STT override (custom response)
2. Keyboard shortcuts (Area 2)
   - Y key → Yes
   - N key → No
   - M key → Mic (STT)
   - Escape → Dismiss (stored as "dismissed")

**Open-Ended Response Type** (Priority: CRITICAL):
1. Implement text input + mic (Area 2, Area 6)
   - [🎤 Mic] [Text input field] layout
   - Mic → STT transcription → populate text field → user can edit → Submit
   - Keyboard → type directly → Submit
   - Submit → POST to `/api/notify/response` with `{answer: "open_ended", text: "...", method: "stt_with_edit"}`

**Timer & Progress Bar** (Priority: HIGH):
1. Implement countdown timer (Area 3, Area 6)
   - Format: MM:SS (e.g., "2:00" → "1:59" → "1:58")
   - Update every second
   - Display in top-right corner of notification card
2. Implement progress bar (Area 3, Area 6)
   - Visual bar showing time remaining
   - Color coding: green (>60s), yellow (30-60s), red (<30s)
   - Positioned below buttons

**Grace Period** (Priority: MEDIUM):
1. Implement client-side intent tracking (Area 3)
   - Track when user starts responding (button hover, text input focus, mic activated)
   - Send `started_at` timestamp with response
   - Server validates: if `started_at < expires_at`, accept response even if submitted late

**Confirmation & Transition** (Priority: HIGH):
1. Implement post-response confirmation (Area 6)
   - Show "Response sent ✓" with green checkmark
   - Wait 2.5 seconds
   - Fade out from "Action Required" section
   - Fade into "Recent Notifications" section with status indicator

**Multi-Device Sync** (Priority: HIGH):
1. Implement WebSocket event handling (Area 9, Q9.4)
   - Listen for `notification_responded` event
   - Update UI in all tabs/devices immediately
   - Show "Already responded ✓" if user tries to respond again
   - Prevent duplicate responses

**Estimated Effort**: 5-6 days
**Completion Criteria**: Both response types working, timer/progress bar functional, multi-modal input working, multi-device sync operational

---

### Phase 2.3: CLI Integration (Week 4)

**Goal**: notify-claude-sync command, return value propagation, documentation

#### Tasks

**notify-claude-sync CLI Command** (Priority: CRITICAL):
1. Create new command: `notify-claude-sync` (symlink to notify-claude with sync mode)
2. Implement SSE client in Python (Area 5)
   - Accept command-line args: `--response-required=yes_no`, `--response-default=yes`, `--timeout=120`
   - POST to `/api/notify` with `Accept: text/event-stream`
   - Stream SSE events, wait for `{"status": "responded"}` or `{"status": "timeout"}`
3. Return value propagation (Area 5)
   - Parse response from SSE stream
   - Exit code 0 + stdout = answer (e.g., "yes", "no", "They're duplicates")
   - Exit code 1 + stdout = "TIMEOUT" (if timeout occurred)
   - Exit code 2 + stdout = "OFFLINE" (if user offline)

**LLM Response Interpretation** (Priority: CRITICAL):
1. Implement server-side interpretation (Area 2, Area 5)
   - For yes/no questions with STT override: LLM interprets free text
   - Examples: "sure" → "yes", "nope" → "no", "maybe later" → custom response
   - Use existing LLM service (reuse Lupin's LLM integration)
   - Store interpreted answer in database
2. Return interpreted answer to CLI
   - Simple stdout output (just the answer text)
   - No JSON encoding needed

**Integration Testing** (Priority: HIGH):
1. End-to-end tests (Area 8)
   - Test 1: Yes/No flow - notify-claude-sync → WebSocket delivery → button click → return "yes"
   - Test 2: Open-ended flow - notification → STT response → interpretation → return text
   - Test 3: Timeout scenario - notification expires → return default value
   - Test 4: Grace period - late response accepted within 30s
   - Test 5: Multi-device sync - respond in Tab A → Tab B updates
   - Test 6: Offline detection - user offline → immediate default return

**Documentation** (Priority: HIGH):
1. Update architecture doc: `02-architecture.md` (Area 8)
   - Add SSE + WebSocket dual protocol section
   - Document in-memory event system
   - Call out localhost-only security model
   - Document scaling limitations (Redis migration path)
2. Create CLI usage guide (Area 8)
   - Command syntax: `notify-claude-sync "Message" --response-required=yes_no --response-default=yes`
   - Response type options: `yes_no`, `open_ended`
   - Return value handling: exit codes + stdout
   - Timeout behavior and defaults
3. Create best practices guide (Area 8)
   - When to use sync vs async notifications
   - Choosing appropriate timeouts
   - Setting good default values
4. Create troubleshooting guide (Area 8)
   - Common issues (timeout too short, user offline, etc.)
   - Debugging techniques (check WebSocket connection, SSE stream, database state)
5. Create in-app help text (Area 8)
   - Tooltip for "Action Required" badge
   - Tooltip for timer (grace period explanation)
   - Tooltip for mic button (multi-modal input)

**Estimated Effort**: 4-5 days
**Completion Criteria**: notify-claude-sync working, LLM interpretation working, all integration tests passing, documentation complete

---

### Testing Summary

**Unit Tests** (~10-15 tests):
- `test_notification_crud.py` - Database CRUD operations
- `test_timeout_calculations.py` - Expiration logic
- `test_grace_period.py` - Intent-based late response acceptance
- `test_state_machine.py` - State transitions (created→delivered→responded/expired)

**Smoke Tests** (~10-15 tests):
- `test_notification_workflows.py` - Basic create→store→retrieve
- `test_llm_interpretation.py` - LLM interprets "sure" → "yes", "nope" → "no"
- `test_simple_timeout.py` - Notification expires correctly

**Integration Tests** (~20-25 tests):
- `test_yes_no_flow.py` - Full yes/no workflow
- `test_open_ended_flow.py` - Full open-ended workflow
- `test_timeout_scenario.py` - Timeout returns default
- `test_grace_period_scenario.py` - Late response accepted
- `test_multi_device_sync.py` - Multi-tab synchronization
- `test_offline_detection.py` - Offline user gets immediate default
- `test_backward_compatibility.py` - Fire-and-forget unchanged

**Total**: ~40-50 tests across all tiers

---

### Risk Areas

**High Risk**:
1. **SSE blocking with asyncio.Event** - Inter-request communication in single-worker FastAPI
   - Mitigation: Thorough integration testing, document scaling limitations
2. **LLM response interpretation** - Natural language understanding can be ambiguous
   - Mitigation: Smoke tests with edge cases, allow user to see interpreted answer
3. **Multi-device sync timing** - Race conditions with WebSocket event broadcasting
   - Mitigation: Server-side duplicate response prevention, client-side state validation

**Medium Risk**:
1. **Grace period implementation** - Client/server clock synchronization
   - Mitigation: Use server timestamps, generous 30s window
2. **Offline detection accuracy** - False positives/negatives
   - Mitigation: Check WebSocket connection state, fallback to timeout if uncertain

**Low Risk**:
1. **Backward compatibility** - Breaking fire-and-forget notifications
   - Mitigation: Comprehensive backward compatibility tests, feature flags for gradual rollout

---

### Success Criteria

**Phase 2 Complete When**:
1. ✅ All 40-50 tests passing (unit + smoke + integration)
2. ✅ notify-claude-sync command returns correct values
3. ✅ Multi-device sync working in real-time
4. ✅ Offline detection returns immediate defaults
5. ✅ Both response types (yes/no + open-ended) working
6. ✅ LLM interpretation accurate for common phrases
7. ✅ Backward compatibility maintained (fire-and-forget unchanged)
8. ✅ Documentation complete (architecture + CLI guide + troubleshooting)
9. ✅ Feature flags working (`enable response required notifications`)
10. ✅ Production deployment on localhost successful

**Ready for Phase 3 When**:
- Phase 2 stable in production for 2+ weeks
- No critical bugs reported
- User feedback incorporated
- Authentication requirements clarified

---

### Future Phases

**Phase 3: Authentication & Authorization**:
- JWT tokens for Claude Code sessions
- API keys for agent-to-agent communication
- Rate limiting per authenticated caller
- Permission models (who can send blocking notifications to whom)
- Audit trail (track who sent what notification)

**Phase 4: Agent-to-Agent Communication**:
- Agent → Agent blocking notifications
- Multi-agent orchestration
- Agent session management
- Advanced permission models

**Phase 5: Scaling**:
- Redis Pub/Sub for multi-worker FastAPI
- Postgres LISTEN/NOTIFY for event distribution
- Horizontal scaling support
- Performance optimization

**Phase 6: Advanced Features**:
- Multiple choice / rating response types
- Notification templates
- Rich media (images, attachments)
- Advanced notification history/search
- Analytics and insights

---

**End of Implementation Plan**
