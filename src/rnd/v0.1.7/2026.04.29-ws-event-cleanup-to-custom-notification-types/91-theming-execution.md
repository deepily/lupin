# 91 — Theming Round 1 execution log

**Pairs with**: `02-theming-round1-design.md`
**Started**: 2026-04-29

---

## Phase status

| Phase | Subject | Status | Notes |
|-------|---------|--------|-------|
| 0 | Design + execution log scaffolds | ✅ complete | Design doc 02 + this scaffold |
| 1 | JS — custom-property piping + badge right-align relocation | ✅ complete | `_hexToRgb` helper added; setters in `createSenderCard` + `_setPersonaBadgeOnCard`; badge moved into `.sender-stats-group` first child |
| 2 | CSS — Tier 1 (4 rules) + Tier 2 (1 rule + hover) | ✅ complete | All rules use `var(--persona-color, fallback)` so personaless cards are unchanged |
| 3 | Regression + close + commit proposal | ✅ complete | 3780/3780 unit + voice_persona allocation pass; 5/5 ws_event_cleanup smoke pass; visual reload check next |

---

## Phase 0 — Documentation

**Files created**:
- `02-theming-round1-design.md`
- `91-theming-execution.md` (this file)

---

## Phase 1 — JS custom-property piping

`src/fastapi_app/static/js/notifications.js`:
- New `_hexToRgb( hex )` helper (handles `#RGB` and `#RRGGBB` forms; returns null on malformed input)
- `createSenderCard`: when `persona && persona.color`, set `--persona-color` (hex) and `--persona-color-rgb` (triplet) on the `.sender-card` div BEFORE the innerHTML template runs
- `_setPersonaBadgeOnCard`: same setter logic on patch path; `removeProperty` on the release path so Tier 1/2 rules cleanly fall back to defaults
- Badge relocated: in `createSenderCard`'s template literal, `${personaBadge}` moved from outside `.sender-stats-group` to its first child position. `_setPersonaBadgeOnCard`'s insertion target updated accordingly (`statsGroup.insertBefore( badge, statsGroup.firstChild )`).

---

## Phase 2 — CSS rule changes

`src/fastapi_app/static/css/notifications.css`:
- `.sender-card` border: `1px solid rgba( var( --persona-color-rgb, 222, 226, 230 ), 0.55 )` (was `1px solid #dee2e6`)
- `.sender-card` shadow: dual-layer persona-tinted box-shadow (was neutral `rgba(0,0,0,0.08)`)
- `.sender-card-active` left stripe: `3px solid var( --persona-color, #28a745 )` (was solid green)
- `.sender-card-active .sender-active-indicator`: `var( --persona-color, #28a745 )` (was green)
- `.sender-card-header` background: persona-tinted gradient with grey fallback (was flat `#f8f9fa`)
- `.sender-card-header:hover` background: brighter persona-tinted gradient with `#e9ecef` fallback (was flat hover color)
- Added `transition` on card border + shadow so live persona updates animate

Pinned-conversation-mode header rule at `.sender-card[data-pinned-conv-mode="true"] .sender-card-header` is more specific than `.sender-card-header` (specificity 0,0,3,0 vs 0,0,1,0) — pinned green still wins when both apply, no selector ordering changes needed.

---

## Phase 3 — Regression + commit

| Suite | Result |
|-------|--------|
| `pytest src/tests/unit/` + `test_voice_persona_allocation.py` | **3780 passed**, 1 xfailed, 0 failures |
| `pytest src/tests/smoke/test_ws_event_cleanup.py` | **5/5 passed** (incl. Layer B server-stamp test) |

Pure-frontend changes — no Python source touched, so unit regression unchanged from prior commit's 3780 baseline.

**Visual verification**: hot-reload picks up CSS + JS via uvicorn `--reload` watcher. User force-refresh expected to show:
- Each persona-bearing card has a tinted border + soft persona-colored glow
- Active session left stripe + indicator dot in persona color
- Header carries a subtle persona-tinted gradient
- Persona badge appears in the right cluster (inside `.sender-stats-group`), not next to the session name
- Personaless cards (legacy / non-CC senders) unchanged — fallback values preserve neutral grey palette

---

## Files staged for commit

- `src/fastapi_app/static/js/notifications.js` — `_hexToRgb`, custom-prop setters, badge relocation
- `src/fastapi_app/static/css/notifications.css` — Tier 1 + Tier 2 rules with fallbacks
- `src/conf/lupin-app.ini` — Rachel persona color `#4CAF50` → `#009688` (teal) to clear collision with the Bootstrap-green conversation-mode pin (discovered post-Tier-1 visual review)
- `src/conf/lupin-app-splainer.ini` — matching splainer with provenance note
- `src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/02-theming-round1-design.md` — NEW
- `src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/91-theming-execution.md` — NEW (this file)

No CoSA changes for Round 1.

### Discovery: Rachel's green collision

Once Tier 1's persona-tinted card border + active stripe shipped, Rachel's `#4CAF50` (Material green) became visually indistinguishable from the conversation-mode pin's Bootstrap-success-green `#198754` (`.sender-card[data-pinned-conv-mode="true"]` glow at `:440-454`). Different hex, same hue family — looked identical at the alphas Tier 1 uses. User flagged mid-implementation; switched Rachel to Material teal `#009688` — distinct hue, still calm to match her "Calm & clear female" profile.

**Existing Rachel session caveat**: bridges allocated before this change retain the old `#4CAF50` (color is copied into the bridge at allocation time, not re-resolved). To pick up the new color, an active Rachel session must be released and re-allocated. New SessionStart hooks immediately get the teal.

### Mid-flight visual polish (user feedback 2026-04-29)

After the initial Round 1 land was staged, user did a force-refresh and surfaced two issues:

1. **Left stripe absent on inactive themed cards**: original Tier 1 design only colored the left stripe for `.sender-card-active`. Inactive cards retained `border-left: 3px solid transparent`, so the persona color appeared only on the most-recent sender. Fix: extended the inactive selector to use `var(--persona-color, transparent)` — full persona color when set, transparent fallback when not. Active vs inactive now distinguished by the indicator dot (●/○) and shadow intensity, not the stripe presence.

2. **Header gradient direction**: original Tier 2 used `linear-gradient(to right, ...)`. Visually the wash drifted horizontally across the header. User preferred top-to-bottom — the tinted weight at the top of the header reads as a colored shadow falling onto the content. Fix: changed direction to `to bottom` for both the base and `:hover` rules.

Both changes are CSS-only; no JS or config impact. Tests still pass.

### Parallel-session staging incident (handled, no contamination)

While staging the Rachel INI fix, `git add src/conf/lupin-app.ini` inadvertently picked up an unrelated `test fix expediter max proposals per cluster` addition from a parallel session's working tree (TFE work, not mine). Caught via `git diff --cached` review; unstaged with `git restore --staged`, the parallel-session content stashed via `git stash push -- <file>` so it survives my commit. After my commit lands, a `git stash pop` restores those changes for the other session to manage.

Lesson: always Read a file before Edit when the working tree may contain other-session changes — the Read-before-Edit guard catches blind staging. Documented for future reference.

---

## Open items (for follow-up rounds, not this one)

- **Round 2 (Tier 3 widgets)**: `.sender-conversation-mode-btn` border tint when not active, `.sender-gist-btn` border tint, `.cc-voice-input-row` chrome tint
- **Round 3 (Tier 4 message bubbles)**: outgoing background → persona color
- **frontend-design plugin polish pass**: visual review against live :7999 after Round 1 lands
