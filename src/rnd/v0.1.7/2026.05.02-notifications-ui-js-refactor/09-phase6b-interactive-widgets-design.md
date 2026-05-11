# Phase 6b — Interactive Widgets Design

**Date**: 2026-05-07
**Status**: Q-decisions ✅ CLOSED 2026-05-07 (12/12 ratified) — REUSE pre-pass ✅ CLOSED 2026-05-07 (28 RE-rows + 5 Layer-3 concerns ratified across 4 batched turns) — Pass 1 Fitness ✅ **CLOSED 2026-05-11** (14/14 ratified across 1 Minors batch + 8 individual Majors; all resolutions applied to this doc). Pass 2 Adversarial pending — gated on user go-ahead. Resume pointer at `93-resume-here-phase6b-pass1-ratification.md` is now historical.
**Slice owner**: Phase 6b (Phase 6a closed 2026-05-06; AC11a/AC11b verified 2026-05-07 — commits `362fa5d` → `243267b`)
**Naming convention**: per `07-phase6-slicing-manifest.md` line 99 — design doc `09-phase6b-interactive-widgets-design.md`, review findings `95-phase6b-review-findings.md`, code-execution plan `<date>-phase6b-code-execution-plan.md`

---

## Context

Phase 6b lifts inertness from the action-required widgets and the `#tts-pane`, attaches handlers, and wires the delete-button (`×`) handler that Phase 6a Q-A6 deferred ("Visual only in 6a, handler in 6b"). Phase 5 shipped the read-only scaffolds; Phase 4 shipped the `ActionRequiredStore` + `AudioStore` public APIs. This phase makes the widgets interactive without modifying any sub-feature out of scope (those go to 6c — voice-persona modal, focus tray, audio recorder).

**Inputs already on disk** (no new dependencies required):

| Input | Source | Phase |
|---|---|---|
| Read-only action-required widget DOM (`actionRequiredReadOnly.ts`) | `src/fastapi_app/static/js/multiplexer/render/templates/actionRequiredReadOnly.ts:43-69` | Phase 5 |
| `ActionRequiredStore.respond(idHash, response)` | `src/fastapi_app/static/js/multiplexer/stores/ActionRequiredStore.ts:113-119` | Phase 4 |
| `AudioStore` events `store_audio_state_change` + `store_audio_chunk_decoded` | `src/fastapi_app/static/js/multiplexer/stores/AudioStore.ts:109-119, 280-323` | Phase 4 |
| `AudioStore` controls `pause()` / `resume()` / `skip()` / `state()` / `queueLength()` | `AudioStore.ts:109-119` | Phase 4 |
| `#tts-pane` page-shell scaffold | `src/fastapi_app/static/html/multiplexer.html:42-44` | Phase 5 |
| Legacy TTS chrome (port target) | `src/fastapi_app/static/js/notifications.js:11617-11660` | Legacy reference |
| Deferred CSS classes | `notifications.css:4692-4712, 4718-4725` (per `06-phase5-renderer-design.md:114`) | Phase 5 deferral |
| Q-A6 (delete-button wire-up) | `08-phase6a-jobs-surface-design.md:366` (ratified 2026-05-05) | Phase 6a |
| Phase 6a renderer/factory pattern | `JobsPaneRenderer.ts` + `boot.ts` boot wiring | Phase 6a |

---

## Strategic design (overview)

### Module structure (proposed)

```
src/fastapi_app/static/js/multiplexer/render/
├── ActionRequiredRenderer.ts          (NEW — pane-level renderer for in-flight prompts)
├── TtsChromeRenderer.ts                (NEW — pane-level renderer for TTS playback chrome)
├── templates/
│   ├── actionRequiredInteractive.ts    (NEW — interactive variant of actionRequiredReadOnly)
│   └── ttsChrome.ts                    (NEW — pause/stop/track-indicator template)
└── index.ts                            (barrel — extend exports)

src/fastapi_app/static/css/multiplexer/
├── action-required.css                 (NEW — per-pane CSS, mirrors 6a `jobs-pane.css` pattern)
└── tts-chrome.css                      (NEW — per-pane CSS for TTS chrome)
```

### Boot wiring

Mirror Phase 6a pattern exactly. Add two factory calls to `boot.ts` after the existing `notificationsRenderer` + `jobsRenderer` mount lines:

```ts
const actionRequiredRenderer = createActionRequiredRenderer({
    container: document.querySelector('#action-required-pane'),
    stores: { actionRequired: actionRequiredStore },
    apiClient,
});
actionRequiredRenderer.mount();
console.log('[multiplexer] actionRequiredRenderer:mounted');

const ttsChromeRenderer = createTtsChromeRenderer({
    container: document.querySelector('#tts-pane'),
    stores: { audio: audioStore },
});
ttsChromeRenderer.mount();
console.log('[multiplexer] ttsChromeRenderer:mounted');
```

Extend `BootCompletePayload.handlers` with two new optional string keys: `actionRequiredRenderer?: string` and `ttsChromeRenderer?: string` (mirrors Phase 6a's `jobsRenderer?: string`).

**`mount()` is synchronous** (per Pass 1 F-12). Both `actionRequiredRenderer.mount()` and `ttsChromeRenderer.mount()` return `void`; the `console.log('[multiplexer] X:mounted')` lines execute synchronously after the DOM write. The boot-complete handshake fires after all four mount calls return — no `await`, no floating promise. AC9 grep guard verifies the four stable `:mounted` lines emit in observed order. If a future refactor wants async work inside mount, it must complete before the `:mounted` console.log line (the line is the AC9 contract).

### Inertness-lift contract (per Q-B2 + Pass 1 F-7)

The inertness-lift is conceptually a **template swap**, not a marker strip. Phase 5's `actionRequiredReadOnly.ts` rendered the widget WITH all 4 inertness markers. Phase 6b's `actionRequiredInteractive.ts` renders the widget WITHOUT them. At mount, the renderer replaces the widget's inner content via a single `innerHTML`/`replaceChildren` write per widget — the markers vanish because the new template never sets them.

**Mechanism (concrete)**:

```ts
mount(): void {
    const widgets = this.container.querySelectorAll<HTMLElement>("[data-action-required-id]");
    for (const widget of widgets) {
        const notification = this.stores.actionRequired.getByDomElement(widget);
        if (!notification) continue;
        // Single atomic write — children replaced in one tick, all 4 markers gone
        const interactiveDom = renderActionRequiredInteractive(notification, {
            onSubmit: (response) => this.handleSubmit(notification.idHash, response)
        });
        widget.replaceChildren(...interactiveDom.children);
    }
    console.log("[multiplexer] actionRequiredRenderer:mounted");
}
```

**Atomicity contract** (verified by AC2c MutationObserver assertion): exactly **1** `childList` mutation entry per widget; post-tick DOM contains NONE of the 4 markers:
1. `data-phase6-pending="true"` attribute — gone
2. `aria-disabled="true"` attribute — gone
3. `style="cursor: not-allowed"` — gone
4. `.action-required-pending-notice` child element — gone

**Post-mount updates use targeted mutations only**. After the initial mount, state changes (countdown tick, submitting state, error stripe, button enable/disable) MUST use targeted mutations (`element.classList.add/remove`, `textNode.data = ...`, `element.appendChild(...)`). NEVER `innerHTML = ...` on the widget post-mount — would destroy user-typed text in `<input>` elements + reset state. AC5 mount-idempotency case + the state-machine transition cases verify this contract.

### Q-B1 dispatch contract (per Pass 1 F-3)

Routing per response_type lives **inside** `actionRequiredInteractive.ts` as a single internal switch — mirrors Phase 5's `actionRequiredReadOnly.ts:71-109` precedent (REUSE row RE-28 ratified). Single exported render function; private helper builders per branch.

**Contract**:

```ts
// src/fastapi_app/static/js/multiplexer/render/templates/actionRequiredInteractive.ts
export function renderActionRequiredInteractive(
    notification: ActionRequiredNotification,
    handlers: { onSubmit: (response: unknown) => void }
): HTMLElement {
    switch (notification.response_type) {
        case "yes_no":            return buildYesNo(notification, handlers);
        case "multiple_choice":   return notification.multiSelect
                                      ? buildCheckbox(notification, handlers)
                                      : buildRadio(notification, handlers);
        case "open_ended":        return buildOpenEnded(notification, handlers);
        case "open_ended_batch":  return buildOpenEndedBatch(notification, handlers);
        default:                  throw new Error(`Unknown response_type: ${notification.response_type}`);
    }
}
```

The `build*` helpers are private functions in the same module. Tests cover them via the public `renderActionRequiredInteractive` function (black-box; counts toward AC5 and AC3 c8 100%).

### Delete-button (Q-A6 follow-through)

Per Q-A6 ratified text: "6b wires `DELETE /api/queue/<name>/<id>` handler. Mirrors Q-H two-phase rollout."

Click handler attaches in 6b's `JobsPaneRenderer` (NOT a new renderer — extends existing). Strips the `data-phase6-pending` from the `.job-delete-button` element + removes the `title="Delete coming in Phase 6b"` tooltip. Calls `apiClient.deleteJob(bucket, idHash)` → optimistic local store removal → rollback on rejection.

---

## Q-decisions — DRAFT (awaiting ratification)

12 decisions, batched into 4 clusters. Each row carries proposed answer + tradeoff. **Ratification gate runs via cosa-voice walkthrough** per Phase 6a precedent (`feedback_pip_plan_review_is_sequential`).

### Cluster 1 — Action-required submit semantics

| # | Question | Proposed | Tradeoff |
|---|---|---|---|
| Q-B1 ✅ Ratified 2026-05-07 | Submit pattern per `response_type` | `yes_no` → 2 buttons (Yes / No, direct on-click; decision UX); `multiple_choice` (`multiSelect: false`) → **radio group** + Submit; `multiple_choice` (`multiSelect: true`) → **checkbox group** + Submit; `open_ended` → text input + Submit (Enter-to-submit); `open_ended_batch` → per-question inputs + ONE Submit-All | Original draft proposed buttons-not-radios for `multiple_choice` — REJECTED 2026-05-07 by user: "use radios for exclusive selection and checkboxes for multi-select". Corrected mapping mirrors web-canonical form controls. **Phase 0 prerequisite**: verify the server `action_required` notification payload carries `multiSelect: bool` for `multiple_choice` type. If absent, it's a CoSA-side prerequisite (alongside the `DELETE /api/queue/<bucket>/<id>` check). |
| Q-B2 ✅ Ratified 2026-05-07 | Inertness-lift mechanism | Strip all 4 markers atomically on mount; one renderer call (not per-marker). The 4 markers: `data-phase6-pending`, `aria-disabled`, `cursor: not-allowed`, `.action-required-pending-notice` child. AC2c unit test verifies single-tick atomicity. | Atomic vs per-marker affects whether a partial-mount can leave an invariant-broken DOM; atomic is obviously safer (per-marker leaves windows where some assistive-tech sees enabled while sighted users see disabled cursor). |
| Q-B3 ✅ Ratified 2026-05-07 (+ Pass 1 F-4 amendment 2026-05-11) | Optimistic UI vs wait-for-response | **Wait-for-response**: disable widget, show "Submitting…" microcopy, on-success transition to responded-historical state; on-rejection re-enable with error indicator. **State machine** (extended by F-4 — see Q-B5 row for countdown vertices): `pending` → `submitting` → `responded` \| `failed`; PLUS `pending` → `expired_visual` → `responded_default` (client-only intermediate; server eventually emits default response). AC5 covers all five primary transitions + 2 expiry transitions. | Optimistic feels snappier but rollback adds renderer-state complexity for a non-latency-critical UX; `respond()` returns `Promise<void>` so the gate is clean. F-4 amendment: expired_visual is a client-side-only visual state; server is canonical for "default applied" determination via its normal response event. |
| Q-B4 ✅ Ratified 2026-05-07 | Error-recovery UX on `respond()` rejection | Re-enable widget + render **inline** error stripe (`.action-required-error-stripe`) reading `"Couldn't submit — try again"`; NO toast/snackbar dependency (none exists in multiplexer codebase, would be scope creep). NO auto-retry. Clearing-on-retry: next click clears stripe + transitions to `submitting`. | Auto-retry conflicts with user intent (they may have meant a different answer); inline-not-toast keeps Phase 6b dependency-free. Project-wide toast system can be added later as separate concern. |
| Q-B5 ✅ Ratified 2026-05-07 (+ Pass 1 F-4 amendment 2026-05-11) | Countdown-expiry behavior | **Local RAF-driven countdown reading notification.countdown_expires_at (ISO8601)**; renderer computes remaining time via `new Date(...) - Date.now()`; RAF-driven visible digit with text-node updates throttled to 1/sec. When local clock crosses expires_at → renderer transitions widget to `expired_visual` state (all controls disabled + aria-disabled; submit area swapped for `<div class="action-required-expired" aria-live="polite">Expired — default applied</div>`; widget chrome retained). NO client auto-submit. Server is canonical: server eventually emits a normal `notification` update with `response: <default>` + `responded_by: "server-default"` → Phase 4 ActionRequiredStore reduces it as a "responded" transition → renderer transitions `expired_visual` → `responded_default` (rendered like `responded` plus "(default applied)" tag). Clock-skew tolerant: if client transitions to `expired_visual` before server records default, server's eventual response event reconciles. | Server is canonical for countdown expiry; client auto-submit risks double-submit on flaky networks. F-4 amendment: client-side timer is best-effort UI only; `expired_visual` is a client-only intermediate state that resolves via the server's normal response channel — no new store events needed for the tick. |

### Cluster 2 — TTS chrome semantics

| # | Question | Proposed | Tradeoff |
|---|---|---|---|
| Q-B6 ✅ Ratified 2026-05-07 | TTS chrome surface | **BOTH surfaces in 6b**: (a) `#tts-pane` centralized chrome — queue rendering + pause/resume/stop/skip controls + current-track indicator; (b) per-notification corner buttons + state classes — `.notification-corner-pause-btn`, `.notification-corner-stop-btn`, `.tts-playing`, `.is-paused-current`. Only `.cc-voice-input` (audio recorder) stays 6c. | Self-audit during walkthrough caught that original draft incorrectly deferred corner buttons to 6c — slicing manifest line 46 explicitly includes them in 6b. Both surfaces share the same AudioStore subscription + control logic, just different render targets. |
| Q-B7 ✅ Ratified 2026-05-07 | Pause/resume/stop/skip control set | **Pane chrome**: 4 controls (Pause/Resume single toggle, Stop, Skip). **Per-notification corner**: 2 controls (Pause, Stop) — verbatim legacy. Skip is pane-only because per-notification skip is semantically ambiguous (this one? whole queue?). State-driven enable/disable per AudioPlaybackState (idle/decoding/playing/paused/ended/error) per table in design. | Pane-only Skip resolves the ambiguity (skip = "advance the queue", which lives where the queue renders); pause/resume as single toggle matches user mental model + legacy `notifications.js:11617`. |
| Q-B8 ✅ Ratified 2026-05-07 | Current-track indicator | **Two-part**: (a) port legacy `.is-playing-current` (`notifications.css:4692-4712`) + `.is-paused-current` (`4718-4725`) verbatim into `tts-chrome.css`; (b) pane chrome shows textual `<div class="tts-current-track">Playing: <track-name></div>` mapped to the notification whose audio is in flight. **Phase 0 prerequisite added**: verify `AudioStore` exposes `currentNotificationIdHash` (or equivalent linkage). If absent, CoSA-side prerequisite to extend `audio_chunk` events with the originating notification's id-hash, OR `AudioStore` maintains the linkage internally. | Verbatim CSS port preserves visual continuity; the AudioStore-linkage Phase-0 check is the third on the list (alongside `multiSelect` payload + `DELETE /api/queue/<bucket>/<id>`). |
| Q-B9 ✅ Ratified 2026-05-07 (+ Pass 1 F-10 + F-13 amendment 2026-05-11) | AudioStore event subscriptions | Subscribe to BOTH `store_audio_state_change` AND `store_audio_chunk_decoded`. **Throttling lives renderer-side** (per F-10) — store stays semantically pure (emits every event; other future subscribers see full stream). **Both events RAF-coalesced** (per F-13 — symmetric design): max 1 render per animation frame (≤16ms latency), latest event wins. Implementation uses a `pendingRender = false` flag + `requestAnimationFrame` schedule on first event; subsequent events within the same frame are absorbed. AC5b tests cover both subscription paths + storm-safety: (a) chunk_decoded storm — 100 events synchronously → ≤1 DOM mutation cycle; (b) state_change storm — 5 transitions synchronously → ≤1 DOM mutation cycle. | Slicing manifest line 47 specifies both events. F-10 amendment: renderer-side throttling preserves store purity. F-13 amendment: state-change events ALSO storm under scrub/flaky-network/queue-advance bursts (per-card state classes × N widgets) — needs symmetric coalescing, NOT a fixed 100ms throttle (would lag user clicks). |

### Cluster 3 — Delete button (Q-A6 follow-through)

| # | Question | Proposed | Tradeoff |
|---|---|---|---|
| Q-B10 ✅ Ratified 2026-05-07 | Delete UX | **Optimistic + rollback, no modal**: click → `JobStore.delete(idHash)` removes locally → `DELETE /api/queue/<bucket>/<id>` → 2xx no-op, 404 treated as success ("already gone"), 5xx + network-err ROLLBACK via `JobStore.upsert(prevState)` + inline error stripe on restored card. Click handler extends existing `JobsPaneRenderer` (NOT a new renderer); strips `data-phase6-pending` + `aria-disabled` + `cursor: not-allowed` + the Q-A6 tooltip. | Modal adds friction for low-stakes deletion; optimistic feels native to fast list management; 404-as-success handles delete-race with server-side retention sweeps. |

### Cluster 4 — Boot, CSS, scope

| # | Question | Proposed | Tradeoff |
|---|---|---|---|
| Q-B11 ✅ Ratified 2026-05-07 | Renderer factory + boot pattern | Two NEW factories: `createActionRequiredRenderer({container, stores, apiClient})` + `createTtsChromeRenderer({container, stores})`. Both mirror Phase 6a's `createJobsPaneRenderer` signature. `BootCompletePayload.handlers` extends with `actionRequiredRenderer?: string` + `ttsChromeRenderer?: string`. AC9 grep guard checks for FOUR stable boot lines (notifications + jobs + actionRequired + ttsChrome). Q-A6 delete-button extends `JobsPaneRenderer` via single click-delegation, NOT a new renderer. AC5c (NEW) covers delete-button extension (≥6 cases). | Mirroring Phase 6a keeps cognitive load low; click-delegation on existing renderer avoids spawning a third new renderer for a one-handler concern. |
| Q-B12 ✅ Ratified 2026-05-07 | CSS port — file scope + LOC budget | Two NEW per-pane CSS files: `action-required.css` (≤500 LOC) + `tts-chrome.css` (**≤700 LOC** — bumped from 500 because Q-B6 expanded scope to BOTH pane chrome AND per-notification corner buttons + list-item state classes). Mirror Phase 6a per-pane pattern; `<link>` injections in `multiplexer.html`; stylelint layer-2 + canary AC10d cover both. Phase 6a's `jobs-pane.css` shipped at 324 LOC for reference. | Per-pane keeps blast radius reviewable; `tts-chrome.css` ceiling bumped after Q-B6 scope expansion. |

### Out-of-scope confirmation (carry forward from slicing manifest)

- Voice-persona modal → Phase 6c
- Focus tray + focus-mode toggle → Phase 6c
- Sender-card audio recorder (`MediaRecorder` API + `.cc-voice-input`) → Phase 6c
- `claude_code_event` consumer → permanently out (D1 A-extended)
- Cross-tab BroadcastChannel → permanently out (Q12)

---

## Acceptance criteria (DRAFT)

Inherits AC1-AC10b machinery from Phase 5 + Phase 6a. AC11a/AC11b scheduled `:8000` per slicing manifest line 108. **All multiplexer TS files at c8 100%** per the 100% coverage mandate (`feedback_100pct_coverage_multiplexer`).

| AC | Test | Executor | Human gate | Command |
|---|---|---|---|---|
| AC1 | tsc clean | AI | none | `npx tsc --noEmit` |
| AC2 | eslint clean | AI | none | `npx eslint src/fastapi_app/static/js/multiplexer/` |
| AC2a | grep guard: NO `data-phase6-pending` in DOM after mount | AI | none | `pytest src/tests/smoke/test_multiplexer_phase6b_smoke.py::test_no_pending_markers_after_mount` |
| AC2b | grep guard: NO `aria-disabled="true"` on action-required-widget post-mount | AI | none | (smoke test above, parameterized) |
| AC2c (rewritten per Pass 1 F-7) | unit test: ActionRequiredRenderer.mount() produces exactly 1 MutationObserver `childList` entry per action-required widget; post-tick DOM contains NONE of the 4 inertness markers (`data-phase6-pending`, `aria-disabled`, `cursor: not-allowed`, `.action-required-pending-notice`) | AI | none | `vitest src/tests/unit/multiplexer/action_required_renderer.test.ts` |
| AC2d (NEW per C-4 + rewritten per Pass 1 F-5) | unit test asserts JobStore exposes public `delete(idHash): { restoreState: () => void }` + tsc check confirms type signature | AI | none | `vitest src/tests/unit/multiplexer/jobstore_delete_api.test.ts` + `npx tsc --noEmit` clean |
| AC3 | template tests `actionRequiredInteractive.ts` | AI | none | `vitest src/tests/unit/multiplexer/templates_action_required_interactive.test.ts` |
| AC4 | template tests `ttsChrome.ts` | AI | none | `vitest src/tests/unit/multiplexer/templates_tts_chrome.test.ts` |
| AC5 (enumerated per Pass 1 F-2) | renderer tests `ActionRequiredRenderer.ts` (≥18 cases — see § AC5 case enumeration sub-table below for full breakdown across submit-happy-path × 5 response_types + error-rollback × 5 + state-machine transitions × 6 + countdown expiry + mount-idempotency + inertness-lift atomic strip + inline error stripe render) | AI | none | `vitest src/tests/unit/multiplexer/action_required_renderer.test.ts` |
| AC5b (enumerated per Pass 1 F-9 + F-13) | renderer tests `TtsChromeRenderer.ts` (≥12 cases — see § AC5b case enumeration sub-table below: 7 state transitions + 4 control-wiring + 2 storm-safety assertions) | AI | none | `vitest src/tests/unit/multiplexer/tts_chrome_renderer.test.ts` |
| AC5c (NEW per Q-B11) | renderer tests for `JobsPaneRenderer` delete-button extension (≥6 cases — 2xx, 404-as-success, 5xx rollback, network-err rollback, idempotency, no-op-on-non-delete-button) | AI | none | `vitest src/tests/unit/multiplexer/jobs_pane_renderer.test.ts` (extend existing) |
| AC6 | c8 100% lines/branches/functions/statements on ALL new TS files | AI | none | `npx c8 --100 vitest src/tests/unit/multiplexer/` |
| AC7 (re-baselined per Pass 1 F-8) | **Pre-implementation step**: capture `gz boot.js` size at HEAD `243267b` (Phase 6a closed) → record as post-6a baseline `B6a` in this doc + 6a execution log. **6b ceiling** = `B6a + 8 KB` (gz). The previously-cited `60382` was the pre-6a baseline and is invalid for 6b delta verification. | AI | none | bundle script + grep for recorded `B6a` value in this doc |
| AC8a | functional smoke test | AI | none | `pytest src/tests/smoke/test_multiplexer_phase6b_smoke.py -v` |
| AC8b | perf gate (50 prompts < 200ms render) | AI | none | (smoke parameterized) |
| AC9 | boot_complete handshake — 4 stable lines (`notifications` + `jobs` + `actionRequired` + `ttsChrome` all `:mounted`) | AI | none | grep on smoke output |
| AC10 | Phase 1+3+4+5+6a regression sweeps green | AI | none | per-phase smoke + unit suites |
| AC10b (corrected per Pass 1 F-1) | CSS LOC ceiling: `action-required.css` ≤500, `tts-chrome.css` ≤700 (per Q-B12 — bumped from 500 due to Q-B6 scope expansion to both pane chrome + per-notification corner buttons) | AI | none | wc -l |
| AC10c | stylelint layer-2 `selector-disallowed-list [*, html, body, :root]` honored | AI | none | `npx stylelint src/fastapi_app/static/css/multiplexer/*.css` |
| AC10d | layer-3 CSS-canary: programmatically disable each new CSS file → prove ZERO body-style drift | AI | none | smoke parameterized |
| AC10e (NEW per C-5 + corrected per Pass 1 F-14) | cross-phase count-cascade regression: re-run Phase 5 + Phase 6a `data-phase6-pending` count assertions with floor = 0 (post-6b lift). Both phases use `pending_count` substring in their assertion test names; verify substring matches both files before commit. | AI | none | `pytest src/tests/smoke/test_multiplexer_phase5_smoke.py src/tests/smoke/test_multiplexer_phase6a_smoke.py -k "pending_count"` |
| AC11a | scheduled `:8000` visual baseline — `pytest_args="-k multiplexer_phase6b"` + `--update-snapshots` | AI | slot-coordination only | `POST /api/test-suite/submit` |
| AC11b | scheduled `:8000` visual regression — same filter, no `--update-snapshots`; pass: `e2e: 1 passed, 0 errors` | AI | slot-coordination only | `POST /api/test-suite/submit` |

**AC11 field-name reminders** (per `feedback_test_types_e2e_not_e2e_ui` + `feedback_test_suite_submit_field_pytest_args`):
- `test_types`: `"e2e"` (NEVER `"e2e_ui"`)
- pytest pass-through: `"pytest_args"` (NEVER `"args"`)

### AC5 case enumeration (per Pass 1 F-2)

`ActionRequiredRenderer.ts` unit tests — ≥18 cases. Each implementer must cover every cluster's enumerated cases at minimum; extras encouraged.

| Cluster | Count | Cases |
|---|---|---|
| **Submit happy-path per response_type** (Q-B1) | 6 | (a) `yes_no` — Yes button → `respond("yes")`; (b) `yes_no` — No button → `respond("no")`; (c) `multiple_choice` multiSelect=false — radio select → Submit → `respond(label)`; (d) `multiple_choice` multiSelect=true — checkbox set → Submit → `respond([labels])`; (e) `open_ended` — text input + Enter → `respond(text)`; (f) `open_ended_batch` — per-question inputs + Submit-All → `respond({header: value, ...})` |
| **Error rollback per response_type** (Q-B4) | 5 | each of (a-e above) with `respond()` rejecting → inline error stripe renders + widget re-enables |
| **State machine transitions** (Q-B3 + Pass 1 F-4 amendment) | 6 | `pending→submitting` (on click); `submitting→responded` (on resolve); `submitting→failed` (on reject); `failed→submitting` (retry click clears stripe); `pending→expired_visual` (local timer crosses `expires_at`); `expired_visual→responded_default` (server emits default response event) |
| **Countdown expiry behavior** (Q-B5) | 1 | local RAF timer reaches 0 → `expired_visual` state visual contract (all controls disabled; submit area swapped for `Expired — default applied`); NO client auto-submit asserted |
| **Mount idempotency** | 1 | `renderer.mount()` called twice → second call is no-op (no duplicate event listeners; assert single dispatch on subsequent click) |
| **Inertness-lift atomic strip** (Q-B2 + Pass 1 F-7 integration view) | 1 | mount() removes all 4 markers via `replaceChildren` template swap (verified via MutationObserver count = 1) |
| **Inline error stripe render** (Q-B4 render view) | 1 | `respond()` reject → `.action-required-error-stripe` appears with correct copy + `aria-live="polite"` |

**Subtotal**: 21. Floor ≥18 met with margin. AC5 wording stays "≥18" so future additions don't trip the AC.

### AC5b case enumeration (per Pass 1 F-9 + F-13)

`TtsChromeRenderer.ts` unit tests — ≥12 cases.

| Cluster | Count | Cases |
|---|---|---|
| **State transitions** | 7 | `idle→decoding`; `decoding→playing`; `playing→paused`; `paused→playing`; `playing→ended`; `ended→idle`; `any→error` |
| **Control wiring** | 4 | pause toggle dispatches `AudioStore.pause()`; resume toggle dispatches `AudioStore.resume()`; stop dispatches stop intent; skip dispatches `AudioStore.skip()` (pane-only — Q-B7) |
| **Storm safety** (Q-B9 + Pass 1 F-13) | 2 | (a) `store_audio_chunk_decoded` storm — 100 events fired synchronously within one frame → ≤1 DOM mutation cycle; (b) `store_audio_state_change` storm — 5 state transitions fired synchronously within one frame → ≤1 DOM mutation cycle |

**Subtotal**: 13. Floor ≥12 met with margin. AC5b wording stays "≥12".

---

## Test pyramid

| Tier | Tests | Files | Target count |
|---|---|---|---|
| Unit (templates) | actionRequiredInteractive + ttsChrome | 2 NEW | ≥30 combined |
| Unit (renderers) | ActionRequiredRenderer + TtsChromeRenderer | 2 NEW | ≥30 combined |
| Smoke (functional + perf + AC9 + AC10d) | test_multiplexer_phase6b_smoke.py | 1 NEW | ≥5 |
| E2E (visual) | test_multiplexer_phase6b_visual.py | 1 NEW | 1 (AC11a/AC11b) |

Existing Phase 6a smoke test (`test_multiplexer_phase6a_smoke.py`) remains untouched — Phase 6b is additive.

---

## Plan-review pipeline

Strict sequential per `feedback_pip_plan_review_is_sequential`:

1. **Q-decision walkthrough** (this gate) — cosa-voice ratification of all 12 Q-B decisions
2. **Apply Q-decision corrections** (if any) → design doc updated to reflect ratified decisions
3. **REUSE pre-pass** — Explore agent, clean context, walks the proposed module structure against existing multiplexer codebase; produces RE-N rows for each proposed component (reuse-as-is / extend-existing / genuinely-new); user gate to ratify
4. **Apply REUSE dispositions** → design doc § "Prior art referenced" appended
5. **Pass 1 Fitness** — Explore agent, clean context, sees REUSE-resolved doc state; produces F-N findings; user gate to ratify
6. **Apply Pass 1 corrections** → design doc updated; "Pass 1 Fitness — closed" subsection appended to `95-phase6b-review-findings.md`
7. **Pass 2 Adversarial** — Explore agent, clean context, sees Pass-1-resolved doc state; produces F-N findings (different cluster — security, DOS, race, contract-drift); user gate to ratify
8. **Apply Pass 2 corrections** → convergence re-grep clean → "Pass 2 Adversarial — closed" subsection appended
9. **Code-execution plan** — `<date>-phase6b-code-execution-plan.md` (NEW) — per-phase progress table + AC scorecard + commit-chain table
10. **Implementation** — Phase 0 (tracking docs) → Phase 1 (interactive widget templates) → Phase 2 (action-required renderer) → Phase 3 (TTS chrome renderer) → Phase 4 (delete-button wiring on JobsPaneRenderer) → Phase 5 (CSS port) → Phase 6 (smoke + cross-phase regression on `:7999`) → Phase 7 (E2E test authored; AC11a/AC11b scheduled-`:8000`)

---

## Risks + mitigations

| # | Risk | Mitigation |
|---|---|---|
| R1 | `respond()` rejection cascade — repeated user-clicks during a flaky network → multiple submits | Disable widget on first click; only re-enable after either resolved or rejected |
| R2 | AudioStore event-storm during chunk-heavy playback (1 chunk → 1 event) → renderer thrashes | Debounce queue-length update (e.g., 100ms throttle); state changes pass through unthrottled |
| R3 | DELETE rollback UX — server says 404 (job already gone) → optimistic delete confused with real removal | Treat 404 as "already deleted" success path; only 5xx rolls back |
| R4 | Phase 5 inertness markers split across attribute + style + child element → easy to leave one stale | AC2c covers atomic-strip; one renderer call = one DOM mutation point |
| R5 | Q-A6 delete-button on jobs-pane lives in 6a renderer — 6b mutates 6a code | Keep change minimal: extend `JobsPaneRenderer` with one new event handler; do NOT refactor; covered by AC2/AC10 regression |
| R6 | Legacy `notifications.css:4692-4712` rules carry !important / specificity hacks that break in multiplexer scope | CSS port reviews each rule individually during Phase 5 (CSS port subphase); fall back to authoring fresh rules if a port doesn't lift cleanly |
| R7 (NEW per Pass 1 F-13) | `store_audio_state_change` storm during seek/scrub, flaky-network buffering, or queue advance — per-card state classes × N widgets → thrashing DOM (R2 covered chunk_decoded only) | Renderer-side RAF coalescing on state-change rendering (symmetric to R2 chunk_decoded throttle): at most 1 render per animation frame regardless of event burst size; latest state wins. AC5b storm-safety case (b) asserts 5 synchronous state changes → ≤1 DOM mutation cycle |

---

## Critical files

### NEW (this phase)

- `src/fastapi_app/static/js/multiplexer/render/ActionRequiredRenderer.ts`
- `src/fastapi_app/static/js/multiplexer/render/TtsChromeRenderer.ts`
- `src/fastapi_app/static/js/multiplexer/render/templates/actionRequiredInteractive.ts`
- `src/fastapi_app/static/js/multiplexer/render/templates/ttsChrome.ts`
- `src/fastapi_app/static/css/multiplexer/action-required.css`
- `src/fastapi_app/static/css/multiplexer/tts-chrome.css`
- `src/tests/unit/multiplexer/templates_action_required_interactive.test.ts`
- `src/tests/unit/multiplexer/templates_tts_chrome.test.ts`
- `src/tests/unit/multiplexer/action_required_renderer.test.ts`
- `src/tests/unit/multiplexer/tts_chrome_renderer.test.ts`
- `src/tests/smoke/test_multiplexer_phase6b_smoke.py`
- `src/tests/e2e_ui/test_multiplexer_phase6b_visual.py`
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/95-phase6b-review-findings.md`
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/<date>-phase6b-code-execution-plan.md`

### Edited (this phase)

- `src/fastapi_app/static/js/multiplexer/boot.ts` — two factory mounts + AC9 stable lines
- `src/fastapi_app/static/js/multiplexer/render/index.ts` — barrel exports for both new renderers
- `src/fastapi_app/static/js/multiplexer/shared/types.ts` — extend `BootCompletePayload.handlers` with two new optional keys
- `src/fastapi_app/static/js/multiplexer/render/JobsPaneRenderer.ts` — extend with delete-button click handler (Q-A6 follow-through)
- `src/fastapi_app/static/html/multiplexer.html` — add `<link>` for both new CSS files; lift `data-phase6-pending` from `#tts-pane` (line 44) post-mount via renderer
- `src/cosa/rest/routers/queues.py` — verify `DELETE /api/queue/<bucket>/<id>` exists with correct shape (CoSA-side); if not present, this phase blocks pending CoSA addition
- `src/docs/rest-api-reference.md` — DELETE endpoint row (if newly added)

---

## Open prerequisites BEFORE Phase 6b implementation begins

All Phase 0 verification checks. Run BEFORE Phase 6b code-writing begins.

1. **`DELETE /api/queue/<bucket>/<id>` endpoint** — verify exists in CoSA. If not, file a CoSA-context task to add it BEFORE Phase 6b implementation Phase 4 (delete-button wiring). Per Q-B10 ratification.

2. **`action_required` payload `multiSelect` flag** — verify the server `action_required` notification carries `multiSelect: bool` for `multiple_choice` type. The renderer needs this to route to radios vs checkboxes. If absent, it's a CoSA-side prerequisite (server-side payload extension). Per Q-B1 ratification.

3. **`AudioStore` notification linkage** (target API shape per Pass 1 F-11) — verify `AudioStore` exposes the linkage from a playing chunk to its originating notification. **Preferred contract**: `AudioStore.currentNotificationIdHash(): string | null` (synchronous getter; returns `null` when idle). **Acceptable alternative**: event payload field `notificationIdHash: string | null` on `store_audio_state_change` (renderer reads on every state change). If neither exists, CoSA-side prerequisite to extend the chunk events with the originating notification's id-hash OR add the getter to `AudioStore`. Phase 0 verification: grep for the chosen shape + tsc clean. Per Q-B8 ratification.

4. **Action-required render mount surface** — verify where Phase 5 mounted the read-only action-required widget. The `boot.ts` snippet in this doc assumed `#action-required-pane`; if Phase 5 actually rendered widgets inline within `#notifications-pane` or elsewhere, `createActionRequiredRenderer` mounts there instead. Read `06-phase5-renderer-design.md` § Action-required template + grep `actionRequiredReadOnly` callers. Discovered during Q-B12 walkthrough.

5. **CoSA-side `multiplexer_config.py` commit** still pending (carries over from Phase 6a; not blocking 6b but worth flagging in the code-execution plan).

6. **`JobStore.delete(idHash)` method** (NEW per C-4 + DOD per Pass 1 F-6) — **verified MISSING 2026-05-07** (grep on `JobStore.ts` returned only `this.indexById.delete(id)` internal Map call at line 292). **Phase 6b implementation Phase 4 splits into**:
   - **sub-step 4A** — extend `JobStore` with `public delete(idHash: string): { restoreState: () => void }` returning a rollback closure (signature in § Phase 4 sub-step DOD below); add AC2d unit tests (≥3 cases enumerated in F-6 ratification: exposes method, removes entry + emits event, no-op on nonexistent); c8 100% on the new method
   - **sub-step 4B** — wire the click handler in `JobsPaneRenderer` consuming the `restoreState` closure for Q-B10 rollback; AC5c (≥6 cases); strip Q-A6 inertness markers; c8 100% on the renderer delta
   - **Ordering**: natural compile-time gate (4B's tests import `JobStore.delete` → `tsc --noEmit` fails 4B without 4A). The code-execution plan tracks 4A → 4B as separate progress-table rows; split-commit preferred for reviewability
   - DOD tables per sub-step appear in new § Phase 4 sub-step DOD subsection below

7. **`action_required` payload `countdown_expires_at` field** (NEW per Pass 1 F-4) — verify the server `action_required` notification carries `countdown_expires_at: ISO8601 string | null` (set when expiry is configured; null when not). The Phase 6b renderer uses this field to drive the local RAF-based countdown + `expired_visual` transition per Q-B5 ratification. If absent, CoSA-side prerequisite to extend the notification payload before Phase 6b implementation Phase 2 (ActionRequiredRenderer). Verification: grep server-side payload construction + integration smoke check that the field appears in a captured `action_required` notification.

---

## Phase 4 sub-step DOD (per Pass 1 F-6)

Phase 6b's implementation Phase 4 (delete-button wiring) splits into two tightly-coupled sub-steps. Each has an explicit DOD; 4B's tests transitively require 4A's API → `tsc` enforces the ordering.

### `JobStore.delete` signature (4A produces)

```ts
public delete(idHash: string): { restoreState: () => void } {
    const previous = this.indexById.get(idHash);
    if (!previous) {
        return { restoreState: () => {} };  // no-op rollback
    }
    this.indexById.delete(idHash);
    this.emit("store_jobs_changed", { changeKind: "removed", idHash });
    return {
        restoreState: () => {
            this.indexById.set(idHash, previous);
            this.emit("store_jobs_changed", { changeKind: "added", idHash });
        }
    };
}
```

### Sub-step 4A — DOD (extend JobStore + AC2d tests)

| # | Check | Pass criterion |
|---|---|---|
| 4A-1 | Method exists on `JobStore.prototype` | `typeof store.delete === "function"` |
| 4A-2 | Method removes entry on hit | `getById(idHash)` returns `undefined` post-`delete()` |
| 4A-3 | Method emits `store_jobs_changed` with `changeKind="removed"` | event subscriber receives correct payload |
| 4A-4 | `restoreState()` re-inserts identical previous state | round-trip `getById()` returns deep-equal entry |
| 4A-5 | `restoreState()` emits `changeKind="added"` | event subscriber receives correct payload |
| 4A-6 | Nonexistent idHash → no-op + no-op `restoreState` | no exception, no event emission |
| 4A-7 | c8 100% on `delete()` + closure | `c8 --100` clean on `JobStore.ts` |
| 4A-8 | AC2d test file exists + passes | `vitest jobstore_delete_api.test.ts` green |

**4A is complete when all 8 rows pass.**

### Sub-step 4B — DOD (wire delete-button in JobsPaneRenderer)

| # | Check | Pass criterion |
|---|---|---|
| 4B-1 | `JobsPaneRenderer` click delegation handles `.job-delete-button` | unit test asserts handler attached |
| 4B-2 | Click calls `JobStore.delete(idHash)` + captures `restoreState` closure | spy on `delete` returns closure |
| 4B-3 | 2xx response → closure discarded; no rollback | assert `restoreState` NOT called |
| 4B-4 | 404 response → treated as success per Q-B10 | same as 2xx |
| 4B-5 | 5xx response → `restoreState()` invoked + inline error stripe rendered | assert `restoreState` called + DOM has stripe |
| 4B-6 | Network error → same as 5xx | same |
| 4B-7 | Idempotency — rapid double-click → only first emits `delete` | spy call count = 1 |
| 4B-8 | Non-delete-button clicks within row → handler is no-op | spy call count = 0 |
| 4B-9 | Q-A6 inertness markers stripped from `.job-delete-button` (4 markers) | querySelector returns null for each marker |
| 4B-10 | c8 100% on `JobsPaneRenderer.ts` delta | `c8 --100` clean on the file |
| 4B-11 | AC5c (≥6 cases) green | `vitest jobs_pane_renderer.test.ts` green |

**4B is complete when all 11 rows pass.**

### Commit chain

Preferred: 4A and 4B ship as **two separate commits** in the same PR — 4A first (JobStore.delete + AC2d tests), 4B second (renderer extension + AC5c tests). Single combined commit acceptable if both DODs are met, but split-commit gives reviewers focal points per concern.

---

## Prior art referenced (REUSE pre-pass — closed 2026-05-07)

Full RE-row table + Layer-3 concern resolutions live in `95-phase6b-review-findings.md` § "REUSE Pre-Pass — Findings". Summary applied to this design:

| RE category | Count | Outcome |
|---|---|---|
| reuse-as-is | 16 | Existing Phase 5 + 6a patterns directly applicable (lifecycle, factory signatures, store consumption, test patterns) |
| extend-existing | 9 | Extend Phase 5 + 6a patterns with new parameters or handlers (boot wiring, BootCompletePayload extension, CSS link tags, response-type dispatch, inertness-lift contract) |
| genuinely-new | 3 | Greenfield: `actionRequiredInteractive.ts` template, `ttsChrome.ts` template, `action-required.css` (interactive Phase 6b had no prior precedent) — plus the wait-for-response state machine (Q-B3) and inline error stripe (Q-B4) cross-cutting patterns |

| Layer-3 concern | Resolution applied |
|---|---|
| C-1 mount-point ambiguity | Confirmed Phase 0 prerequisite #4 |
| C-2 `multiSelect` flag | Confirmed Phase 0 prerequisite #2 |
| C-3 AudioStore notification linkage | Confirmed Phase 0 prerequisite #3 |
| C-4 `JobStore.delete(idHash)` missing | **Confirmed empirically 2026-05-07**: grep on `JobStore.ts` returned only `this.indexById.delete(id)` (internal Map call at line 292). No public method. → Phase 0 prerequisite #6 added; AC2d added (grep + tsc guard); Phase 6b code-execution Phase 4 splits into sub-step 4A (extend JobStore) + 4B (wire handler) |
| C-5 count-cascade drift | AC10e added (re-run Phase 5 + 6a count assertions with floor = 0) |

**Convergence re-grep**: all 28 RE-rows have ratified dispositions; no proposed component lacks a Prior-art entry. Pass 1 Fitness next.

---

## Out-of-cycle items (NOT addressed by this design doc)

- Pre-existing failures in `src/tests/e2e_ui/test_cc_session_strip_and_focus.py` — explicitly skipped per user direction 2026-05-07 ("no point fixing the legacy app").
- Phase 6a CoSA-side endpoint commit — separate CoSA-context session.
- `history.md` archival — deferred while parallel session has uncommitted history.md edits.
