# Phase 7 Execution Log — Multiplexer Rename + Legacy Notifications.js Wire Fix

**Date**: 2026-05-12 (PM EDT)
**Owner**: [LUPIN] (Rio session 83ba1e51)
**Companion design doc**: [`16-phase7-multiplexer-ui-design.md`](16-phase7-multiplexer-ui-design.md)
**Status**: ✅ Complete for the minimum-viable scope. Mode-aware widget work scope-deferred (see §7).

---

## 1. Execute-time audit (per design doc §4 step 1 + `feedback_audit_plans_at_execute_time`)

Pre-implementation sweep:

```bash
grep -rln 'conversation_mode|conversation-mode|conversationMode|ConversationMode' \
    src/fastapi_app/static/js/multiplexer/ src/tests/unit/multiplexer/
```

Result: **only 5 files** in the multiplexer area had legacy refs.

| File | Hit |
|---|---|
| `src/fastapi_app/static/js/multiplexer/shared/types.ts` | `LupinEventType` literal `"conversation_mode_change"` |
| `src/fastapi_app/static/js/multiplexer/shared/broadcast.ts` | `BROADCAST_WHITELIST` entry (INERT in production per Q12) |
| `src/fastapi_app/static/js/multiplexer/stores/SenderStore.ts` | `STATE_UPDATE_TYPES` set entry `"conversation_mode_changed"` + 1 comment |
| `src/tests/unit/multiplexer/sender_store.test.ts` | 1 test + 1 assertion using legacy type literal |
| `src/tests/unit/multiplexer/broadcast.test.ts` | 1 test expecting legacy literal in whitelist |

Crucially: **the multiplexer does NOT render the speakerphone toggle widget.** The 📞/🔔 button + monopoly-pin logic lives in legacy `src/fastapi_app/static/js/notifications.js` (lines 5356-5369 dispatch + 9590-9736 handler/render). The design doc anticipated `multiplexer/render/*` touches for a toggle widget that doesn't exist in the multiplexer codebase.

Additional discovery: legacy `notifications.js` has been **silently broken since Phase 3** of this refactor. Phase 3 renamed the server-emitted notification type from `conversation_mode_changed` → `speakerphone_changed` AND the payload field from `active` → `on`. The legacy switch case at `notifications.js:5356` was still matching the old `conversation_mode_changed` string, so the toggle widget stopped receiving WS-driven state updates. That's not a Phase 7 regression — it's a pre-existing Phase 3 omission surfaced by this audit.

## 2. In-scope work executed

### 2a. Multiplexer rename — 3 source files

- `types.ts`: `LupinEventType` literal `"conversation_mode_change"` → `"speakerphone_change"`
- `broadcast.ts`: `BROADCAST_WHITELIST` entry rename to match `types.ts`
- `SenderStore.ts`:
  - `STATE_UPDATE_TYPES` set entry `"conversation_mode_changed"` → `"speakerphone_changed"` (server-canonical wire type post-Phase-3)
  - Comment block updated for consistency

### 2b. Multiplexer test updates — 2 test files

- `sender_store.test.ts`: test name + assertion type literal renamed (`speakerphone_changed`)
- `broadcast.test.ts`: whitelist-membership assertion updated to expect `speakerphone_change`

### 2c. Legacy notifications.js minimum-viable fix

The audit revealed the legacy widget has been receiving zero state updates since Phase 3. Minimum-viable fix to restore functionality:

- Line 5356: `case "conversation_mode_changed":` → `case "speakerphone_changed":`
- Line 5365: `notification.payload?.active` → `notification.payload?.on` (server-canonical payload field)
- Lines 177 + 2257: comment references updated for consistency

The internal envelope key `conversation_mode_active` and the handler name `handleConversationModeChanged` (line 9599) are deliberately preserved as a local naming layer — those are private to notifications.js's call graph and renaming them would touch ~10 additional call sites for purely cosmetic gain. Out of scope for the minimum-viable fix.

## 3. Files touched (Lupin parent — will be committed)

- `src/fastapi_app/static/js/multiplexer/shared/types.ts`
- `src/fastapi_app/static/js/multiplexer/shared/broadcast.ts`
- `src/fastapi_app/static/js/multiplexer/stores/SenderStore.ts`
- `src/tests/unit/multiplexer/sender_store.test.ts`
- `src/tests/unit/multiplexer/broadcast.test.ts`
- `src/fastapi_app/static/js/notifications.js` — 3 edits (case literal, payload field, 2 comments)
- `src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/97-phase7-execution-log.md` — this file

No CoSA-side edits this phase.

## 4. Verification

| Layer | Check | Result |
|---|---|---|
| Multiplexer unit | `npm test -- 'src/tests/unit/multiplexer/*.test.ts'` | 329/329 ✅ |
| Multiplexer c8 (100% gate per `feedback_100pct_coverage_multiplexer`) | `npx c8 --100 --include=multiplexer/shared/broadcast.ts --include=multiplexer/stores/SenderStore.ts npm test` | 100/100/100/100 on all dimensions ✅ |
| TypeScript compile | implicit via `tsx --test` | No errors |
| Python unit regression | `pytest src/tests/unit/` | 4267 passed, 1 xfailed, 0 failures |
| Static sweep post-edit | `grep -rn 'conversation_mode' src/fastapi_app/static/js/multiplexer/` | Zero hits |

`types.ts` is not in the c8 report because it's pure type declarations (no runtime). That's correct behavior — TypeScript types compile to nothing at runtime.

## 5. Deviations from design doc

| Deviation | Rationale |
|---|---|
| Did NOT add a `SpeakerphoneToggle` component to `multiplexer/render/` | Audit revealed the multiplexer never had a toggle widget; the design's §3.2 / §3.3 component proposals would be NEW feature work (migrate from legacy notifications.js). Out of minimum-viable scope; flagged in §7 below |
| Did NOT add a `handleSpeakerphoneChanged` handler in multiplexer | Same — that's part of the deferred toggle-widget migration. The multiplexer's role today is unread-bump-suppression for the state-update notification type; that role is preserved with the renamed literal |
| Did NOT add `tts_interaction_mode` reading via `get_session_info()` to a multiplexer store | The multiplexer doesn't currently render anything mode-aware; reading mode is meaningless until there's a renderer to consume it. Scope-deferred with the widget migration |
| Did NOT migrate the localStorage key `notifications_conversation_modes` → `notifications_speakerphone_states` | Per design doc §2 out-of-scope, plus `feedback_no_migration_code` — orphan keys are accepted |
| Did NOT make the toggle icons mode-aware (solo bell↔phone, chorus phone↔speaker) | UX polish; effectively Phase 8 territory. The current legacy widget continues to render 📞/🔔 (solo-style) regardless of mode |

## 6. The Phase 7 design doc estimate (240-360 min) vs actual (under 60 min)

The estimate assumed the multiplexer had a toggle widget + mode-aware renderer to refactor. Audit reality: the multiplexer is event-classification-only on the speakerphone front. The actual minimum-viable rename took well under an hour.

The "missing" 200-300 minutes of design-doc work is the toggle-widget migration described in §7 below. That work is real but its scope as written would substantially exceed Phase 7's bounded intent (string renames + coverage) — it's a feature add, not a refactor.

## 7. Deferred work (recommended scope-out as "Phase 7b" or absorb into Phase 8)

The design doc proposed three deliverables that are NEW features in the multiplexer codebase, not renames:

1. **`SpeakerphoneToggle` component** — mode-aware icon glyph rendering, sender card integration, click handler wired through the multiplexer's API client. ~120-180 min.
2. **Mode-aware affordances** — green mic-monopoly pin in solo only, displaced-event handling, DOM index-0 pinning. Today these live in `notifications.js:9590-9707`. Migrating them as 100%-c8-covered TS is a substantial lift. ~90-120 min.
3. **localStorage cache + mode-state store** — `getTtsInteractionMode()` + `setSpeakerphoneOn(sid, on)` getters on a session store, session-info hydration wiring. ~30-60 min.

**Recommendation**: open a separate ticket (e.g., "Phase 7b — multiplexer toggle widget migration") so the scope is explicit and not muddled with the rename work in this commit. Alternatively, fold these into Phase 8 since both phases are UX-layer work on the chorus rollout.

Phase 8's stub design doc (`17-phase8-color-glyph-uxs-design.md`) covers chorus-mode color/glyph polish, which is narrower than the widget-migration work above. The two would compose well as a single "post-rename UI follow-up" arc.

## 8. Memory checks (per design doc §7)

- [[feedback_100pct_coverage_multiplexer]] — 100% c8 maintained on every touched multiplexer file. ✓
- [[feedback_no_migration_code]] — hard cut on the rename; no aliases for old event names. ✓
- [[feedback_sweep_for_pattern_offenders]] — full grep across multiplexer + tests + notifications.js; all real hits resolved. ✓
- [[feedback_audit_plans_at_execute_time]] — audit surfaced the legacy notifications.js Phase 3 omission AND the design-doc / code-reality scope mismatch; both called out before implementing. ✓
- [[feedback_lupin_only_never_cosa]] — no CoSA edits this phase. ✓
- [[feedback_never_auto_commit_push]] — no commits yet; awaiting Rick auth. ✓
- [[feedback_skip_rnd_doc_for_trivial_fixes]] — this is part of a multi-phase plan; execution log warranted (and surfaces the deferred-work proposal). ✓
