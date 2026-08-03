# Time Saved Dashboard — Build Plan (accordion #10, TRULY ABSENT → build)

**Date**: 2026-06-26 (this session, for Rick)
**Status**: 🟡 **DRAFT for cascaded review** — not yet ratified; cascaded review is the gate before any implementation.
**Author**: section-time-saved lane (this session)
**Source-audit refs**: `04-remaining-accordions-audit.md` §Master-verdict row #10 + §Detail "#10 Time Saved" (lines 96–99); index `00-plans-index.md` row 07.
**Decision-of-record refs**: ruling **(g)** "Port ALL 7 absent accordions → total 13/13 parity" (`04-…-audit.md` §Resolved, lines 135–137); sequenced AFTER CC-session (`01-`) + the 3 partials. TODO Decisions Log 2026-06-26.

> Inherits all 7 cross-cutting mandates from `00-plans-index.md §"Cross-cutting mandates"` (100% L/B/F · Layout-Parity Oracle T0–T4 · single-source CSS · venue routing · manage-don't-build/lane isolation · coordinate-with-in-flight-crews · doc touchpoints). They are **referenced, not restated** here.

---

## 1. Goal & parity target

Restore the legacy **⏱️ Time Saved Dashboard** accordion (`notifications.html:1036-1066`) into the multiplexer as a self-owned, read-only, poll-driven pane: a 4-cell stats grid (Time Saved You / for Others / Solutions Created / Cache Hits You) plus a "🏆 Most Helpful Solutions" leaderboard. "Done" = a `#time-saved-pane` that, on the SAME two existing endpoints the legacy uses, paints the identical 4 stats + ranked leaderboard, with a section-toolbar visibility toggle, ⟳ refresh, and an "updated HH:MM:SS TZ" stamp — visually at parity with legacy under the Oracle tiers.

## 2. Scope

**IN**
- New `TimeSavedStore` (fetch + cache + 60s poll + emit; the `FleetStatusStore` poller idiom).
- New `TimeSavedRenderer` (owns its `#time-saved-pane` subtree: header chrome + stats grid + leaderboard container; repaints on store change).
- New EventBus event type `store_time_saved_changed` (payload `{ stampUpdated }`, mirroring the fleet/task-list payload shape).
- New `#time-saved-pane` `<section>` mount point in `multiplexer.html`.
- `boot.ts` wiring: construct renderer, mount, `startPolling()` AFTER mount (off the WS transports — Cheech's rule), add to `boot_complete` handler manifest + console line.
- `createStores()` registration in `stores/index.ts` (+ `StoreSet` field + `CreateStoresOptions.api` widening note).
- New section-toolbar toggle entry for `time-saved-pane` in `SECTION_TOGGLES` (`render/templates/sectionToolbar.ts`).
- New shared-CSS block (`stats-grid` / `stat-item` / `stat-value` / `stat-label` / `top-solutions` / `top-solution-item` / `rank` / `question` / `stats` / `no-data`) extending the single-source sheet; a thin `css/multiplexer/time-saved.css` for pane-shell adaptation only.
- HTML-escaping of `question` text in the leaderboard (legacy uses `escapeHtml`; mux uses `textContent`/the `html` tagged-template — no `innerHTML` of untrusted strings).

**OUT**
- Any backend change. Both endpoints (`GET /api/stats/time-saved`, `GET /api/stats/time-saved/global`) already exist and are unchanged — `src/cosa/rest/routers/stats.py:60-198`. No new INI keys.
- The `days=30` query-window selector UI (legacy hard-codes the default 30-day window via the endpoint default; no UI control exists in legacy to port).
- Real-time/WS reactivity — this pane is poll-only by design (matches legacy's manual-refresh + init-call model; promoted to a 60s auto-poll for parity with the other read-only mux pollers).

**Ratified ruling this executes**: (g) total 13/13 parity, build the absent #10.

## 3. Source anchors

### Legacy (reference behavior — do NOT edit)
| Concern | Anchor |
|---|---|
| Accordion HTML (stats-grid + leaderboard) | `static/html/notifications.html:1036-1066` |
| Stat element ids | `#time-saved-total`, `#time-saved-others`, `#solutions-created`, `#replays-benefited` (`:1045,1049,1053,1057`) |
| Leaderboard ids | `#top-solutions-container`, `#top-solutions-list` (`:1061,1063`) |
| `data-testid`s | `notifications-time-total` / `-time-others` / `-solutions-created` / `-replays-benefited` / `-top-solutions` (`:1045-1063`) |
| Fetch + paint | `notifications.js refreshTimeSavedStats()` ~`8401-8455` (GETs `/api/stats/time-saved` + `/api/stats/time-saved/global`) |
| Leaderboard render | `notifications.js renderTopSolutions()` ~`8457-8484` (rank · escaped question · "N replays · X saved"; empty → "No replayed solutions yet") |
| Init call | `notifications.js` ~`:534` |
| Legacy CSS | `static/css/notifications.css:4403-4485` (`.stats-grid`/`.stat-item`/`.stat-value`/`.stat-label`/`.top-solutions h4`/`.top-solution-item`{`.rank`,`.question`,`.stats`}/`.no-data`) |

### Backend (existing — unchanged, reference for response shape)
| Field consumed | Source |
|---|---|
| `total_time_saved_formatted`, `time_saved_for_others_formatted`, `solutions_created`, `total_replays_benefited` | `stats.py:65-135` (`get_time_saved_stats`) |
| `top_solutions[] = { question, replays, time_saved_formatted }`, `total_solutions`, `total_replays` | `stats.py:143-198` (`get_global_time_saved_stats`) |

### Mux targets (add / edit)
| File | Add/Edit | What |
|---|---|---|
| `js/multiplexer/stores/TimeSavedStore.ts` | **ADD** | poller store (model on `stores/FleetStatusStore.ts`) |
| `js/multiplexer/render/TimeSavedRenderer.ts` | **ADD** | DOM-owning renderer (model on `render/FleetStatusRenderer.ts`) |
| `js/multiplexer/render/timeSavedModel.ts` | **ADD** | pure formatters/shape types (mirror `render/fleetModel.ts` split) |
| `js/multiplexer/render/templates/timeSavedGrid.ts` | **ADD** | stats-grid + leaderboard template fns (mirror `templates/fleetStatusTable.ts`) |
| `js/multiplexer/shared/types.ts` | **EDIT** | add `store_time_saved_changed` to the event-type union (~`:125`) + `StoreTimeSavedChangedPayload` (~`:810`) |
| `js/multiplexer/stores/index.ts` | **EDIT** | `StoreSet.timeSaved` field; construct in `createStores()`; add to return tuple (~`:88,155,165`) |
| `js/multiplexer/render/templates/sectionToolbar.ts` | **EDIT** | append `time-saved-pane` toggle to `SECTION_TOGGLES` (~`:35-42`) — **convergence file** |
| `js/multiplexer/boot.ts` | **EDIT** | construct + mount + `startPolling()`; `boot_complete` manifest + console line (~`:498-505,575,603`) — **convergence file** |
| `html/multiplexer.html` | **EDIT** | new `#time-saved-pane` `<section>` + stylesheet `<link>` (~after `:207` task-list-pane) — **convergence file** |
| `css/shared/notifications-surface.css` | **EDIT** | new shared block (port `notifications.css:4403-4485`) — **convergence file (single-source)** |
| `css/multiplexer/time-saved.css` | **ADD** | pane-shell adaptation only (header layout); never fork shared rules |

## 4. Dependencies & prerequisites

- **No cross-plan prereq.** Unlike #3/#4 (`AudioStore` multi-item) this needs no store extension — it is purely additive and read-only. Can land independently of plans 01–06.
- **Endpoints**: both already live; `current_user`-authed (`Depends(get_current_user)`). The mux `ApiClient.get<T>` already throws `ApiError`-with-`.status` on non-2xx → reuse the `FleetStatusStore.fetchState()` 401→sentinel / other→sentinel mapping.
- **`CreateStoresOptions.api`** already types as `ActionRequiredApiClient & FleetApiClient & TaskListApiClient` (`stores/index.ts:105`); `FleetApiClient` is `{ get<T>(path): Promise<T> }` — the new store's API surface is a structural subset, so **no widening of the production `api` type is required** (document this; reviewers tend to ask).
- **INI**: none.
- **Coordinate with in-flight crews** (`00-index §mandate 6`): `boot.ts`, `multiplexer.html`, `shared/types.ts` union, `sectionToolbar.ts SECTION_TOGGLES`, and `css/shared/notifications-surface.css` are **manager-serial-merged convergence files**. Rachel's `mux-section-toolbar-accordion-toggle` branch owns `SECTION_TOGGLES` — the new toggle entry must rebase on her landed list (today: notifications/jobs/commons/tts/fleet/task-list → this adds a 7th).

## 5. Work breakdown

> Oracle tier legend per node: **T0** CSS-hash · **T1** DOM-contract · **T2** computed-style · **T3** geometry · **T4** pixel backstop (`00-index §mandate 2`).

### WI-1 — Event type + payload (shared/types.ts)
- **What**: add `"store_time_saved_changed"` to the event-type string union (~`:125`, alongside `store_fleet_status_changed`); add `export interface StoreTimeSavedChangedPayload { stampUpdated: boolean }` (~`:810`, mirroring `StoreFleetStatusChangedPayload`).
- **Files**: `shared/types.ts`.
- **ACs**: (functional) the bus emit/on round-trips the new type; (structural) payload shape === `{ stampUpdated: boolean }`; union member present.
- **Oracle**: n/a (type-only) — gated by `c8 --100` on consumers.

### WI-2 — Pure model + formatters (render/timeSavedModel.ts)
- **What**: type the two response shapes (`UserTimeSaved`, `GlobalTimeSaved` with `top_solutions: TopSolution[]`); a pure `normalizeStats()` that maps missing/`undefined` fields to the legacy fallbacks (`'--'` for the two formatted strings, `0` for the two counts — verbatim `notifications.js:8432-8435`); a pure `selectTopSolutions()` returning `[]` on null/empty (drives the "No replayed solutions yet" branch). No DOM, no fetch.
- **Files**: `render/timeSavedModel.ts`.
- **ACs**: (functional) fallback mapping matches legacy exactly incl. the `solutions_created || 0` / `total_replays_benefited || 0` zero-coalesce; empty/null leaderboard → `[]`; (structural) module is DOM-free + fetch-free (mirrors `fleetModel.ts`).
- **Oracle**: n/a (pure) — 100% L/B/F by unit test incl. every fallback branch.

### WI-3 — Templates (render/templates/timeSavedGrid.ts)
- **What**: `renderStatsGrid(stats)` → `.stats-grid` with the 4 `.stat-item`s carrying the legacy `data-testid`s and `.stat-value`/`.stat-label`; `renderTopSolutions(list)` → `.top-solutions` (h4 "🏆 Most Helpful Solutions") + `#top-solutions-list`-equivalent container with one `.top-solution-item` per row (`.rank` `#N` · `.question` · `.stats` "N replays · X saved") OR the `.no-data` "No replayed solutions yet" paragraph when empty. Use the `html` tagged-template / `textContent` for `question` (XSS-safe equivalent of legacy `escapeHtml`).
- **Files**: `render/templates/timeSavedGrid.ts`.
- **ACs**: (functional) rank is 1-based; "N replays · X saved" string composes from `replays` + `time_saved_formatted`; empty → exactly one `.no-data`; question never interpolated as raw HTML; (structural) emitted class names + `data-testid`s are byte-identical to legacy `notifications.html:1043-1064`.
- **Oracle**: **T1 DOM-contract** (every `data-testid` + class present, correct nesting) gates this node; **T0 CSS-hash** confirms class names resolve to the shared sheet.

### WI-4 — Store (stores/TimeSavedStore.ts)
- **What**: carbon of `FleetStatusStore` poller: `lastUser`/`lastGlobal` caches, `inFlight` debounce guard, `refresh()` = two `api.get` calls (user then global) → cache → `emitChanged(true)`, `startPolling()`/`stopPolling()` on a 60s interval (immediate refresh + `setInterval`), injectable `nowFn`/`setIntervalFn`/`clearIntervalFn`/`api`. Map `ApiError.status===401`→an `auth_required` sentinel and any other error→an `unreachable` sentinel (renderer paints sign-in / offline messages). Both endpoints are independent — a failure of the global call must NOT blank the user stats (mirror legacy: it logs and proceeds), so cache each leg independently.
- **Files**: `stores/TimeSavedStore.ts`. Export `TIME_SAVED_USER_ENDPOINT`/`TIME_SAVED_GLOBAL_ENDPOINT`/`TIME_SAVED_POLL_INTERVAL_MS = 60000`.
- **ACs**: (functional) in-flight debounce blocks double-fetch; 401→auth sentinel; non-401→unreachable sentinel; global-leg failure leaves user-leg cache intact; `startPolling` idempotent; `stopPolling` idempotent; (structural) store is DOM-free, emits only `store_time_saved_changed`, subscribes to NO server frames (poll-only, like fleet).
- **Oracle**: n/a — 100% L/B/F by unit test with fake api + fake timers (`fleet_status_store.test.ts` is the template).

### WI-5 — Renderer (render/TimeSavedRenderer.ts)
- **What**: DOM-owning renderer modeled on `FleetStatusRenderer`. `mount(root)` builds chrome once — `<header>` (title "⏱️ Time Saved Dashboard" · ⟳ refresh button wired to `store.refresh()` · "updated …" stamp span) + a stats-grid container + a leaderboard container — then `renderFromStore(false)`, then subscribes `store_time_saved_changed`. Dispatch states: auth_required → sign-in message; unreachable → offline message; ready → paint `renderStatsGrid` + `renderTopSolutions`. `stampUpdated` re-stamps "updated HH:MM:SS TZ" (reuse the fleet timestamp formatter or a shared `render/time.ts` helper). Throw on double-mount; idempotent `unmount()`; `forceRenderForTesting()`.
- **Files**: `render/TimeSavedRenderer.ts`.
- **ACs**: (functional) 3-state dispatch; ⟳ calls `store.refresh()`; stamp only on `stampUpdated===true`; double-mount throws; unmount detaches subscription + clears subtree; (structural) renderer OWNS `#time-saved-pane` subtree (builds chrome, not pre-existing ids) — JobsPane/Fleet "renderer owns its DOM" convention.
- **Oracle**: **T1** (chrome contract: header/title/refresh/stamp/containers) + **T2 computed-style** (stat-value font-size/weight, grid gap) gate this node; **T3 geometry** on the 4-up grid cell layout; **T4 pixel backstop** on the assembled pane vs legacy capture.

### WI-6 — Store registration (stores/index.ts)
- **What**: add `timeSaved: TimeSavedStore` to `StoreSet`; `const timeSaved = createTimeSavedStore({ bus: opts.eventBus, api: opts.api })` in `createStores()` appended after the Lane-E quartet (order-neutral — no server-frame subscription); add to the return tuple. Update the StoreSet count comment.
- **Files**: `stores/index.ts`.
- **ACs**: (functional) `createStores()` returns a usable `timeSaved`; does NOT start polling here (boot owns that — Cheech's rule); (structural) subscription order of the pinned five is unchanged.

### WI-7 — Section-toolbar toggle (CONVERGENCE)
- **What**: append `{ sectionId: "time-saved-pane", icon: "⏱️", title: "Time Saved", testid: "multiplexer-section-toolbar-time-saved" }` to `SECTION_TOGGLES` (order: place after `task-list` to follow page vertical order). No renderer logic change — `SectionToolbarRenderer` already drives any `data-section` generically via `ViewStateStore`.
- **Files**: `render/templates/sectionToolbar.ts` (**manager-serial-merge**; rebase on Rachel's landed list).
- **ACs**: (functional) clicking the toggle flips `#time-saved-pane.section-hidden` + persists via `ViewStateStore`; persisted-hidden replays on mount; (structural) new spec carries all four fields incl. `data-testid`.
- **Oracle**: **T1** (toolbar button present with `data-section="time-saved-pane"`).

### WI-8 — HTML mount point (CONVERGENCE)
- **What**: add `<section id="time-saved-pane" data-testid="multiplexer-time-saved-pane"></section>` after the task-list-pane section (~`multiplexer.html:207`); add `<link rel="stylesheet" href="/static/css/multiplexer/time-saved.css">` in the head (~`:20` block).
- **Files**: `html/multiplexer.html` (**manager-serial-merge**).
- **ACs**: (structural) empty section element present with correct id + testid; stylesheet linked.

### WI-9 — Boot wiring (CONVERGENCE)
- **What**: construct `createTimeSavedRenderer({ eventBus, stores: { timeSaved: stores.timeSaved } })`, resolve `#time-saved-pane` (throw if null), `mount()`, then `stores.timeSaved.startPolling()` AFTER mount (off the WS transports). Add `timeSavedRenderer: "mounted"` to `bootCompletePayload.handlers` + a `console.log("[multiplexer] timeSavedRenderer:mounted")` line (after `taskListRenderer`).
- **Files**: `boot.ts` (**manager-serial-merge**).
- **ACs**: (functional) renderer mounts before `startPolling`; transports still start AFTER all renderer mounts; (structural) `boot_complete` manifest + console line present.

### WI-10 — CSS port (CONVERGENCE / single-source)
- **What**: port `notifications.css:4403-4485` into `css/shared/notifications-surface.css` as a new block (`.stats-grid`, responsive `@media` collapse, `.stat-item`, `.stat-value`, `.stat-label`, `.top-solutions h4`, `.top-solution-item`(+`.rank`/`.question`/`.stats`), `.no-data`). Legacy must continue to resolve these — confirm legacy links the shared sheet BEFORE its monolith so the shared block wins / is identical (`00-index §mandate 3`). `css/multiplexer/time-saved.css` holds only the pane-shell header layout adaptation (the mux pane chrome, NOT the grid/leaderboard rules).
- **Files**: `css/shared/notifications-surface.css` (**single-source**) + `css/multiplexer/time-saved.css` (new).
- **ACs**: (structural) zero forked copies of the grid/leaderboard rules; (functional) legacy + mux render the same computed styles.
- **Oracle**: **T0 CSS-hash** on the shared block (legacy ≡ mux source); **T2** on the migrated nodes.

## 6. Test strategy & venue routing

**100% L/B/F mandate** (`00-index §mandate 1`): TS via `c8 --100` (lines + branches + functions); any `c8 ignore` only for genuinely-unreachable defensive branches with a same-line reason (follow the `FleetStatusRenderer`/`Store` `/* c8 ignore next */` precedents for tsx phantom-branch + production-default-fallback lines).

| Layer | Venue | Suite / file | Covers |
|---|---|---|---|
| Unit — store | **:7999** (AI-discretionary) | `src/tests/unit/multiplexer/time_saved_store.test.ts` (NEW; model on `fleet_status_store.test.ts`) | fetch/cache/poll, in-flight debounce, 401→auth & error→unreachable sentinels, independent-leg caching, idempotent start/stop, fake timers |
| Unit — model | **:7999** | `src/tests/unit/multiplexer/render/time_saved_model.test.ts` (NEW) | every fallback branch (`'--'`/`0`), empty-leaderboard `[]` |
| Unit — templates | **:7999** | `src/tests/unit/multiplexer/render/time_saved_grid.test.ts` (NEW) | class names + 5 `data-testid`s, rank 1-based, "N replays · X saved", empty `.no-data`, XSS-safe question |
| Unit — renderer | **:7999** | `src/tests/unit/multiplexer/render/time_saved_renderer.test.ts` (NEW; model on `fleet_status_renderer.test.ts`) | 3-state dispatch, ⟳→refresh, stamp gating, double-mount throw, unmount detach |
| Unit — toolbar | **:7999** | extend `sectionToolbar` template + renderer tests | new `time-saved-pane` toggle spec + toggle behavior |
| Integration (DOM-in-page / boot) | **:8000** (scheduled) | extend `src/tests/integration/` multiplexer boot suite | `#time-saved-pane` mounts, `boot_complete` manifest carries `timeSavedRenderer:mounted`, console line emitted |
| E2E UI + visual | **:8000** (scheduled) | `src/tests/e2e_ui/test_multiplexer_time_saved.py` (NEW; model on `test_multiplexer_fleet_status.py`) | live render against seeded snapshots, toolbar toggle hide/show, ⟳ refresh, visual snapshot vs golden |

**Routing rationale** (`00-index §mandate 4`): pure TS unit/model/template/renderer tests are read-only & fast → **:7999** AI-discretionary. The E2E UI + visual-regression + boot-integration suites need server monopoly + golden snapshots → **:8000** via `POST /api/test-suite/submit` (self-authorized on a verified-idle server; never side-door).

## 7. Oracle & visual parity

- **T0 CSS-hash**: the migrated `.stats-grid`/`.stat-*`/`.top-solution*`/`.no-data` block hashes identically between the legacy monolith source and the shared sheet (single-source proof).
- **T1 DOM-contract**: the 4 stat `data-testid`s + leaderboard `data-testid` + class nesting match legacy `notifications.html:1043-1064` exactly.
- **T2 computed-style**: stat-value typography, grid gap, leaderboard row spacing.
- **T3 geometry**: 4-up grid cell layout + responsive single-column collapse (`@media` at the legacy breakpoint, `notifications.css:4410`).
- **T4 pixel backstop**: assembled `#time-saved-pane` vs a NEW legacy `:8000` golden capture of `#section-time-saved`.
- **New golden captures needed**: (1) legacy `#section-time-saved` baseline (legacy `:8000` capture cost — one capture, two states: populated + empty-leaderboard); (2) mux `#time-saved-pane` rebaseline once the renderer lands. Seed identical snapshot data for both so the diff is style-only.

## 8. Risks & open questions (for reviewers)

1. **Empty-fleet realism for visual goldens** — the leaderboard needs ≥1 replayed solution to render a populated state. Does the `:8000` test snapshot contain replayed solutions, or must we seed `replay_stats`/`replay_history` fixtures? (Determines whether the populated-state golden is capturable at all.) **Open.**
2. **Poll vs manual-refresh fidelity** — legacy refreshes only on init + manual ⟳ click. We promote to a 60s auto-poll for symmetry with fleet/task-list. Is that an accepted enhancement, or should the pane be refresh-only (no timer) to be byte-faithful? Recommendation: auto-poll (consistent mux read-only-pane idiom). **Confirm.**
3. **`time_saved_for_others_formatted` label drift** — legacy label is "Time Saved for Others" but the 4th cell label is "Cache Hits (You)" mapped to `total_replays_benefited` (not a time value). Port the labels verbatim (they are slightly inconsistent in legacy) — flag so reviewers don't "fix" it into a divergence. **Note, not a question.**
4. **`days` window** — endpoint defaults to 30; no legacy UI control. Confirm we ship without a window selector (OUT of scope) and simply consume the default. **Confirm.**
5. **Icon collision** — proposed toolbar icon ⏱️ duplicates the legacy section glyph; fleet uses 🛰️, tts 🔊. No collision with existing `SECTION_TOGGLES` icons, but verify after Rachel's branch lands. **Low.**

## 9. Lane decomposition & rough size

**Suggested parallel lanes** (worktree-isolated per `00-index §mandate 5`):

- **Lane A — core logic (no convergence files)**: WI-1 (types — technically shared/types.ts is a convergence file; treat its union-add as a serial micro-merge), WI-2 (model), WI-3 (templates), WI-4 (store), WI-5 (renderer), WI-6 (stores/index registration) + all four :7999 unit suites. Fully buildable + 100%-coverable in isolation against fakes. **~60–90% of the work.**
- **Lane B — convergence wiring (manager-serial-merge)**: WI-7 (`sectionToolbar` SECTION_TOGGLES), WI-8 (`multiplexer.html`), WI-9 (`boot.ts`), WI-10 (`css/shared/notifications-surface.css` + new `time-saved.css`). Each touches a shared convergence file — manager merges serially after Lane A's renderer/store land and after Rachel's `SECTION_TOGGLES` list is final. **Plus the :8000 E2E/visual + boot-integration suites.**

**Convergence-file callouts** (manager-serial-merged, never parallel-edited): `boot.ts`, `multiplexer.html`, `shared/types.ts` (union), `stores/index.ts` (StoreSet), `render/templates/sectionToolbar.ts` (SECTION_TOGGLES), `css/shared/notifications-surface.css`.

**Rough size**: ~250–350 LOC TS new (store ~140 · renderer ~150 · model ~40 · templates ~70) + ~85 LOC CSS migrated + ~10 LOC HTML/boot wiring; ~5 new test files. Audit's "moderate (~100–150 LOC)" estimate counted only the renderer+store surface; the store/renderer/model/template split + tests roughly doubles it. **Moderate.**

**Doc touchpoints** (`00-index §mandate 7` / CLAUDE.md §DOCUMENTATION TOUCHPOINTS): no `routers/*.py` change → `/docs` unaffected. This is a UI-only port; update the parity-contract / discrepancies doc set for #10 (own discrepancy→remediation doc per `04-…-audit.md §Next` item 3) and run the doc-01 §7–8 live-render diff. No API-reference or websocket-doc change.
