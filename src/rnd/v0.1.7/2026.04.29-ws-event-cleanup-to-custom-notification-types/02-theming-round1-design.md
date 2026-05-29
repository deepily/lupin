# 02 — Persona Theming v2, Round 1 (Foundation + Tier 1 + Tier 2)

**Date**: 2026-04-29
**Author**: Claude Opus 4.7 (1M ctx)
**Status**: in progress
**Pairs with**: `91-theming-execution.md` (execution log)
**Builds on**: `01-design.md` (WS-event cleanup) — provides the data plumbing this work consumes

---

## 1. Context

The user direction (verbatim): *"It's perfectly fine to use pink with Nora, but you really need to apply it liberally to the entire session window — borders, shadows, and maybe even widgets."*

Round 1 establishes the CSS-custom-property foundation and applies persona color across the most-visible card-chrome surfaces (Tier 1) and the header background wash (Tier 2). Tier 3 widget tinting and Tier 4 message-bubble tinting are explicitly held until the user has lived with Round 1 to gauge intensity.

A late-arriving requirement: **the persona badge must be right-aligned**, not left-aligned beside the project/session name. Round 1 incorporates this as part of the Foundation by relocating the badge into the existing right-aligned `.sender-stats-group` cluster.

---

## 2. Foundation — CSS custom properties + badge relocation

### 2.1 `--persona-color` and `--persona-color-rgb` on each `.sender-card`

When the persona is known for a sender, set two custom properties on the card root element:

```js
card.style.setProperty( "--persona-color",     persona.color );           // "#E91E63"
card.style.setProperty( "--persona-color-rgb", _hexToRgb( persona.color ) ); // "233, 30, 99"
```

The RGB triplet form is needed because CSS `rgba( r, g, b, a )` cannot consume a hex value — and Tier 1 + 2 use rgba for alpha-blended tints.

A small `_hexToRgb( "#E91E63" ) → "233, 30, 99"` helper feeds the RGB form.

Two callsites set/clear these properties:

- `createSenderCard` — set on initial render when `getPersonaForSender( senderId )` returns a persona
- `_setPersonaBadgeOnCard` — set when patching badge in (live arrival), clear via `removeProperty` when patching badge out (release)

Once the variables exist on the card, every CSS rule below references them. No inline styles, no per-rule color hardcoding. New personas added to `lupin-app.ini` ripple through automatically.

### 2.2 Badge relocated to right cluster

**Was**: badge sat between `${sessionDisplay}` and `.sender-stats-group` in the header — left-aligned beside the session name.

**Now**: badge moves *inside* `.sender-stats-group` as its first child. The stats group already has `margin-left: auto`, so the badge is auto-pushed right.

Resulting header order:

```
[active-dot] [status] [project-name] [session-name] [gist-btn]                                                [badge] [new-count] [count] [last-activity] [×] [▼]
←────── identity (name) ──────→                                                                       ←──── identity (voice) + recency ────→
```

`createSenderCard`'s template literal moves `${personaBadge}` from outside the stats group to its first child. `_setPersonaBadgeOnCard`'s insertion logic anchors at `.sender-stats-group :first-child` instead of `.sender-stats-group` itself.

---

## 3. Tier 1 — Card chrome

Four CSS rule changes in `notifications.css`. Each uses `var( --persona-color* )` with a fallback equal to today's color, so cards without a persona render exactly as before.

| Rule | File:line | Change |
|------|-----------|--------|
| `.sender-card` border | `:1531` | `border: 1px solid rgba( var( --persona-color-rgb, 222, 226, 230 ), 0.55 );` (was `1px solid #dee2e6`) |
| `.sender-card` shadow | `:1534` | `box-shadow: 0 0 0 1px rgba( var( --persona-color-rgb, 0, 0, 0 ), 0.06 ), 0 2px 6px rgba( var( --persona-color-rgb, 0, 0, 0 ), 0.12 );` (was neutral grey) |
| `.sender-card-active` left stripe | `:1909` | `border-left: 3px solid var( --persona-color, #28a745 );` (was solid green) |
| `.sender-card-active .sender-active-indicator` color | `:1899` | `color: var( --persona-color, #28a745 );` (was green) |

**Effect**: a vertical stack of cards becomes a vertical color stripe (left edges + dots colored per persona). Glow ties each card to its speaker.

**Tradeoff acknowledged**: the universal "green = active" reading is replaced by per-persona color. The conversation-mode pin retains its green glow (already at `:440-454`, more specific selector wins) — green now means *"this one's monopolizing the mic"*, which is a sharper semantic.

---

## 4. Tier 2 — Header wash

One CSS rule change.

| Rule | File:line | Change |
|------|-----------|--------|
| `.sender-card-header` background | `:1543` | `background: linear-gradient( to right, rgba( var( --persona-color-rgb, 248, 249, 250 ), 0.14 ), rgba( var( --persona-color-rgb, 248, 249, 250 ), 0.04 ) );` (was flat `#f8f9fa`) |

**Effect**: a subtle persona-tinted wash across the header. Reads as a gradient, not a solid color.

**Coexistence with the conversation-mode pin gradient** at `:448-454`: the pinned-mode selector (`.sender-card[data-pinned-conv-mode="true"] .sender-card-header`) is more specific (specificity 0,0,3,0 vs my new rule's 0,0,1,0), so the pinned green wins automatically. No selector ordering change needed.

The hover rule at `:1551` (`background-color: #e9ecef`) becomes slightly less effective because the new gradient overrides flat color on the base — keep it as-is for now; the inherited base gradient is still readable.

---

## 5. Files to modify

**Parent Lupin** (will be staged):
- `src/fastapi_app/static/js/notifications.js` — `_hexToRgb` helper, custom-property setters in `createSenderCard` + `_setPersonaBadgeOnCard`, badge relocation into `.sender-stats-group`
- `src/fastapi_app/static/css/notifications.css` — 5 rule changes (4 Tier 1 + 1 Tier 2)
- `src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/02-theming-round1-design.md` — this doc (NEW)
- `src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/91-theming-execution.md` — execution log (NEW)

**No CoSA changes** for Round 1 (pure client work).

---

## 6. Verification

1. **Python regression** (no Python touched, but confirm nothing transitively broke): `pytest src/tests/unit/`. Expect 3773/3773.
2. **WS event cleanup smoke**: `pytest src/tests/smoke/test_ws_event_cleanup.py`. Expect 5/5 (asserts persona data flow which we depend on).
3. **Visual reload check**: hot-reload :7999 (CSS / JS auto-reloads on save), force-refresh browser, observe:
   - Each sender card shows a tinted border + soft shadow in its persona color
   - Active sender's left stripe and indicator dot match its persona color
   - Header background carries a subtle persona-tinted wash
   - Persona badge is now right-aligned inside the stats cluster
   - Cards without a persona (legacy / non-CC senders) render with the old neutral palette unchanged

This last item is what the fallback values (`var( ..., #dee2e6 )` etc.) guarantee — explicitly verify no regression on personaless cards.

---

## 7. Held for follow-up rounds

- **Round 2 (Tier 3 widgets)**: `.sender-conversation-mode-btn` border tint when not active, `.sender-gist-btn` border tint, `.cc-voice-input-row` chrome tint. Decide after living with Round 1.
- **Round 3 (Tier 4 message bubbles)**: outgoing-message background → persona color. Held for explicit user opt-in.
- **Frontend-design polish pass**: invoke `frontend-design` plugin subagent for visual review against the live :7999 UI after Round 1 lands.
