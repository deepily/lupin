# Q&A Interface — Build Plan (accordion #1, TRULY ABSENT → build)

**Date**: 2026-06-26 (this session, for Rick)
**Status**: 🟡 DRAFT for the cascaded review (run on Rick's dev server).
**Author**: research/planning pass (absent-accordion lane).
**Source audit refs**: doc `04-remaining-accordions-audit.md` §"#1 Q&A Interface" (lines 79-83) + master verdict row 1 (line 21).
**Decision-of-record refs**: doc `04` §Resolved ruling **(g)** — "Port ALL 7 absent accordions → total 13/13 parity … No 'obsolete' drops — strict total parity." This plan executes (g) for #1.
**Inherits** all 7 cross-cutting mandates from `00-plans-index.md §"Cross-cutting mandates"` — not restated here.

---

## 1. Goal & parity target

Restore the legacy **Q&A Interface** accordion in the multiplexer: the primary text/voice entry point for
submitting a question to Lupin. "Done" = a `#qa-pane` section that reproduces the legacy DOM contract /
styling of `notifications.html:83-143` — an **Agent-Mode selector** (System auto-route + Quick-Agents /
Agentic-Processes optgroups) with mode badge + status text, a **mic (STT) button + text input + TTS-mode
selector + Submit** row, a **TTT/TTFA/RTT metrics** strip, and a **response area** — wired into the
section-toolbar as the 7th toggle, submitting via the same `/api/push` endpoint and driving server mode
via `/api/mode/current`, using the mux-native `recordingManager` for voice input.

## 2. Scope

The ratified ruling this executes: **(g)** total 13/13 parity — no obsolete drops.

**IN**

- New `#qa-pane` section in `multiplexer.html` reproducing the legacy structure (legacy class names —
  `.agent-mode-select`, `.mode-badge`, `.qa-stt-button`, `.qa-metrics`, `.metric`/`.metric-label` — used
  VERBATIM so the shared CSS applies identically — mandate 3).
- New `QaModeStore` — single source of truth for the user's **agent mode** (mirrors server-side
  per-user mode), the **last response text**, and the **timing metrics** (TTT / TTFA / RTT). Emits a new
  `store_qa_changed` event on every change. Hydrates from `GET /api/mode/current` on boot; mutates via
  `POST /api/mode/current` on selector change (1:1 with legacy `setAgentMode`/`getAgentMode`/`loadCurrentMode`).
- New `QaPaneRenderer` — mounts the pane chrome, wires the selector/mic/input/tts-mode/submit handlers,
  subscribes to `store_qa_changed` to repaint the mode badge/status + metrics + response, follows the
  canonical mux renderer lifecycle (`mount`/`unmount`/`forceRenderForTesting`, throw-on-double-mount).
- New `templates/qaPane.ts` — pure DOM builders (`html\`…\`` tagged template, returns
  `HTMLElement`/`DocumentFragment`, **no `.innerHTML`** — mux AC2e safety invariant) for: the mode-selector
  row (select + optgroups + badge + status), the input row (mic + input + tts-mode + submit + spinner), the
  metrics strip, and the response box.
- **Submit action** — port of `submitQA()` (`notifications.js:2915`): debounce (2s), `POST /api/push`
  with body `{ question, websocket_id }` (the mux's queue-session id), reset+capture submit-time metric,
  disable button + show spinner, render the push-ack into the response box, clear the input on success,
  route server errors through the existing mux error path.
- **STT (voice input)** — reuse mux `audio/recordingManager.ts` (singleton): mic button →
  `recordingManager.startRecording({ contextId: "qa-input", onComplete: (text) => fill #qa-input })`, with
  the manager's TTS pause/resume injection. Direct analogue of legacy `qa-stt-button` →
  `handleSTTButtonClick('qa-input', button)` (`notifications.js:3932-3933`).
- **Agent-Mode selector** — System (auto-route) + the two optgroups (Quick Agents: math/calendar/weather/
  receptionist/todo/datetime/calculator; Agentic Processes: deep_research/podcast/research_to_podcast/
  claude_code/swe_team/presentation/research_to_presentation/test_suite) VERBATIM from
  `notifications.html:93-112`; change handler POSTs the mode (or `null` for `system`); badge click resets to
  System (legacy `notifications.js:1804-1823`); badge/status repaint mirrors `updateModeUI`
  (`notifications.js:20295-20325`).
- New event-type literal `store_qa_changed` in `shared/types.ts` + its payload interface.
- 7th `SECTION_TOGGLES` entry (`sectionId: "qa-pane"`) in `templates/sectionToolbar.ts`.
- The legacy Q&A CSS rules (`.agent-mode-select`, `.mode-badge`, `.mode-selector-container`,
  `.qa-stt-button`, `.qa-metrics`, `.metric`, `.metric-label`, `#response-text`, `.spinner`/`.loading`)
  lifted into the **single-source shared sheet** (`css/shared/notifications-surface.css`) so legacy + mux
  consume one copy (mandate 3). Legacy's heavy use of inline `style=""` on these nodes (e.g.
  `notifications.html:90,114,117,125`) is normalized into the shared sheet during the lift.
- Boot wiring (`boot.ts`): construct store + `.hydrate()`, construct renderer, mount on `#qa-pane`.

**OUT**

- NO new job-submit dispatcher cards — that is accordion **#2** (`06-absent-submit-agentic-jobs.md`,
  the heaviest plan). Q&A submits a single free-text question via `/api/push`; it does NOT own the 7
  agentic-job forms. The Agent-Mode selector here only sets the *routing preference* for that one question.
- NO change to the legacy `notifications.js` Q&A behavior or its endpoints.
- NO progressive/streaming render of the answer into `#response-text` — legacy renders only the `/api/push`
  **ack JSON** there (the actual answer arrives via the queue→notification→TTS pipeline). Strict 1:1: the
  response box shows the ack, not the synthesized answer (see §8 Q2).
- NO persistence of the agent mode in `localStorage` — server is the source of truth (legacy reads/writes
  `/api/mode/current`); the store mirrors it, it does not own it.

## 3. Source anchors

**Legacy (reference behavior — do NOT edit):**

- `html/notifications.html:83-143` — the whole `#section-qa` accordion: `#agent-mode` select with the
  two optgroups + `selected` System option (`:92-113`), `#mode-badge` (`:114-116`) + `#mode-status`
  (`:117-119`), input row `#qa-stt-button` / `#qa-input` / `#tts-mode` (instant|reliable) / `#submit-qa`
  with `#submit-loading.spinner` (`:122-135`), `#qa-metrics` TTT/TTFA/RTT (`:136-140`), `#response-text`
  (`:141`). Note testids: `notifications-qa-mode-select`, `notifications-qa-stt-btn`, `notifications-qa-input`,
  `notifications-qa-tts-mode-select`, `notifications-qa-submit-btn`, `notifications-qa-metrics`.
- `js/notifications.js:2915-2998` — `submitQA()`: trim guard, 2s debounce (`_lastSubmitTime`), reset
  metrics, `ensureValidToken()`, `POST /api/push` body `{ question, websocket_id: this.queueSessionId }`
  with `Authorization` + `X-Session-ID` headers, render ack JSON into `response-text`, clear input, error →
  `handleServerError`.
- `js/notifications.js:1673-1703` — event wiring: `#submit-qa` click → `submitQA()`; `#qa-stt-button`
  click → STT; `#qa-input` keydown (Enter) → `submitQA()`.
- `js/notifications.js:3931-3933` — `#qa-stt-button` → `handleSTTButtonClick('qa-input', button)` (the STT
  flow this plan replaces with `recordingManager`).
- `js/notifications.js:1804-1826` — agent-mode change handler (`change` → `setAgentMode(value==='system'?null:value)`)
  + badge-click → `setAgentMode(null)` + reset select to `'system'`.
- `js/notifications.js:20212-20336` — `setAgentMode(mode)` (`POST /api/mode/current` `{mode}`),
  `getAgentMode()` (`GET /api/mode/current`), `updateModeUI(mode, displayName)` (badge show/hide + status
  text/color), `loadCurrentMode()` (boot hydrate).
- `js/notifications.js:6027-6060` — metrics render: `resetMetricsDisplay()` (hide strip, `--`/`--`/`--`),
  `updateMetricsTTT()` (`metricsTextTime - metricsSubmitTime`), `updateMetricsTTFA()`
  (`metricsFirstAudioTime - metricsTTSStartTime`), `updateMetricsRTT()` (`metricsFirstAudioTime -
  metricsSubmitTime`). Metric source-timestamps: `metricsSubmitTime` set in `submitQA` (`:2949`),
  `metricsTextTime` (`:3965`), `metricsTTSStartTime` (`:4270`,`:4327`), `metricsFirstAudioTime` (`:4670`).
- `css/notifications.css` — the Q&A rules to lift (grep `.mode-badge`, `.qa-stt-button`, `.qa-metrics`,
  `.agent-mode-select`, `#response-text`; exact line span to be confirmed during the lift, mandate 3).

**Mux targets (add / edit):**

- ADD `js/multiplexer/stores/QaModeStore.ts` (new).
- ADD `js/multiplexer/render/QaPaneRenderer.ts` (new).
- ADD `js/multiplexer/render/templates/qaPane.ts` (new).
- EDIT `js/multiplexer/shared/types.ts` (`LupinEventType` union ~line 22-135) — append
  `| "store_qa_changed"` + add `StoreQaChangedPayload` interface.
- EDIT `js/multiplexer/render/templates/sectionToolbar.ts:35-42` — add 7th `SECTION_TOGGLES` entry.
- EDIT `js/multiplexer/boot.ts` (NEW-LANE MOUNT SLOT ~lines 389-393) — construct store + `.hydrate()`,
  construct + mount renderer on `#qa-pane`; add to `boot_complete` handlers map + the canonical
  `[multiplexer] qaPaneRenderer:mounted` console line.
- EDIT `js/multiplexer/stores/index.ts` + `render/index.ts` — export the new factories (barrel pattern).
- EDIT `html/multiplexer.html` (~line 104, as the FIRST pane — legacy puts Q&A at the top of the column,
  above Jobs) — add the `<section id="qa-pane">`.
- EDIT `css/shared/notifications-surface.css` — add the lifted Q&A rules.
- VERIFY `html/notifications.html` `<head>` links the shared sheet BEFORE `notifications.css` (mandate 3).

**Mux non-source (confirms ABSENT):** grep of `qa-input` / `submit-qa` / `submitQA` / `agent-mode` /
`mode-badge` / `response-text` across `js/multiplexer/**` → **0 hits** (doc 04:80). No Q&A store, renderer,
template, pane div, or mode plumbing exists in the mux today.

## 4. Dependencies & prerequisites

- **`recordingManager` (STT) — already present, no prereq.** `audio/recordingManager.ts` singleton exposes
  `startRecording({ contextId, authToken?, onComplete:(text,blob)=>…, onError, onRecordingStart, onCancel })`,
  `stopRecording(contextId)`, `cancelRecording(contextId)`, plus TTS-coordination injection points
  (`ttsIsPlaying`/`ttsPause`/`ttsResume`). Default upload endpoint `/api/upload-and-transcribe-mp3`. The
  mux already consumes it (SenderCardRecorder) — Q&A is a second consumer with `contextId: "qa-input"`.
- **Endpoints (already exist, no backend work):**
  - `POST /api/push` `{ question, websocket_id }` — submit. (Same endpoint the legacy client uses.)
  - `GET` / `POST /api/mode/current` `{ mode }` — read/set the per-user agent routing mode (server extracts
    user from the JWT). Returns `{ mode, display_name, message }`.
- **Authenticated fetch** — the store needs `Authorization: Bearer …` + the queue session id. Reuse the
  mux's existing auth seam: `StorageService.getAccessToken()` for the bearer, and the mux's queue-session
  id (the `websocket_id` for `/api/push`). **Grep target**: confirm the canonical mux authed-fetch helper
  / `ApiClient` shape that `JobStore.hydrateHistory` / `JobHistoryApiClient` already use, and route the
  store's three calls through it rather than hand-rolling `fetch` (keeps token-refresh behavior consistent).
- **Metrics (TTT/TTFA/RTT) — the one cross-cutting dependency (see §8 Q1).** Legacy captures four
  timestamps across the submit → text-response → tts-start → first-audio lifecycle. In the mux those phases
  surface as **EventBus / AudioStore** transitions, not direct method calls:
  - `metricsSubmitTime` — set synchronously in the submit handler (trivial).
  - `metricsTextTime` — needs the WS/notification event that delivers the Q&A answer text correlated back
    to this submission (mux: a `store_notifications_changed` / completion event).
  - `metricsTTSStartTime` / `metricsFirstAudioTime` — derivable from `AudioStore` transitions
    (`store_audio_state_change` → first `playing`) (`stores/AudioStore.ts`).
  Wiring all three requires correlating the submitted question to its downstream answer + audio. This is
  the gated risk; a **metrics phasing** option is offered in §8 Q1.
- **Carves inherited**: none. **INI keys**: none new.

## 5. Work breakdown

### Task 1 — `templates/qaPane.ts` (pure DOM builders)
- **What**: exported builders returning `HTMLElement`/`DocumentFragment` via `html\`…\``:
  `renderModeSelectorRow()` (label + `#agent-mode.agent-mode-select` with the System option + both
  optgroups VERBATIM + `#mode-badge.mode-badge` hidden + `#mode-status`), `renderInputRow()`
  (`#qa-stt-button.qa-stt-button` 🎤 + `#qa-input` + `#tts-mode` instant|reliable + `#submit-qa` with
  `#submit-loading.loading > .spinner`), `renderMetricsStrip()` (`#qa-metrics.qa-metrics` hidden, three
  `.metric` cells TTT/TTFA/RTT each `.metric-label` + `#metric-ttt|ttfa|rtt`), `renderResponseBox()`
  (`#response-text` seeded "No response yet..."). All ids + testids string-equal to legacy. No `.innerHTML`.
- **Files**: `render/templates/qaPane.ts` (new).
- **ACs**: (functional) optgroup option set + values == legacy exactly; badge starts hidden; metrics start
  hidden with `--`/`--`/`--`. (structural) every legacy id + `data-testid` present and string-equal.
- **Oracle tier**: **T1 (DOM-contract)** — selector/optgroups, input row, metrics, response box ids+classes.

### Task 2 — `QaModeStore.ts` (mode + response + metrics; emission)
- **What**: `createQaModeStore({ eventBus, api })`. State: `mode: string|null`, `displayName: string`,
  `lastResponse: string`, `metrics: { submitTs, textTs, ttsStartTs, firstAudioTs }`. Methods:
  `hydrate()` (`GET /api/mode/current` → set mode/displayName → emit), `setMode(mode)` (`POST
  /api/mode/current`; `'system'`→`null`; on ok set + emit; on fail emit error state — 1:1 `setAgentMode`),
  `setResponse(text)` (+emit), and the metric setters (`markSubmit`/`markText`/`markTtsStart`/`markFirstAudio`
  → recompute TTT/TTFA/RTT, +emit), `resetMetrics()`. Getters return copies. `subscribe()` (if metrics
  Task 6 lands) wires the AudioStore/notification events → metric marks; returns teardown. Emits
  `{ type: "store_qa_changed", payload: StoreQaChangedPayload, source: "QaModeStore", ts }`.
- **Files**: `stores/QaModeStore.ts` (new); export from `stores/index.ts`.
- **ACs**: (functional) `setMode('system')` posts `{mode:null}`; non-system posts the value; failed POST
  surfaces an error state without throwing; metric math == legacy (TTT=text-submit, TTFA=firstAudio-ttsStart,
  RTT=firstAudio-submit); emits exactly once per mutation. (structural) payload carries a `changeKind`
  discriminator (`"mode"|"response"|"metrics"`) matching the Phase-4 store envelope shape.
- **Oracle tier**: n/a (logic) — unit tests, 100% L/B/F.

### Task 3 — `QaPaneRenderer.ts` (mount + wire + repaint)
- **What**: `createQaPaneRenderer({ eventBus, stores: { qa }, recording })`. `mount(root)`: throw on
  double-mount (mirror `SectionToolbarRenderer` lifecycle), append the four template fragments, then wire:
  `#agent-mode` change → `qa.setMode(...)`; `#mode-badge` click → `qa.setMode(null)` + reset select to
  `system`; `#qa-stt-button` click → `recordingManager.startRecording({ contextId:"qa-input",
  onComplete:(text)=>{ #qa-input.value = text } })`; `#submit-qa` click + `#qa-input` Enter → `submitQa()`
  (Task 5). Subscribe to `store_qa_changed` → repaint badge/status (`updateModeUI` logic), metrics strip,
  response box. `unmount()`: idempotent, drop subscriptions, cancel any active recording for `qa-input`,
  clear children.
- **Files**: `render/QaPaneRenderer.ts` (new); export from `render/index.ts`.
- **ACs**: (functional) selector change calls `setMode`; badge click resets to system; mic click starts a
  recording bound to `qa-input` and the transcription lands in the input; Enter submits; repaint reflects
  store mode/metrics/response; double-mount throws; unmount idempotent + unsubscribes + cancels recording.
  (structural) post-mount DOM under `#qa-pane` == legacy contract.
- **Oracle tier**: **T1 (DOM-contract)** post-mount + badge/status state transitions.

### Task 4 — `multiplexer.html` `#qa-pane` section + boot wiring
- **What**: add `<section id="qa-pane" data-testid="multiplexer-qa-pane">` with a `<header><h2>Q&A
  Interface</h2></header>` (mux idiom: own header, collapse delegated to the section-toolbar — mirrors
  fleet-status/jobs panes, NOT the legacy header-click ▼ accordion) + an empty body the renderer fills.
  Placed as the **first** pane (legacy column-top). In `boot.ts` NEW-LANE MOUNT SLOT: construct
  `createQaModeStore`, float `.hydrate()` (catch → emit a non-fatal failure event, never an unhandled
  rejection — mirror `JobsPaneRenderer`'s hydration pattern), construct `createQaPaneRenderer`, resolve
  `#qa-pane` (`if (mountEl === null) throw`), `.mount()`; add to `boot_complete` handlers + console line.
- **Files**: `html/multiplexer.html`, `boot.ts`, `stores/index.ts`.
- **ACs**: (functional) on boot the pane renders and the mode selector reflects the server's current mode
  after hydrate. (structural) `#qa-pane` present, contains the full Q&A contract.
- **Oracle tier**: **T1** (presence + contract).

### Task 5 — submit action (`submitQa()` port)
- **What**: in the renderer (or a small `qa/submitQa.ts` helper): trim guard + 2s debounce
  (`_lastSubmitTime`), `qa.markSubmit()` + `qa.resetMetrics()`, disable `#submit-qa` + show
  `#submit-loading` spinner, `POST /api/push` `{ question, websocket_id }` via the authed-fetch seam
  (Authorization + `X-Session-ID`), on ok `qa.setResponse(JSON.stringify(ack,null,2))` + clear input, on
  error route through the mux error path + `qa.setResponse("Error: …")`, finally re-enable button + hide
  spinner. 1:1 with `notifications.js:2915-2998`.
- **Files**: `render/QaPaneRenderer.ts` (or `render/qa/submitQa.ts`).
- **ACs**: (functional) empty input → no POST + a user-visible "enter some text"; rapid double-click within
  2s → second ignored; success clears input + renders ack; HTTP error renders `Error:` + spinner always
  cleared. (structural) request body == `{ question, websocket_id }`; headers include bearer + session id.
- **Oracle tier**: n/a (logic) — unit tests with a stubbed fetch.

### Task 6 — metrics wiring (TTT/TTFA/RTT) — **conditional, see §8 Q1**
- **What**: `QaModeStore.subscribe()` binds `store_audio_state_change` (first `playing` →
  `markFirstAudio`; the transition into `playing`/decoding → `markTtsStart`) and the
  notification/completion event that carries the answer text (→ `markText`, correlated to the last
  submission). Renderer paints the strip from the recomputed metrics.
- **Files**: `stores/QaModeStore.ts`, `render/QaPaneRenderer.ts`.
- **ACs**: (functional) after a submit+answer+audio cycle the three metrics populate with the legacy
  arithmetic; on a fresh submit the strip resets to `--`. (structural) strip shown (`display:flex`) only
  once a metric is set.
- **Oracle tier**: **T1** (strip visibility + cell text) + n/a logic.
- **Fallback if deferred** (§8 Q1): ship the metrics **strip DOM** (parity contract) but leave it inert
  (`--`/`--`/`--`, hidden) with a `# TODO(metrics)` marker; the strip then has no live source. The plan's
  parity DOM target is still met; only the live numbers wait on a follow-up.

### Task 7 — section-toolbar 7th toggle
- **What**: add `{ sectionId: "qa-pane", icon: "❓", title: "Q&A Interface",
  testid: "multiplexer-section-toolbar-qa" }` to `SECTION_TOGGLES`. The existing delegated click handler +
  `ViewStateStore` persistence pick it up (no renderer change).
- **Files**: `render/templates/sectionToolbar.ts`.
- **ACs**: (functional) toggle dims the button + adds `.section-hidden` to `#qa-pane`, persisted via
  ViewStateStore across reload. (structural) toolbar renders 7 `.toolbar-btn[data-section]`.
- **Oracle tier**: **T1** (button count/contract) — existing toolbar tests extend by one.

### Task 8 — shared CSS lift
- **What**: lift the Q&A rules (`.mode-selector-container`, `.agent-mode-select`, `.mode-badge`,
  `.qa-stt-button`, `.qa-metrics`, `.metric`, `.metric-label`, `#response-text`, `.loading`/`.spinner`)
  from `css/notifications.css` into `css/shared/notifications-surface.css`; normalize the legacy inline
  `style=""` on these nodes into the shared sheet. Legacy keeps rendering identically because it links the
  shared sheet (mandate 3). Verify both pages link the shared sheet.
- **Files**: `css/shared/notifications-surface.css`, `html/multiplexer.html`, (verify) `html/notifications.html`.
- **ACs**: (structural) one copy of each rule; both pages link the shared sheet; legacy monolith no longer
  re-declares them (or declares identically — T0 hash check). (visual) the inline-style normalization is
  pixel-equal to legacy.
- **Oracle tier**: **T0 (CSS-hash)** + **T2 (computed-style)** — badge pill, mic button, metric typography.

## 6. Test strategy & venue routing

- **Unit (tsx `node:test` + happy-dom + c8 — AI-discretionary, no server, :7999-class)** — the bulk:
  - `qa_pane_template.test.ts`: optgroup option set/values == legacy; all ids + testids present; metrics +
    badge start hidden; no `.innerHTML`.
  - `qa_mode_store.test.ts`: `setMode` system↔non-system POST bodies; failed POST → error state (no throw);
    metric arithmetic (TTT/TTFA/RTT); single emission per mutation; `hydrate()` maps the GET response;
    inject `createEventBusForTesting()` + a fake `api`/fetch.
  - `qa_pane_renderer.test.ts`: mount paints the contract; selector change → `setMode`; badge click →
    reset-to-system; mic click → `recordingManager.startRecording` (inject a fake recording manager) and
    `onComplete` fills `#qa-input`; Enter + button → submit (stubbed fetch); repaint on `store_qa_changed`;
    double-mount throws; unmount idempotent + unsubscribes + cancels recording.
  - `submit_qa.test.ts`: empty guard, 2s debounce, success clears input + renders ack, error path,
    spinner always cleared, request body/headers.
  - `section_toolbar.test.ts` (existing) extended: 7 toggles, Q&A entry present.
  - **100% L/B/F** (TS `c8 --100`) — mandate 1. `c8 ignore` only for genuinely-unreachable defensive
    branches with a same-line reason (follow the existing tsx phantom-branch pragmas in `sectionToolbar.ts`).
- **E2E UI + visual regression** → **:8000 scheduled** via `POST /api/test-suite/submit` (self-authorized
  on a verified-idle server; `list-pending` first; never side-door — mandate 4):
  - Playwright: `#qa-pane` mounts with the full contract; mode selector change flips the badge + status +
    persists server-side (`GET /api/mode/current` reflects it); ❓ toolbar toggle hides/shows + persists
    across reload; a typed question + Submit hits `/api/push` and renders the ack; mic button records (mock
    getUserMedia) and fills the input.
  - **Visual**: new golden of the Q&A pane (see §7) — `--update-snapshots` to baseline; version-controlled.
- **Doc touchpoints** (mandate 7): this accordion's own discrepancy→remediation doc under
  `…/2026.06.25-…-discrepancies/` (doc 04 §Next item 3). **No `src/docs/` API doc change** — `/api/push` and
  `/api/mode/current` are pre-existing endpoints; if a new router/INI key were introduced (none planned) the
  CLAUDE.md §DOCUMENTATION TOUCHPOINTS rows would apply. (`/docs` is auto-generated regardless.)

## 7. Oracle & visual parity

Tiers exercised (methodology `2026.06.19-…/01-layout-parity-methodology.md`):

- **T0 CSS-hash** — the lifted Q&A rules served from the single shared sheet; hash-match against legacy.
- **T1 DOM-contract** — `#agent-mode.agent-mode-select` + both optgroups + `#mode-badge` + `#mode-status`;
  `#qa-stt-button` / `#qa-input` / `#tts-mode` / `#submit-qa` + `#submit-loading.spinner`;
  `#qa-metrics` + three `.metric` cells; `#response-text`; toolbar +1 `.toolbar-btn[data-section="qa-pane"]`.
- **T2 computed-style** — mode badge pill (radius 12px, bold uppercase, blue bg), mic button, metric
  label/value typography, response box.
- **T3 geometry** — input-row flex layout (mic · input · tts-mode · submit) and the metrics-strip flex.
- **T4 pixel backstop** — a single golden of a seeded state (System mode, empty input, hidden metrics) +
  one of an active non-system mode (badge visible). Freeze any time/text so diffs are deterministic.

**New golden captures**: (1) legacy `:8000` reference capture of `#section-qa` in two states (System;
non-system badge shown) — legacy-capture cost per mandate 2; (2) mux `#qa-pane` baseline via
`--update-snapshots`. Seed both identically so the diff is clean.

## 8. Risks & open questions (for reviewers)

1. **Metrics (TTT/TTFA/RTT) live wiring — ship now or phase?** This is the only non-trivial integration:
   legacy correlates four timestamps across submit → answer-text → tts-start → first-audio, which in the
   mux means correlating a submission to its downstream completion notification + AudioStore `playing`
   transition (§4). **Option A**: build the full wiring now (Task 6) — more coupling, depends on the
   answer-correlation event existing/being identifiable. **Option B (recommended for a clean first cut)**:
   ship the metrics **DOM contract** inert (parity met) and land live numbers as a fast follow once the
   answer-correlation seam is confirmed. Reviewer call.
2. **`#response-text` shows the push-ack, not the answer (strict 1:1).** Legacy renders only the `/api/push`
   queue-ack JSON there; the synthesized answer arrives via the notification/TTS pipeline (which the mux
   already renders in `#notifications-pane` + `tts-pane`). So the Q&A response box is intentionally
   low-value. **Confirm**: faithful-port the ack-only box (this plan's default), or is this the moment to
   upgrade it to render the actual answer (a redesign beyond parity)?
3. **`#tts-mode` (instant|reliable) — where is the value consumed?** Legacy's `submitQA` body does NOT
   include tts-mode; the select is read by other TTS paths (`notifications.js:3956,4017,10426,15019`) as a
   page-level preference. In the mux there is no obvious consumer. **Grep/decide**: port the select as inert
   parity chrome, wire it to a server/AudioStore TTS-mode preference, or drop it (the one sanctioned
   deviation)? Defaulting to "port as parity chrome + flag the unwired consumer."
4. **Agent-mode is per-user server state, shared with the legacy page.** Both clients POST the same
   `/api/mode/current`; if a user has both pages open, mode changes race. This is pre-existing legacy
   behavior (not introduced here) but worth a reviewer nod — the store should `hydrate()` on mount and could
   optionally re-hydrate on focus.
5. **Header-accordion vs section-toolbar toggle** — `#qa-pane` delegates collapse to the section-toolbar
   like every other mux pane (the header→toolbar divergence is already accepted fleet-wide, doc 04 §#6).
   Confirm consistent, not a #1-specific regression.
6. **Optgroup mode list drift.** The 15 modes are hard-coded VERBATIM from legacy. If the server's mode
   registry is authoritative, a future-proofing option is to populate the optgroups from an endpoint —
   OUT of scope here (strict parity), but flagged.

## 9. Lane decomposition & estimate

**One lane, mild internal sequencing.** Larger than #13 (Debug) but still a single-engineer plan:
templates → store → renderer/submit → html/boot → toolbar/CSS. Rough new code ~300-400 TS LOC + ~40
HTML/CSS lines. Metrics (Task 6) is the one optionally-splittable sub-lane (§8 Q1).

**Convergence files (manager-serial-merged — mandate 5):**

- `shared/types.ts` (event union +1 literal + payload),
- `render/templates/sectionToolbar.ts` (`SECTION_TOGGLES` +1),
- `boot.ts` (mount slot),
- `html/multiplexer.html` (pane + `<head>` link),
- `css/shared/notifications-surface.css` (lifted rules),
- `stores/index.ts` + `render/index.ts` (barrels).

All are shared with other corpus plans (esp. types.ts / boot.ts / sectionToolbar.ts / shared CSS) → the
manager merges this lane's edits serially. The three NEW files (store / renderer / template) + the optional
`qa/submitQa.ts` are lane-private, no merge risk. **Reused, untouched**: `audio/recordingManager.ts`,
`audio/AudioRecorder.ts`, `stores/AudioStore.ts`, `shared/StorageService.ts`, `shared/EventBus.ts`.

**Sequencing**: per ruling (g), build **after** CC-session (`03-`) + the 3 partials. Within the absent set
Q&A is the natural **first** absent accordion (lowest of the user-facing four, and a prerequisite-free warm-up
for the heavier Submit-Agentic-Jobs #2 which shares the STT + authed-fetch patterns). No dependency on any
other absent plan.

**Rough size**: ~1 day implementation + ~½-day tests/visual baseline ≈ **1.5 days** (add ~½-day if §8 Q1
Option A — full metrics wiring — is ratified for this pass).
