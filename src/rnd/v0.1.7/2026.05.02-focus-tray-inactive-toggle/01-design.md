# Focus-Tray Inactive-Session Toggle + Bubble Differentiation for Personaless Cards

**Status**: Design
**Branch**: `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe`
**Author session**: 4ede5bad (2026-05-02)
**Bug-fix queue entry**: "Focus tray: hide-inactive toggle + bubble differentiation for personaless cards" (Owner 4ede5bad)
**Companion log**: [`90-execution-log.md`](90-execution-log.md)

---

## 1. Problem Statement

Two related polish gaps in the CC notifications UI surfaced during user review of the focus tray + conversation pane.

### 1.1 Tweak 1 — Inactive sessions crowd the focus tray

The 24-hour history filter is working as intended: every session that posted notifications in the last day shows a strip icon in `#cc-strip-icons`. But sessions that have since been **deallocated** (their cosa-voice bridge file is gone, their voice persona has been released back to the pool) keep occupying tray slots as **faceless slate-gray icons** (the CSS `var( --persona-color, #6c757d )` fallback at `src/fastapi_app/static/css/notifications.css:2044`).

The user wants a **toggle** to hide these inactive icons so the tray reads as "currently-live sessions only" without losing the ability to flip back to "everything in the last 24 h".

### 1.2 Tweak 2 — Personaless cards' conversation pane is undifferentiated

For sessions with an allocated persona, `.sender-message.incoming` renders with a vertical persona-tinted gradient (`notifications.css:2261-2266`) — bubbles get visible structure from the color. For **personaless** sessions, the same gradient collapses to `rgba(248, 249, 250, 0.10)` → `rgba(248, 249, 250, 0.02)` over white, which is effectively **flat near-white wallpaper**. The user described it as "plain vanilla gray from top to bottom with no differentiation between each individual notification entry."

The user picked **Option 1** of three I proposed: subtle hairline separators between adjacent bubbles + barely-visible alternate-row tint, gated to personaless cards so persona-tinted cards keep their existing look.

---

## 2. Active-Session Detection (the load-bearing signal)

There is **no explicit `isActive` boolean** on session groups in `notifications.js`. The slate-gray rendering surfaces organically:

| Step | What happens |
|------|---|
| 1 | Server-side, when a session's bridge is alive, the notifications router stamps `voice_persona` onto every outbound envelope (`src/cosa/rest/routers/notifications.py` → `_voice_persona_for_sender_id`). |
| 2 | Client receives an envelope with `voice_persona` → `senderPersonaMap.set( sender_id, persona )` (`notifications.js:5392`). |
| 3 | When the bridge dies and the persona is released, server stops stamping. Existing `senderPersonaMap` entry is removed via `voice_persona_released` WS event (`notifications.js:5401`). |
| 4 | `_addStripIcon` reads `persona?.color` (8966) → `null` → CSS rule `background: var( --persona-color, #6c757d )` falls back to slate. |
| 5 | Same fallback chain in `.sender-card`'s border + header gradient (`notifications.css:1582, 1605-1606`). |

**Therefore**: the canonical "is this session inactive?" predicate on the frontend is `!senderPersonaMap.has( senderId )`. We do **not** need a new server-side endpoint. We just hook the same signal the CSS already uses.

---

## 3. Design

### 3.1 Tweak 1 — Hide-inactive toggle

**HTML** (`src/fastapi_app/templates/notifications.html`):
- Insert a new `<button id="cc-hide-inactive-toggle" class="cc-strip-toggle">` adjacent to the existing focus-mode toggle in `#cc-session-strip`.
- Default label/title indicates current state (`👁 All` / `👁 Active`).

**JS** (`src/fastapi_app/static/js/notifications.js`):
- Persisted state via `localStorage` key `cc_hide_inactive_strip` (boolean).
- New helpers:
  - `_isStripIconInactive( senderId )` — returns `!this.senderPersonaMap.has( senderId )`.
  - `_applyHideInactiveStripFilter()` — walks every `.cc-strip-icon`, sets `data-inactive-hidden="true"` on the inactive ones (or removes the attr) based on current toggle state.
  - `_setHideInactiveStrip( enabled )` — sets the state, persists to `localStorage`, mirrors button visual state, calls `_applyHideInactiveStripFilter()`.
- Hook points (so newly-arriving / state-changing icons always obey the toggle):
  - End of `_addStripIcon( senderId, ... )` — re-apply for the just-added icon (cheap one-icon update).
  - WS handler for `voice_persona_assigned` — newly-active session: re-apply (icon may now be eligible to show).
  - WS handler for `voice_persona_released` — newly-inactive session: re-apply (icon may now need hiding).
- Toggle button click handler wires `_setHideInactiveStrip( !current )`.
- Initial application: read `localStorage` on UI bootstrap, set button state, apply once.

**CSS** (`src/fastapi_app/static/css/notifications.css`):
- New rule: `.cc-strip-icon[data-inactive-hidden="true"] { display: none; }`
- Toggle pill reuses `.cc-strip-toggle` styling. Active state uses `[data-hide-inactive="true"]` attribute on the toggle pill (mirrors existing `[data-focus-active="true"]` pattern).
- When the toggle hides every icon (zero-active edge case), the strip itself stays visible so the toggle is reachable. (We do **not** auto-hide the strip — that would strand the user.)

**Strip ordering fix (added during iteration)**:

Pre-existing bug surfaced by user during Option 1 review: the strip's initial-load ordering was reversed (oldest leftmost). Cause: `_addStripIcon` always prepended (`insertBefore(firstChild)`), so processing newest-first API order one icon at a time pushed the previously-first icon rightward each time — the *last-processed* (oldest) ended up leftmost.

**Fix**: `_addStripIcon` now takes an `insertAtTop` parameter (default `true`). `createSenderCard` passes its own `insertAtTop` flag down — `false` during initial load, `true` at runtime. Initial load thus appends in API order (newest first → newest leftmost); runtime prepends (newest arrival → leftmost). Mirrors the existing sender-card list ordering pattern (`notifications.js:10287-10296`).

**Edge cases handled**:
- **Focus mode + hide-inactive simultaneously**: `[data-focus-hidden]` and `[data-inactive-hidden]` are independent CSS rules that both fire `display: none`. Either one wins. No interaction needed.
- **Focused session goes inactive while toggle is ON**: same recovery as the existing "focused session deleted" path — `_exitFocusMode()` is **not** auto-called for hide-inactive, since the underlying card still exists; only the icon is hidden. User can flip the toggle off to re-show. (We considered auto-exit but rejected: a quick persona-pool churn would otherwise dump the user out of focus mode unexpectedly.)
- **Re-enable toggle while focus mode is on**: applying the hide filter inside focus mode is fine — `[data-focused="true"]` will still target by attribute presence, and the focused icon's senderId is by definition still active (the user is in conversation with it).

### 3.2 Tweak 2 — Bubble differentiation for personaless cards (Option 4 — gray gradient)

**Iteration history**: Option 1 (hairline separators + alternate-row zebra striping) was tried first (commit candidate, never landed). User vetoed: the zebra rule changed perceived bubble layout in a way they didn't want. Option 4 is the user-directed redo — same bubble size, same content, same date/abstract icon layout, just a different fill.

**CSS-only change** (`notifications.css`).

The `--persona-color` custom property is set on `.sender-card` via inline `style="..."` only when a persona is known (see `notifications.js:10227-10231`). We can therefore gate selectors on the **absence** of the inline custom property using attribute-substring matching:

```
.sender-card:not([style*="--persona-color"]) .sender-message.incoming {
    background: linear-gradient(
        to bottom,
        #e9ecef,  /* Bootstrap gray-200 */
        #f8f9fa   /* Bootstrap gray-100 */
    );
}
```

That single rule replaces the existing `rgba(--persona-color-rgb, 248, 249, 250)` low-alpha fallback for personaless cards. Each individual incoming bubble now carries internal vertical gradient depth that gives the eye structure without inter-bubble separators or alternation. Persona-color cards keep their existing tinted gradient untouched.

**Why gate on `style*="--persona-color"`**: this is the same signal the existing fallback CSS uses (line 1582: `border: 1px solid rgba( var( --persona-color-rgb, 222, 226, 230 ), 0.55 );`). Whether or not `--persona-color` is set on the card root drives the entire visual fallback chain. Cards with personas: untouched. Cards without: get the gray gradient.

**Why not key on a class**: gating via a class would require adding/removing a class on the card root every time a persona arrives or releases. The CSS fallback is already implicit in the `style` attribute presence; gating the new rule on the same signal keeps single-source-of-truth.

**Tradeoff acknowledged**: `:not([style*="--persona-color"])` is a **substring** match. In practice the only inline style properties on `.sender-card` are `--persona-color` and `--persona-color-rgb`, both set together (`notifications.js:10227-10231`) and removed together (`8916-8917`), so the substring test is a reliable proxy for "has persona". Documented here so a future reader who adds a third inline property knows the gating selector may need updating.

---

## 4. Sweep Check (per memory: sweep for all pattern offenders)

Locations that read `senderPersonaMap` or persona availability — verify the new helpers don't miss a code path:

| Site | Behavior we need |
|------|---|
| `_addStripIcon` (8957) | Already calls our new filter at the end — covered. |
| `voice_persona_assigned` handler (~5439) | Calls `_applyHideInactiveStripFilter()` after `senderPersonaMap.set` — covered. |
| `voice_persona_released` handler (~5401) | Calls `_applyHideInactiveStripFilter()` after `senderPersonaMap.delete` — covered. |
| Layer B initial-load hydration (~10967-10975) | Pre-populates `senderPersonaMap` before any strip icon exists, so no filter call needed at this point — but we MUST call the filter **once** on UI bootstrap after both the persona hydration and the initial `_addStripIcon` calls have run. The cleanest hook is the same place where the focus-mode toggle gets its initial `data-focus-active` value applied. |

Sites that mutate `--persona-color` on `.sender-card`:

| Site | Pattern |
|------|---|
| `createSenderCard` (10227-10231) | Sets both `--persona-color` and `--persona-color-rgb` together — Option 1 selectors work correctly. |
| `_setPersonaBadgeOnCard` live patch | TBD — verify during implementation. If it sets the badge background but does NOT also set the card-root `--persona-color`, then a live-arriving persona for an existing personaless card would render a colored badge but keep the personaless zebra striping. Resolution: ensure the card-root `--persona-color` is always set whenever `_setPersonaBadgeOnCard` fires. |

---

## 5. Test Plan

**E2E** (`src/tests/e2e_ui/test_cc_session_strip_and_focus.py`):

`TestHideInactiveToggle` (5 cases):
1. `test_toggle_pill_present_in_dom` — `#cc-hide-inactive-toggle` exists.
2. `test_toggle_hides_personaless_icons` — 3 icons seeded (2 with personas, 1 without), toggle ON, assert only the personaless icon has `data-inactive-hidden="true"`.
3. `test_toggle_persists_across_reload` — toggle ON, reload page, assert toggle still ON + personaless icon still hidden.
4. `test_persona_release_hides_icon_when_toggle_on` — fire a `voice_persona_released` event, assert the now-personaless icon picks up `data-inactive-hidden="true"`.
5. `test_persona_assign_unhides_icon_when_toggle_on` — fire a `voice_persona_assigned` event for a previously personaless icon, assert the attribute is cleared.

`TestPersonalessBubbleGradient` (3 cases):
6. `test_personaless_card_incoming_has_gray_gradient` — personaless card's incoming bubble's computed `background-image` contains both `233, 236, 239` (gray-200) and `248, 249, 250` (gray-100) stops.
7. `test_persona_card_incoming_does_not_get_personaless_gradient` — persona-color cards keep their tinted gradient; the gray-200 stop is absent.
8. `test_persona_release_switches_to_gray_gradient` — live persona release re-engages the gray gradient on the same card.

`TestStripOrdering` (2 cases):
9. `test_initial_load_appends_in_api_order` — with `isInitialLoad=true`, three injected senders end up DOM-ordered exactly as injected (newest leftmost).
10. `test_runtime_addition_lands_leftmost` — with default runtime path, the most recently injected icon is leftmost regardless of injection order.

**Smoke** (`:7999`-eligible per the testing-venues rubric — these tests don't mutate persistent state, run in <2 min, and don't need server monopoly).

**Visual check**: User-driven. Per memory "Always verify staging before commit" the user does the look-see; if Option 4 is too gray or too saturated, redirect.

---

## 6. Risks and Open Questions

- **Risk: `_setPersonaBadgeOnCard` may not set card-root `--persona-color`** — see §4 sweep table. Verify during implementation; if it doesn't, fold the fix into Tweak 2's CSS gating change so live-arriving personas correctly drop a card out of personaless styling.
- **Open: should the toggle default ON or OFF?** Default OFF (show all) preserves current behavior for users who haven't opted in. User can flip ON and it'll stick via `localStorage`.
- **Open: should there be a "0 active, all hidden" empty-state hint inside the strip?** Out of scope for this round — the toggle pill itself stays visible so the user can flip back. Filing as a follow-up if usage shows confusion.

---

## 7. Out of Scope

- Reordering icons by activity recency — already handled by `_promoteStripIcon` (newest leftmost). Hide-inactive does not change ordering.
- Server-side notification of "this session is now inactive" — we use the existing `voice_persona_released` event, no new wire format.
- Renaming or repainting the inactive icons themselves (e.g., desaturating instead of hiding) — user picked "hide" outright.
- Bubble differentiation for persona-color cards — they already have visible structure from the gradient; user only flagged the personaless case.
