# SSE Notification System - Design Questions (DRAFT)

**Document Purpose**: Capture design questions and decision points for Phase 2 SSE notification system implementation

**Created**: 2025.10.16
**Status**: DRAFT - Questions to be answered before Phase 2 implementation

---

## 📌 **DESIGN SESSION IN PROGRESS**

**Answers Being Documented In**: [05-phase2-design-decisions.md](05-phase2-design-decisions.md)

**Progress**: 3/9 areas complete (Database Schema, Response Types, Timeout partial)

**Resume Point**: Area 3, Question 3.2 (Timeout Handling)

**Next Session**: Read 05-phase2-design-decisions.md to resume context, then continue answering questions below

---

---

## Context

This document captures clarifying questions raised during the transition from Phase 1 (SSE PoC) to Phase 2 (production integration). The user identified critical gaps:

1. **Notification Persistence**: No database serialization - notifications lost on server shutdown
2. **Response-Required Notifications**: Need synchronous "I need an answer now" capability
3. **Response Types**: Yes/No buttons, open-ended STT, timeout handling
4. **Return Value Propagation**: bash script needs to return response to Claude Code caller

**Next Steps**: Answer these questions in a design session, then create Phase 2 implementation plan.

---

## 🗄️ Area 1: Notification Persistence & Data Model

### Database Schema

**Q1.1: Unique ID Strategy**

The user mentioned `time + sender_id + recipient_id` hash. Should this be:
- SHA-256 hash of concatenated values?
- Or a composite primary key (time, sender_id, recipient_id)?
- Or auto-incrementing ID + indexed composite key?

**Q1.2: Lifecycle States**

What states should a notification have?
- `created` → `delivered` → `read` → `responded`?
- Do we need `expired` state for timeout?
- Do we need `deleted` state or just remove from DB?

**Q1.3: Essential Fields**

What's the minimal schema?

```sql
CREATE TABLE notifications (
    id                  -- hash or UUID?
    sender_id           -- user ID
    recipient_id        -- user ID
    message             -- text
    created_at          -- timestamp
    expires_at          -- timestamp (for response-required notifications)
    response_required   -- boolean
    response_type       -- enum: yes_no, open_ended, none
    response_value      -- JSON? text?
    state               -- enum: created, delivered, read, responded, expired, deleted
    priority            -- urgent, high, medium, low (already in notify-claude)
);
```

What am I missing? What should be removed?

**Q1.4: Deletion Semantics**

- User clicks delete → soft delete (state=deleted) or hard delete (remove row)?
- Auto-cleanup for old notifications? (after 30 days? 7 days?)
- Should deleted notifications stay in DB for audit trail?

---

## 🎯 Area 2: Response Types & UI Affordances

### Response Type Design

**Q2.1: Yes/No Type**

- Just two buttons: [Yes] [No]?
- Or three: [Yes] [No] [Ignore/Dismiss]?
- Should Yes/No responses be stored as boolean or text ("yes"/"no")?

**Q2.2: Open-Ended Type**

- Microphone icon only (STT)?
- Or microphone + text input field (for keyboard users)?
- Character limit on open-ended responses?

**Q2.3: Future Response Types**

Should we design for extensibility?
- Multiple choice (A/B/C/D)?
- Numeric rating (1-5 stars)?
- Confirmation with reason (Yes + text field)?

Do we need a `response_options` JSON field to support future types?

**Q2.4: Mixed Response Modes**

The user said "click yes/no OR use microphone for free text STT"
- Does this mean yes_no type also allows STT override?
- Or are yes_no and open_ended strictly separate types?

---

## ⏱️ Area 3: Timeout & Expiration

### Timeout Behavior

**Q3.1: Timeout Duration**

- Is 120 seconds (2 minutes) the standard?
- Should timeout be configurable per notification?
- Should different priority levels have different timeouts? (urgent=60s, high=120s, etc.)

**Q3.2: Timeout Handling**

Server-side: When does server mark notification as `expired`?
- At exact timeout moment?
- When SSE client polling detects timeout?

Client-side: What happens to the notification UI?
- Fade out and remove?
- Stay visible but disabled?
- Move to "Expired Notifications" section?

**Q3.3: Visual Countdown**

- Update every second (120s → 119s → 118s...)?
- Format: "2:00" → "1:59" → "1:58"?
- Color coding? (green → yellow → red as time runs out?)
- Audio alert at T-minus 10 seconds?

**Q3.4: Grace Period**

- If user starts typing/speaking at T-minus 2 seconds but finishes at T+5 seconds, do we accept it?
- Or strict cutoff at 0 seconds?

---

## 🔄 Area 4: SSE vs WebSocket Architecture

### Integration Strategy

**Q4.1: Dual Connection Model**

- Current: Client has WebSocket connection for real-time events
- New: Client also needs SSE for synchronous response-required notifications?
- Or: Use SSE *only* for response-required, WebSocket for fire-and-forget?

**Q4.2: Delivery Mechanism**

- **Fire-and-forget notifications**: WebSocket (as now)?
- **Response-required notifications**: SSE endpoint?
- Do we need both protocols active simultaneously?

**Q4.3: SSE Endpoint Location**

- `/sse/notification/{notification_id}` - one SSE stream per notification?
- `/sse/user/{user_id}` - one SSE stream per user for all their response-required notifications?
- Which makes more sense?

**Q4.4: Notification Flow**

Help me understand the complete flow:

```
1. User A sends response-required notification to User B
2. Server creates notification in DB (state=created)
3. Server... WebSocket push to User B? Or wait for User B to poll?
4. User B's client... opens SSE connection? Or already has one?
5. User B responds within timeout
6. Response flows back via... SSE? POST to REST endpoint?
7. Server updates DB (state=responded, response_value=...)
8. Server... returns response via SSE to User A's waiting bash script?
```

Can you walk me through the complete flow as you envision it?

---

## 📡 Area 5: Return Value Propagation (bash → Claude Code)

### Caller Integration

**Q5.1: notify-claude Script Return Values**

- Success with response: Exit code 0, stdout = response text?
- Timeout/no response: Exit code 1, stdout = "TIMEOUT"?
- User declined: Exit code 2, stdout = "DECLINED"?
- Error: Exit code 3, stdout = error message?

**Q5.2: Response Encoding**

- Yes/No: stdout prints "YES" or "NO"?
- Open-ended: stdout prints full text response?
- JSON encoding? `{"status": "responded", "value": "yes", "timestamp": "..."}`?

**Q5.3: Claude Code Usage**

Does this match your vision?

```bash
response=$(notify-claude "[LUPIN] Should I delete these 5 files?" \
           --type=task --priority=urgent --response-required=yes_no \
           --timeout=120)
exit_code=$?

if [ $exit_code -eq 0 ]; then
    # User responded
    if [ "$response" = "YES" ]; then
        # Delete files
    fi
elif [ $exit_code -eq 1 ]; then
    # Timeout - default behavior?
fi
```

**Q5.4: Blocking Behavior**

- `notify-claude` with `--response-required` blocks for up to 120s?
- Claude Code freezes during this time (can't do other work)?
- Is this acceptable, or do we need async/background notification support?

---

## 🎨 Area 6: Client UI/UX

### Visual Design

**Q6.1: Notification Display**

- Do response-required notifications appear in same UI as fire-and-forget?
- Or separate "Action Required" section?
- Should they be pinned to top of notification list?

**Q6.2: Interactive Elements**

- Yes/No buttons: Inline in notification card?
- Microphone icon: Where exactly? (top-right corner? bottom-right? center?)
- Timer: Where? (top-right with countdown? progress bar around border?)

**Q6.3: After Response Submitted**

- Notification disappears immediately?
- Shows "Response sent" confirmation for 2 seconds then fades?
- Stays in list with checkmark/status?

**Q6.4: Multiple Active Response-Required Notifications**

- Can user have 3 response-required notifications active simultaneously?
- How does UI handle this? (stack them? queue them? show all?)

---

## 🔌 Area 7: Existing System Integration

### Current Architecture

**Q7.1: Existing notify-claude Flow**

- Current: `notify-claude` → POST to `/notifications` endpoint → WebSocket push to user
- New: `notify-claude --response-required` → POST to `/notifications` → ??? → wait for response → return to caller

What changes in the existing flow?

**Q7.2: Database**

- Current notifications table exists? Or is everything in-memory?
- If table exists, what does it look like now?
- Can you point me to current schema?

**Q7.3: WebSocket Events**

- Current events: `notification:new`, `notification:read`, etc.?
- New events needed: `notification:response_required`, `notification:responded`, `notification:expired`?

**Q7.4: Backward Compatibility**

- Do existing fire-and-forget notifications keep working exactly as before?
- Should we version the API? (`/v1/notifications` vs `/v2/notifications`?)

---

## 🚀 Area 8: MVP Scope & Phasing

### What's the Minimum Viable Product?

Given all the above, what's the absolute minimum we need for Phase 2?

**Strawman MVP**:
1. ✅ Database table for persistent notifications (basic schema)
2. ✅ `response_required` boolean flag (start with just yes/no type)
3. ✅ SSE endpoint for response-required notifications
4. ✅ Client UI: Yes/No buttons + countdown timer
5. ✅ Return value propagation to bash script
6. ⏸️ Defer: Open-ended STT responses (Phase 3?)
7. ⏸️ Defer: Deletion UI (just auto-cleanup after 7 days?)
8. ⏸️ Defer: Multiple choice, ratings, etc.

**Does this phasing make sense, or would you prioritize differently?**

---

## 🤔 Area 9: Conceptual Questions

### Broader Design Considerations

**Q9.1: Who Sends Response-Required Notifications?**

- Only Claude Code → Human?
- Or Human → Human too?
- Or Human → Claude Code? (Does Claude need to respond to human questions via SSE?)

**Q9.2: Security & Authorization**

- Can User A send response-required notification to User B without permission?
- Rate limiting? (prevent notification spam)
- Should response-required notifications require higher privilege level?

**Q9.3: Offline Behavior**

- User B is offline when notification arrives
- Notification times out while user offline
- When user comes back online, do they see expired notification? Or is it gone?

**Q9.4: Multi-Device**

- User has 2 browser tabs open
- Response-required notification arrives
- User responds in Tab 1
- What happens in Tab 2? (notification disappears? shows "Already responded"?)

---

## 📊 Summary: Key Decision Points

Before we can design Phase 2, we need to decide:

1. **Database schema** for persistent notifications (exact fields)
2. **Response types** to support in MVP (just yes/no? or include open-ended?)
3. **SSE architecture** (per-notification stream? per-user stream? hybrid?)
4. **Notification flow** (complete sequence diagram from send → response → return)
5. **Return value format** for bash script (exit codes + stdout format)
6. **UI placement** for response-required notifications (separate section? inline?)
7. **Timeout behavior** (grace period? what happens to expired notifications?)
8. **MVP scope** (what's Phase 2 vs Phase 3 vs Phase 4?)

---

## Next Steps

1. **Design Session**: Answer all questions in this document
2. **Create Decisions Log**: Document each decision with rationale (update 03-decisions.md)
3. **Update Architecture**: Revise 02-architecture.md with persistent notification design
4. **Phase 2 Implementation Plan**: Create detailed task breakdown (update 01-implementation-current.md)
5. **Begin Implementation**: Database schema → API endpoints → Client UI → Testing

---

## Related Documents

- `00-index.md` - SSE documentation overview
- `01-implementation-current.md` - Phase 1 implementation (complete)
- `02-architecture.md` - Technical architecture (needs update for Phase 2)
- `03-decisions.md` - Architectural decisions log (needs Phase 2 decisions)
- `04-testing-validation.md` - Testing strategy
- `99-sse-conceptual-qna.md` - Async/sync conceptual Q&A

---

**Status**: 🟡 DRAFT - Awaiting design session to answer questions and finalize Phase 2 plan
