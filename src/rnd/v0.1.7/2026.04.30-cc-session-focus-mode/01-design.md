# CC Session Selector Strip + Exclusive Focus Mode — Design

**Status**: APPROVED 2026-04-30
**Plan file**: `~/.claude/plans/i-want-to-start-parsed-blossom.md`
**Pattern**: Pattern 3 (Feature Development), 1-2 weeks
**Audience**: a future developer (likely the author 6 months from now) who needs to understand WHY the strip + focus mode exist, what choices were taken, and what was deliberately deferred

---

## 1. Pain & Motivation

The notifications panel (`src/fastapi_app/static/html/notifications.html`) renders one **sender card** per active Claude Code (CC) session, stacked vertically inside `#notifications-list`. Two problems compound when 3+ sessions are active:

1. **Volume** — every card carries header chrome, voice-input row, date accordion(s), and progress-group history; total surface area exceeds one viewport quickly
2. **Reorder churn** *(primary focus-killer)* — every incoming `notification` event bubbles the receiving session's card to the top of the stack. Reading or composing on session A is repeatedly disrupted by sessions B/C/D pinging and shuffling A out of view

The existing **conversation-mode pin** (`.sender-card[data-pinned-conv-mode="true"]` at `notifications.css:440-454`) partially addresses #2 by anchoring the conv-mode session to index 0. But:
- Pin only engages when audio is active — silent reading/contemplation is unprotected
- Other (non-pinned) cards still reorder around the pin
- One pin slot at a time (mutex), no help when you want to focus on a non-conv-mode session

## 2. Modality Choice

**Two new affordances**, both **orthogonal to conversation mode** (independent on/off axes):

### A. Always-on horizontal session selector strip
Sticky permanent chrome above `#notifications-list`. One large icon per active CC session. **Leftmost = most recently updated**, mirroring the stack's reorder behavior in real time.

### B. Exclusive focus mode (toggleable)
A pill button inside the strip. When ON, only the focused session's card is visible (others hidden via `display: none`). User picks which session is focused by clicking its strip icon.

**The single ordering rule** (used in both modes): leftmost = most recently updated session. In focus mode this means non-focused sessions getting fresh activity slide leftward — providing peripheral awareness ("you have newer notifications to look at later") without yanking the user out of their current read.

## 3. Conv-mode coupling: orthogonal

The two modes operate on independent axes — either, both, or neither can be active:

| Conv-mode | Focus-mode | Behavior |
|---|---|---|
| OFF | OFF | Today's behavior (vertical stack, reorders by recency) |
| ON | OFF | Today's behavior + conv-mode session pinned to index 0 (existing) |
| OFF | ON | One card visible (focused); strip shows recency for others |
| ON | ON | One card visible (focused); strip shows mic overlay on whichever icon is in conv-mode (which may or may not be the focused one) |

The focused session does not have to be the conv-mode session — they are decoupled by design. The strip icon for whichever session is in conv-mode gets a small mic glyph overlay; this is the only place where the two axes become visually linked.

## 4. DOM

```
#notifications-list (existing)
  ├── #cc-session-strip (NEW — sticky chrome)
  │   ├── .cc-strip-icon[data-sender-id=...]
  │   ├── .cc-strip-icon[data-sender-id=...]
  │   ├── ...
  │   └── .cc-strip-toggle (focus on/off pill)
  │
  ├── .sender-card[data-sender-id=...]
  ├── .sender-card[data-sender-id=...]
  └── ...
```

The strip is `hidden` (HTML attribute) until ≥1 CC sender card exists. It uses `position: sticky; top: 0;` so it stays at viewport top during scroll.

In focus mode, every `.sender-card` whose `data-sender-id` ≠ focused gets `data-focus-hidden="true"`, and CSS rule `.sender-card[data-focus-hidden="true"] { display: none; }` removes them from layout.

## 5. Strip Icon Spec

- **Shape**: circle ~40-44px diameter
- **Background**: `var(--persona-color, #6c757d)` (reuses the existing CSS custom property set on `.sender-card` by `_setPersonaBadgeOnCard()` at `notifications.js:8835-8875`; falls back to neutral grey if no persona assigned yet)
- **Center label**: project initial in white (e.g. `L` for lupin, `C` for cosa)
- **Tooltip on hover**: `[PROJECT] #sessionhash` for disambiguation
- **State markers** via data-attributes:
  - `data-focused="true"` → border + slight scale (visual highlight when this is the focused session)
  - `data-unread="true"` with `data-unread-count="N"` → pulsing glow + numeric badge (CSS `::after { content: attr(data-unread-count); }`)
  - `data-conv-mode="true"` → small mic glyph overlay (CSS `::before` with mic icon)

Icons are anchored to a flex row inside the strip; their order is mutated by `_promoteStripIcon(senderId)` which moves the icon to position 0 (leftmost) using DOM `insertBefore`.

## 6. Focus Toggle UX

- A pill button at the right end of the strip (`.cc-strip-toggle`)
- Default text: `👁 Focus` (off state); active text: `👁 Focus: ON`
- ON → reads `data-sender-id` from currently-leftmost icon (or the persisted focused id from localStorage); calls `_enterFocusMode(senderId)`:
  - Sets `data-focused="true"` on that icon
  - Sets `data-focus-hidden="true"` on every other `.sender-card`
  - Highlights the toggle pill
  - Saves state to localStorage
- OFF → calls `_exitFocusMode()`:
  - Removes `data-focus-hidden` from all cards
  - Clears `data-focused` from all icons
  - Clears `data-unread` on all icons (visit assumed; user is now seeing everything)
  - Un-highlights the pill
  - Saves state

While focus is ON, clicking a different strip icon calls `_handleStripIconClick(senderId)` → switches focus to that session (clears prior `data-focused`, sets new one, swaps which card is `data-focus-hidden`). Clicking the **already-focused** icon is a no-op.

## 7. Click Semantics

| Mode | Click on strip icon |
|---|---|
| Default (focus OFF) | Smooth-scroll to that card: `card.scrollIntoView({behavior: "smooth", block: "start"})` |
| Focus ON, different icon | Switch focus to that session |
| Focus ON, focused icon | No-op |

| Mode | Click on toggle pill |
|---|---|
| Default | Enter focus mode using leftmost icon (or persisted focused id) |
| Focus ON | Exit focus mode |

## 8. Peripheral Awareness in Focus Mode

When focus is ON and a `notification` event fires for `senderId !== focused_sender_id`:

1. `_promoteStripIcon(senderId)` moves the icon to leftmost (recency rule applies in both modes)
2. Sets `data-unread="true"` on that icon
3. Increments `data-unread-count` (1, 2, 3, ...)
4. Card's underlying DOM still receives the new notification (it's just hidden via `display: none`); no information lost

When the user switches focus to that session OR exits focus mode entirely:
- `_clearUnreadOnFocusedIcon()` removes `data-unread` and resets count to 0 on the now-visible session's icon

The focused session's own icon is never marked unread (since the user is already looking at it).

## 9. Persistence

`localStorage` key `cc-focus-state`, JSON-encoded:

```json
{ "enabled": true, "focused_sender_id": "claude.code@lupin.deepily.ai#488ca8bd" }
```

- Written by `_saveFocusStateToStorage()` on every state change (enter focus, exit focus, switch focus)
- Read by `_loadFocusStateFromStorage()` on `DOMContentLoaded`; if `enabled === true` and the focused sender card exists, re-enter focus mode for that session
- If the persisted focused session does NOT exist on reload (e.g. user cleared notifications since), state is discarded and default mode is shown

Why localStorage and not server-side: focus is a per-browser visual filter, not a cross-device coordination concern. Conv-mode handles cross-device for the audio mutex (server-tracked in the bridge). If we ever need cross-device focus sync (phone ↔ laptop), it would be a separate WS event + bridge field — explicitly deferred (see §11).

## 10. Edge Cases

| Event | Behavior |
|---|---|
| Focused session ends or × deleted | `_exitFocusMode()` auto-fires; stack view returns; icon removed from strip |
| New CC session arrives during focus | New icon appears at leftmost (it's the freshest); focus stays on current session; new session's card is hidden via `data-focus-hidden` |
| `/clear` within focused session | Focus survives — `cc-focus-state` localStorage key is per-page-origin, not per-CC-session-id; reload re-enters focus for same id |
| Page hard-refresh | `_loadFocusStateFromStorage()` restores prior focus |
| Voice persona reassigned mid-focus | `_setStripIconPersonaColor(senderId, newColor)` updates icon background; mirrors existing `_setPersonaBadgeOnCard()` pattern |
| Conv-mode toggled on another session | Strip icon for that session gets/loses mic overlay; focus state untouched |
| Strip overflows horizontally (8+ sessions) | `overflow-x: auto` with thin scrollbar (default); revisit if ugly in practice |

## 11. Why Client-Only (No Server / WS / Bridge State)

- Cross-device sharing not in scope (per elicitation answer)
- Conv-mode already handles the cross-device audio-mutex problem; focus is *visual* only
- No new WS events → no doc churn in `src/docs/websocket-events.md`, `websocket-configuration.md`
- No server-side state → no router edits, no bridge field, no migration
- localStorage is sufficient for "remember my focus across reload on this browser"

If a cross-device use case emerges later, the upgrade path is clean: add `cc_focus_state` field to the bridge file (parallel to `conversation_mode_active`), add `focus_state_changed` WS event, switch the JS persistence layer to read/write via the existing notification endpoint instead of localStorage. Defer until the use case exists.

## 12. Coexistence with Conversation-Mode Pin

`.sender-card[data-pinned-conv-mode="true"]` rule (`notifications.css:440-454`) is **untouched**. In default mode it continues to pin the conv-mode session to stack index 0 with green-glow border. In focus mode it's a no-op visually (only one card is rendered, so "pin to top" has no effect on layout), but the strip icon for the conv-mode session shows the mic overlay regardless of which session is focused — making the orthogonal axes both visible.

The conv-mode-pinned session and the focused session may be:
- The same session → focused card shows pin-styling AND is the only visible card; strip icon shows mic overlay + focused highlight
- Different sessions → focused card is visible; pinned session's card is hidden (display:none); pinned session's strip icon shows mic overlay; focused session's strip icon shows the focused highlight

## 13. Strip Ordering — the One Rule

> **Leftmost icon = most recently updated session, at all times, in both modes.**

This is the single invariant. Every `notification` arrival triggers `_promoteStripIcon(senderId)`, which moves that session's icon to position 0. Card stack ordering in default mode and strip ordering are synchronized by sharing the same trigger (the WS `notification` handler).

Tradeoff: this loses the muscle-memory benefit of "session A is always the second icon" — icons move around. The user explicitly accepted this in elicitation Q5: the recency-meter benefit of "I can see at a glance which session is freshest" outweighs the muscle-memory benefit of stable positions. The focused icon participates in this reorder like any other; if you're focused on A and B starts pinging, A's icon will get bumped rightward as B's takes leftmost. The badge + glow on B's icon supplements this signal.

## 14. Files to Modify (Critical Path)

| File | Section | Nature of change |
|---|---|---|
| `src/fastapi_app/static/html/notifications.html` | line 605-633 (above `#notifications-list`) | Add `<div id="cc-session-strip" class="cc-session-strip" hidden></div>` |
| `src/fastapi_app/static/css/notifications.css` | new section after line ~1948 (after `.sender-card` foundation rules) | All `.cc-session-strip`, `.cc-strip-icon`, `.cc-strip-toggle`, and `.sender-card[data-focus-hidden="true"]` rules |
| `src/fastapi_app/static/js/notifications.js` | `createSenderCard` (lines 9669-9817) | Hook in `_addStripIcon` on creation, `_removeStripIcon` on × delete |
| `src/fastapi_app/static/js/notifications.js` | event handlers (lines 5358-5375) | Extend `notification`, `voice_persona_assigned/_released`, `conversation_mode_changed` |
| `src/fastapi_app/static/js/notifications.js` | `_setPersonaBadgeOnCard` (lines 8835-8875) | Mirror onto `_setStripIconPersonaColor` for synchronized persona color updates |
| `src/fastapi_app/static/js/notifications.js` | new functions appended near other strip helpers | All `_addStripIcon`, `_removeStripIcon`, `_promoteStripIcon`, `_setStripIconPersonaColor`, `_enterFocusMode`, `_exitFocusMode`, `_handleStripIconClick`, `_handleStripToggleClick`, `_loadFocusStateFromStorage`, `_saveFocusStateToStorage`, `_clearUnreadOnFocusedIcon` |
| `src/fastapi_app/static/js/notifications.js` | DOMContentLoaded init | Call `_loadFocusStateFromStorage()` |

## 15. Testing Layers

| Tier | Venue | What |
|---|---|---|
| Unit (backend) | n/a | No backend code touched |
| Browser hard-refresh smoke | :7999 | 13-row verification table from plan, run by Claude in Phase 1 |
| WS-smoke layer | :7999 | New `test_focus_state_persistence.py` covering badge update without focus swap, localStorage round-trip |
| E2E UI functional | :8000 (scheduled) | New `test_cc_session_strip_and_focus.py`, Playwright headless covering all 13 scenarios |
| E2E visual regression | :8000 (scheduled) | 4 new baselines under `__snapshots__/` |
| Integration sanity | :8000 (scheduled) | Run as final gate before merge to confirm no auth/queue regression from the static-asset edits |

`:8000` E2E runs are **gated** — Phase 1 stops; user confirms slot before submission via `/schedule-tests`.

## 16. Deferred / Open Items

- **Cross-device focus sync** — server-side state + WS event; defer until use case exists
- **Strip overflow strategy** — start with `overflow-x: auto`; revisit (collapse menu vs two-row wrap) only if ugly with 8+ sessions
- **Per-card "anchor" pinning** (Q5 option-c from elicitation) — separate small feature if reorder churn in default-stacked-view still bothers user even with focus-mode escape
- **Tier 3 persona theming** (held from Round 1 follow-ups in TODO.md) — orthogonal; remains held

## 17. Out of Scope

- Any changes to conv-mode behavior, mutex, or pin styling
- Any changes to notification rendering inside a card (date accordions, progress groups)
- Any changes to WebSocket event schema
- Any changes to FastAPI routers or backend Python
- CoSA submodule edits

## Revision Log

| Date | Author | Note |
|---|---|---|
| 2026-04-30 | Session 488ca8bd | Initial design from elicitation |
