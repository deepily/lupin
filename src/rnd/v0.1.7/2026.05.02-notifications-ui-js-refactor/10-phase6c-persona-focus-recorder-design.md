# Phase 6c Design Doc — Persona Modal + Focus Tray + Audio Recorder + Conversation-Mode UI Pin

| Field | Value |
|---|---|
| **Slice** | 6c per `07-phase6-slicing-manifest.md` |
| **Status** | 🟡 **DRAFT — awaiting Rick's Q-decisions walkthrough** |
| **Author** | Rachel 🕊️ (`56ee76d6`), 2026-05-12 |
| **Predecessors** | Phase 6a CLOSED 2026-05-06 (jobs surface); Phase 6b CLOSED 2026-05-12 (interactive widgets + TTS chrome + delete-button — see `97-phase6b-closure.md`) |
| **Background docs to lean on** | `src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md`, `src/rnd/v0.1.7/2026.05.02-focus-tray-inactive-toggle/01-design.md` — Phase 6c is the **multiplexer port of features designed elsewhere**, not a greenfield design |

---

## Scope (per slicing manifest §6c)

Four sub-features, all mounted under `multiplexer.html`:

| ID | Sub-feature | Notes |
|---|---|---|
| **6c-A** | Voice-persona display modal | Sender-card click → modal with `{name, icon, color, voice_id, borrowed}` |
| **6c-B** | Focus tray + focus-mode toggle | `#focus-tray` mount; `data-focus-hidden` / `data-focus-flash` attribute management |
| **6c-C** | Sender-card audio recorder | `MediaRecorder` API; STT pipeline; "Send" button → `notify` POST per legacy `notifications.js:1692-1704` |
| **6c-D** | Conversation-mode UI pin | Sender-card glow when `data-pinned-conv-mode="true"`; mic-monopoly indicator |

## Out-of-scope confirmation

- **`claude_code_event` consumer** — permanently out per D1 A-extended (2026-05-04 PM)
- **Cross-tab BroadcastChannel** — permanently out per Q12 (single-tab application)
- **Forced cutover from `/app/notifications`** — Q9 unbounded coexistence; legacy page survives unchanged
- **New server-side endpoints** — Phase 6c is client-side port only. Audio-recorder Send-button reuses the existing `/api/notify` POST surface. Voice persona data already arrives via `voice_persona_assigned` / `voice_persona_released` (no new wire format).

---

## Pre-design recon (verified before Q-decisions)

| Item | Status | Source |
|---|---|---|
| `SenderStore.voice_persona` 5-field shape (`name`, `icon`, `color`, `voice_id`, `borrowed`) | ✅ Present | `stores/SenderStore.ts:50, 61`; `shared/types.ts:227, 263` |
| `voice_persona_assigned` / `voice_persona_released` events routed via notifications | ✅ Present | `SenderStore.ts:34-35, 140-200`; `types.ts:40-41` |
| `--persona-color-rgb` CSS variable already set on `.sender-card` per Phase 5 | ✅ Present | `notifications.css:1585-1628` + design doc `2026.04.28-per-session-voice-personas/01-design.md` |
| `data-focus-hidden` + `data-focus-flash` attribute pattern in legacy | ✅ Present | `notifications.js:9126-9362, 9355-9362`; design doc `2026.05.02-focus-tray-inactive-toggle/01-design.md` |
| `data-pinned-conv-mode="true"` attribute pattern + top-of-list reordering | ✅ Present | `notifications.js:9601-10163` (`_pinSenderCardForConversationMode` + sibling helpers) |
| `conversation_mode_active` field on notifications + custom-type routing | ✅ Present | `notifications.js:5359-5365` (case `conversation_mode_changed`) |
| `.cc-voice-input` template + `data-session-hash` + `data-sender-id` | ✅ Legacy reference | `notifications.js:10270` |
| Audio-recorder STT button + Send button delegated click | ✅ Legacy reference | `notifications.js:1667, 1675, 1738` |
| `MediaRecorder` browser support | ✅ Phase 1 modern-browsers commitment; no polyfill needed | — |
| `/api/notify` POST surface (recorder Send button target) | ✅ Already exists | `cosa/rest/routers/notifications.py` (existing) |

## Phase 0 prereqs (verify at code-write time, NOT now)

1. `SenderStore` exposes a per-sender subscription API the modal can wire to (or the modal subscribes globally to `store_senders_changed`). **Recon**: confirm `store_senders_changed` payload shape exposes `voice_persona` change discriminator.
2. Conversation-mode envelope shape on the wire (per Phase 4 `conversation_mode_changed` notification type) carries `session_id` so the pin-helper can route by sender. **Recon**: check `cosa/rest/routers/notifications.py` for the canonical envelope.
3. Audio-chunk binary path (Phase 3 audio transport) does NOT collide with the recorder's outbound POST. Recorder is HTTP-only; no new WS frame types.
4. `MediaRecorder` MIME type + codec selection — legacy `notifications.js` uses what? **Recon**: check the legacy recorder for `audio/webm;codecs=opus` vs `audio/mp4` selection.

---

## Cluster A — Voice-persona modal (Q-A1..Q-A5)

**Surface**: a modal popup triggered by sender-card click, showing the 5 persona fields. Used for "which Claude is talking to me right now?"

### Q-A1 — Trigger surface ✅ **Ratified 2026-05-12: dedicated `.sender-persona-badge` chip**

**Decision**: Click target is a dedicated `.sender-persona-badge` chip embedded in each sender card.

**Rationale**: Small one-time template edit avoids paying ongoing event-conflict guards on every future on-card control (recorder, focus click-to-pin, etc.). Chip doubles as an always-visible persona-status surface (color + icon), matching the "users should know who's talking" framing.

**Implications for downstream Qs**:
- Cluster C (recorder) keeps full ownership of `.cc-voice-input` click events with NO need for stop-propagation guards against a card-level persona handler.
- Cluster B (focus click-to-pin, if Q-B3 ever flips to click-mode) is similarly unblocked.
- senderCard template (Phase 5) needs a small edit to render the chip — adds `~10-15` LOC.
- New `.sender-persona-badge` CSS class added to `persona-modal.css` (or a shared sender-card chrome stylesheet).

**Original options walked**:
- ~~Whole-card click~~ — rejected: HARD recorder conflict, semantic muddiness.
- ~~Right-click / context menu~~ — rejected: invisible affordance, mobile-hostile, inconsistent UX.

### Q-A2 — Modal implementation pattern ✅ **Ratified 2026-05-12: HTML Popover API anchored to chip**

**Decision**: Native HTML Popover API. The `.sender-persona-badge` chip carries `popovertarget="persona-popover-<sessionId>"` (declarative wiring); the popover element uses `popover="auto"` mode so light-dismiss (click-outside + ESC + single-instance) is by spec.

**Rationale**: Popover API pairs naturally with chip-trigger (declarative wiring), light-dismiss is built in (~30-50 LOC saved vs a hand-rolled portal), and contextual placement near the chip matches the "peek info" UX better than a centered overlay.

**Implications for downstream Qs**:
- `popover="auto"` mode auto-closes when ANY other auto-popover opens → Q-A3's "single-instance" requirement is by spec, no renderer logic needed.
- ESC + outside-click are built-in → Q-A3's close-affordance question narrows to "do we ALSO add an explicit × button" only.
- Per-instance popover element renders into a portal-like layer managed by the browser → no z-index plumbing.
- Phase 1 modern-browsers commitment covers Popover API (Chrome 114+, Firefox 125+, Safari 17.0+). QA check: Safari handling of `[popover]` styling edge cases.

**Original options walked**:
- ~~Native `<dialog>` centered~~ — rejected: body-centered placement less contextual than chip-anchored.
- ~~Custom portal `<div>`~~ — rejected: 30-50 extra LOC for focus-trap + ESC + backdrop that Popover gives for free.
- ~~Position-absolute child of card~~ — non-starter: stacking-context / clipping issues.

### Q-A3 — Close affordances ✅ **Ratified 2026-05-12: × button + ESC + outside-click**

**Decision**: All three pathways close the popover:
- **ESC key** — built-in to `popover="auto"`
- **Outside-click** — built-in to `popover="auto"` light-dismiss
- **Explicit `.persona-popover-close` × button** — added to template (~5 LOC)

Single-instance behavior is by spec for `popover="auto"` (opening any other auto-popover auto-closes the first); no renderer logic needed.

**Rationale**: × button gives mobile users a clear close target (no ESC key on mobile), Tab-focusable for keyboard a11y, and matches universal close conventions. Belt-and-suspenders for the small DOM cost.

### Q-A4 — Persona-color treatment in the popover ✅ **Ratified 2026-05-12: subtle**

**Decision**: Thin top accent (e.g. 4px strip or top border colored via `--persona-color-rgb`) + tinted name text. Body stays neutral.

**Rationale**: Chip already telegraphs the persona color as the trigger; the popover doesn't need to shout it again — a subtle echo is enough. Body-neutral keeps text always readable regardless of persona color luminance. No runtime luminance calc needed (which the "bold full strip" option would have required for black-vs-white text selection).

**CSS surface**: reuses the existing `--persona-color-rgb` custom property already set on `.sender-card` per `2026.04.28-per-session-voice-personas/01-design.md`. The popover inherits the var from its host card (or sets it locally from the persona data).

### Q-A5 — "Borrowed" persona display ✅ **Ratified 2026-05-12: `(borrowed)` label only**

**Recon outcome (2026-05-12)**: Wire shape carries `borrowed: boolean` ONLY. There is NO `original_owner` field on `ServerVoicePersona` (`SenderStore.ts:50-65`, `types.ts:227`). Server-side: `cosa/rest/voice_persona_helpers.py:152-198 borrowed_persona_for_sid()` returns the persona with `borrowed=True` but does NOT include the original owner in the payload.

**Decision**: Show a small `(borrowed)` label in the popover when `borrowed === true`. Chip stays unchanged for now. Attribution ("borrowed from X") would require a server-side `original_owner` field — explicitly **out of scope for Phase 6c** (which is a client-side port).

**Rationale**: Uses existing wire data; tells user "this persona is shared with another session" without requiring a server-side change. Attribution can be a follow-on once the wire shape extends.

**Follow-on filed**: If `original_owner` becomes a desirable surface, that's a separate initiative — extend `ServerVoicePersona` payload in `cosa/rest/voice_persona_helpers.py`, then Phase 6c popover swaps `(borrowed)` → `(borrowed from {name})`. Not blocking Phase 6c.

---

## Cluster A — FULLY RATIFIED (5/5) 2026-05-12

Cluster A is closed. Concrete design surface:
- **Trigger**: `.sender-persona-badge` chip embedded in each sender card
- **Modal**: HTML Popover API element with `popover="auto"` mode; chip carries `popovertarget` attribute (declarative wiring); single-instance + light-dismiss are by spec
- **Close**: ESC + outside-click (built-in) + explicit `.persona-popover-close` × button
- **Color treatment**: subtle — thin top accent + tinted name text; body neutral
- **Borrowed display**: small `(borrowed)` label when flag is true; no attribution (server data limitation)

---

## Cluster B — Focus tray + focus-mode toggle (Q-B1..Q-B5)

**Surface**: Toggle that hides non-focused sender cards (per `data-focus-hidden`) and shows a compact "tray" of hidden senders so the user can re-focus quickly. Mirrors legacy at `notifications.js:9126-9362`.

### Q-B1 — Mount surface
**Proposed**: New `<aside id="focus-tray" data-phase6-pending="true" hidden></aside>` after `#tts-pane` in `multiplexer.html`. Renderer lifts `hidden` + `data-phase6-pending` on mount (same pattern as 6a/6b).

### Q-B2 — Focus-mode toggle UI
| Option | Tradeoff |
|---|---|
| **Proposed A**: Single toggle button at top of notifications-pane: "Focus mode ON/OFF" | Discoverable; one click toggles. |
| B: Per-card "focus on me" button | Granular; more clicks; conflicts with persona-modal click handler. |
| C: Keyboard shortcut (`f` to toggle) | Power-user; no UI affordance. |

### Q-B3 — Focus-target selection
**Proposed**: The focus-target is the sender card that currently holds `data-pinned-conv-mode="true"` (i.e. the conversation-mode-active sender). If no card is pinned, focus mode is a no-op (toggle is disabled). This reuses Cluster D's pin state — keeps focus and conversation-mode coupled.

**Alternative**: Click-to-focus — the user clicks a card to make it the focus target. More flexible but requires another click handler that conflicts with persona-modal Q-A1.

### Q-B4 — Tray contents
**Proposed**: List of hidden senders (compact rows: `{icon} {name}` per row, persona-color tinted). Click a tray row → toggles focus to that sender (and un-pin-and-re-pin if Q-B3 path-A is ratified).

### Q-B5 — Flash-on-focus-change animation
**Proposed**: When focus changes (pin moves to a new card), the new focus target gets `data-focus-flash="true"` for 1.2s (CSS animation), then attribute removes. Same pattern as legacy `notifications.js:9176-9192`.

---

## Cluster C — Sender-card audio recorder (Q-C1..Q-C6)

**Surface**: A recorder embedded in each sender card. User records audio → STT button transcribes → editable text → Send button POSTs to `/api/notify` as a fresh notification "from" the user back to the sender's Claude session.

This is the most complex sub-feature of Phase 6c.

### Q-C1 — Mount placement
**Proposed**: Recorder controls live in a `.cc-voice-input` div appended to each `.sender-card`'s footer. Class verbatim from legacy. Rendered by `SenderCardRenderer` (extends Phase 5 sender-card template).

### Q-C2 — `MediaRecorder` MIME type
| Option | Tradeoff |
|---|---|
| **Proposed A**: `audio/webm;codecs=opus` (Chrome/Firefox default) | Best size; Safari support is recent (16.4+) |
| B: Feature-detect with fallback chain | Bullet-proof; adds branching |

### Q-C3 — Recording state machine
**Proposed**: 4 states: `idle → recording → processing → ready_to_send → (back to idle on send)`. State stored on the renderer instance keyed by `sender_id`. Same shape as legacy STT button.

### Q-C4 — STT pipeline target
**Proposed**: Reuse existing `/api/transcribe` or whatever the legacy `notifications.js` recorder POSTs to. **Recon**: pull the legacy endpoint from `notifications.js:1667-1738`.

### Q-C5 — Send-button POST payload shape
**Proposed**: Match legacy at `notifications.js:1692-1704`. POST `/api/notify` with body `{target_user, sender_id, message, type:"task", priority:"medium"}`. Re-verify legacy line range at code-write time.

### Q-C6 — Per-sender concurrency
**Proposed**: Only one recorder active at a time across all cards. Starting a new recording cancels any in-flight one. Single `Set<senderId>` guard on the renderer.

---

## Cluster D — Conversation-mode UI pin (Q-D1..Q-D4)

**Surface**: When `conversation_mode_active=true` on a sender, that sender's card gets a persistent glow + sticks to the top of the notifications list. Mirrors legacy `_pinSenderCardForConversationMode` at `notifications.js:9601-10163`.

### Q-D1 — Where the pin state lives
| Option | Tradeoff |
|---|---|
| **Proposed A**: New `SenderRecord.conversation_mode_active: boolean` on the store; reducer flips on `conversation_mode_changed` events | Single source of truth; renderer reads it. |
| B: DOM-only attribute managed by renderer | No store change; but invisible to other consumers. |

### Q-D2 — Top-of-list pinning mechanism
| Option | Tradeoff |
|---|---|
| **Proposed A**: Renderer sorts senders by `(conversation_mode_active DESC, last_seen DESC)` before render | Clean; pure reducer. |
| B: Physical DOM `insertBefore` after each event | Matches legacy; imperative; risks stale ordering. |

### Q-D3 — Mic-monopoly indicator
**Proposed**: When the user's local mic is monopolized by this session (a state external to the multiplexer — comes from `conversation_mode_changed` payload field `mic_monopoly` or similar), the pinned card gets an additional `data-mic-monopoly="true"` attribute. CSS shows a pulsing mic icon. **Recon**: verify the field name on the wire.

### Q-D4 — Multiple-sender conversation-mode race
**Proposed**: At most ONE sender is pinned at a time. If `conversation_mode_changed` fires for sender B while sender A is pinned, the renderer un-pins A and pins B. The store enforces single-pin invariant.

---

## Acceptance criteria (DRAFT)

Inherits AC1..AC10 machinery from Phases 5/6a/6b. AC11a/AC11b scheduled `:8000`. **All multiplexer TS files at c8 100%** per `feedback_100pct_coverage_multiplexer`.

| AC | Test | Executor | Notes |
|---|---|---|---|
| AC1 | `npx tsc --noEmit` | AI | |
| AC2 | `npx eslint multiplexer/` | AI | |
| AC2a | grep guard: NO `data-phase6-pending` on `#focus-tray` post-mount | AI | (Cluster B mount) |
| AC2b | grep guard: NO `data-phase6-pending` on `.cc-voice-input` post-mount | AI | (Cluster C mount) |
| AC3 | `persona_modal_renderer.test.ts` ≥ N PASS | AI | Cluster A enum TBD post-Q-A walk |
| AC4 | `focus_tray_renderer.test.ts` ≥ N PASS | AI | Cluster B |
| AC5 | `sender_card_recorder.test.ts` ≥ N PASS | AI | Cluster C |
| AC6 | conversation-mode pin tests | AI | Cluster D |
| AC7 | `c8 --100` on ALL new + edited multiplexer TS files | AI | mandate |
| AC8 | `boot.js` gz ≤ B6b + 8 KB = **TBD** | AI | re-baseline from Phase 6b's 34,647 B |
| AC9 | functional smoke (per-cluster) | AI | |
| AC10 | perf gate — 20 senders × pin/un-pin paint <100ms | AI | Cluster D |
| AC11 | boot_complete handshake — 5+ stable lines (add `personaModalRenderer:mounted` + `focusTrayRenderer:mounted` + `senderCardRecorderRenderer:mounted` + `conversationModePinRenderer:mounted`) | AI | depends on Q-decisions for renderer breakdown |
| AC12 | cross-phase regression (5+6a+6b+6c smoke all green) | AI | |
| AC13 | CSS scope-leak canary (per-pane CSS for each new surface) | AI | |
| AC14a | `:8000` baseline submission with `--update-snapshots -k multiplexer_phase6c` AND `auto_fix_on_failure: False` (per `feedback_baseline_capture_disable_tfe`) | AI | slot-coord |
| AC14b | `:8000` regression — "passed, 0 errors" | AI | slot-coord |

---

## Files affected (rough inventory — finalize after Q-decisions)

### NEW (estimated 6-10 files)
- `static/js/multiplexer/render/PersonaModalRenderer.ts` (Cluster A)
- `static/js/multiplexer/render/FocusTrayRenderer.ts` (Cluster B)
- `static/js/multiplexer/render/SenderCardRecorderRenderer.ts` (Cluster C)
- `static/js/multiplexer/render/ConversationModePinRenderer.ts` (Cluster D — OR rolled into NotificationsListRenderer; Q-D2 ratifies)
- `static/js/multiplexer/render/templates/personaModal.ts` (Cluster A)
- `static/js/multiplexer/render/templates/focusTray.ts` (Cluster B)
- `static/js/multiplexer/render/templates/audioRecorder.ts` (Cluster C)
- `static/css/multiplexer/persona-modal.css` (≤500 LOC)
- `static/css/multiplexer/focus-tray.css` (≤500 LOC)
- `static/css/multiplexer/sender-card-recorder.css` (≤500 LOC)
- Companion tests per Phase 5/6a/6b pattern (one per renderer + one per template)
- Smoke: `test_multiplexer_phase6c_smoke.py`
- Visual: `test_multiplexer_phase6c_visual.py`

### EDITED
- `static/html/multiplexer.html` — 3 new `<link>` + 1-2 new mount points (`#focus-tray`, `#persona-modal-portal`)
- `static/html/dev-tools.html:145` — Phase 6c live-status copy
- `static/js/multiplexer/boot.ts` — mount the 3-4 new renderers in canonical order
- `static/js/multiplexer/render/index.ts` — barrel exports
- `static/js/multiplexer/shared/types.ts` — `BootCompletePayload.handlers` extension; `SenderRecord.conversation_mode_active` if Q-D1 path A
- `static/js/multiplexer/stores/SenderStore.ts` — conversation-mode reducer if Q-D1 path A
- `.stylelintrc.json` — 3 new override blocks
- `static/js/multiplexer/render/templates/senderCard.ts` — mount points for persona-click-target (Q-A1 ratifies) + recorder div (Q-C1)

---

## What this draft is and isn't

**IS**: A scaffold of the 4 clusters with Q-decisions enumerated and provisional "Proposed" answers. The Proposed answers are educated defaults — NOT decisions. The intent is to give Rick a Q-by-Q walk-through so we converge on the design choices before authoring full templates / mechanism snippets.

**ISN'T**: A finalized design. No code-execution plan yet. No REUSE pass yet. No Pass 1/2 yet. Per `feedback_pip_plan_review_is_sequential`, those come AFTER Q-decisions are ratified.

**Next step**: Rick walks through clusters A → B → C → D, ratifying / iterating each Q-decision. After Q-decisions close, we do the REUSE pre-pass (catalog reusable patterns from Phases 5/6a/6b), then Pass 1 Fitness, then Pass 2 Adversarial.

**Estimated cycle time**: Q-decisions ~1-2 sessions; REUSE + Pass 1 + Pass 2 ~2-3 sessions; implementation ~3-5 sessions (likely the biggest slice yet given 4 distinct sub-features). Compare Phase 6b: 1 design + 4 plan-review + 5 implementation sessions across ~7 days.
