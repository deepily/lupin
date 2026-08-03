# Direct TTS Test (#12) — Build Plan

**Date**: 2026-06-26
**Status**: 🟡 DRAFT for cascaded review (run on Rick's dev server, not the laptop)
**Author**: section-direct-tts lane (this session, for Rick)
**Source audit refs**: doc `04-remaining-accordions-audit.md` §"#12 Direct TTS Test" (line 107-111) + Master verdict row 12 (TRULY ABSENT; `tts-pane` ≠ this)
**Decision-of-record refs**: ruling **(g)** "Port ALL 7 absent accordions → total 13/13 parity" (doc 04 §Resolved, TODO Decisions Log 2026-06-26). Sequenced AFTER CC-session (`01-`) + the 3 partials (`02`/`03`/`04`).

> Inherits all 7 cross-cutting mandates from `00-plans-index.md` §"Cross-cutting mandates" — 100% L/B/F, Layout-Parity Oracle T0–T4, single-source CSS, venue routing, manage-don't-build lane isolation, in-flight-crew coordination, doc touchpoints. Not restated; referenced where they bind.

---

## 1. Goal & parity target

Restore the legacy **Direct TTS Test** dev harness — a one-line text field + "🔊 Speak Now" + "Test Instant TTS" + "Test Reliable TTS" + "Stop Audio" — into the multiplexer, wired to the **existing** mux audio path (`AudioStore` receive-side + the server's `/api/get-speech*` synthesis endpoints). "Done" = a developer can type arbitrary text in the mux, fire it through either TTS mode, hear it stream back through the mux's `/ws/audio` → `AudioStore` pipeline, and stop it — **bypassing Q&A / job-completion / notifications entirely**, exactly as legacy `directTTSTest()` does.

This is explicitly a **dev/diagnostic surface**, not a user feature — §8 carries the open question of whether it ships visible in prod or behind a debug gate.

## 2. Scope

**IN**
- A new standalone mux pane `#direct-tts-pane` (recommendation — see §5.1 for the fold-vs-standalone decision) holding: text input, Speak-Now button, Test-Instant button, Test-Reliable button, Stop button — DOM-contract parity with legacy `notifications.html:1136-1150`.
- A new `DirectTtsTestRenderer.ts` (+ `directTtsTest.ts` template) owning the harness chrome and click wiring.
- A new **outbound TTS-synthesis request helper** (the one genuinely-missing primitive) that POSTs to `/api/get-speech-elevenlabs` (instant) and `/api/get-speech` (reliable) with `{ text, session_id }` via the existing mux `ApiClient`. The **receive** side already exists — chunks return over `/ws/audio` → `AudioStore.binaryHandler` (no new receive code).
- Stop → `AudioStore.stop()` (Phase 6b primitive already in place, `AudioStore.ts:239`).
- Section-toolbar registration (a 7th `SECTION_TOGGLES` entry) so the pane participates in the show/hide + collapse-all chrome — **iff** §8 resolves "ship visible".
- A debug/admin gate hook (boot-time conditional mount) — see §5.5 + §8.

**OUT**
- The `tts-mode` selector itself. Legacy `directTTSTest()` reads the **shared** `#tts-mode` `<select>` (`notifications.js:4150`); the mux has no global TTS-mode selector today. Per §5.2 the mux harness carries its OWN instant/reliable choice via the two dedicated buttons (legacy already had `test-instant-tts` / `test-reliable-tts` as explicit-mode buttons) — Speak-Now defaults to **instant** (legacy `TTS_MODE_DEFAULT`, `notifications.js:35`). No global mode-selector port (that belongs to #1 Q&A, plan `05-`).
- Audio-cache integration (`audioCache.checkCache`, `notifications.js:4205`). The mux receive path has its own caching surface (`TtsAudioCache.ts` / `JobCompletionCache.ts`); the dev harness does NOT need cache short-circuiting and SHOULD always hit the server for a true synthesis probe. Document as an intentional divergence.
- Per-item TTS-queue viz, Focus-mode, Clear-all — those are #4 (plan `03-tts-queue-full-restore.md`), not this.

## 3. Source anchors

**Legacy (reference behavior — do NOT port verbatim; mux idiom)**
- `src/lupin_app/static/html/notifications.html:1135-1151` — `#section-direct-tts` markup: `#direct-tts-input` (`data-testid="notifications-direct-tts-input"`), `#direct-tts-button`, `#test-instant-tts`, `#test-reliable-tts`, `#stop-audio`, each with `notifications-*` testids.
- `src/lupin_app/static/js/notifications.js:1668-1696` — click wiring (`direct-tts-button`→`directTTSTest()`, `test-instant-tts`→`testTTS(INSTANT)`, `test-reliable-tts`→`testTTS(RELIABLE)`, `stop-audio`→`stopAudio()`).
- `src/lupin_app/static/js/notifications.js:4141-4163` — `directTTSTest()` (reads `#direct-tts-input`, calls `playTTS(text, mode)`, clears input).
- `src/lupin_app/static/js/notifications.js:4191-4197` — `testTTS(mode)` (fixed probe string per mode).
- `src/lupin_app/static/js/notifications.js:4199-4224` — `playTTS()` dispatch (instant→`playInstantTTS`, reliable→`playReliableTTS`).
- `src/lupin_app/static/js/notifications.js:4257-4307` — `playInstantTTS()` → `POST /api/get-speech-elevenlabs` body `{ text, session_id, [voice_id] }`.
- `src/lupin_app/static/js/notifications.js:4309-4345+` — `playReliableTTS()` → `POST /api/get-speech` same body.
- `stopAudio()` (grep `notifications.js` for `stopAudio`) — legacy multi-mode halt; mux equivalent is the single `AudioStore.stop()`.

**Server endpoints (already exist — no backend work)**
- `src/cosa/rest/routers/speech.py:487` — `POST /api/get-speech-elevenlabs` (instant PCM streaming to `/ws/audio` by session).
- `src/cosa/rest/routers/speech.py:362` — `POST /api/get-speech` (OpenAI reliable batch, "stream to the client's WebSocket session").

**Mux targets (add / edit)**
- ADD `src/lupin_app/static/js/multiplexer/render/DirectTtsTestRenderer.ts` (new renderer).
- ADD `src/lupin_app/static/js/multiplexer/render/templates/directTtsTest.ts` (new template, `html`-tagged, safe-write per AC2e).
- ADD a TTS-synthesis request method — **recommend** extending `ApiClient` (`src/lupin_app/static/js/multiplexer/api/ApiClient.ts:57-65`) with `requestSpeech(mode, text, sessionId)` (or a thin `TtsRequestService`); reuses the existing auth-header + timeout plumbing (`ApiClient.ts:124-194`).
- EDIT `src/lupin_app/static/html/multiplexer.html` — add `<section id="direct-tts-pane" hidden …>` mount slot (near the `#tts-pane` slot, line 186-188, and the `#tts-preview-slider-mount`).
- EDIT `src/lupin_app/static/js/multiplexer/boot.ts` — 8-line mount handshake (NEW-LANE MOUNT SLOT, ~line 230-260 region) + `bootCompletePayload.handlers` entry + AC9 console line; **conditional** on the debug gate (§5.5).
- EDIT (conditional) `src/lupin_app/static/js/multiplexer/render/templates/sectionToolbar.ts:36-43` — 7th `SECTION_TOGGLES` entry `{ sectionId: "direct-tts-pane", icon: "🔧", title: "Direct TTS Test", testid: "multiplexer-section-toolbar-direct-tts" }`.
- ADD CSS to the shared sheet (`css/shared/notifications-surface.css` per mandate #3) for the `.direct-tts-controls` row — reuse legacy `.audio-controls` flex semantics (`notifications.html:1142` inline `display:flex; gap:12px`). No forked copy.

## 4. Dependencies & prerequisites

- **No `AudioStore` multi-item extension needed** (unlike plan `03-`). The dev harness fires single utterances through the existing single-stream `AudioStore`; `stop()` already exists (`AudioStore.ts:239`, Phase 6b).
- **`sessionId`** is available in boot (`boot.ts:144` `storage.getSessionId()`) and is the SAME id used for `transports.audio.start(sessionId, …)` (`boot.ts:547`). The synthesis POST MUST carry this exact `session_id` so the server routes chunks back to the mux's live `/ws/audio` connection. Thread `sessionId` into the renderer (or into the `ApiClient.requestSpeech` call site).
- **No INI keys, no new endpoints, no DB.** Pure front-end + reuse of two existing routes.
- **Auth**: `ApiClient` injects `Authorization: Bearer <token>` (`ApiClient.ts:136-139`) — matches legacy `getAuthHeader()`. The `X-Session-ID` header legacy also sends (`notifications.js:4283`) is redundant with the body `session_id` for these routes; confirm server reads body `session_id` (it does per `playInstantTTS` contract) — if the server also requires the header, add it via a per-call option (open item, §8).
- **Cross-plan**: independent of `01-`/`02-`/`03-`/`04-`. Touches two convergence files (`boot.ts`, `multiplexer.html`, `sectionToolbar.ts`) → manager-serial-merged per mandate #5.

## 5. Work breakdown

### 5.1 — Decision: standalone pane vs fold into `tts-pane` *(structural; gates all else)*
**Recommendation: STANDALONE pane + standalone renderer.** Rationale:
- `TtsChromeRenderer` has an explicit, documented narrow scope: "AudioStore-driven rendering only" (`boot.ts:328-329`, `TtsChromeRenderer.ts:2-7`). It renders **receive-side transport state** (pause/resume/stop/skip/queue-length) and re-renders on `store_audio_state_change` / `store_audio_chunk_decoded`. A text-input + outbound-synthesis harness is a different concern (it WRITES to the server, the chrome only reflects playback). Folding it in would pollute that renderer's contract and its RAF-coalesced re-render loop.
- Standalone keeps the dev surface independently gateable/removable (§5.5 / §8) without touching production playback chrome.
- **Files**: this decision selects `DirectTtsTestRenderer.ts` + `#direct-tts-pane` (NOT a `tts-pane` sub-block).
- **AC**: `TtsChromeRenderer.ts` is UNMODIFIED by this plan. · **Oracle**: T1 (DOM-contract: two distinct panes).

### 5.2 — Template `directTtsTest.ts` *(the chrome)*
Build, via the `html` tagged template (safe-write, no `.innerHTML`/`rawHTML` per AC2e precedent in `ttsChrome.ts:5-7`): a root `.direct-tts-controls` containing `<input type="text" data-testid="multiplexer-direct-tts-input">`, and 4 `<button>`s with testids `multiplexer-direct-tts-speak`, `multiplexer-direct-tts-instant`, `multiplexer-direct-tts-reliable`, `multiplexer-direct-tts-stop`. Accept a `handlers` object `{ onSpeak, onInstant, onReliable, onStop }` wired via `addEventListener` (mux idiom, no inline `onclick`).
- **ACs (functional)**: input present + 4 buttons present; clicking each invokes the matching handler exactly once; Stop is always enabled (it's a no-op from idle per `AudioStore.stop()`).
- **ACs (structural)**: root carries `data-testid="multiplexer-direct-tts-pane"` + `class="direct-tts-controls"`; testids match the table above. · **Oracle**: T0 (CSS-hash on shared sheet), T1 (DOM-contract), T2 (computed-style on the flex row vs legacy `.audio-controls`).

### 5.3 — `ApiClient.requestSpeech(mode, text, sessionId)` *(the missing outbound primitive)*
Add a typed method: instant → `post("/api/get-speech-elevenlabs", { text, session_id })`; reliable → `post("/api/get-speech", { text, session_id })`. Returns the server's JSON ack (chunks arrive async over `/ws/audio`). Reuses existing auth + timeout + 401-trampoline.
- **ACs (functional)**: instant mode POSTs the elevenlabs URL with the exact body; reliable POSTs `/api/get-speech`; both include `session_id`; 401 trips `authManager.invalidate()` (inherited). Empty/whitespace text is rejected client-side BEFORE the POST (legacy `directTTSTest()` guards `if (!text)`, `notifications.js:4145`).
- **ACs (structural)**: method on the `ApiClient` interface; no new fetch plumbing (delegates to `request`). · **Oracle**: n/a (logic — covered by unit).

### 5.4 — `DirectTtsTestRenderer.ts` *(mount + behavior)*
`mount(root)`/`unmount()` per the Phase 6a renderer contract (atomic `replaceChildren`, throw-on-double-mount, idempotent unmount — mirror `TtsChromeRenderer.ts:106-145`). Handlers:
- `onSpeak` / `onInstant`: read+trim input → guard empty → `apiClient.requestSpeech("instant", text, sessionId)` → clear input on success. (Speak-Now = instant default per §2.)
- `onReliable`: same with `"reliable"`. Uses a fixed probe string is NOT required — legacy `directTTSTest` speaks the **input** while `testTTS` speaks a canned string; mux folds both kinds into "speak the input in mode X" for the three speak-buttons, with `onInstant`/`onReliable` falling back to the canned legacy probe string (`"This is a test of the text-to-speech system in {mode} mode."`, `notifications.js:4192`) when the input is empty — preserving the legacy "Test Instant/Reliable" zero-typing affordance.
- `onStop`: `stores.audio.stop()`.
- **Dependencies injected** (narrow stores per Pass 2 F4): `{ audio: AudioStore }` + `apiClient` + a `sessionIdProvider: () => string`.
- **ACs (functional)**: each button path verified; empty-input speak with canned fallback; success clears input; error path surfaces (console + no crash); double-mount throws; unmount idempotent. · **Oracle**: T1 (mounted DOM), behavioral via unit.

### 5.5 — boot wiring + debug gate
8-line mount handshake in the NEW-LANE MOUNT SLOT (`boot.ts` ~230-260), `bootCompletePayload.handlers.directTtsTestRenderer = "mounted"`, AC9 console line `"[multiplexer] directTtsTestRenderer:mounted"`. Mount is **conditional** on a debug gate (§8 resolves the gate mechanism — candidate: a `window.__LUPIN_DEBUG__` / URL `?debug=1` / server-config `multiplexer_dev_tools` flag fetched alongside `tts_preview_fraction` at `boot.ts:182`). When gated-off: pane stays `hidden`, renderer not mounted, no section-toolbar entry, AC9 payload reports `"skipped"`.
- **ACs**: gate-on → pane visible + renderer mounted + toolbar entry present; gate-off → pane absent from layout + no toolbar entry + boot still completes cleanly. · **Oracle**: T1/T3 (presence/geometry under each gate state).

### 5.6 — section-toolbar entry (conditional on visible-in-prod)
Add the 7th `SECTION_TOGGLES` spec only if §8 ⇒ ship-visible. If debug-gated, register it dynamically only when the gate is on (the renderer builds the toolbar from the static list today — `sectionToolbar.ts:36`; a conditional entry needs the list to be gate-aware, a small change). · **Oracle**: T1 + T2 (toolbar button parity).

## 6. Test strategy & venue routing

**:7999 (AI-discretionary)** — all pure-logic + DOM + mount tests:
- TS unit (`node:test` + jsdom, `c8 --100`): `directTtsTest.test.ts` (template DOM-contract + handler dispatch), `DirectTtsTestRenderer.test.ts` (mount/unmount/double-mount, empty-input guard + canned fallback, clear-on-success, stop→`AudioStore.stop()`), `ApiClient` new-method cases (instant URL, reliable URL, body shape, empty-text-rejected-before-POST, 401 trampoline) added to the existing `ApiClient` test.
- `py_compile`/import — n/a (no Python touched).
- Front-end build + the multiplexer boot smoke (verify `boot_complete` payload carries `directTtsTestRenderer` under both gate states).

**:8000 (scheduled via `POST /api/test-suite/submit`, self-authorized on verified-idle)** — anything that actually synthesizes audio:
- E2E UI (Playwright): gate-on, type text, click each speak button, assert a `/ws/audio` chunk arrives and `AudioStore` transitions `idle→decoding→playing`, click Stop → `idle`. This **hits real ElevenLabs/OpenAI TTS = real API spend + server monopoly** → :8000 only, never :7999. Add to `run-e2e-ui-tests.sh` suite (visual snapshot for the controls row).
- Reliable-mode probe likewise on :8000 (OpenAI spend).

**100% L/B/F**: every new TS file (`DirectTtsTestRenderer.ts`, `directTtsTest.ts`) and the `ApiClient` delta meet `c8 --100` lines AND branches AND functions. `c8 ignore` only for the documented tagged-template phantom-branch + production-default-fallback lines (same precedent as `ttsChrome.ts:105`, `ApiClient.ts:90`), each with a same-line reason. No Python coverage delta (no backend change).

## 7. Oracle & visual parity

- **T0 CSS-hash**: the `.direct-tts-controls` styling extends `css/shared/notifications-surface.css` (mandate #3) — hash-gate the shared sheet.
- **T1 DOM-contract**: input + 4 buttons with the named testids; standalone `#direct-tts-pane` distinct from `#tts-pane`.
- **T2 computed-style**: flex row (gap/alignment) vs legacy `.audio-controls` (`notifications.html:1142`).
- **T3 geometry**: pane placement + control row dimensions; gate-state presence/absence.
- **T4 pixel backstop**: ONE new golden capture of the controls row (gate-on). **Legacy `:8000` capture cost**: the legacy `#section-direct-tts` is inside a collapsible section — capturing the legacy baseline requires expanding it; budget one legacy capture. If §8 ⇒ debug-gated-off-in-prod, the prod visual baseline is "pane absent" (no new golden needed for the default prod build) and the gate-on golden lives in the dev/debug snapshot set.

## 8. Risks & open questions (for reviewers)

1. **★ Ship-visible vs debug-gated (the headline decision).** Audit row 12 explicitly flags "decide if a dev harness belongs in the prod mux UI." Options: (a) ship visible (full section-toolbar parity, simplest, but a synth-arbitrary-text box in prod is an odd user surface + a small abuse/cost vector — anyone can spam TTS synthesis); (b) debug-gated (URL `?debug=1` / `window.__LUPIN_DEBUG__` / server `multiplexer_dev_tools` INI flag) — keeps prod clean, matches the harness's true nature; (c) admin-gated (JWT role check) if it should be reachable in prod-by-admins. **Recommendation: (b) debug-gated**, with the gate mechanism itself an open item (config-flag is most testable; mirrors the `tts_preview_fraction` server-config fetch at `boot.ts:182`). This choice cascades into §5.5/§5.6/§7 (whether a section-toolbar entry + prod golden exist at all).
2. **Strict 13/13 parity vs the gate.** Ruling (g) says "No 'obsolete' drops — strict total parity." A debug-gated harness is *present but hidden in prod* — does that satisfy "13/13 parity," or does parity demand it be visible like legacy (where it IS visible, just inside a collapsed section)? Reviewer call: I read debug-gating as parity-satisfying (the capability exists; legacy also hid it behind a collapse) — confirm.
3. **`X-Session-ID` header.** Legacy sends both body `session_id` AND an `X-Session-ID` header (`notifications.js:4283`). Confirm `/api/get-speech*` route chunks correctly with body-only (the mux `ApiClient` has no per-call header hook today). If the server requires the header, add a minimal `headers` option to `ApiClient` — small scope creep to flag.
4. **Mode default for Speak-Now.** Legacy reads the shared `#tts-mode` select; mux has none. Recommendation: Speak-Now = instant (legacy `TTS_MODE_DEFAULT`). Acceptable, or should the harness carry its own 2-state mode toggle?
5. **Cache bypass.** §2 OUTs `TtsAudioCache` integration so every probe is a true synthesis. Confirm a dev harness should always hit the server (recommended) vs honor the cache.

## 9. Lane decomposition & estimate

**Single small lane** (one worktree) — this is the lowest-build absent accordion (~40-60 LOC of harness + a thin `ApiClient` method + template). Internal ordering: §5.1 decision → §5.3 `ApiClient.requestSpeech` (independently unit-testable) ∥ §5.2 template → §5.4 renderer → §5.5 boot+gate → §5.6 toolbar.

**Convergence files (manager-serial-merged, mandate #5)**: `boot.ts`, `multiplexer.html`, `sectionToolbar.ts`, `ApiClient.ts`, `css/shared/notifications-surface.css`. All low-conflict (append-only mount slot + one toolbar entry + one interface method); merge after the heavier `02`/`03`/`04` lanes land to absorb their `boot.ts`/`sectionToolbar.ts` deltas.

**Rough size**: new TS ~120-180 LOC incl. tests' fixtures; production-source ~70-100 LOC. Smallest of the 7 absent ports. Front-end only; zero backend.

**Doc touchpoints (mandate #7)**: per CLAUDE.md §DOCUMENTATION TOUCHPOINTS — no `routers/*` change (endpoints pre-exist, `/docs` unaffected). Update this milestone's own discrepancy→remediation doc + the parity contract; if a `multiplexer_dev_tools` INI flag is added, document it in `lupin-app-splainer.ini` and note the gate in `src/docs/websocket-configuration.md` (TTS path) — TBD on §8 outcome.
