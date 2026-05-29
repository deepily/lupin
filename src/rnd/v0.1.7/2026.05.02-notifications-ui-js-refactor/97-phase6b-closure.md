# Phase 6b Closure — TTS Chrome + Action-Required Interactive Widgets + Delete-Button Handler

| Field | Value |
|---|---|
| **Initiative** | Multiplexer notifications-UI greenfield rebuild, Phase 6b (per `07-phase6-slicing-manifest.md` slice B) |
| **Phase 6b status** | ✅ **CLOSED 2026-05-12** |
| **Owners (across cycle)** | Mr. Radio 🦉 (`e8228026`) — Q-decisions + REUSE + Pass 1 paused; María (`df880556`) — Pass 1 finish + Pass 2 + Phases 1-4; Rachel 🕊️ (`56ee76d6`, this session) — Phases 5A + 5B + 6 + 7 + 8 + closure |
| **Plan-review pipeline** | CLOSED 2026-05-11 (Q-decisions 12/12, REUSE 28+5, Pass 1 Fitness 14/14, Pass 2 Adversarial 11/11 all closed before code-write started) |
| **Implementation window** | 2026-05-11 (Phases 1-4 by María) + 2026-05-12 (Phases 5A → 8 + closure by Rachel) |

---

## What landed (by phase)

### Phase 0 — Tracking seeds
Plan + execution log seeded; B6a baseline captured = **31,484 bytes** (`boot.65c779ac946b.js` at HEAD `243267b`); AC7 ceiling = **39,676 bytes** (B6a + 8 KB).

### Phase 1 — Store API prereqs (commit `057dbd8`)
| Change | File |
|---|---|
| `respondAndAwait(idHash, response)` + widened `respond()` signature (`string | ReadonlyArray<string> | Record<string,string>`) per Pass 2 A1+A2 | `stores/ActionRequiredStore.ts` |
| `stop()` method + `STOP_REQUESTED` machine event per Pass 2 A6 | `stores/AudioStore.ts` |
| `phase6bOwner` ownership-flag guard (short-circuits read-only path when ActionRequiredRenderer claims the surface) per Pass 2 A3 | `render/NotificationsListRenderer.ts:228` |
| `ActionRequiredState` + `ChangeKind` + `Payload` extensions + NEW `ActionRequiredResponse` type | `shared/types.ts` |
| 22 new unit tests (14 + 6 + 2) — c8 100% maintained on all 3 edited files | tests |

### Phase 2 — Interactive widget templates (commit `ed4fc94`)
| File | LOC | Tests | c8 |
|---|---|---|---|
| `render/templates/actionRequiredInteractive.ts` (NEW) | 228 | 22 | 100% |
| `render/templates/ttsChrome.ts` (NEW) | 147 | 18 | 100% |

AC2e grep-ban on `.innerHTML =` / `rawHTML(` / `.outerHTML =` landed (security-belt per Pass 2 a1). `ActionRequiredItem.multiSelect?: boolean` added per Pass 2 A2.

### Phase 3 — ActionRequiredRenderer (commit `bad00c5`)
NEW `render/ActionRequiredRenderer.ts` (~360 LOC). Five widget builders (`interactive` / `submitting` / `responded` / `expired` / `cancelled`); ownership claim via `dataset.phase6bOwner="true"` BEFORE any DOM write (Pass 2 A3); click → `respondAndAwait` (Pass 2 A1); tick → `.textContent` only (Pass 2 a2 NO-RAF; spy-asserted); inline error stripe on `failed` state. 34 tests; c8 100% with `cssEscape` polyfill `c8 ignore` (NLR.ts precedent).

### Phase 4 — TtsChromeRenderer (commit `bad00c5`)
NEW `render/TtsChromeRenderer.ts` (~155 LOC). Dual-subscription (state_change + chunk_decoded) → shared `pendingRender` flag → single RAF (Q-B9 + Pass 1 F-13). Test-injectable RAF lets storm-safety tests deterministically flush. `replaceChildren` for atomic full-pane swap. 20 tests; c8 100% on first try.

### Phase 5A — JobStore.delete() (commit `118ed10`)
NEW public `delete(idHash): { restoreState: () => void }` on `JobStore`. Captures bucket + index + job, splices out, deletes from `indexById`, emits `removed`. `restoreState` splice-inserts at original idx, restores `indexById`, emits `added` with `to: bucketName`. Nonexistent idHash → no-op closure + zero events. **All 8 DOD rows green** (11 new tests in `jobstore_delete_api.test.ts`).

### Phase 5B — Delete-button click handler (commit `118ed10`)
NEW `JobsPaneApiClient extends JobHistoryApiClient` adding `delete<T>(path)`; production `ApiClient` satisfies structurally. Click delegation dispatches `.job-delete-button` clicks BEFORE the card-header toggle path (preserves Pass 2 F23 invariant under active-button semantics). `handleDeleteClick()` with optimistic-removal + `Set<string> deleteInFlight` for idempotency. `api.delete(/api/queue/${UI_STATUS_TO_SERVER_QUEUE[status]}/${idHash})` where `running → run` legacy maps. 2xx + 404 → discard restoreState (Q-B10); 5xx + non-ApiError Error → `restoreState()` + inline `.job-card-error-stripe` (role=alert, aria-live=polite). `stripInertnessMarkers()` post-renderAll removes `aria-disabled` + `tabindex` + `title` from `.job-delete-button`. **All 11 DOD rows green** (9 new AC5c tests in `jobs_pane_renderer.test.ts`, Tests 21-29).

### Phase 6 — CSS port + page shell + boot wiring
| File | Change |
|---|---|
| `static/css/multiplexer/action-required.css` (NEW) | 295 LOC, ≤500 ceiling ✓, stylelint clean |
| `static/css/multiplexer/tts-chrome.css` (NEW) | 187 LOC, ≤700 ceiling ✓, stylelint clean |
| `.stylelintrc.json` | 2 new `selector-disallowed-list` override blocks (Phase 6b F28 layer-2) |
| `static/html/multiplexer.html` | 2 new `<link>` entries |
| `static/html/dev-tools.html:145` | Phase 6b live-status copy |
| `static/js/multiplexer/boot.ts` | A7/A8 ordering: notifications → jobs → actionRequired → ttsChrome → transports LAST; 4 stable `:mounted` console lines; `#tts-pane` `hidden` + `data-phase6-pending` lift |
| `static/js/multiplexer/render/index.ts` | barrel exports for both new renderers + `JobsPaneApiClient` type |
| `static/js/multiplexer/shared/types.ts` | `BootCompletePayload.handlers` extended with optional `actionRequiredRenderer` + `ttsChromeRenderer` (F11 unconditional, F12 type-optional) |
| `boot.666863463c09.js` (built) | gz = **34,647 bytes** = B6a + 3,163; **5,029 bytes of headroom** vs AC7 ceiling 39,676 |

### Phase 7 — `:7999` smoke + AC10 cross-phase sweep
| File | Change |
|---|---|
| `tests/smoke/test_multiplexer_phase6b_smoke.py` (NEW) | 6 Playwright sub-tests covering AC2a/AC2b/AC8a/AC8b/AC9/AC9b/AC10d. **All 6 PASS in 6.76s on :7999.** |
| `tests/smoke/test_multiplexer_phase5_smoke.py` | AC10e cascade: `pending_count` floor from ≥3 → **==0**; substring-filter tightened from loose `"notificationsRenderer" and "mounted"` → literal `"notificationsRenderer:mounted"` (no quotes between key/value) so the JSON-form boot_complete line isn't double-counted |
| `tests/smoke/test_multiplexer_phase6a_smoke.py` | AC10e cascade: `pending_count` floor from ==1 → **==0** (Phase 6b lifts `#tts-pane`) |

Full cross-phase sweep: tsc clean + eslint clean + stylelint clean + **602/602 multiplexer unit tests pass** + **14/14 Phase 5+6a+6b smoke pass** + AC2e grep-ban green + c8 --100 confirmed across **all 9 Phase 6b-touched TS files** in a single sweep.

### Phase 8 — `:8000` scheduled E2E (AC11a + AC11b)
| File | Change |
|---|---|
| `tests/e2e_ui/test_multiplexer_phase6b_visual.py` (NEW) | 2 Playwright visual tests: `action_required_visual` (3 prompts × 3 response_types, countdown pinned to "5m 0s") + `tts_chrome_visual` (idle chrome) |
| Submitted: `ts-5b88515c` (AC11a baseline, `--update-snapshots -k multiplexer_phase6b`) | 13:35 EDT; result: 2 passed + 2 library-convention "Snapshots updated" errors (expected first-run signal); 2 PNGs written: `multiplexer_phase6b_action_required.png` (24,925 B) + `multiplexer_phase6b_tts_chrome.png` (4,015 B) |
| Submitted: `ts-83e38e5f` (AC11b regression, `-k multiplexer_phase6b` no `--update-snapshots`) | 13:36 EDT; result: **2 passed, 0 errors in 9.9s — AC11 GREEN ✓** |

---

## ACs verified

| AC | Verification | Status |
|---|---|---|
| **AC1** | `npx tsc --noEmit -p tsconfig.json` exit 0 | ✅ |
| **AC2** | `npx eslint src/.../multiplexer/` exit 0 | ✅ |
| **AC2a** | `data-phase6-pending` 0 hits page-wide post Phase 6b mount | ✅ smoke `test_phase6b_no_pending_markers_after_mount` |
| **AC2b** | `aria-disabled="true"` 0 hits inside `.action-required-widget` post-mount | ✅ smoke same test |
| **AC2c** | 1 MutationObserver `childList` entry per widget; 4 markers gone | ✅ unit `action_required_renderer.test.ts` (Phase 3) |
| **AC2d** | `jobstore_delete_api.test.ts` green via `node:test` (plan said vitest; codebase uses tsx --test) | ✅ 11/11 |
| **AC2e** | grep ban on `.innerHTML =` / `rawHTML(` / `.outerHTML =` in interactive template files | ✅ 0 hits (comments-stripped grep) |
| **AC3** | `templates_action_required_interactive.test.ts` ≥15 | ✅ 22/22 |
| **AC4** | `templates_tts_chrome.test.ts` ≥15 | ✅ 18/18 |
| **AC5** | `action_required_renderer.test.ts` ≥21 | ✅ 34/34 |
| **AC5b** | `tts_chrome_renderer.test.ts` ≥13 | ✅ 20/20 |
| **AC5c** | `jobs_pane_renderer.test.ts` ≥6 NEW AC5c cases | ✅ 9 new (Tests 21-29); cumulative 32/32 |
| **AC6** | `c8 --100` on all new + edited multiplexer TS files | ✅ **100/100/100/100 across all 9 files** (3 stores + 4 renderers + 2 templates) in single c8 sweep |
| **AC7** | `boot.js` gz ≤ `B6a + 8192` = 39,676 | ✅ **34,647 B** = B6a + 3,163 (5,029 headroom) |
| **AC8a** | functional smoke + no-pending-markers | ✅ `test_phase6b_functional_smoke` + `test_phase6b_no_pending_markers_after_mount` |
| **AC8b** | perf gate — 50 prompts pre-seed paint <200ms | ✅ `test_phase6b_perf_gate` |
| **AC9** | 4 stable `:mounted` console lines in canonical order (notifications → jobs → actionRequired → ttsChrome) | ✅ `test_phase6b_boot_complete_handshake` |
| **AC9b** | 4 `:mounted` lines BEFORE first `store_audio_chunk_decoded` event | ✅ `test_phase6b_audio_chunks_arrive_after_mount` (synthesized chunk + console-marker probe) |
| **AC10** | Cross-phase regression sweep (tsc + eslint + stylelint + full unit + Phase 5/6a/6b smoke + AC2e + c8 100%) | ✅ all green |
| **AC10b** | `action-required.css` ≤500, `tts-chrome.css` ≤700 + stylelint exit 0 | ✅ 295 + 187 |
| **AC10c** | stylelint scope-leak (layer-2 fail-build rule) | ✅ clean |
| **AC10d** | 3-layer CSS scope-leak detection (grep + stylelint + canary) | ✅ all 3 layers; `test_phase6b_css_canary_no_body_drift` confirms disabling both Phase 6b stylesheets produces zero body-style drift |
| **AC10e** | Phase 5 + 6a `pending_count` regression with **floor=0** | ✅ both updated, both PASS |
| **AC11a** | `:8000` baseline submission via `/api/test-suite/submit` | ✅ `ts-5b88515c`; 2 baseline PNGs on disk |
| **AC11b** | `:8000` regression — visual baselines non-empty + "2 passed, 0 errors" | ✅ `ts-83e38e5f`; 2 passed, 0 errors, 9.9s |

---

## Notable deviations from the original design

### D1 (declared during Phase 5A) — Test path correction
Plan said `src/tests/unit/multiplexer/stores/jobstore_delete_api.test.ts` but existing convention is flat (`job_store.test.ts`, `audio_store.test.ts`, etc. live directly under `src/tests/unit/multiplexer/`; no `stores/` subdir exists; renderer tests live under `render/` subdir). Flat path used. The plan's reference was author-error.

### D2 (declared during Phase 5A) — Test framework reality
Plan referenced `vitest jobstore_delete_api.test.ts`. The codebase uses `tsx --test` (Node's `node:test` runner) per `package.json scripts.test`. All assertions ported to `node:test` style — same coverage surface, same `c8 --100` gate.

### D3 (declared during Phase 5B) — "4 markers" is actually 3 attributes
Plan said: "Strip Q-A6 inertness markers from `.job-delete-button` (4 markers): `data-phase6-pending`, `aria-disabled`, `cursor: not-allowed`, `title=...`". Reality:
- `data-phase6-pending` is on `#tts-pane`, NOT on `.job-delete-button` (template never emitted it there).
- `cursor: not-allowed` is a CSS rule keyed on `[aria-disabled]` — stripping `aria-disabled` lifts the cursor.
- Actual attribute strip = 3: `aria-disabled`, `tabindex`, `title`.

DOM-level test (5B-9) asserts all 3 are gone post-render.

### D4 (declared during Phase 5B) — Dead idempotency branch removed
`renderErrorStripe()` originally had `if (existing !== null) existing.remove()` to handle "stripe already on card" case. But `restoreState()` synchronously emits `added` → `renderAll` rebuilds the card fresh before `renderErrorStripe` runs. The "existing stripe" path is structurally unreachable. Dead branch removed; c8 100% achieved without `c8 ignore` workaround.

### D5 (declared during Phase 5B) — `SimpleApiStub` widened in existing tests
Phase 6b adds `delete<T>` to the renderer's API surface. The existing `SimpleApiStub` in `jobs_pane_renderer.test.ts` was widened (extends `JobsPaneApiClient` instead of `JobHistoryApiClient`) and a default `delete: async () => null` was added to `makeStubApi`. The 4 inline narrow stubs at lines 223/464/509/555 were left as-is because their tests don't dispatch delete events; `tsx --test` doesn't type-check test files (per `tsconfig.json` `include`), so runtime semantics are what matter.

### D6 (declared during Phase 7) — AC10e cascade in Phase 5 boot-handshake test
The Phase 5 `test_phase5_boot_complete_handler_handshake` had a stale loose-substring filter (`"notificationsRenderer" in line and "mounted" in line`) that matched BOTH the stable line AND the JSON-form line. This had been broken since Phase 6a Pass 2 F22 added the stable line; it surfaced only when Phase 6b added more handler entries to the JSON line. Tightened to the literal substring `"notificationsRenderer:mounted"` (no quotes between key/value) so the JSON line is excluded. Filed as part of AC10e cascade cleanup.

### D7 (declared during Phase 8) — TFE auto_fix forgot
AC11a baseline submission did NOT include `auto_fix_on_failure: False`. The library-convention "Snapshots updated" errors tripped the TFE, which expanded scope to `test_doc_viewer_directory.py` (a parallel session's tests) and stalled at the voice gate with a (correctly diagnosed but not-my-problem) proposal awaiting ratification. **TFE `tfe-9751e730` is left for the doc-viewer team to resume.** Memory `feedback_baseline_capture_disable_tfe.md` filed so this isn't repeated a third time (Phase 6a learned, Phase 6b re-learned).

### D8 (carry-over Phase 6a) — `JobHistoryApiClient` interface name
Phase 6b adds `JobsPaneApiClient extends JobHistoryApiClient`. The `JobHistoryApiClient` name no longer fully describes its purpose (it's the hydrate-only surface; delete lives on the extended interface). The split was chosen over renaming + widening to minimize blast radius on `JobStore.hydrateHistory(api)`'s 7 test-stub call sites. Future tidy-up if a naming-cleanup pass is run.

---

## Deferred items (Phase 6c unblock + carry-over)

| Item | Origin | Phase 6c work |
|---|---|---|
| `multiSelect: bool` on `action_required` wire payload | Phase 0 prereq #2 | Server-side notification builder needs to populate `multiSelect` from prompt metadata. Frontend already consumes it via Pass 2 A2 type extension. Verification recon only in Phase 6b; wire-side population is Phase 6c (or earlier server fix once a multiSelect prompt is sent in real traffic). |
| `AudioStore.currentNotificationIdHash` linkage | Phase 0 prereq #3 | Required for `.tts-current-track` to display the real currently-speaking track name. Phase 6b ships with the placeholder template element but never populates it. Phase 6c either adds the linkage on AudioStore OR threads it via a new EventBus event. |
| Phase 6a CoSA `multiplexer_config.py` commit | Phase 0 prereq #5 (carries from Phase 6a) | Server-side commit lives in CoSA. Not a Phase 6b blocker — `boot.ts` falls back to the default cap (256000) if `/api/multiplexer/config` is unreachable. |
| `notifications.py` `response_value` wire-schema acceptance | Pass 2 A2 recon | Recon-only in Phase 6b. If a multi-select / open-ended-batch response is sent in real traffic and the server string-coerces, file CoSA-context task. Tests cover the client-side widening; server-side widening is server-context work. |
| Phase 5 `NotificationsListRenderer.tick` text-node-only contract | Pass 2 noted-out-of-scope | Design-doc citation per Pass 2 noted item; no code change. |

Phase 6c full scope (voice-persona modal + audio recorder + focus tray + conversation-mode UI pin) is independently scoped per the slicing manifest §3 — Phase 6b CLOSE does NOT unblock 6c's design phase, which kicks off whenever the user wants.

---

## Cross-project follow-ups

- **`auto_fix_on_failure: False` for `--update-snapshots` submits** — memory captured at `feedback_baseline_capture_disable_tfe.md`. Re-confirm on every future Phase visual-test baseline.
- **`JobHistoryApiClient` rename** — optional tidy-up if a future naming-cleanup pass runs (rename to `JobsApiClient` or similar; widen the single interface; drop the `extends` layer). Not currently blocking anything.

---

## Files touched (Phase 6b — final)

### NEW (8 files)
- `src/fastapi_app/static/js/multiplexer/render/templates/actionRequiredInteractive.ts` (Phase 2)
- `src/fastapi_app/static/js/multiplexer/render/templates/ttsChrome.ts` (Phase 2)
- `src/fastapi_app/static/js/multiplexer/render/ActionRequiredRenderer.ts` (Phase 3)
- `src/fastapi_app/static/js/multiplexer/render/TtsChromeRenderer.ts` (Phase 4)
- `src/fastapi_app/static/css/multiplexer/action-required.css` (Phase 6) — 295 LOC
- `src/fastapi_app/static/css/multiplexer/tts-chrome.css` (Phase 6) — 187 LOC
- `src/tests/unit/multiplexer/jobstore_delete_api.test.ts` (Phase 5A) — 11 tests
- `src/tests/smoke/test_multiplexer_phase6b_smoke.py` (Phase 7) — 6 Playwright sub-tests
- `src/tests/e2e_ui/test_multiplexer_phase6b_visual.py` (Phase 8) — 2 visual tests
- `src/tests/unit/multiplexer/templates_action_required_interactive.test.ts` (Phase 2) — 22 tests
- `src/tests/unit/multiplexer/templates_tts_chrome.test.ts` (Phase 2) — 18 tests
- `src/tests/unit/multiplexer/render/action_required_renderer.test.ts` (Phase 3) — 34 tests
- `src/tests/unit/multiplexer/render/tts_chrome_renderer.test.ts` (Phase 4) — 20 tests

### MODIFIED
- `src/fastapi_app/static/js/multiplexer/stores/ActionRequiredStore.ts` (Phase 1)
- `src/fastapi_app/static/js/multiplexer/stores/AudioStore.ts` (Phase 1)
- `src/fastapi_app/static/js/multiplexer/stores/JobStore.ts` (Phase 5A)
- `src/fastapi_app/static/js/multiplexer/render/NotificationsListRenderer.ts` (Phase 1)
- `src/fastapi_app/static/js/multiplexer/render/JobsPaneRenderer.ts` (Phase 5B + Phase 6 — barrel)
- `src/fastapi_app/static/js/multiplexer/render/index.ts` (Phase 6 — barrel exports)
- `src/fastapi_app/static/js/multiplexer/shared/types.ts` (Phase 1 + Phase 6 — `BootCompletePayload.handlers` extension)
- `src/fastapi_app/static/js/multiplexer/boot.ts` (Phase 6 — A7/A8 ordering + 2 new mounts + 4-line console contract)
- `.stylelintrc.json` (Phase 6 — 2 new `overrides` blocks)
- `src/fastapi_app/static/html/multiplexer.html` (Phase 6 — 2 new `<link>` entries)
- `src/fastapi_app/static/html/dev-tools.html:145` (Phase 6 — Phase 6b live-status copy)
- `src/tests/unit/multiplexer/stores/action_required_store.test.ts` (Phase 1)
- `src/tests/unit/multiplexer/stores/audio_store.test.ts` (Phase 1)
- `src/tests/unit/multiplexer/render/notifications_list_renderer.test.ts` (Phase 1)
- `src/tests/unit/multiplexer/render/jobs_pane_renderer.test.ts` (Phase 5B — 9 new AC5c tests; Phase 6 — `SimpleApiStub` widened)
- `src/tests/smoke/test_multiplexer_phase5_smoke.py` (Phase 7 — AC10e cascade)
- `src/tests/smoke/test_multiplexer_phase6a_smoke.py` (Phase 7 — AC10e cascade)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/90-execution-log.md` (running execution log — all phase rows + AC scorecard rows ticked)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/09-phase6b-interactive-widgets-design.md` (Phase 0 + plan-review pipeline closures)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/95-phase6b-review-findings.md` (Pass 1 + Pass 2 closures)

---

## Idempotency marker

`phase-6b-closed-at: 2026-05-12 (phases 0-8 all CLOSED; c8 100% on 9 multiplexer TS files; 602/602 unit + 14/14 :7999 smoke + AC11b 2 passed/0 errors on :8000; gz boot.js = 34,647 B = B6a + 3,163, headroom = 5,029)`
