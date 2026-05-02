# Execution Log — Focus-Tray Inactive-Session Toggle + Bubble Differentiation

**Companion to**: [`01-design.md`](01-design.md)
**Bug-fix session**: 4ede5bad (2026-05-02)

---

## Phase 0 — Documentation (in progress)

- [x] R&D directory `src/rnd/v0.1.7/2026.05.02-focus-tray-inactive-toggle/` created.
- [x] `01-design.md` written.
- [x] `90-execution-log.md` (this file) skeleton.
- [x] `bug-fix-queue.md` In Progress entry added (Owner 4ede5bad).
- [x] `history.md` session header added.
- [x] `.claude-session.md` Session: 4ede5bad section appended.

## Phase 1 — Tweak 1: Hide-inactive toggle ✅

- [x] Added `#cc-hide-inactive-toggle` button to `notifications.html` (after `#cc-strip-icons`, before `#cc-strip-toggle`).
- [x] Added `CC_HIDE_INACTIVE_KEY` localStorage key + `ccHideInactiveStrip` state field; bootstrap reads localStorage and mirrors button visual state on construct.
- [x] Added `_bindHideInactiveToggle`, `_isStripIconInactive`, `_applyHideInactiveStripFilter`, `_setHideInactiveStrip` helpers next to existing strip-toggle plumbing.
- [x] Hooked filter re-apply: end of `_addStripIcon` (cheap one-icon update), inside `voice_persona_assigned` case (becomes-active → un-hide), inside `voice_persona_released` case (becomes-inactive → hide).
- [x] CSS: `.cc-strip-icon[data-inactive-hidden="true"] { display: none; }` + `.cc-strip-toggle[data-hide-inactive="true"]` active-state styling mirroring focus-active.
- [x] Focus-mode + hide-inactive interplay verified by inspection: `[data-focus-hidden]` and `[data-inactive-hidden]` are independent CSS rules; either fires `display: none` and both can be active simultaneously without interaction needed.

## Phase 2 — Tweak 2: Bubble differentiation (Option 1) ✅

- [x] Verified `_setPersonaBadgeOnCard` (notifications.js:8897) sets card-root `--persona-color` via `setProperty` on live persona arrival and `removeProperty` on release. The substring-gating selector responds correctly to both transitions. No patch needed.
- [x] CSS: hairline rule `.sender-card:not([style*="--persona-color"]) .date-accordion-messages .sender-message + .sender-message { border-top: 1px solid rgba( 0, 0, 0, 0.06 ); ... }`.
- [x] CSS: zebra rule `.sender-card:not([style*="--persona-color"]) .date-accordion-messages .sender-message.incoming:nth-child(even) { background: rgba( 0, 0, 0, 0.025 ); }`.

## Phase 3 — Test coverage ✅

- [x] `TestHideInactiveToggle` (5 cases): pill present in DOM, hides personaless icons under filter, persists across reload, persona-release hides, persona-assign un-hides.
- [x] `TestPersonalessBubbleDifferentiation` (3 cases): personaless card has 1px hairline, persona card has none, personaless card produces alternating backgrounds.
- [x] Helpers added: `_click_hide_inactive_toggle`, `_seed_persona`, `_release_persona` (mirror real `voice_persona_assigned/released` paths).
- [x] `pytest src/tests/unit/` — 3942 passed, 1 xfailed, 0 failed (132s, no regressions from JS/CSS/HTML edits).
- [x] `run-websocket-smoke-tests.sh` — 50/50 passed, 44.6s.
- [x] JS parses (`new Function(src)`); test file `py_compile` clean.
- [ ] **PENDING**: User does the visual check on `:7999` notifications UI. If Option 1 is too subtle the user will redirect to Option 2 (drop-shadow per bubble) or Option 3 (time-cluster grouping).
- [ ] **DEFERRED**: E2E run on `:8000` — these tests are :8000-only per the testing-venues rubric. User schedules via `/api/test-suite/submit` after sign-off on the visual.

## Phase 4 — Wrap (pending)

- [ ] User signs off on visual after looking at the UI on `:7999`.
- [ ] User schedules E2E run on `:8000` for the new `TestHideInactiveToggle` + `TestPersonalessBubbleDifferentiation` cases.
- [ ] Mark `bug-fix-queue.md` In Progress → Completed with commit hash.
- [ ] Update `history.md` "(planned)" → final test + commit lines.
- [ ] Update `.claude-session.md` 4ede5bad section → `committed`.
- [ ] User reviews staging, commits (per memory: never auto-commit).

---

## Surprises / Notes

- The substring match `:not([style*="--persona-color"])` reads slightly fragile but is the same signal every existing fallback CSS rule uses (e.g. `notifications.css:1582` border, `notifications.css:1605-1606` header gradient). Single-source-of-truth for "personaless" gating.
- `_setPersonaBadgeOnCard`'s `removeProperty( "--persona-color" )` correctly empties the substring from the inline `style` attribute (browsers actually delete the property string, not just zero it), so live persona-release re-engages the new rules without a card re-render.
- No need for a server-side "is this session active?" endpoint. The client already tracks the canonical signal via `senderPersonaMap` (persona arrives via `voice_persona_assigned`, leaves via `voice_persona_released`).

## Iteration 2 (2026-05-02 ~12:00 EDT) — User feedback on Option 1

User reviewed the live `:7999` UI and surfaced two issues:

1. **Strip ordering reversed on initial load**: oldest icon was leftmost, newest rightmost. Counterintuitive. Pre-existing bug — Option 1's gating selector didn't touch the strip ordering, but the user noticed it during the same review.
2. **Zebra striping vetoed**: user disliked the alternate-row tint and the hairline border between bubbles. Asked for the same balloon size/format/icon layout but a real gray gradient on each individual inactive-session bubble.

### Iteration 2 changes (this commit)

- [x] **Strip ordering**: `_addStripIcon` accepts new `insertAtTop` param (default `true`). `createSenderCard` passes its own `insertAtTop` flag down. Initial load (`isInitialLoad=true` → `createSenderCard(senderId, false)` → `_addStripIcon(..., false)`) appends in API order; runtime prepends. Fix is symmetric with the existing sender-card list ordering pattern at `notifications.js:10287-10296`.
- [x] **CSS reset**: removed `.sender-message + .sender-message` hairline rule and `.sender-message.incoming:nth-child(even)` zebra rule.
- [x] **CSS replace**: single new rule `.sender-card:not([style*="--persona-color"]) .sender-message.incoming { background: linear-gradient(to bottom, #e9ecef, #f8f9fa); }`. Same bubble size, same date/abstract icon layout — only the fill changes.
- [x] **Tests rewritten**: `TestPersonalessBubbleDifferentiation` → `TestPersonalessBubbleGradient` (3 new cases asserting the gradient stops). New `TestStripOrdering` class (2 cases asserting initial-load API order + runtime leftmost-prepend).
- [x] **Design doc + this log updated**.

### Iteration 2 verification

- [x] `pytest src/tests/unit/` — re-run still green (no Python touched).
- [x] `run-websocket-smoke-tests.sh` — re-run green (no WS touched).
- [x] JS parses (`new Function(src)`); test file `py_compile` clean.
- [ ] **PENDING**: User does the visual check on `:7999` for both ordering + new gradient.
