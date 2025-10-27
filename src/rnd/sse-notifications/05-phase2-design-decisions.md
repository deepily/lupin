# SSE Phase 2 Design Decisions

**Document Purpose**: Record all architectural decisions from interactive design session for Phase 2 SSE notification system implementation

**Created**: 2025.10.17
**Updated**: 2025.10.26 (Session 2 - Day 2)
**Status**: 🚧 IN PROGRESS (Session 2 of Design Q&A - Day 2)
**Resume Point**: Area 6, Question 6.3 (After Response Submitted)
**Progress**: 6/9 areas completed (Areas 1-5 complete, Area 6 partial - 2/4 questions)

---

## Navigation

**Related Documents**:
- [98-notification-design-draft.md](98-notification-design-draft.md) - Original design questions (this document contains the answers)
- [01-implementation-current.md](01-implementation-current.md) - Phase 1 PoC implementation (complete)
- [02-architecture.md](02-architecture.md) - Technical architecture (needs Phase 2 update)
- [03-decisions.md](03-decisions.md) - Architectural decisions log (will consolidate with this doc)

**Next Session**:
1. Read this document to resume context
2. Continue with Area 6, Q6.3: "What happens after response submitted?"
3. Complete Areas 6-9 (3.5 remaining areas)
4. Generate implementation plan and task breakdown

---

## Executive Summary

**Goal**: Design persistent, response-required notification system for Claude Code → User synchronous communication

**Key Decisions Made (Areas 1-6, partial)**:
- ✅ Database schema with persistent storage (response_requested, response_default fields)
- ✅ Title/message split for voice-first UX (title: terse/technical, message: prose/TTS-friendly)
- ✅ LLM-based natural language response interpretation (user says "sure, why not?" → "yes")
- ✅ Multi-modal UX (voice, keyboard, mouse - accessibility first)
- ✅ Hybrid countdown timer (MM:SS + progress bar + color coding)
- ✅ Hybrid lazy server + active client expiration (asyncio.Event for single-worker)
- ✅ Intent-based grace period (30s if user started before expiration)
- ✅ Dual protocol architecture (WebSocket for delivery, SSE for blocking/waiting)
- ✅ In-memory event system with scaling documentation for future Redis migration
- ✅ Server-side interpretation, simple stdout output (exit 0=success, 1=error)
- ✅ Separate "Action Required" section in UI, buttons inline with timer + progress bar paired

**Still To Decide (Areas 6-9, partial)**:
- After response submitted (Q6.3-Q6.4)
- Existing system integration strategy (Area 7)
- MVP scope and phasing (Area 8)
- Conceptual questions: security, offline, multi-device (Area 9)

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

**Documentation Location**: Add to `src/rnd/sse-notifications/02-architecture.md`

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

### Q6.3: After Response Submitted ⏸️ NEXT SESSION

**Question**: What happens to the notification after user responds?

**Options to Discuss**:
- Disappears immediately?
- Shows "Response sent ✓" confirmation for 2-3 seconds, then moves to Recent?
- Stays in Action Required with disabled state and checkmark?
- Immediately moves to Recent Notifications with status indicator?

---

### Q6.4: Multiple Simultaneous Notifications ⏸️ PENDING

**Question**: How does the UI handle multiple response-required notifications at once?

**Options to Discuss**:
- Show all in Action Required section (scrollable if many)?
- Limit to showing 3 at a time, queue the rest?
- Priority-based display (show urgent first, collapse lower priority)?
- Visual indication of "3 more pending" if many active?

---

## 🔌 AREA 7: EXISTING SYSTEM INTEGRATION ⏸️ PENDING

**Questions for Tomorrow's Session**:

### Q7.1: Current notify-claude Flow Changes
- What changes in existing `/api/notify` endpoint?
- New endpoint for response-required?
- Backward compatibility?

### Q7.2: Database Migration
- Migrate existing `NotificationItem` to new schema?
- Create migration script?
- How to handle in-flight notifications during deployment?

### Q7.3: WebSocket Events
- New events: `notification:response_required`, `notification:responded`, `notification:expired`?
- Update existing `notification_queue_update` event?

### Q7.4: Backward Compatibility
- Do fire-and-forget notifications keep working exactly as before?
- Version the API? (`/v1/notifications` vs `/v2/notifications`)

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

**Cumulative Progress**:
- ✅ **Area 1**: Database schema complete (5 questions) - CORRECTED field names
- ✅ **Area 2**: Response types complete (3 questions)
- ✅ **Area 3**: Timeout behavior complete (4 questions - NEW)
- ✅ **Area 4**: SSE vs WebSocket complete (4 questions - NEW)
- ✅ **Area 5**: Return value propagation complete (3 questions - NEW)
- ⏸️ **Area 6**: Client UI/UX partial (2/4 questions - NEW)
- ⏸️ **Areas 7-9**: Pending (3 areas remaining)

**Key Milestones Session 2**:
- Clarified inter-request communication (asyncio.Event for single-worker)
- Documented scaling limitations and migration path
- Unified field naming (response_requested, response_default)
- Complete notify-claude-sync CLI specification
- Separate "Action Required" UI section design

**Status**: 🟢 Excellent progress - 6/9 areas complete (67%), well-defined architecture, ready for Area 6 completion + Areas 7-9

---

**End of Document** - Resume next session at Area 6, Q6.3 (After Response Submitted)
