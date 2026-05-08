# Phase 6b — Interactive Widgets Design

**Date**: 2026-05-07
**Status**: Q-decisions ✅ CLOSED 2026-05-07 (12/12 ratified) — REUSE pre-pass ✅ CLOSED 2026-05-07 (28 RE-rows + 5 Layer-3 concerns ratified across 4 batched turns) — Pass 1 Fitness ⏸️ **DISPATCHED 2026-05-07; 14 findings produced; ratification PAUSED at user break point**. Resume pointer at `93-resume-here-phase6b-pass1-ratification.md`. Pass 2 Adversarial pending.
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

### Inertness-lift contract

When a renderer mounts a widget interactively, it removes ALL FOUR Phase 5 inertness markers atomically:
1. `data-phase6-pending="true"` attribute → removed
2. `aria-disabled="true"` attribute → removed
3. `style="cursor: not-allowed"` → cleared
4. `.action-required-pending-notice` child element → removed (innerHTML re-render or explicit `.remove()`)

Failure to strip any marker = test failure (AC2c grep guard, see AC table).

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
| Q-B3 ✅ Ratified 2026-05-07 | Optimistic UI vs wait-for-response | **Wait-for-response**: disable widget, show "Submitting…" microcopy, on-success transition to responded-historical state; on-rejection re-enable with error indicator. Renderer state machine: `pending` → `submitting` → `responded` \| `failed`. AC5 covers all three transitions. | Optimistic feels snappier but rollback adds renderer-state complexity for a non-latency-critical UX; `respond()` returns `Promise<void>` so the gate is clean. |
| Q-B4 ✅ Ratified 2026-05-07 | Error-recovery UX on `respond()` rejection | Re-enable widget + render **inline** error stripe (`.action-required-error-stripe`) reading `"Couldn't submit — try again"`; NO toast/snackbar dependency (none exists in multiplexer codebase, would be scope creep). NO auto-retry. Clearing-on-retry: next click clears stripe + transitions to `submitting`. | Auto-retry conflicts with user intent (they may have meant a different answer); inline-not-toast keeps Phase 6b dependency-free. Project-wide toast system can be added later as separate concern. |
| Q-B5 | Countdown-expiry behavior | Visual-only: countdown ticks to 0, widget transitions to "expired — default applied" state via store event; NO client-side auto-submit | Server is canonical for countdown expiry; client auto-submit risks double-submit on flaky networks |

### Cluster 2 — TTS chrome semantics

| # | Question | Proposed | Tradeoff |
|---|---|---|---|
| Q-B6 ✅ Ratified 2026-05-07 | TTS chrome surface | **BOTH surfaces in 6b**: (a) `#tts-pane` centralized chrome — queue rendering + pause/resume/stop/skip controls + current-track indicator; (b) per-notification corner buttons + state classes — `.notification-corner-pause-btn`, `.notification-corner-stop-btn`, `.tts-playing`, `.is-paused-current`. Only `.cc-voice-input` (audio recorder) stays 6c. | Self-audit during walkthrough caught that original draft incorrectly deferred corner buttons to 6c — slicing manifest line 46 explicitly includes them in 6b. Both surfaces share the same AudioStore subscription + control logic, just different render targets. |
| Q-B7 ✅ Ratified 2026-05-07 | Pause/resume/stop/skip control set | **Pane chrome**: 4 controls (Pause/Resume single toggle, Stop, Skip). **Per-notification corner**: 2 controls (Pause, Stop) — verbatim legacy. Skip is pane-only because per-notification skip is semantically ambiguous (this one? whole queue?). State-driven enable/disable per AudioPlaybackState (idle/decoding/playing/paused/ended/error) per table in design. | Pane-only Skip resolves the ambiguity (skip = "advance the queue", which lives where the queue renders); pause/resume as single toggle matches user mental model + legacy `notifications.js:11617`. |
| Q-B8 ✅ Ratified 2026-05-07 | Current-track indicator | **Two-part**: (a) port legacy `.is-playing-current` (`notifications.css:4692-4712`) + `.is-paused-current` (`4718-4725`) verbatim into `tts-chrome.css`; (b) pane chrome shows textual `<div class="tts-current-track">Playing: <track-name></div>` mapped to the notification whose audio is in flight. **Phase 0 prerequisite added**: verify `AudioStore` exposes `currentNotificationIdHash` (or equivalent linkage). If absent, CoSA-side prerequisite to extend `audio_chunk` events with the originating notification's id-hash, OR `AudioStore` maintains the linkage internally. | Verbatim CSS port preserves visual continuity; the AudioStore-linkage Phase-0 check is the third on the list (alongside `multiSelect` payload + `DELETE /api/queue/<bucket>/<id>`). |
| Q-B9 ✅ Ratified 2026-05-07 | AudioStore event subscriptions | Subscribe to BOTH `store_audio_state_change` (drives button-enable/disable + list-item state classes) AND `store_audio_chunk_decoded` (drives queue-length indicator on pane chrome). State changes pass through unthrottled; `chunk_decoded` is throttled (e.g., 100ms RAF debounce) per R2 to prevent DOM thrash on chunk-heavy playback. AC5b tests cover both subscription paths + throttling. | Slicing manifest line 47 specifies both events; throttling addresses chunk-storm risk without sacrificing state-change responsiveness. |

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
| AC2c | grep guard: ALL 4 inertness markers stripped atomically (one render → no partial state) | AI | none | unit test on renderer |
| AC2d (NEW per C-4) | grep guard + tsc check: `JobStore.prototype.delete(idHash)` exists | AI | none | `grep -nE 'delete\\s*\\(\\s*idHash' src/fastapi_app/static/js/multiplexer/stores/JobStore.ts` returns ≥1 + `npx tsc --noEmit` clean |
| AC3 | template tests `actionRequiredInteractive.ts` | AI | none | `vitest src/tests/unit/multiplexer/templates_action_required_interactive.test.ts` |
| AC4 | template tests `ttsChrome.ts` | AI | none | `vitest src/tests/unit/multiplexer/templates_tts_chrome.test.ts` |
| AC5 | renderer tests `ActionRequiredRenderer.ts` (≥18 cases — submit per response_type, error rollback, expiry, mount-idempotency) | AI | none | `vitest src/tests/unit/multiplexer/action_required_renderer.test.ts` |
| AC5b | renderer tests `TtsChromeRenderer.ts` (≥12 cases — state transitions, control wiring, queue-length) | AI | none | `vitest src/tests/unit/multiplexer/tts_chrome_renderer.test.ts` |
| AC5c (NEW per Q-B11) | renderer tests for `JobsPaneRenderer` delete-button extension (≥6 cases — 2xx, 404-as-success, 5xx rollback, network-err rollback, idempotency, no-op-on-non-delete-button) | AI | none | `vitest src/tests/unit/multiplexer/jobs_pane_renderer.test.ts` (extend existing) |
| AC6 | c8 100% lines/branches/functions/statements on ALL new TS files | AI | none | `npx c8 --100 vitest src/tests/unit/multiplexer/` |
| AC7 | gz `boot.js` ≤ 60382 + 6b delta budget (≤ +8 KB → 68382 B ceiling); re-baselined per slicing manifest line 110 | AI | none | bundle script |
| AC8a | functional smoke test | AI | none | `pytest src/tests/smoke/test_multiplexer_phase6b_smoke.py -v` |
| AC8b | perf gate (50 prompts < 200ms render) | AI | none | (smoke parameterized) |
| AC9 | boot_complete handshake — 4 stable lines (`notifications` + `jobs` + `actionRequired` + `ttsChrome` all `:mounted`) | AI | none | grep on smoke output |
| AC10 | Phase 1+3+4+5+6a regression sweeps green | AI | none | per-phase smoke + unit suites |
| AC10b | CSS LOC ceiling: `action-required.css` ≤500, `tts-chrome.css` ≤500 | AI | none | wc -l |
| AC10c | stylelint layer-2 `selector-disallowed-list [*, html, body, :root]` honored | AI | none | `npx stylelint src/fastapi_app/static/css/multiplexer/*.css` |
| AC10d | layer-3 CSS-canary: programmatically disable each new CSS file → prove ZERO body-style drift | AI | none | smoke parameterized |
| AC10e (NEW per C-5) | cross-phase count-cascade regression: re-run Phase 5 + Phase 6a `data-phase6-pending` count assertions with floor = 0 (post-6b lift) | AI | none | `pytest src/tests/smoke/test_multiplexer_phase5_smoke.py::test_data_phase6_pending_count + src/tests/smoke/test_multiplexer_phase6a_smoke.py -k pending_count` |
| AC11a | scheduled `:8000` visual baseline — `pytest_args="-k multiplexer_phase6b"` + `--update-snapshots` | AI | slot-coordination only | `POST /api/test-suite/submit` |
| AC11b | scheduled `:8000` visual regression — same filter, no `--update-snapshots`; pass: `e2e: 1 passed, 0 errors` | AI | slot-coordination only | `POST /api/test-suite/submit` |

**AC11 field-name reminders** (per `feedback_test_types_e2e_not_e2e_ui` + `feedback_test_suite_submit_field_pytest_args`):
- `test_types`: `"e2e"` (NEVER `"e2e_ui"`)
- pytest pass-through: `"pytest_args"` (NEVER `"args"`)

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

3. **`AudioStore` notification linkage** — verify `AudioStore` exposes `currentNotificationIdHash` (or equivalent linkage from a playing chunk to its originating notification). If absent, CoSA-side prerequisite to extend `audio_chunk` events with the originating notification's id-hash, OR `AudioStore` maintains the linkage internally. Per Q-B8 ratification.

4. **Action-required render mount surface** — verify where Phase 5 mounted the read-only action-required widget. The `boot.ts` snippet in this doc assumed `#action-required-pane`; if Phase 5 actually rendered widgets inline within `#notifications-pane` or elsewhere, `createActionRequiredRenderer` mounts there instead. Read `06-phase5-renderer-design.md` § Action-required template + grep `actionRequiredReadOnly` callers. Discovered during Q-B12 walkthrough.

5. **CoSA-side `multiplexer_config.py` commit** still pending (carries over from Phase 6a; not blocking 6b but worth flagging in the code-execution plan).

6. **`JobStore.delete(idHash)` method** (NEW per C-4) — verify the method exists in `src/fastapi_app/static/js/multiplexer/stores/JobStore.ts`. If absent, extend JobStore as a tightly-coupled sub-step within Phase 6b's Phase 4 (delete-button wiring): sub-step 4A adds the method + 100% c8 unit tests; sub-step 4B wires the click handler in `JobsPaneRenderer`. Verified empirically post-ratification — see `95-phase6b-review-findings.md` § "REUSE — closed" for the grep result.

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
