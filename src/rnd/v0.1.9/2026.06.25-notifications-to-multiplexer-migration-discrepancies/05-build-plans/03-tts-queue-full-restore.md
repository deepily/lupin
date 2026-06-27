# TTS Queue — Full 1:1 Restore Plan

**Date**: 2026-06-26 (this session, for Rick)
**Status**: 🟡 **DRAFT for cascaded review** (run on Rick's dev server, not the laptop). Not yet ratified — cascaded review is the gate before any implementation.
**Author**: this session
**Source audit refs**: doc `04-remaining-accordions-audit.md` §"#4 TTS Queue" (detail) + §Resolved design call **(e)**; master verdict row #4 ("⚠️ REMAPPED / PARTIAL").
**Decision-of-record refs**: doc `04` §Resolved **(e)** — "TTS Queue → FULL 1:1 RESTORE (chrome + per-item queue)" (Rick, 2026-06-26 `/plan-decide`); TODO Decisions Log 2026-06-26; through-line TOTAL 13/13 parity.
**Inherits**: all 7 cross-cutting mandates in [`00-plans-index.md`](00-plans-index.md) §"Cross-cutting mandates" (100% L/B/F · Layout-Parity Oracle Tiers 0–4 · single-source CSS · venue routing · manage-don't-build / lane isolation · coordinate with in-flight crews · doc touchpoints). Referenced, not restated.

> Path convention: legacy anchors are written static-relative (`html/notifications.html`, `js/notifications.js`, `css/notifications.css`) — repo root for these is `src/lupin_app/static/`. Mux anchors are static-relative under `js/multiplexer/`.

---

## 1. Goal & parity target

Restore legacy's **per-item TTS playback queue** — a rich collapsible section with header transport (Focus-mode Resume + Pause/Play + Clear-all + live "🔊 Playing: N" count) over an **active-slot** (the currently-speaking item rendered as a full card) plus a **pending-queue** of minimized cards (position badge, type icon, timestamp, truncated text, delete) and an empty state — **while keeping** the multiplexer's two genuine additions: the explicit **Skip** control and the **6-state enable matrix** (`idle/decoding/playing/paused/ended/error`). "Done" = the mux `tts-pane` presents exactly **one** active item as a full card, all other queued items as minimized pending cards in array order, with header chrome and empty state visually + behaviorally at parity with `notifications.html`'s `#tts-queue-section`, driven by a multi-item-aware `AudioStore`.

This is **best-of-both, explicitly NOT either/or**: the per-item queue presentation wraps the existing 6-state transport chrome; the chrome's state matrix and Skip are **not** discarded.

## 2. Scope

This plan executes design call **(e)** verbatim.

**IN**
- **AudioStore multi-item extension** (the gating prereq, §4 + WP1): model a notification-level queue of TTS items (`enqueue / advance / removeById / clear / current / pending`) layered on the existing PCM chunk-stream state machine. Emits new store events so a renderer can paint active + pending. **This is the keystone — everything else depends on it.**
- **Rich section chrome** in `multiplexer.html` + `ttsChrome.ts`: collapsible header carrying `🔊 Playing: <count>`, the Focus-mode **Resume** button, **Pause/Play** pair, **Clear-all** button — alongside the existing **Stop** + **Skip** controls and the 6-state matrix.
- **Active-slot card** template — type icon, timestamp, truncated text (80-char), Stop, delete (`🗑`) — ported from `renderActiveTTSCard`.
- **Pending minimized-card** template — position badge (`#N`), type badge, timestamp, truncated text (50-char), delete (`×`), `.priority` variant for action-required items — ported from `renderMinimizedTTSCard`.
- **Queue reordering / position resync** — DOM order follows queue-array order; position badges renumber after any removal (ported from `reorderTTSQueueDOM` + `updateTTSQueuePositions`). **NB: legacy is strict FIFO with no user drag-reorder — see §8 open question.**
- **Empty state** — "🔇 Nothing in the queue" (`#tts-queue-empty`), shown when section visible but queue empty.
- **Header-state machine** — `🔊 Playing: N` / `Paused: N` (manual pause) / `Paused: N waiting` (Focus mode), + class toggles `.paused` / `.focus-mode`, ported from `updateTTSQueueSection`.
- **Section-toolbar entry already exists** (`tts-pane` is in `SECTION_TOGGLES`) — verify it drives the restored section's visibility correctly.
- **CSS** for active/minimized cards, header transport, empty state, focus/paused header skins — moved into the **shared** surface sheet (single-source mandate), consumed by both legacy and mux.
- Lift `data-phase6-pending="true"` off `#tts-pane` once the restore lands (it is a stub marker today).

**OUT**
- **Direct TTS Test** harness (legacy `section-direct-tts`) — a *different* accordion (#12), its own plan `09-`. Not folded here.
- Rewriting the PCM decode / AudioContext / chunk-streaming internals of `AudioStore` — the chunk-stream state machine is reused as-is; the multi-item queue is layered **on top**, not in place of it.
- Changing the underlying audio scheduling (still sequential one-item-at-a-time playback) — the queue is a *presentation + ordering* model over sequential playback (see §8).
- The `currentTrackName` Phase-0 prereq #3 (`AudioStore.currentNotificationIdHash()`) is **pulled IN** here as part of the multi-item model (the active item now carries its own display text) — noted so reviewers see the prior deferral is resolved, not skipped.

## 3. Source anchors

### Legacy reference behavior (`html/notifications.html`, `js/notifications.js`, `css/notifications.css`)

| What | Anchor |
|---|---|
| Section markup: `#tts-queue-section`, `.tts-queue-header`, `#tts-queue-count`, `#tts-resume-btn`, `.tts-playback-controls` (`#tts-pause-btn`/`#tts-play-btn`), `#tts-clear-all-btn`, toggle | `html/notifications.html:586-628` |
| Body: `#tts-active-slot`, `#tts-pending-queue`, `#tts-queue-empty` | `html/notifications.html:616-626` |
| Queue state: `ttsQueue` array + `activeTTSItem` field | `js/notifications.js:309` (`activeTTSItem`); array used throughout |
| `addToTTSQueue(item)` — FIFO push + activate/minimized-render branch | `js/notifications.js:16506-16539` |
| `renderActiveTTSCard(item)` — full active card (icon/time/text/Stop/delete) | `js/notifications.js:16661-16718` |
| `renderMinimizedTTSCard(item)` — pending card (position/badge/time/text/delete) + reorder call | `js/notifications.js:16721-16786` |
| `updateTTSQueuePositions()` — renumber badges | `js/notifications.js:16789-16797` |
| `reorderTTSQueueDOM()` — DOM children re-sorted to array order | `js/notifications.js:16799-16812` |
| `removeFromTTSQueue(itemId)` — splice + shrink-fade animate-out | `js/notifications.js:16814-16843` |
| `clearTTSQueue()` — empty queue + active, clear DOM | `js/notifications.js:16859-16877` |
| `updateTTSClearAllButtonState()` — show/disable Clear-all | `js/notifications.js:16889-16898` |
| `updateTTSQueueSection()` — section visibility + header-state machine (Playing/Paused/Focus) | `js/notifications.js:16904-16978` |
| `toggleTTSFocusMode()` — manual Resume from Focus mode | `js/notifications.js:17177-17182` |
| `pauseTTS()` / `resumeTTS()` — suspend/resume audio mid-stream | `js/notifications.js:17197-17228` / `:17231-17262` |
| `updateTTSPausePlayButtons()` — pause/play enable states | `js/notifications.js:17264-…` |
| `saveTTSQueueState()` — localStorage persistence | `js/notifications.js:17304-…` |
| CSS: header/active/minimized/empty/focus/paused skins | `css/notifications.css:661` (`.tts-queue-empty-state`), `:3125-3400` (full block) |

### Mux targets (`js/multiplexer/`, `css/multiplexer/`, `html/multiplexer.html`)

| File | Action |
|---|---|
| `stores/AudioStore.ts` | **EXTEND** — add notification-item queue layer (`enqueue/advance/removeById/clear/current/pending`) + new store events. (378 LoC today; single-stream sequential.) |
| `shared/types.ts` | **ADD** — `TtsQueueItem` interface + new store-event payload types (`StoreTtsQueueChangePayload`). `AudioPlaybackState` at `:558`; audio payloads at `:560-566`. |
| `render/templates/ttsChrome.ts` | **EXTEND** — add header transport (Resume/Pause/Play/Clear-all + count), active-slot + pending-queue + empty-state subtrees. Keep 6-state matrix + Skip. (141 LoC; AC2e safe-write invariant — no `.innerHTML`.) |
| `render/templates/ttsActiveCard.ts` | **NEW** — active-slot card template. |
| `render/templates/ttsMinimizedCard.ts` | **NEW** — pending minimized-card template. |
| `render/TtsChromeRenderer.ts` | **EXTEND** — subscribe to new queue-change event; render active/pending/empty; wire Resume/Pause/Play/Clear-all/delete handlers; keep RAF-coalescing. (193 LoC.) |
| `html/multiplexer.html` | **EDIT** — `#tts-pane` at `:186-188` (still `data-phase6-pending="true"`) gains the section structure; lift the stub marker. |
| `render/templates/sectionToolbar.ts` | **VERIFY** — `tts-pane` entry already present at `:39`; confirm it toggles the restored section. |
| `css/shared/notifications-surface.css` | **ADD** (single-source) — port `css/notifications.css:3125-3400` + `:661` card/header/empty styles here; legacy + mux both link it. |
| `css/multiplexer/tts-chrome.css` | **EXTEND** — mux-only layout glue if needed; never fork the shared card styles. |
| `boot.ts` | **VERIFY/EXTEND** — `tts-pane` mount + marker-lift at `:319-331`; thread any new AudioStore queue API through the renderer wiring. |

## 4. Dependencies & prerequisites

**KEYSTONE PREREQ — AudioStore multi-item model (WP1 gates WP2–WP6).** Today `AudioStore` is a **single PCM stream** tracker: its state machine runs `idle→decoding→playing→(paused|ended|error)` over audio *chunks*, and `queueLength()` returns `chunksInBurst` — the count of decoded chunks **in the current burst**, NOT a count of queued notifications (`stores/AudioStore.ts:216-218`). Legacy's `ttsQueue` is an entirely different layer: an array of **notification items** `{ id, ttsText, type, addedAt, notification }` with exactly one `activeTTSItem` audible and the rest pending (`js/notifications.js:16506-16539`). The mux migration ported only the chunk-stream transport; the notification-item queue was never built. **The per-item visualization (active-slot + pending cards + position badges + count + reordering) is impossible until this layer exists.** Hence WP1 is its own early, standalone work item and the merge-gate for the rest.

**Cross-plan coordination:**
- **Plan `02-` (Action Required funnel)** has an explicit dependency *on this plan*: its TTS-coupled activation-deferral (`if (!this.activeTTSItem)` gate, `notifications.js:16038`) is carved OUT of `02-` pending this restore (doc `02` §4 / §8). Land `03-` first, or land the AudioStore item-queue API early enough that `02-` can consume `current()`/`pending()`.
- **`4b33ceb7` focus-bar work** (push held for Rick) and **Tiberius full-parity build** (`704c71b2` / Foundation `3a5d87eb`) touch the mux chrome region; the `#cc-session-strip` / focus controls sit adjacent to `#tts-pane` in `multiplexer.html`. Coordinate header insertion to avoid a layout collision (see mandate 6).
- **Rachel section-toolbar branch** (`mux-section-toolbar-accordion-toggle`, commit-held) owns `sectionToolbar.ts` — the `tts-pane` toggle already exists there; do not re-add it, just verify.

**Carves inherited:** none new. The AR carve belongs to `02-`; this plan must *supply* the `current()`/`pending()` API that lets `02-` eventually close it.

**INI keys / endpoints:** none new. Focus-mode + pause/resume + Clear are all client-side state over the existing audio WebSocket (`/ws/audio/{session_id}`); persistence is localStorage (`saveTTSQueueState`).

## 5. Work breakdown

> Each WP lists: what · files · ACs (functional + structural) · gating Oracle tier(s). 100% L/B/F is assumed on every WP per mandate 1 — not restated per-AC.

### WP1 — AudioStore multi-item queue model **(KEYSTONE; gates WP2–WP6)**
- **What**: Layer a notification-item queue over the existing chunk-stream machine. New private `items: TtsQueueItem[]` + `activeItem: TtsQueueItem | null`. Public API: `enqueue(item)`, `advance()` (active→next), `removeById(id)`, `clearQueue()`, `current(): TtsQueueItem | null`, `pending(): readonly TtsQueueItem[]`, `itemCount(): number` (active + pending, for the header count). Emit a new `store_tts_queue_change` event on every mutation so the renderer repaints. Keep the chunk-stream `state()`/`queueLength()`/`pause()/resume()/skip()/stop()` API intact — the item-queue is additive.
- **Files**: `stores/AudioStore.ts`, `shared/types.ts` (`TtsQueueItem`, `StoreTtsQueueChangePayload`).
- **ACs (functional)**: enqueue appends FIFO; first enqueue with no active item promotes it to active; `advance()` pops next pending → active (or null when drained); `removeById` splices from pending or clears active+promotes-next; `clearQueue` empties both; `current()`/`pending()` reflect state; the existing chunk-stream state machine is unaffected (regression: all current AudioStore tests still pass).
- **ACs (structural)**: new event type registered in `shared/types.ts` + the EventBus union (convergence file — manager-serial-merged, mandate 5); `TtsQueueItem` carries `{ id, ttsText, type, addedAt, notification? }`; `disposeForTesting` clears items.
- **Oracle**: none (pure store; unit-tested). Behavioral foundation only.

### WP2 — Active-slot + minimized-card templates
- **What**: Port `renderActiveTTSCard` → `ttsActiveCard.ts` (icon/time/text-80/Stop/delete) and `renderMinimizedTTSCard` → `ttsMinimizedCard.ts` (position/badge/time/text-50/delete, `.priority` for `action-required`). Use the `html` tagged template + `.textContent` only (AC2e safe-write — no `.innerHTML`, per `ttsChrome.ts:1-7`).
- **Files**: `render/templates/ttsActiveCard.ts` (NEW), `render/templates/ttsMinimizedCard.ts` (NEW).
- **ACs (functional)**: active card renders `⚠️`/`🔔` by type, truncates text >80 to `…`, delete button fires `onDelete(id)`, Stop fires `onStop()`; minimized card shows 1-indexed position, truncates >50, `.priority` class on action-required, delete fires `onDelete(id)`.
- **ACs (structural)**: both templates return a single root `HTMLElement`; carry `data-testid` (`multiplexer-tts-active-card` / `multiplexer-tts-minimized-card`); zero `.innerHTML`/`rawHTML`/`.outerHTML` (grep-verified per AC2e precedent).
- **Oracle**: T1 DOM-contract (node taxonomy matches legacy `.tts-active-card` / `.tts-minimized` children), T2 computed-style (after WP7 CSS).

### WP3 — ttsChrome header transport extension
- **What**: Extend `renderTtsChrome` to emit the rich header: `🔊 Playing: <count>` title, Focus **Resume** button (shown only in focus mode), **Pause/Play** pair, **Clear-all** button — preserving the existing **Stop** + **Skip** + 6-state matrix. Header text + class (`.paused`/`.focus-mode`) follow the legacy header-state machine (`updateTTSQueueSection`).
- **Files**: `render/templates/ttsChrome.ts`, `render/templates/ttsChrome` handler interface (`TtsChromeHandlers` gains `onResume`/`onClearAll`; `onPause`/`onResume`/`onStop`/`onSkip` already present).
- **ACs (functional)**: count = `itemCount()`; header shows `🔊 Playing: N` (normal) / `Paused: N` (manual pause) / `Paused: N waiting` (focus); Resume visible iff focus mode; Clear-all hidden+disabled when no items, shown+enabled otherwise; Pause/Play/Stop/Skip enable per the 6-state matrix (unchanged).
- **ACs (structural)**: matrix table in the file header comment updated to include Resume/Clear-all; `data-state` attribute retained; AC2e safe-write preserved.
- **Oracle**: T1 (header node contract), T2 (header skins playing/paused/focus), T0 CSS-hash on the shared sheet.

### WP4 — TtsChromeRenderer: active/pending/empty wiring
- **What**: Subscribe to `store_tts_queue_change` (in addition to the existing `store_audio_state_change` + `store_audio_chunk_decoded`, all RAF-coalesced). On render: paint header (WP3) + active-slot card (WP2) from `current()` + pending minimized cards (WP2) from `pending()` in array order + empty state when both empty. Reorder/renumber after any change (port `reorderTTSQueueDOM` + `updateTTSQueuePositions` — for the mux this is just re-deriving the pending list from `pending()` on each render, so DOM order = array order for free). Wire handlers: `onResume`→`exitFocusMode`-equivalent, `onClearAll`→`store.clearQueue()`, per-card `onDelete`→`store.removeById(id)`, `onStop`→`store.stop()`, `onSkip`→`store.skip()`, `onPause`/`onResume`→ existing.
- **Files**: `render/TtsChromeRenderer.ts`, `boot.ts` (thread new API if the `AudioStoreLike` interface widens).
- **ACs (functional)**: queue mutation → ≤1 render per RAF tick (storm-safe, existing F-13 coalescing extended to the new event); empty queue → empty-state visible, no cards; N items → 1 active card + (N-1) minimized in order with positions 1..N-1; delete renumbers; clear empties.
- **ACs (structural)**: `AudioStoreLike` interface in the renderer extended with `current()/pending()/itemCount()/enqueue?/removeById/clearQueue`; unmount unsubscribes the new event; mount-twice still throws (F-26 contract).
- **Oracle**: T1 (full pane DOM contract vs legacy `#tts-queue-section` subtree), T3 geometry (active-above-pending stacking).

### WP5 — multiplexer.html section structure + marker lift
- **What**: Replace the bare `<section id="tts-pane" data-phase6-pending="true">` with the section structure the renderer mounts into (the renderer owns the inner DOM via `replaceChildren`, so the HTML change is minimal — mainly removing the stub marker and confirming the mount point). Lift `data-phase6-pending` (boot.ts already does this at `:330-331`; confirm it stays correct).
- **Files**: `html/multiplexer.html:186-188`, `boot.ts:319-331`.
- **ACs (functional)**: `#tts-pane` hidden when section-toolbar toggle off, visible when items exist or toggle on (mirror legacy `updateTTSQueueSection` show-logic); no `data-phase6-pending` remains after mount.
- **ACs (structural)**: `data-testid="multiplexer-tts-pane"` retained; section sits in canonical boot order (notifications → jobs → actionRequired → ttsChrome, `boot.ts:317-318`).
- **Oracle**: T1 (pane presence + toolbar wiring).

### WP6 — Section-toolbar verification
- **What**: Confirm the existing `tts-pane` `SECTION_TOGGLES` entry (`sectionToolbar.ts:39`) shows/hides the restored section as legacy's toolbar button did (`updateTTSQueueSection` reads `.toolbar-btn[data-section="tts-queue-section"]`). No new entry — verify only.
- **Files**: `render/templates/sectionToolbar.ts` (read-only verify), `render/SectionToolbarRenderer.ts`.
- **ACs (functional)**: toggling the 🔊 toolbar button collapses/expands `#tts-pane`; persists per existing toolbar storage.
- **Oracle**: T1.

### WP7 — CSS port to shared surface sheet (single-source)
- **What**: Port `css/notifications.css:661` (`.tts-queue-empty-state`) + `:3125-3400` (header/active/minimized/position/focus/paused/clear-all/shrink-fade) into `css/shared/notifications-surface.css`. Legacy links the shared sheet *before* its monolith (mandate 3); mux consumes it via `tts-chrome.css`. **Never fork** — the mux must not re-declare `.tts-active-card`/`.tts-minimized`.
- **Files**: `css/shared/notifications-surface.css` (ADD), `css/multiplexer/tts-chrome.css` (mux glue only), `css/notifications.css` (remove the moved rules, link shared sheet first).
- **ACs (structural)**: single declaration of each `.tts-*` card class repo-wide (grep: exactly one source); T0 CSS-hash equal across legacy + mux for the shared block.
- **Oracle**: T0 (CSS-hash), T2 (computed-style parity), T4 pixel backstop (rebaseline — see §7).

## 6. Test strategy & venue routing

**TS unit (vitest + `c8 --100`) — :7999 / laptop-local, AI-discretionary:**
- `src/tests/unit/multiplexer/stores/audio_store.test.ts` — **extend** for WP1: enqueue/advance/removeById/clearQueue/current/pending/itemCount + new `store_tts_queue_change` emission + regression that the chunk-stream machine is unchanged.
- `src/tests/unit/multiplexer/render/templates_tts_active_card.test.ts` (NEW), `…/templates_tts_minimized_card.test.ts` (NEW) — WP2 templates incl. AC2e safe-write grep.
- `src/tests/unit/multiplexer/render/templates_tts_chrome.test.ts` — **extend** for WP3 header transport + matrix (existing file at `src/tests/unit/multiplexer/render/`).
- `src/tests/unit/multiplexer/render/tts_chrome_renderer.test.ts` — **extend** for WP4 active/pending/empty render + storm coalescing of the new event + handler dispatch.
- 100% L/B/F (lines + branches + functions); `c8 ignore` only for genuinely-unreachable defensive branches with same-line reason.

**Python smoke (:7999):** none required — TTS queue is client-side. Optional inline check that `/ws/audio` still streams (existing websocket smoke covers transport).

**WebSocket smoke (:7999):** `src/scripts/run-websocket-smoke-tests.sh` — confirm audio-channel events still deliver after AudioStore widening (no regression).

**E2E UI + visual (:8000, scheduled via `POST /api/test-suite/submit`, self-authorized on verified-idle):** Playwright functional spec exercising enqueue→active→skip→delete→clear→empty + focus/pause header states; visual regression against the rebaselined golden (§7). Submit per mandate 4 / CLAUDE.md §TESTING VENUES — never side-door.

**Legacy golden capture cost (:8000):** the T4 pixel parity needs a fresh legacy capture of `#tts-queue-section` populated with ≥2 items (active + pending) — legacy capture runs on :8000.

## 7. Oracle & visual parity

Tiers exercised (methodology `2026.06.19-…/01-layout-parity-methodology.md`):
- **T0 CSS-hash** — the shared `.tts-*` block must hash-match between legacy and mux consumers (WP7).
- **T1 DOM-contract** — `#tts-pane` subtree node taxonomy (header transport, active-slot, pending-queue, empty-state, card children) matches legacy `#tts-queue-section` (WP2–WP5).
- **T2 computed-style** — header skins (playing/paused/focus), card spacing, position-badge styling.
- **T3 geometry** — active-above-pending vertical stack; minimized-card row metrics.
- **T4 pixel backstop** — rebaseline the existing `io/test-suite/visual-baselines/test_multiplexer_phase6b_visual/test_multiplexer_phase6b_tts_chrome_visual/multiplexer_phase6b_tts_chrome.png` (currently the transport-only chrome) to the restored per-item queue. **New golden captures needed**: (a) populated queue (1 active + 2 pending), (b) empty state, (c) paused header, (d) focus-mode header. Plus the legacy reference capture (§6, :8000 cost). Rebaseline via `--update-snapshots` after functional pass.

## 8. Risks & open questions (for reviewers)

1. **★ Reorderable queue ↔ sequential audio playback (the headline question).** The ruling (e) lists "reordering" among the restored features, but **legacy has no user-facing drag-reorder**: `addToTTSQueue` is strict FIFO push-to-back (explicit comment `notifications.js:16511-16518` — priority-displacement was *removed* 2026-05-14 because it broke arrival-order mental model), and `reorderTTSQueueDOM` only re-syncs DOM order to the array after a *removal/splice* + renumbers badges. So "reordering" = **position-badge resync on delete**, not drag-and-drop. **Confirm**: does (e) intend (a) faithfully restore legacy's FIFO-with-resync (recommended — matches legacy, low risk), or (b) add NEW user drag-reorder of the pending queue? Option (b) is a genuine feature *beyond* legacy and collides with sequential playback semantics: reordering pending items only changes *what plays next*, never interrupts the active item — workable, but a net-new design needing its own ACs. **Recommendation: option (a)** unless Rick explicitly wants drag-reorder; flag (b) as a separate enhancement.
2. **AudioStore layering risk.** The chunk-stream machine and the notification-item queue are orthogonal: one item's audio = a *burst* of chunks. The active item's `playing/paused/ended` must drive `advance()` (item ends → promote next). Reviewers should confirm the seam: who calls `advance()`? Proposed: the renderer/boot wiring observes `store_audio_state_change → "ended"` and calls `advance()`, mirroring legacy `onTTSPlaybackComplete` (`notifications.js:16989`). This couples the two layers — name it explicitly in review.
3. **Focus-mode semantics.** Legacy Focus mode (`ttsFocusModeActive`) pauses the *queue* (not the audio) while awaiting an action-required response, showing "Paused: N waiting" + Resume. The mux has no `ttsFocusModeActive` flag today. Does the multi-item AudioStore own this flag, or does it stay in a higher coordinator? Proposed: AudioStore owns a `focusMode` boolean alongside the item queue (keeps all queue state in one store). Confirm.
4. **localStorage persistence.** Legacy `saveTTSQueueState` persists the queue across reloads. Does the mux want queue persistence, or is a fresh queue per session acceptable? (Mux stores generally rehydrate from server, not localStorage.) Recommend: defer persistence unless explicitly wanted — flag as a possible OUT.
5. **`data-phase6-pending` lift timing** — confirm lifting the marker doesn't break any test asserting the stub state (grep for the attribute in tests before removing).
6. **Coordination collision** — header insertion near `#cc-session-strip` / focus-bar (`4b33ceb7`, push held) — sequence after the in-flight crews land or coordinate the merge (mandate 6).

## 9. Lane decomposition & estimate

**Suggested parallel lanes** (worktrees; convergence files manager-serial-merged):

| Lane | Scope | WPs | Convergence files (serial-merge) |
|---|---|---|---|
| **L1 — AudioStore (keystone, lands first)** | multi-item queue model + new event | WP1 | `shared/types.ts` + **EventBus union** (manager-merged), `boot.ts` |
| **L2 — templates + CSS** | active/minimized cards, header transport, shared-sheet port | WP2, WP3, WP7 | `css/shared/notifications-surface.css` (shared CSS — manager-merged), `ttsChrome.ts` |
| **L3 — renderer + html + toolbar** | active/pending/empty wiring, section structure, toolbar verify | WP4, WP5, WP6 | `boot.ts`, `multiplexer.html`, `sectionToolbar.ts` (Rachel branch — coordinate) |

**Sequencing**: L1 **must merge before** L3 (renderer consumes the queue API) and before plan `02-` can close its AR carve. L2 can develop in parallel with L1 (templates are pure functions over `TtsQueueItem`, which L1 defines — share the `shared/types.ts` interface early). L3 integrates last.

**Convergence-file callouts** (mandate 5): `shared/types.ts` + EventBus union, `boot.ts`, `css/shared/notifications-surface.css`, `multiplexer.html`, `sectionToolbar.ts` (also touched by Rachel's commit-held branch). All manager-serial-merged.

**Rough size**: ~700–900 LoC TS (AudioStore +~150, two new templates ~120, ttsChrome +~80, renderer +~120) + ~250 LoC CSS (ported, net-near-zero new) + ~600 LoC tests for 100% L/B/F. Medium build — heavier than #3/#9 partials due to the AudioStore architectural extension, lighter than the absent-accordion builds.

**Doc touchpoints** (mandate 7 / CLAUDE.md §DOCUMENTATION TOUCHPOINTS): this is a mux-internal UI restore — no `routers/`/INI/auth docs change. Update the parity discrepancy ledger (this corpus) + the `04` audit row #4 verdict on completion; note the `tts-pane` `data-phase6-pending` lift in the Phase-6b execution log; rebaseline the visual golden (§7).
