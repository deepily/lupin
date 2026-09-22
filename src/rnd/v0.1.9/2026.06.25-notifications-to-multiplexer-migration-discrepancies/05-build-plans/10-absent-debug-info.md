# Debug Info — Build Plan (accordion #13, TRULY ABSENT → build)

**Date**: 2026-06-26 (this session, for Rick)
**Status**: 🟡 DRAFT for the cascaded review (run on Rick's dev server).
**Author**: research/planning pass (absent-accordion lane).
**Source audit refs**: doc `04-remaining-accordions-audit.md` §"#13 Debug Info" (line 113-116) + master verdict row 13 (line 27).
**Decision-of-record refs**: doc `04` §Resolved ruling **(g)** — "Port ALL 7 absent accordions → total 13/13 parity … No 'obsolete' drops — strict total parity." This plan executes (g) for #13.
**Inherits** all 7 cross-cutting mandates from `00-plans-index.md §"Cross-cutting mandates"` — not restated here.

---

## 1. Goal & parity target

Restore the legacy on-page **Debug Information** accordion in the multiplexer: a capped (20-entry,
newest-first), timestamped, monospace, scrollable debug-log panel — `#debug-log.debug-log-scrollable`
holding `.debug-info` rows — fed by a mux-native diagnostic stream. "Done" = a `#debug-pane` section
that renders the same DOM contract / styling as legacy `notifications.html:1153-1163`, capped + ordered
identically to legacy `addDebugMessage` (`notifications.js:15461-15477`), wired into the section-toolbar
as the 7th toggle.

## 2. Scope

The ratified ruling this executes: **(g)** total 13/13 parity — no obsolete drops.

**IN**

- New `#debug-pane` section in `multiplexer.html` containing `#debug-log.debug-log-scrollable`
  (legacy class names VERBATIM so the shared CSS applies identically — mandate 3).
- New `DebugLogStore` — in-memory ring buffer, **cap 20**, **newest-first** (prepend), each entry
  `{ ts, type, message }`; emits a new `store_debug_log_changed` event on every append.
- New `DebugLogRenderer` — subscribes to `store_debug_log_changed`, repaints the capped list.
- New `templates/debugLog.ts` — pure DOM builder for one `.debug-info <type>` row +
  the `.debug-log-scrollable` container, timestamp via `toLocaleTimeString()` (legacy parity).
- New event-type literal `store_debug_log_changed` in `shared/types.ts`.
- 7th `SECTION_TOGGLES` entry (`sectionId: "debug-pane"`) in `templates/sectionToolbar.ts`.
- The two legacy CSS rules (`.debug-info`, `.debug-log-scrollable`, `notifications.css:339-355`)
  lifted into the **single-source shared sheet** (`css/shared/notifications-surface.css`) so legacy
  and mux both consume one copy (mandate 3).
- The diagnostic **event source**: `DebugLogStore` subscribes to a **curated allow-list of existing
  EventBus diagnostic events** (the mux's native diagnostic stream — see §4) and formats each into an
  entry. This is the parity-faithful analogue of legacy's `log()/error()/wsDiag()` feed without a
  call-site retrofit. (Approach choice is a §8 reviewer question.)
- Boot wiring (`boot.ts`): construct store, mount renderer on `#debug-pane`, register subscriptions.

**OUT**

- NO new global `muxLog()` helper and NO migration of the ~65 scattered `console.*` call sites in
  `js/multiplexer/**` (rejected Approach B — see §8). The EventBus IS the diagnostic seam.
- NO log-level filtering, search, export, or copy controls (legacy has none; strict 1:1).
- NO persistence across reloads (legacy debug log is ephemeral; in-memory only).
- NO change to legacy `notifications.js` logging behavior.

## 3. Source anchors

**Legacy (reference behavior — do NOT edit):**

- `html/notifications.html:1153-1163` — `#section-debug` / `#debug-section` / `#debug-log.debug-log-scrollable`
  seeded with one `<div class="debug-info">System starting up...</div>`.
- `js/notifications.js:15461-15477` — `addDebugMessage( message, type='info' )`: `getElementById('debug-log')`,
  `toLocaleTimeString()` timestamp, `div.className = 'debug-info ' + type`, `insertBefore(div, firstChild)`
  (prepend = newest-first), `while (children.length > 20) removeChild(lastChild)` (cap 20).
- `js/notifications.js:15444-15459` — feeders: `log()` (gated on `this.debug`, also `console.log`),
  `error()` (`'ERROR: '+msg`, type `'error'`, also `console.error`), `wsDiag()` (`'WS-DIAG: '+msg`).
- `css/notifications.css:339-355` — `.debug-info` (monospace, 12px, `#6c757d`, `margin-bottom:5px`) +
  `.debug-log-scrollable` (`max-height:300px; overflow-y:auto; padding:10px; bg #f8f9fa; border 1px #dee2e6;
  border-radius:4px; monospace 12px`).

**Mux targets (add / edit):**

- ADD `js/multiplexer/stores/DebugLogStore.ts` (new).
- ADD `js/multiplexer/render/DebugLogRenderer.ts` (new).
- ADD `js/multiplexer/render/templates/debugLog.ts` (new).
- EDIT `js/multiplexer/shared/types.ts:138` — append `| "store_debug_log_changed"` to `LupinEventType`.
- EDIT `js/multiplexer/render/templates/sectionToolbar.ts:35-42` — add 7th `SECTION_TOGGLES` entry.
- EDIT `js/multiplexer/boot.ts` (~line 533, after the section-toolbar block) — construct + mount.
- EDIT `js/multiplexer/stores/index.ts` + `render/index.ts` — export the new factories (barrel pattern).
- EDIT `html/multiplexer.html` (~after line 127, sibling to `#jobs-pane`/`#commons-activity-pane`) —
  add the `#debug-pane <section>`.
- EDIT `css/shared/notifications-surface.css` — add `.debug-info` + `.debug-log-scrollable` (lifted).
- EDIT `html/notifications.html` `<head>` — ensure it links the shared sheet BEFORE `notifications.css`
  (mandate 3: "legacy links it before its monolith") IF not already linked.

**Mux non-source (confirms ABSENT):** the only "debug-logger" hits in the mux
(`transport/AudioTransport.ts:9,36`, `shared/types.ts:581`) are the Phase-3 default **audio binary-chunk**
handler — unrelated to an on-page log. Confirmed: no `#debug-log`, no debug store/renderer exists.

## 4. Dependencies & prerequisites

- **No cross-plan prereq.** Self-contained; does not touch `AudioStore`, `4b33ceb7`, or Plan 01's CC-session
  work. Lowest-coupling member of the corpus.
- **EventBus diagnostic event source** (the heart of the design). The mux has NO centralized logger —
  every module calls raw `console.*` (boot.ts 20×, SequentialAudioManager 18×, TtsAudioCache 12×, etc.).
  Instead of retrofitting a logger, `DebugLogStore` subscribes to a **curated allow-list of already-emitted
  diagnostic EventBus events** and renders them as the debug stream:
  - `connection_state_change`, `connection_reconnecting`, `connection_offline`, `connection_online`
    → the mux analogue of legacy `wsDiag()`.
  - `listener_error` (payload `{ originalEvent, error }`), `refresh_failed`, `hydration_failed`
    → the mux analogue of legacy `error()` (formatted `ERROR: …`).
  - `auth_state_change`, `auth_success`, `transport_ready`, `boot_complete`
    → the mux analogue of legacy `log()` lifecycle chatter.
  The exact allow-list is a **§8 reviewer question** (curate for signal, avoid log-spam from high-frequency
  store events like `store_audio_chunk_decoded`).
- **No INI keys, no endpoints, no backend** — purely client-side; zero new API surface.
- **Carves inherited**: none.

## 5. Work breakdown

### Task 1 — `templates/debugLog.ts` (pure DOM builder)
- **What**: two exported builders: `renderDebugLogContainer()` → a `<div id="debug-log"
  class="debug-log-scrollable">`; `renderDebugEntry({ ts, type, message })` → `<div class="debug-info <type>">`
  with `textContent = `[${ts.toLocaleTimeString()}] ${message}``. No inline HTML injection (use `textContent`
  exactly as legacy — XSS-safe).
- **Files**: `render/templates/debugLog.ts` (new).
- **ACs**: (functional) timestamp format == legacy `toLocaleTimeString()`; `error`-type row gets
  `class="debug-info error"`. (structural) container id/class string-equal to legacy; entry text format
  `[HH:MM:SS] message`.
- **Oracle tier**: **T1 (DOM-contract)** — id `debug-log`, class `debug-log-scrollable`, per-row `.debug-info`.

### Task 2 — `DebugLogStore.ts` (capped ring buffer + emission)
- **What**: `createDebugLogStore({ eventBus })`. State: `entries: DebugEntry[]` (newest-first). Method
  `addEntry(type, message)`: unshift `{ ts: new Date(), type, message }`, **truncate to length 20**
  (`entries.length = 20` after unshift if > 20 — mirrors legacy `while(children>20) remove last`), emit
  `{ type: "store_debug_log_changed", payload: { entries }, source: "DebugLogStore", ts: Date.now() }`.
  `getEntries()` returns a copy. `subscribe()`: register `eventBus.on(...)` for each allow-listed
  diagnostic event (§4), each handler maps the event → `addEntry(level, formattedMessage)`; returns an
  unsubscribe-all teardown.
- **Files**: `stores/DebugLogStore.ts` (new); export from `stores/index.ts`.
- **ACs**: (functional) 21st append drops the oldest; order is newest-first; emits exactly once per append;
  `subscribe()` wires every allow-list event and teardown removes them all. (structural) emits the new
  event type with `changeKind`-free `entries` payload (matches Phase-4 store envelope shape).
- **Oracle tier**: n/a (logic) — covered by unit tests, 100% L/B/F.

### Task 3 — `DebugLogRenderer.ts` (subscribe + repaint)
- **What**: `createDebugLogRenderer({ eventBus, stores: { debugLog } })`. `mount(root)`: throw on
  double-mount (mirror `MissedBadgeRenderer`/`SectionToolbarRenderer` lifecycle), append the
  `renderDebugLogContainer()`, paint current `getEntries()`, subscribe to `store_debug_log_changed` →
  rebuild the container children from the entries array (full repaint; ≤20 rows = cheap). `unmount()`:
  idempotent, drop subscription + clear children.
- **Files**: `render/DebugLogRenderer.ts` (new); export from `render/index.ts`.
- **ACs**: (functional) repaints on event; double-mount throws; unmount idempotent + unsubscribes.
  (structural) DOM under `#debug-pane` == container + N `.debug-info` rows, capped at 20.
- **Oracle tier**: **T1 (DOM-contract)** post-mount.

### Task 4 — `multiplexer.html` `#debug-pane` section
- **What**: add a `<section id="debug-pane" data-testid="multiplexer-debug-pane">` with a
  `<header><h2>Debug Information</h2></header>` (mux idiom: own header, collapse delegated to
  section-toolbar — mirrors fleet-status/jobs panes; NOT the legacy header-click accordion) + an empty
  mount the renderer fills. Placed as a sibling after `#commons-activity-pane` (page-order intuition,
  matches legacy bottom-of-column placement). Seed parity: renderer paints an initial
  `System starting up…`-equivalent entry on mount (legacy seeds `.debug-info` literally).
- **Files**: `html/multiplexer.html`.
- **ACs**: (structural) `#debug-pane` present; contains `#debug-log.debug-log-scrollable`.
- **Oracle tier**: **T1** (presence) + ties into **T3 geometry** (300px max-height scroll).

### Task 5 — section-toolbar 7th toggle
- **What**: add `{ sectionId: "debug-pane", icon: "🐞", title: "Debug Info",
  testid: "multiplexer-section-toolbar-debug" }` to `SECTION_TOGGLES`. The existing delegated click
  handler + `ViewStateStore` persistence pick it up automatically (no renderer change).
- **Files**: `render/templates/sectionToolbar.ts`.
- **ACs**: (functional) toggling dims the button + adds `.section-hidden` to `#debug-pane`, persisted
  via ViewStateStore. (structural) toolbar now renders 7 `.toolbar-btn[data-section]`.
- **Oracle tier**: **T1** (button count/contract) — existing toolbar tests extend by one.

### Task 6 — shared CSS lift
- **What**: move `.debug-info` + `.debug-log-scrollable` rules (legacy `notifications.css:339-355`) into
  `css/shared/notifications-surface.css`; legacy continues to render identically because it links the
  shared sheet (mandate 3). Add the `<link>` to `multiplexer.html <head>` if the shared sheet is not
  already linked there.
- **Files**: `css/shared/notifications-surface.css`; `html/multiplexer.html`; (verify) `html/notifications.html`.
- **ACs**: (structural) one copy of each rule; both pages link the shared sheet; legacy monolith no longer
  re-declares them (or declares them identically — T0 hash check).
- **Oracle tier**: **T0 (CSS-hash)** + **T2 (computed-style)** — monospace/12px/`#6c757d`/300px must match.

### Task 7 — boot wiring
- **What**: after the section-toolbar mount block (`boot.ts` ~533), construct `createDebugLogStore({ eventBus })`,
  call `.subscribe()`, construct `createDebugLogRenderer`, resolve `#debug-pane` (throw if null — matches
  the existing `if (mountEl === null) throw` idiom), `.mount()`. Add the store to the `createStores()`
  aggregate per the established pattern.
- **Files**: `boot.ts`, `stores/index.ts`.
- **ACs**: (functional) on boot the pane is populated as diagnostic events fire; `boot_complete` itself
  appears as the first/seed entry. (structural) no `console.*`-only path — entries route through the store.
- **Oracle tier**: n/a (wiring) — covered by an E2E boot smoke + the boot unit harness.

## 6. Test strategy & venue routing

- **Unit (Vitest + c8, runs in Node — AI-discretionary, no server)** — the bulk of coverage:
  - `debugLog.test.ts`: timestamp format, `.debug-info <type>` class, container id/class, `textContent`
    (no HTML injection).
  - `debug_log_store.test.ts`: cap-at-20 eviction (append 21 → oldest dropped), newest-first order,
    single emission per append, `subscribe()` wires every allow-list event + teardown removes them,
    each diagnostic-event mapping produces the right `level`/message (inject `createEventBusForTesting()`).
  - `debug_log_renderer.test.ts`: mount paints current entries, repaint on `store_debug_log_changed`,
    double-mount throws, unmount idempotent + unsubscribes (happy-dom document).
  - `section_toolbar.test.ts` (existing) extended: 7 toggles, debug entry present.
  - **100% L/B/F** (TS `c8 --100`) — mandate 1. `c8 ignore` only for genuinely-unreachable defensive
    branches with a same-line reason (follow existing tsx phantom-branch pragmas).
- **E2E UI + visual regression** → **:8000 scheduled** via `POST /api/test-suite/submit` (self-authorized
  on a verified-idle server; `list-pending` first; never side-door — mandate 4):
  - Playwright: `#debug-pane` mounts, contains `#debug-log.debug-log-scrollable`; toolbar 🐞 toggle
    hides/shows + persists across reload; entries accumulate + cap at 20 under a scripted event burst.
  - **Visual**: new golden snapshot of the debug pane (see §7) — requires `--update-snapshots` to baseline;
    snapshots are version-controlled.
- **Doc touchpoints** (mandate 7): this accordion's own discrepancy→remediation doc under
  `…/2026.06.25-…-discrepancies/` (per doc 04 §Next item 3); no `src/docs/` API/architecture doc is
  affected (purely client-side, no endpoint/router/INI change).

## 7. Oracle & visual parity

Tiers exercised (methodology `2026.06.19-…/01-layout-parity-methodology.md`):

- **T0 CSS-hash** — `.debug-info` + `.debug-log-scrollable` served from the single shared sheet; hash-match
  the lifted rules against the legacy originals.
- **T1 DOM-contract** — `#debug-log.debug-log-scrollable` container + N `.debug-info` rows, cap 20,
  newest-first; toolbar gains one `.toolbar-btn[data-section="debug-pane"]`.
- **T2 computed-style** — monospace family, 12px, `#6c757d` text, `#f8f9fa` bg, `1px #dee2e6` border,
  4px radius on the legacy reference vs mux.
- **T3 geometry** — `max-height:300px` + `overflow-y:auto` scroll behavior at ≥20 rows.
- **T4 pixel backstop** — OPTIONAL; a single golden of a seeded 3-row state is enough (monospace text on a
  flat panel; low pixel-risk).

**New golden captures**: (1) legacy `:8000` reference capture of `#section-debug` seeded with a few
entries (legacy-capture cost per mandate 2); (2) mux `#debug-pane` baseline via `--update-snapshots`.
Seed both with the SAME deterministic entries (freeze `Date` in the harness) so the timestamp column
diffs clean.

## 8. Risks & open questions (for reviewers)

1. **Is an on-page debug log even wanted?** (Mandated question.) The mux philosophy favors browser
   devtools/console over an in-page log panel; the audit (doc 04:116) calls #13 "very low … likely
   intentional — mux favors devtools/console." Ruling **(g)** is *total* parity, so this plan builds it —
   but the reviewers should explicitly confirm (g) overrides the devtools-preference, or **defer #13 alone**
   as the one sanctioned drop. It is the lowest-value, lowest-risk member of the corpus; deferring it costs
   nothing else.
2. **Event source: Approach A (curated EventBus allow-list) vs Approach B (a `muxLog()` helper +
   migrate ~65 `console.*` call sites).** This plan picks **A** — non-invasive, touches no audio/transport
   internals, treats the EventBus as the mux's native diagnostic stream (the legitimate analogue of
   legacy's `wsDiag/error/log`). **B** is closer to a literal 1:1 of legacy's logger but churns 9+ files
   incl. convergence files and risks log-spam/perf. **Reviewer call**: ratify A, or insist on B for
   literal fidelity?
3. **Allow-list curation** — which EventBus events feed the log (§4 candidate set). High-frequency store
   events (`store_audio_chunk_decoded`, `store_jobs_changed`) would flood a 20-cap buffer into uselessness;
   the list must favor connection/auth/error lifecycle signal. Reviewers should sign off on the final set.
4. **Header-accordion vs section-toolbar toggle** — like every other mux pane, `#debug-pane` delegates
   collapse to the section-toolbar rather than legacy's header-click ▼ (doc 04 §#6 notes the same
   header→toolbar divergence is already accepted fleet-wide). Confirm this is consistent, not a #13-specific
   regression.
5. **Seed entry** — legacy hard-seeds `System starting up…`. Mux has no equivalent literal; plan paints a
   seed entry on mount. Acceptable, or drop the seed (let the first real diagnostic event populate)?

## 9. Lane decomposition & estimate

**Single small lane** — this is the lowest-coupling, lowest-LOC plan in the corpus (~120-160 new TS LOC +
~15 HTML/CSS lines). One engineer end-to-end; no intra-plan parallelism warranted.

**Convergence files (manager-serial-merged — mandate 5):**

- `shared/types.ts` (event union +1 literal),
- `render/templates/sectionToolbar.ts` (`SECTION_TOGGLES` +1),
- `boot.ts` (mount block),
- `html/multiplexer.html` (pane + `<head>` link),
- `css/shared/notifications-surface.css` (lifted rules),
- `stores/index.ts` + `render/index.ts` (barrels).

All six are touched by other corpus plans (esp. types.ts / boot.ts / sectionToolbar.ts / shared CSS) →
the manager merges this lane's edits to them serially. The three NEW files (store/renderer/template) are
lane-private and carry no merge risk.

**Sequencing**: per ruling (g), build **after** CC-session (`03-`) + the 3 partials. Within the absent set
it can land **first or last** — it has no dependency on Q&A / Submit-Jobs / Time-Saved / Filter-Settings /
Direct-TTS / System-Status. Recommend scheduling it **last** so it can be the clean trailing item (or the
deferred one, per §8 Q1).

**Rough size**: ~½-day implementation + ~½-day tests/visual baseline = ~1 day. Smallest in the corpus.
