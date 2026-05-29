# Phase 6 Slicing Manifest — A / B / C

**Date**: 2026-05-05
**Status**: Slicing boundaries decided 2026-05-05; per-slice design docs land as separate artifacts (`08-phase6a-*-design.md` etc.).
**Cadence per slice**: identical to Phase 4 + 5 — design doc → plan-review pipeline (REUSE + Pass 1 + Pass 2) → user ratifies Q-decisions + D-tier → Resolution Loop → user go-ahead → code-execution plan (separate plan-mode session) → implementation + AC matrix → commit gate → AC11-style scheduled `:8000` visual baseline.

## Slice status (live)

| Slice | Status | Closed | Closure doc |
|---|---|---|---|
| 6a — Jobs surface | ✅ **CLOSED** | 2026-05-06 | `90-execution-log.md` § "Phase 6a — Jobs Surface" |
| 6b — Interactive widgets (action-required + TTS chrome + delete-button handler) | ✅ **CLOSED** | 2026-05-12 | `97-phase6b-closure.md` |
| 6c — Persona + focus + audio recorder | ⏸ Not started | — | — |

---

## Why slice (recap)

Phase 6 was originally framed as a single "feature parity" cycle covering ~9 sub-features:
jobs queue rendering, TTS chrome, action-required interactive submit, focus tray, voice-persona modal, conversation-mode UI pin, sender-card audio recorder, plus two intentional out-of-scope items (`claude_code_event` consumer, `JobStore.hydrateHistory` invocation).

Compared to Phase 5's single-pane scope (notifications list), this is ~5-9× the surface area. Slicing into A/B/C keeps each commit's blast radius reviewable and lets the project redirect mid-Phase-6 if any slice surfaces a contract change.

---

## Slice boundaries

### 6a — Jobs surface

**Scope**: render the `#jobs-pane` (currently hidden in Phase 5 markup with `data-phase6-pending="true"`).

| Element | Source |
|---|---|
| `JobStore.hydrateHistory(api)` body — Phase 4 left the public method but Q7 ratified lazy invocation in Phase 5+ | Q7 (`05-phase4-stores-design.md` § JobStore + `06-phase5-renderer-design.md` § Out of scope) |
| Jobs-pane renderer (5-bucket layout: todo / running / done / dead / history) | Phase 5 § Out of scope (line "Jobs queue rendering") |
| Job card template per `JobState` (4-value UI status: `todo` / `running` / `done` / `dead`; history is reducer-derived view) | Phase 4 `JobStore` interface |
| Lift `data-phase6-pending="true"` from `#jobs-pane` (Q-L) | Phase 5 § Page shell update |
| `BootCompletePayload.handlers.jobsRenderer = "mounted"` extension (mirroring Phase 5's `notificationsRenderer`) | RE-16 + F22 pattern |
| AC2a grep ban on `hydrateHistory` lifts (Phase 5 explicitly forbade it; 6a opens the gate) | Phase 5 AC2a |

**Dependencies**: Phase 4 `JobStore` (✓); Phase 5 `keyedListMerge` (✓); Phase 5 `html` helper (✓).

**Independence**: 6a is the most isolated slice — jobs-pane is its own DOM surface; no shared mutable state with 6b or 6c.

### 6b — Interactive widgets (action-required + TTS chrome)

**Scope**: lift `data-phase6-pending="true"` from action-required widgets and the `#tts-pane`; attach handlers; wire input controls.

| Element | Source |
|---|---|
| Action-required interactive submit — click handlers per `response_type` (`yes_no` chips → buttons; `multiple_choice` chips → radios; `open_ended` placeholder → text input; `open_ended_batch` placeholder → per-question inputs) | Q-H two-phase rollout (Phase 5 ships read-only; Phase 6 attaches handlers) |
| `actionRequiredStore.respond(idHash, response)` invocation from handlers | Phase 4 `ActionRequiredStore` public API |
| Strip inertness markers post-attach: `aria-disabled`, `cursor: not-allowed`, `.action-required-pending-notice` microcopy | Phase 5 § Action-required read-only template |
| TTS chrome on `#tts-pane`: playback queue rendering, pause/resume/stop controls, current-track indicator | Phase 5 § Out of scope (lines "TTS playback chrome + queue", `.cc-voice-input`, `.notification-corner-pause-btn`, `.notification-corner-stop-btn`, `.tts-playing`, `.is-paused-current` — all dropped from Phase 5 CSS port pending Phase 6) |
| AudioStore consumer: subscribes to `store_audio_state_change` + `store_audio_chunk_decoded` for chrome state | Phase 4 `AudioStore` interface |
| Lift `data-phase6-pending="true"` from `#tts-pane` (Q-L) + every `.action-required-widget` (Q-H) | Phase 5 § Page shell update + § Action-required template |

**Dependencies**: Phase 4 `ActionRequiredStore` + `AudioStore` (✓); Phase 5 read-only widget DOM scaffold (✓); Phase 5 `html` helper (✓).

**Independence from 6a**: no jobs-pane interaction.

### 6c — Persona + focus + audio recorder

**Scope**: chrome polish + new mount surfaces.

| Element | Source |
|---|---|
| Voice-persona display modal (sender-card click → modal showing persona name/icon/voice_id/borrowed status) | Phase 5 § Out of scope (line "Voice persona display modal") + Phase 4 `SenderStore.voice_persona` (D-E full 5-field shape) |
| Conversation-mode UI pin (sender-card glow when `data-pinned-conv-mode="true"`; mic-monopoly indicator) | Phase 5 § Out of scope (line "Conversation-mode UI pin") |
| Focus tray + focus-mode toggle (`#focus-tray` mount; `data-focus-hidden`/`data-focus-flash` attribute management on sender cards) | Phase 5 § Out of scope (line "Focus tray + focus-mode toggle") |
| Sender-card audio recorder (`MediaRecorder` API; STT pipeline integration; "Send" button → `notify` POST per legacy `notifications.js:1692-1704`) | Phase 5 § Out of scope (line "Sender-card audio recorder", `.cc-voice-input` — dropped from Phase 5 CSS) |
| New mount points in `multiplexer.html`: `#focus-tray`, persona-modal portal | Greenfield (no Phase 5 scaffold) |

**Dependencies**: Phase 4 `SenderStore` + `AudioStore` (✓); Phase 5 sender card chrome (✓); browser `MediaRecorder` API (no polyfill needed per Phase 1 modern-browsers commitment).

**Independence from 6a + 6b**: 6c does not modify jobs-pane, action-required widgets, or TTS chrome.

---

## Recommended order

**6a → 6b → 6c**. Rationale:

1. **6a is the most isolated** — jobs-pane is its own DOM surface; lowest risk of contract drift; cleanest independent commit.
2. **6b extends existing Phase 5 surfaces** (action-required widgets, sender-card chrome via TTS playback states) — landing 6b second means 6a's jobs-pane patterns can inform 6b's pane chrome conventions.
3. **6c is "polish + new surfaces"** — focus mode + voice-persona modal + audio recorder are net-new surfaces that benefit from 6a + 6b's settled patterns. Lowest urgency since they're optional UX features rather than core function.

---

## Permanently out of scope (across all 3 slices)

- **`claude_code_event` consumer** — D1 A-extended ratification (2026-05-04 PM): "defer `ClaudeCodeTransport` from Phase 3 *and* from all subsequent multiplexer phases (not just Phase 4)." `claude_code_event` flows to EventBus floor with no listener. Per Phase 4 F16: "Phase 5+ may add a consumer when CC functionality re-enters scope" — but the bug-fix-queue's `/api/claude-code/dispatch` retirement (commit `73bee1b`) means CC infrastructure is being torn down, not rebuilt. Phase 6 maintains the punt.

- **Cross-tab BroadcastChannel features** — Q12 single-tab application policy ratified 2026-05-04 PM. Phase 6 maintains the policy; `broadcast.ts` stays inert.

- **Forced cutover from `/app/notifications`** — Q9 unbounded coexistence. Legacy page survives Phase 6 unchanged.

---

## Per-slice file naming

Following the existing R&D directory convention (`02-phase1-scaffolding-design.md`, `03-phase2-foundation-design.md`, etc.):

| Slice | Design doc | Review findings | Code-execution plan |
|---|---|---|---|
| 6a | `08-phase6a-jobs-surface-design.md` | `94-phase6a-review-findings.md` | `<date>-phase6a-code-execution-plan.md` |
| 6b | `09-phase6b-interactive-widgets-design.md` | `95-phase6b-review-findings.md` | `<date>-phase6b-code-execution-plan.md` |
| 6c | `10-phase6c-persona-focus-recorder-design.md` | `96-phase6c-review-findings.md` | `<date>-phase6c-code-execution-plan.md` |

---

## Acceptance for each slice

Inherit Phase 5's AC machinery patterns:
- AC1-AC10b: tsc, eslint, slice-specific grep guards, unit tests with per-file floors, c8 coverage ≥90%, gz boot.js delta ≤ +30 KB vs prior phase baseline (revisable per Q-I), smoke tests on `:7999` (AC8a functional + AC8b perf gate + AC9 boot_complete handshake), Phase 1/3/4/5 regression suites still green, CSS LOC ceiling per slice.
- AC11a + AC11b: scheduled `:8000` visual baseline via `POST /api/test-suite/submit` with `pytest_args="-k <slice>"` filter; deterministic-fixture pattern from Phase 5 spec drift §4-§5 baked in from the start.

`boot.js` ceiling per slice will be re-baselined from the prior slice's actual gz size, not Phase 4's frozen 24,325 byte literal. Each slice's design doc captures its own baseline + delta budget at design-time.

---

## Where this manifest lives in the cadence

This doc IS the slicing decision artifact. It does NOT replace per-slice design docs — those are the next deliverables. The manifest lets each slice's design doc focus on slice-internal concerns rather than re-litigating "which features land here vs there".

**Next step**: per-slice design doc for the FIRST slice the user wants to tackle. Recommended: 6a (jobs surface). User direction required.
