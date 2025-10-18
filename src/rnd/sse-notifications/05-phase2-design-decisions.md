# SSE Phase 2 Design Decisions

**Document Purpose**: Record all architectural decisions from interactive design session for Phase 2 SSE notification system implementation

**Created**: 2025.10.17
**Status**: 🚧 IN PROGRESS (Session 1 of Design Q&A)
**Resume Point**: Area 3, Question 3.2 (Timeout Handling)
**Progress**: 3/9 areas completed, 1 partial

---

## Navigation

**Related Documents**:
- [98-notification-design-draft.md](98-notification-design-draft.md) - Original design questions (this document contains the answers)
- [01-implementation-current.md](01-implementation-current.md) - Phase 1 PoC implementation (complete)
- [02-architecture.md](02-architecture.md) - Technical architecture (needs Phase 2 update)
- [03-decisions.md](03-decisions.md) - Architectural decisions log (will consolidate with this doc)

**Next Session**:
1. Read this document to resume context
2. Continue with Area 3, Q3.2: "When does server mark notification as expired?"
3. Complete Areas 3-9 (6 remaining areas)
4. Generate implementation plan and task breakdown

---

## Executive Summary

**Goal**: Design persistent, response-required notification system for Claude Code → User synchronous communication

**Key Decisions Made (Areas 1-3)**:
- ✅ Database schema with persistent storage (notifications survive server restart)
- ✅ Title/message split for voice-first UX (title: terse/technical, message: prose/TTS-friendly)
- ✅ LLM-based natural language response interpretation (user says "sure, why not?" → "yes")
- ✅ Multi-modal UX (voice, keyboard, mouse - accessibility first)
- ✅ Hybrid countdown timer (MM:SS + progress bar + color coding)

**Still To Decide (Areas 4-9)**:
- Timeout expiration logic, grace periods, audio alerts
- SSE vs WebSocket architecture and dual connection model
- Return value propagation to bash/Claude Code
- UI placement and behavior
- Existing system integration strategy
- MVP scope and phasing

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
    response_required       INTEGER DEFAULT 0, -- Boolean: 0 = no, 1 = yes
    response_type           TEXT,              -- NULL, 'yes_no', 'open_ended'
    response_value          TEXT,              -- JSON object (e.g., {"answer": "yes", "raw_utterance": "sure!", "confidence": "high"})
    responded_at            TEXT,              -- When user responded (NULL until responded)
    timeout_seconds         INTEGER,           -- Per-notification timeout (nullable, falls back to config max)
    default_answer          TEXT,              -- 'yes', 'no', NULL (for pre-selecting button, accepting default with Enter)

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
- **Field**: `default_answer TEXT` (values: 'yes', 'no', NULL)
- **Why**: Keyboard accessibility - user can hit Enter to accept pre-selected default
- **UI**: If `default_answer = "yes"`, Yes button is pre-focused/highlighted
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
- Sender can specify `default_answer` field: `"yes"`, `"no"`, or `null`
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

## ⏱️ AREA 3: TIMEOUT & EXPIRATION BEHAVIOR (PARTIAL - 1/4 questions)

### Overview

**Goal**: Clear visual countdown and predictable timeout behavior

**Progress**: Q3.1 ✅ complete, Q3.2-Q3.4 pending for tomorrow

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

### Q3.2: Timeout Handling ⏸️ NEXT SESSION

**Question**: When does server mark notification as `expired`?

**Options to Discuss Tomorrow**:
- At exact timeout moment (server-side timer)?
- When client polling detects timeout (SSE keepalive)?
- Hybrid (server marks expired, client shows UI immediately)?

**What happens to UI when expired?**:
- Fade out and remove?
- Stay visible but disabled (grayed out)?
- Move to "Expired Notifications" section?

---

### Q3.3: Visual & Audio Alerts ⏸️ PENDING

**Questions for Tomorrow**:
- Audio chime at T-minus 10 seconds? (optional, configurable)
- Visual flash/pulse when <10s remaining?
- User preference settings: "Never play audio alerts" vs "Always alert me"
- Different alert sounds for different priorities? (urgent = loud chime, low = soft beep)

---

### Q3.4: Grace Period ⏸️ PENDING

**Question for Tomorrow**:
If user starts typing/speaking at T-minus 2 seconds but finishes at T+5 seconds, do we:
- Accept it (grace period)?
- Strict cutoff at 0 seconds?
- Show "Expired, but we'll accept your late response" message?

---

## 📋 AREA 4: SSE VS WEBSOCKET ARCHITECTURE ⏸️ PENDING

**Questions for Tomorrow's Session**:

### Q4.1: Dual Connection Model
- WebSocket for fire-and-forget notifications (existing)
- SSE for response-required notifications (new)
- OR: Use SSE for everything?
- OR: Use WebSocket for everything?

### Q4.2: Delivery Mechanism
- How does response-required notification get delivered?
- Server pushes via WebSocket → client opens SSE?
- Client long-polls SSE endpoint?
- Hybrid push/pull?

### Q4.3: SSE Endpoint Design
- `/sse/notification/{notification_id}` - one stream per notification?
- `/sse/user/{user_id}` - one stream per user for all notifications?
- Which makes more sense for our architecture?

### Q4.4: Complete Notification Flow
- Walk through end-to-end: Claude Code sends → Server persists → User sees → User responds → Response returns to Claude Code
- Sequence diagram needed (Area 11)

---

## 📡 AREA 5: RETURN VALUE PROPAGATION ⏸️ PENDING

**Questions for Tomorrow's Session**:

### Q5.1: notify-claude Script Return Values
- Exit code 0 + stdout = response text (success)?
- Exit code 1 = timeout?
- Exit code 2 = dismissed?
- Exit code 3 = error?

### Q5.2: Response Encoding
- Stdout prints: "YES" or "NO"?
- JSON: `{"status": "responded", "value": "yes"}`?
- Which is more bash-friendly?

### Q5.3: Claude Code Integration
- How does Claude Code consume the response?
- Blocking behavior acceptable? (freeze for 120s waiting for response)
- Or async notification support?

### Q5.4: Timeout Behavior
- What happens in bash script when timeout occurs?
- Return default value?
- Return error and let Claude Code decide?

---

## 🎨 AREA 6: CLIENT UI/UX DESIGN ⏸️ PENDING

**Questions for Tomorrow's Session**:

### Q6.1: Notification Display Location
- Response-required in same list as fire-and-forget?
- Separate "Action Required" section?
- Pinned to top of notification list?

### Q6.2: Interactive Elements Placement
- Buttons inline in notification card?
- Countdown timer: top-right corner? Bottom? Separate row?
- Microphone icon: where exactly?

### Q6.3: After Response Submitted
- Notification disappears immediately?
- Shows "Response sent ✓" confirmation for 2 seconds?
- Stays in list with checkmark/status?

### Q6.4: Multiple Simultaneous Notifications
- Can user have 3 response-required active at once?
- How does UI handle: stack, queue, show all?

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
    response_required       INTEGER DEFAULT 0,
    response_type           TEXT,
    response_value          TEXT,
    responded_at            TEXT,
    timeout_seconds         INTEGER,
    default_answer          TEXT,

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

**End of Document** - Resume tomorrow at Area 3, Q3.2
