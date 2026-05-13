# Phase 7 — Multiplexer UI: Mode-Aware Toggle + Affordances

**Date**: 2026.05.12
**Status**: 📝 Design — not yet implemented
**Owner**: [LUPIN]
**Phase**: 7 of 8 (final code-touching phase)
**Prerequisites**: Phases 1–6 (especially Phase 4 — `tts_interaction_mode` must be exposed via `get_session_info()`).
**Companion docs**: [`00-index.md`](00-index.md), [`01` (May 12 canonical plan)](2026.05.12-tts-interaction-mode-solo-chorus.md), [`02-background-synthesis.md`](02-background-synthesis.md)
**Execution log**: [`97-phase7-execution-log.md`](97-phase7-execution-log.md) (TBD)

---

## 1. Goal

Update the multiplexer TypeScript UI to render mode-appropriate affordances:

- **Solo mode** — preserve today's UI exactly: bell↔phone toggle, green mic-monopoly pin, displaced-event handling, card pinning.
- **Chorus mode** — render the new UI: phone↔speaker toggle, no monopoly pin, no displaced-event handling, no pinning (or different pinning semantics if multiple speakerphone-on cards need to coexist).

Rename the WebSocket event listener from `conversation_mode_changed` to `speakerphone_changed` (uniform across both modes — the event name doesn't depend on mode, only the payload semantics do).

**Hard gate**: 100% c8 coverage on every touched file in `src/fastapi_app/static/js/multiplexer/` plus its tests in `src/tests/unit/multiplexer/`. The [100% coverage mandate for multiplexer TypeScript](#references) applies absolutely.

---

## 2. Scope

### In scope

**Event listener rename** — every reference to `conversation_mode_changed`:

- WebSocket subscription list.
- Event handler dispatch (switch statements, registries).
- Payload field references: `active` → `on`; `conversation_mode_active` → `speakerphone_on`.

**Mode-aware toggle widget**:

- Read `tts_interaction_mode` from session-info payload on session-start.
- Render the toggle component based on mode:
  - Solo mode: existing bell↔phone toggle (today's component, preserved).
  - Chorus mode: new phone↔speaker toggle (two-state, both states valid steady-states, no "currently displaced" intermediate).

**Mode-aware affordances**:

- Solo mode: green mic-monopoly pin rendered on the active session's sender card. Displaced-event handler runs. DOM index-0 pin runs.
- Chorus mode: no pin, no displaced handler (or handler short-circuits), no DOM pin (cards sort by normal recency/activity).

**Tests**: every touched file gets paired unit tests parameterized over `mode = ["solo", "chorus"]`. Coverage at `c8 --100`.

### Out of scope

- Visual restyling of either toggle widget beyond functional correctness (icon swaps).
- Persona-color-pool changes (Phase 8 deferred).
- Mobile / Firefox plugin UI — separate repos, separate concerns.
- localStorage migration of `notifications_conversation_modes` → `notifications_speakerphone_states`. Per [[feedback_no_migration_code]], the localStorage cache is regenerated on first WS event after deploy; no migration needed.

---

## 3. Deliverables

### 3.1 File-level change inventory

Without an exhaustive multiplexer audit (deferred to implementation step 1), the expected touched files are:

| File pattern | Likely change |
|---|---|
| `multiplexer/transport/*` — WS event subscription + dispatch | Rename event in subscription list, dispatch table, handler switch |
| `multiplexer/stores/*` — toggle state, mode state | Add mode field, rename speakerphone state, update getters/setters |
| `multiplexer/render/*` — sender card + toggle component | Mode-aware rendering (toggle widget, pin, glow border) |
| `multiplexer/shared/*` — types, constants, helpers | Type names, event-name constants, payload-field constants |
| `tests/unit/multiplexer/*` — paired unit tests | Mode-parameterized tests, c8 coverage maintenance |

**Step 1 of implementation order**: grep `src/fastapi_app/static/js/multiplexer/` for every reference to `conversation_mode` / `conversation-mode` / `conversationMode`. Build the exhaustive file list in `97-phase7-execution-log.md` BEFORE touching any file.

### 3.2 Mode-aware toggle component

**Component name**: `SpeakerphoneToggle` (replaces today's conversation-mode toggle).

**Props**:
- `mode: "solo" | "chorus"` — global TTS interaction mode (from session-info).
- `speakerphoneOn: boolean` — this session's state (from bridge via session-info or WS event).
- `sessionId: string` — for callback wiring.
- `onToggle: (newState: boolean) => Promise<void>` — caller-supplied handler.

**Render** (pseudo-component):

```typescript
function SpeakerphoneToggle( { mode, speakerphoneOn, sessionId, onToggle } ) {
    if ( mode === "solo" ) {
        // Today's UI: bell when off, phone when on
        const icon = speakerphoneOn ? "📞" : "🔔";
        const aria = speakerphoneOn ? "Speakerphone active (solo)" : "Notification mode";
        return <Button icon={ icon } aria={ aria } onClick={ () => onToggle( !speakerphoneOn ) } />;
    }
    // Chorus mode: phone when off, speaker when on
    const icon = speakerphoneOn ? "🔊" : "📞";
    const aria = speakerphoneOn ? "Speakerphone on (chorus)" : "Phone mode (text-only)";
    return <Button icon={ icon } aria={ aria } onClick={ () => onToggle( !speakerphoneOn ) } />;
}
```

**Why different icons per mode**: in solo, the "off" state is "notification mode" (default behavior), so the bell icon makes sense (notifications are happening normally). In chorus, the "off" state is "phone mode" (deliberately quiet), and the "on" state is "speakerphone" (literally speaker icon).

Note: emoji choices are illustrative; actual implementation uses the existing icon system (likely Bootstrap icons or similar). The point is: different glyphs per mode.

### 3.3 Mode-aware affordance rendering

**Sender card** (`SenderCard` component, approximate today's structure):

```typescript
function SenderCard( { session, mode } ) {
    const isPinned = mode === "solo" && session.speakerphoneOn;
    const hasGreenGlow = mode === "solo" && session.speakerphoneOn;
    return (
        <div
            className={ classNames( "sender-card", {
                "pinned": isPinned,
                "speakerphone-active-solo": hasGreenGlow,
            } ) }
        >
            { /* ... existing card content ... */ }
            <SpeakerphoneToggle
                mode={ mode }
                speakerphoneOn={ session.speakerphoneOn }
                sessionId={ session.id }
                onToggle={ ... }
            />
        </div>
    );
}
```

Chorus mode: no `pinned` class, no `speakerphone-active-solo` class. Card flows in normal sort order.

### 3.4 Event handler

**WebSocket `speakerphone_changed` handler**:

```typescript
function handleSpeakerphoneChanged( payload ) {
    const { session_id, on, displaced, displaced_by } = payload;

    // Update local store
    sessionStore.setSpeakerphoneOn( session_id, on );

    // Mode-conditional pinning
    const mode = sessionStore.getTtsInteractionMode();
    if ( mode === "solo" ) {
        if ( on ) {
            domPin.pinSenderCard( session_id );
        } else {
            domPin.unpinSenderCard( session_id );
            if ( displaced ) {
                ttsQueue.pauseAll();  // Today's displaced-pause behavior
            }
        }
    }
    // mode === "chorus": no pin, no pause. The card flows normally;
    // TTS continues as queued. `displaced` field will always be false in chorus.
}
```

**Subscription list update**: in WS auth/subscription payload, replace `conversation_mode_changed` with `speakerphone_changed`. Also requires server-side allowlist update (Phase 3 deliverable in `lupin-app.ini`).

### 3.5 Tests

**File-level**: every touched file gets a `*.test.ts` (or `.spec.ts` per existing convention) under `src/tests/unit/multiplexer/`.

**Coverage target**: 100% lines AND branches AND functions AND statements via `c8 --100`. `c8 ignore` comments require same-line reason per the mandate.

**Test matrix** (parameterized over `mode = ["solo", "chorus"]`):

| Test family | Coverage |
|---|---|
| `SpeakerphoneToggle.test.ts` | Mode→icon mapping; click-toggles-state; aria labels correct per mode; both modes render without errors |
| `SenderCard.test.ts` | Pinning class present in solo+on, absent in chorus+on; green-glow class present in solo+on, absent in chorus+on; toggle component receives correct props |
| `handleSpeakerphoneChanged.test.ts` | Store updates; pin/unpin invoked only in solo; displaced→pauseAll invoked only in solo; chorus payload ignored for pin logic |
| `transport/subscription.test.ts` | Auth payload includes `speakerphone_changed`, NOT `conversation_mode_changed`; dispatch table routes to `handleSpeakerphoneChanged` |
| `stores/session.test.ts` | `getTtsInteractionMode()` reads from session-info hydration; `setSpeakerphoneOn(sid, on)` updates the entry; cleared on session unmount |
| Integration smoke | Render a SenderCard in solo mode with speakerphoneOn=true; click toggle; assert WS POST fired with correct shape | Both modes |

**c8 coverage commands** (run as part of pre-merge checklist):

```bash
# Per [[100pct_coverage_mandate_multiplexer]]
npx c8 --100 npm test -- --testPathPattern multiplexer
```

### 3.6 Tooling / config updates

- Update existing c8 config to keep `--100` enforcement (likely already in place per Phase 4 + Phase 5 backfill that landed before Phase 6a).
- Any localStorage key constant `NOTIFICATIONS_CONVERSATION_MODES_KEY` or similar renames to `NOTIFICATIONS_SPEAKERPHONE_STATES_KEY`. Old localStorage entries become dormant (not read); per [[feedback_no_migration_code]], no migration code.

---

## 4. Implementation order

1. **Sweep audit** — grep `src/fastapi_app/static/js/multiplexer/` for every form of `conversation` / `conversationMode` / `conversation_mode` / `conversation-mode`. Build exhaustive worklist in `97-phase7-execution-log.md`.
2. **Read the existing toggle + sender-card components** end-to-end. Map today's behavior to the solo-mode contract (verify they match).
3. **Implement mode-aware renaming** layer by layer:
   - a. Shared constants + types (event names, payload field names).
   - b. Transport: subscription + dispatch.
   - c. Stores: speakerphone state + mode state.
   - d. Render: toggle component + sender card + pin/glow logic.
4. **Update existing unit tests** to use new names (preserves coverage during refactor).
5. **Add new unit tests** for chorus-mode branches (~30 tests across files, parameterized).
6. **Run c8 with `--100`**: fix any uncovered lines/branches/functions.
7. **Run typecheck** (`tsc --noEmit`).
8. **Run integration smoke** (Playwright or jsdom-based) in both modes.
9. **Manual smoke** in browser: toggle bridge state via INI flip + dev-server restart; verify toggle widget renders correctly per mode.

---

## 5. Verification matrix

| Layer | Check | Venue | Pass criteria |
|---|---|---|---|
| Typecheck | `tsc --noEmit` | local | No errors |
| Static sweep | `grep -rn conversation_mode src/fastapi_app/static/js/multiplexer/` | local | Zero hits |
| Unit | All `multiplexer/*.test.ts` files | :7999 (or local node runner) | 100% pass |
| Coverage | `c8 --100 npm test -- --testPathPattern multiplexer` | local | 100% lines/branches/functions/statements |
| Integration | Render tests for SenderCard in both modes | local | All variants render without errors |
| Manual (solo) | Browser: INI mode=solo, session activates speakerphone, other session displaces | :7999 | Pin + green glow appear/disappear correctly; bell↔phone toggle works |
| Manual (chorus) | Browser: INI mode=chorus, two sessions activate simultaneously | :7999 | No pin, no glow, both cards show phone↔speaker toggle |

---

## 6. Risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | Multiplexer codebase is large and unfamiliar — grep audit may miss reference patterns | Step 1 explicitly enumerates grep patterns; check both kebab-case, snake_case, and camelCase variants. |
| 2 | 100% c8 coverage gate is hard — chorus-mode branches add new code paths that need test coverage | Write tests FIRST per existing TDD-ish discipline in multiplexer testing; parameterize over modes to share coverage where possible. |
| 3 | `c8 ignore` comments cannot be used as a shortcut — only for genuinely-unreachable branches | Per [[feedback_100pct_coverage_multiplexer]] — every `c8 ignore` requires same-line reason. If you find yourself wanting to ignore many lines, the test is the problem, not the gate. |
| 4 | Mode flag must be read at component mount and on session-info refresh, but not per-render (perf) | Cache in store; refresh on `session-info` payload only. WS events update speakerphone-on state, not mode (mode is global, changed only via INI + server restart). |
| 5 | Bell icon and phone icon are similar visually; users may not perceive the difference between solo+phone-display and chorus+phone-display | Acceptable — the meaning differs but the visual is similar. Phase 8 (deferred UX) is where icon/color polish lives. |
| 6 | DOM pinning logic has two `moveSenderCardToTop` definitions (lines ~9317 + ~15163 per April 28 §11 doc) | Both must be patched to be mode-aware. Step 3.d explicitly covers both. |
| 7 | localStorage key rename leaves orphan entries on user's machine after deploy | Acceptable; per the no-migration-code rule. Orphan keys are small; can be cleaned manually if user cares. |
| 8 | Chorus mode lacks the "active session" visual indicator that solo has (green pin) — UX may feel flat | Defer to Phase 8. Plan recommends (c) drop green reservation in chorus; toggle uses icon shape only. |

---

## 7. Cross-cutting concerns

### Memory check

- [[feedback_100pct_coverage_multiplexer]] — 100% c8 coverage hard gate. ✓ (explicit in §1, §3.5, §5)
- [[feedback_no_migration_code]] — no localStorage migration; orphan keys accepted. ✓
- [[feedback_sweep_for_pattern_offenders]] — step 1 is the sweep. ✓
- [[feedback_enumerate_all_activation_paths]] — both event-driven (WS speakerphone_changed) and user-driven (click) toggle paths are mode-aware. ✓

### Naming

- Component: `SpeakerphoneToggle` (PascalCase per React/TSX convention).
- Constants: `NOTIFICATIONS_SPEAKERPHONE_STATES_KEY` (SCREAMING_SNAKE_CASE).
- Event name string: `speakerphone_changed` (snake_case to match server-side).
- Store field: `speakerphoneOn` (camelCase per JS/TS convention).

### Documentation touchpoints

- `src/docs/websocket-events.md` — event name updated (Phase 3 already touched the INI; this phase verifies the doc reflects).
- `src/docs/websocket-architecture.md` — if it references mic-monopoly enforcement, add a note that the affordance is mode-conditional.

---

## 8. Implementation timing

Estimated active work: 240–360 minutes (4–6 hours) including comprehensive tests + c8 coverage tuning. This is the heaviest phase by line count and test surface.

---

## 9. Hand-off to Phase 8 (deferred)

Phase 8 (chorus-mode UX color/glyph follow-up) inherits from Phase 7:

- `SpeakerphoneToggle` component is the surface where icon/color choices land.
- Persona-color-pool changes are independent of toggle wiring.
- The decision recorded in `90-decisions-log.md` (recommend option C — drop green reservation in chorus) is the starting point for Phase 8.

---

## References

- 100% coverage mandate ratified 2026-05-06 — see [[feedback_100pct_coverage_multiplexer]].
- Predecessor Phase 6a design doc: `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/08-phase6a-jobs-surface-design.md` (sets the c8 coverage pattern this phase inherits).
