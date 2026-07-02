# 08 — Lane 0a + 0c Implementation Log (Rachel 🕊️)

**Date**: 2026-07-02 · **Implementer**: Rachel 🕊️ (session 99376ee8) · **Manager**: Tiberius 👑 (95c8eba0) · **Reviewer**: Clayton-seat
**Governing docs**: [07-cascade-revision-handoff.md](07-cascade-revision-handoff.md) → [06-consolidation-build-plan.md](06-consolidation-build-plan.md) §3 (Lane 0a/0c). Where 06 prose and 07 revision conflict, **07 wins**.
**Worktree**: `lupin-worktrees/lane-0a0c` (branch `lane-0a0c` off `wip-v0.1.9-2026.06.21-bug-fix-implementation`). Validate via unit+c8 IN the worktree (dev :7999 serves MAIN-tree bundle — worktree TS not served).
**Store items**: Lane 0a = `2a73567f`, Lane 0c = `2aad5b7b`.

## Recon — current header state of the 6 accordions (all confirmed by direct read)

| # | Accordion | Renderer | Mount root | Current header | Count el | Collapse today |
|---|---|---|---|---|---|---|
| 1 | Action Required | ActionRequiredRenderer | `#action-required-section` | **NONE** (smoking gun) | — | — |
| 2 | Playing/TTS | TtsChromeRenderer | `#tts-pane` | none (`renderTtsChrome` template) | queue-len chip | — |
| 3 | CC Notifications | NotificationsHeaderRenderer (header) + NotificationsListRenderer (body) | `#notifications-header-mount` (above) + `#notifications-pane` | `.notifications-header` (env-label + 🔔 title + clock) | `.notifications-count` (=list().length) | per sender/date accordion (`data-collapsed`) |
| 4 | Fleet Status | FleetStatusRenderer | `#fleet-status-pane` | `.fleet-status-header` | `.fleet-status-count` | — |
| 5 | Task List | TaskListRenderer | `#task-list-pane` | `.task-list-header` | `.task-list-count` | per-owner (`taskListCollapse.ts`, localStorage) |
| 6 | Jobs | JobsPaneRenderer | `#jobs-pane` | STATIC `.jobs-pane-header` in `multiplexer.html` | — | per-card details |

Each has a DIVERGENT header class (or none) — Lane 0a converges all to the legacy `.section-header` contract.

## Legacy CSS source blocks (verbatim transcription sources — cited per-block)
- **Base cluster** `notifications.css:126-198`: `.section-header` (bg `#e9ecef`, padding 15px 20px, flex space-between, cursor:pointer), `.section-header h3` (`#495057`), `.toggle-button` (+`:hover`), `.section-header-actions`, `.refresh-link` (+states), `.section-content` (+`.collapsed`).
- **AR variant** `notifications.css:509-521`: `#action-required-section` (border 3px `#0d6efd`, bg `#e7f1ff`), `.section-header` bg **BLUE `#0d6efd`** white text. Selector **UNCHANGED** (mux id == legacy id) per 07 §3.A.
- **TTS variant** `notifications.css:2947-2958`: `#tts-queue-section .section-header.tts-queue-header` bg green `#198754` white. **Re-key → `#tts-pane .section-header`** per 07 §3.A.

Port target = **EXTEND `shared/notifications-surface.css`** (WS1 single-source). Port target already has `.collapsible-section{margin-bottom:30px}` (L98) + `.toolbar-btn`/`.task-accordion-btn` (shared). It does NOT yet have the `.section-header` bar cluster — the gap. Krishna (Lane 0b) also edits this sheet (~5409-5640 region, disjoint); fence my blocks with cited headers so Tiberius' merge is a clean concat.

## Mechanism decisions

### Lane 0a — uniform `.section-header` bar
- **Shared helper** `render/templates/sectionHeader.ts` (NEW; grep confirmed no prior-art): `renderSectionHeader({ icon, title, count?, actions?, testid })` → a `.section-header` element = `<h3>` (icon+title) + `.section-header-count` span + optional `.section-header-actions` slot (existing per-renderer controls: refresh/clear/history/updated) + a `.toggle-button` chevron (▼ expanded). One test surface for the contract.
- **Collapse** = session-only `data-collapsed` idiom (AC3; mirrors `NotificationsListRenderer.toggleSenderCard@605`/`toggleDateAccordion@599`). Chevron/header click toggles `data-collapsed` on the section root; CSS hides the `.section-content` body when `[data-collapsed="true"]`. NOT the localStorage `taskListCollapse.ts` (that stays for per-owner rows). NOT persisted.
- **Content wrapper**: each renderer wraps its existing body in a `.section-content` container; header stays a persistent sibling above it (renderers currently `replaceChildren` the root → restructure so the header survives repaints).
- **Counts** (F-Clay-A4): `.section-header-count` span. Notifications = UNREAD count; Jobs = total across the 4 live buckets (todo+running+done+dead, net-new source); others = their existing count semantics.
- Per-renderer: Notifications/Fleet/Task CONVERT their bespoke header → `.section-header` (controls move into `.section-header-actions`); AR/TTS/Jobs GAIN a header bar. Jobs static `.jobs-pane-header` in HTML → replaced by renderer-emitted `.section-header`.

### Lane 0c — ordering & default-visibility
- **multiplexer.html div reorder** → `Action Required → Playing/TTS → CC Notifications → Fleet Status → Task List → Job Queues`. Extract `#action-required-section` OUT of `#notifications-pane` into a standalone **leading** section (CSS is ID-scoped — grep confirmed only a stale comment says "inside #notifications-pane"; safe). `#tts-pane` → **remove `hidden`**. `#jobs-pane` → **add `hidden`**.
- **F13 mount-order invariant PRESERVED**: boot.ts mounts by `getElementById` (order-independent); DOM-div order = visual order only.
- **Visibility precedence (F-Clay-A3)**: HTML `hidden` = cold-start default; persisted user choice (`.section-hidden`) OVERRIDES it. Requires:
  - `ViewStateStore.hasSectionPreference(id)` (NEW, minimal — `id in sectionVisibility`) so mount can tell "no preference (use cold default)" from "explicitly shown".
  - `SectionToolbarRenderer` reconcile at mount: for each toolbar section, effective = preference ? isSectionVisible : !DEFAULT_HIDDEN.has(id); apply `.section-hidden` class AND manage the HTML `hidden` attr (clear on show / set on hide) so a persisted-visible choice actually wins over cold `hidden`; set button `.active` to match. `sectionToolbar.ts` renders the jobs button dimmed by default (cold-hidden).
  - **JobsPaneRenderer** currently `root.removeAttribute("hidden")` on mount (L163, Phase-6a leftover) — REMOVE that strip (keep the `data-phase6-pending` lift) so HTML `hidden` survives as jobs' cold default. Cross-renderer interaction — the plan's "add hidden to #jobs-pane" is a no-op without this.
- **DEFAULT_HIDDEN** = `{ "jobs-pane" }`. AR is NOT toolbar-managed (always-visible leading accordion) — matches legacy default-visible set.

## Sequencing (incremental, reviewable)
1. CSS port into `shared/notifications-surface.css` (cited blocks). ← low-risk foundation
2. Lane 0c (html reorder + SectionToolbar reconcile + ViewStateStore + JobsPaneRenderer strip removal) + tests.
3. Lane 0a shared `sectionHeader.ts` helper + tests.
4. Wire each renderer + collapse CSS + per-renderer test updates → 100% L/B/F (`c8 --100`).

## Progress checklist
- [x] CSS port (base + AR + TTS re-keyed + collapse-hide rule) — shared/notifications-surface.css, fenced+cited. CSS single-source guard: 33/33 green.
- [x] Lane 0c: multiplexer.html reorder + visibility flags (AR extracted leading; TTS unhidden; Jobs hidden). Parity oracle 8/8, header-region placement 6/6 green.
- [x] Lane 0c: ViewStateStore.hasSectionPreference + test — 11/11, c8 100%.
- [x] Lane 0c: SectionToolbar reconcile + sectionToolbar DEFAULT_HIDDEN + tests — 11/11, c8 100% (renderer+template).
- [x] Lane 0c: JobsPaneRenderer hidden-strip removal + test — 36/36, c8 100%.
- [x] Lane 0a: sectionHeader.ts helper + test — 5/5, c8 100%. Exports renderSectionHeader / setSectionCollapsed / wireSectionCollapse.
- [x] Lane 0a: wire ALL 6 renderers + tests — **ActionRequired 44/44 · TtsChrome 22/22 · FleetStatus 18/18 · TaskList 93/93 (3 files) · Jobs 37/37 · NotificationsHeader 24/24 (2 files)** — all c8 --100.
- [x] Full regression sweep: **render-dir 989/989**, view_state_store 11/11, section_toolbar 11/11, Python guards 41/41 (CSS-single-source 33 + parity-oracle 8 + header-region 6). All touched TS at c8 --100. (Non-render store suites = 42 files, unrelated to my changes, not re-run — no dependency on touched modules.)

## STATUS: Lane 0a + 0c BUILD-COMPLETE + GREEN in worktree lane-0a0c. Ready for Clayton's review (0a+0c as one diff). Commit HELD to Tiberius/Rick.

## Lane 0a — DONE. Per-renderer landing notes
- **ActionRequired** (`#action-required-section`): ADD header (⚠️ Action Required), count=item count, content wrapper absorbs pre-seeded Phase-5 widgets (preserves AC2c atomic swap).
- **TtsChrome** (`#tts-pane`): ADD header (🔊 Playing), count=burstLength, chrome → content wrapper.
- **FleetStatus** (`#fleet-status-pane`): CONVERT `.fleet-status-header`→`.section-header` (🛰️), refresh+updated → actions slot, count chip keeps `multiplexer-fleet-status-count` testid, `.fleet-status-container` gains `.section-content`.
- **TaskList** (`#task-list-pane`): CONVERT `.task-list-header`→`.section-header` (📋), refresh+collapse-all+expand-all+updated → actions, container gains `.section-content`. Per-owner ROW collapse (taskListCollapse) untouched.
- **Jobs** (`#jobs-pane`): REPLACE static `.jobs-pane-header` (removed from multiplexer.html; the unwired "Load history" button too) with renderer-emitted `.section-header` (📝), count = **4 live buckets** (todo+running+done+dead, history excluded — F-Clay-A4), `#jobs-buckets-container` gains `.section-content`.
- **NotificationsHeader** (`#notifications-header-mount`, above the pane): CONVERT `.notifications-header`→`.section-header` (🔔), env-label + live clock injected into the h3, history-toggle+clear-all+status → actions, count = **UNREAD** (`store.unreadCount()`, F-Clay-A4 — added to the narrowed interface). Collapse is CROSS-ELEMENT: the chevron toggles `data-collapsed` on the sibling `#notifications-pane` (mux rule `#notifications-pane[data-collapsed="true"]{display:none}` added to `css/multiplexer/notifications-list.css` — NOT the shared sheet, which bars `#notifications-pane`).

## ⚠️ DECISION FLAG for Tiberius/Clayton (count semantics)
NotificationsHeader count: 07 §3.A F-Clay-A4 (+ my crew brief) says **UNREAD** — implemented as `unreadCount()`. BUT the pre-cascade shipped code + its inline comment cited **list().length TOTAL** as "matches legacy notifications.js:15229/15294" (F-Sam-BC3). These conflict. I followed the authoritative 07 handoff / brief (UNREAD). If legacy actually shows TOTAL, this DIVERGES from legacy — needs a ruling. One-line flip if overturned (`unreadCount()` ↔ `list().length`).

## Lane 0a — the wiring PATTERN (proven on ActionRequiredRenderer; apply to the other 5)
1. Import `renderSectionHeader, wireSectionCollapse, type SectionHeaderHandle` from `./templates/sectionHeader`.
2. Add fields: `content: HTMLElement|null`, `header: SectionHeaderHandle|null`, `collapseOff: (()=>void)|null`.
3. In `mount(root)`: build `const header = renderSectionHeader({icon, title, testid, actions?})`; create `content = div.section-content`; **absorb pre-existing children** if the renderer previously rendered into root directly (`content.append(...Array.from(root.childNodes))`); `root.replaceChildren(header.header, content)`; `this.collapseOff = wireSectionCollapse(root, header)`.
4. Repoint every `root.replaceChildren/appendChild/querySelector` for BODY content → `this.content`.
5. Add `updateCount(n)` → `header.setCount(n)` (guard `header!==null` with a c8-ignore — set/nulled in lockstep with content); call it wherever the item count changes.
6. In `unmount()`: call `collapseOff()`; null `content`/`header`.
7. Tests: repoint root-structure assertions; widgets now nest in `.section-content`; add header/count/collapse behavioral tests (mirror the 3 AR "Lane 0a:" tests). c8 --100 per renderer (multi-test-file renderers: include ALL their test files in ONE c8 run — see notifications_list_tts_controls.test.ts:6).

### Per-renderer specifics (icons/titles/counts + structural notes)
- **TtsChromeRenderer** (`#tts-pane`): icon 🔊, title "Playing" (legacy "Playing / TTS"). Count = queue/burst length (`audio.burstLength()`). `renderNow()` does `root.replaceChildren(chrome)` → repoint to `content.replaceChildren(chrome)`; build header+content ONCE in mount, not per-render (currently mount just calls renderNow — restructure so header persists). NO pre-existing children to absorb (fresh pane).
- **JobsPaneRenderer** (`#jobs-pane`): icon 📝, title "Jobs". Count = **total across the 4 live buckets** todo+running+done+dead (F-Clay-A4 net-new source — `ALL_BUCKETS` minus history, sum `jobs.bucket(b).length`). REPLACE the STATIC `<header class="jobs-pane-header">` in multiplexer.html with the renderer-emitted `.section-header` (delete the static header from the HTML; keep #jobs-buckets-container). The "Load history" button → move into the header `actions` slot. mount() currently `root.querySelector("#jobs-buckets-container")` — keep that as the content target (it IS the content); prepend the header as sibling. Careful: jobs is cold-hidden (Lane 0c) — header still builds (hidden pane).
- **NotificationsHeaderRenderer** (`#notifications-header-mount`, ABOVE `#notifications-pane`): CONVERT the existing `.notifications-header` → `.section-header`. icon 🔔, title "Notifications" (keep env-label prefix + live clock in the h3 — special case: the title area already holds env-label + clock spans; put them in the h3 alongside icon/title). Count = **UNREAD** count (F-Clay-A4 — NOT list().length; check NotificationStore for an unread accessor; currently uses list().length at :214 — change to unread). Controls (history-toggle, clear-all, status) → `actions` slot. NOTE: this renderer's header sits in a SEPARATE mount from the notifications body pane, so collapse-on-this-header would need to target `#notifications-pane` (cross-element) — evaluate: may keep collapse OFF for notifications (its body is the sender-cards pane, a different element) OR wire collapse to toggle the sibling pane. Simplest faithful: the notifications accordion header + body are separate divs; wiring collapse to hide `#notifications-pane` is the parity behavior. Decide during wiring.
- **FleetStatusRenderer** (`#fleet-status-pane`): CONVERT `.fleet-status-header` → `.section-header`. icon 🛰️, title "Fleet Status". Count = existing live count (`fleet-status-count`). Controls: ⟳ refresh + updated-stamp → `actions` slot. Body (`.fleet-status-container`) → wrap in `.section-content` (or make the container the content). Straightforward header conversion.
- **TaskListRenderer** (`#task-list-pane`): CONVERT `.task-list-header` → `.section-header`. icon 🗒️, title "Task List". Count = existing count. Controls: ⟳ refresh + collapse-all/expand-all + updated-stamp → `actions` slot. NOTE: TaskList already has per-owner collapse (`taskListCollapse.ts`, localStorage) — that's the ROW collapse, SEPARATE from the section-header collapse (session-only). Keep both.

### Gotchas
- Collapse listener guard ignores `button,a,input,select` clicks — so header ACTION buttons (refresh/clear) won't collapse. The chevron is a `<span>` (collapses). Good for all.
- Each renderer's existing test suite asserts root structure — expect breakage; repoint to `.section-content`. Run c8 including ALL of a renderer's test files.
- CSS `[data-collapsed="true"] > .section-content{display:none}` needs the content wrapper to be a DIRECT child of the element carrying `data-collapsed`. AR/Tts/Jobs/Fleet/Task: `data-collapsed` on the pane root, content is direct child → OK. Notifications: header+body are separate divs — special handling (see above).

## Lane 0c — DONE (pending full-suite confirm). Touched files
- `html/multiplexer.html` — 6-accordion reorder + AR extraction + TTS unhide + Jobs hide (cited Lane 0c block).
- `css/shared/notifications-surface.css` — section-header cluster (also serves Lane 0a).
- `js/multiplexer/stores/ViewStateStore.ts` — `hasSectionPreference()`.
- `js/multiplexer/render/templates/sectionToolbar.ts` — `DEFAULT_HIDDEN_SECTION_IDS` + dimmed cold-hidden button.
- `js/multiplexer/render/SectionToolbarRenderer.ts` — `currentEffectiveVisible` / `applyVisibilityToDom` / `reconcileSectionVisibility` (manages `.section-hidden` + HTML `hidden` in lockstep so persisted-visible overrides cold `hidden`).
- `js/multiplexer/render/JobsPaneRenderer.ts` — stop stripping `hidden` on mount (cross-renderer interaction: the plan's "add hidden to #jobs-pane" is a no-op without this).
- Tests: section_toolbar_renderer / view_state_store / jobs_pane_renderer updated to the new cold-default + precedence semantics.

**Lane 0c open items for Lane 3 / :8000 (NOT unit-coverable here)**: E2E `test_multiplexer_section_toolbar.py` may assert jobs-pane visible-by-default — needs a rebaseline to cold-hidden on the scheduled run; the visual golden reflects the new order. Flagged for the oracle lane.

## Test harness (worktree)
`node_modules` symlinked from main tree. Run: `npx tsx --test "src/tests/unit/multiplexer/render/<file>.test.ts"`. Baseline confirmed: section_toolbar 9/9 green. c8 command TBD (locate the gate invocation).
