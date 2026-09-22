# Action Required — Funnel-Restore Plan

**Date**: 2026-06-26 (this session, for Rick)
**Status**: 🟡 **DRAFT for cascaded review** (run on Rick's dev server, not the laptop). Not yet ratified — cascaded review is the gate before any implementation.
**Author**: this session
**Source audit refs**: doc `04-remaining-accordions-audit.md` §"#3 Action Required" (detail) + §Resolved design call **(f)**; reconciliation doc `02-reconciliation-with-in-flight-parity-work.md` §4 (inherited AR read-only↔interactive carve).
**Decision-of-record refs**: doc `04` §Resolved **(f)** — "Action Required → FULL FUNNEL RESTORE + rich responder" (Rick, 2026-06-26 `/plan-decide`); TODO Decisions Log 2026-06-26; through-line TOTAL 13/13 parity.
**Inherits**: all 7 cross-cutting mandates in [`00-plans-index.md`](00-plans-index.md) §"Cross-cutting mandates" (100% L/B/F · Layout-Parity Oracle Tiers 0–4 · single-source CSS · venue routing · manage-don't-build / lane isolation · coordinate with in-flight crews · doc touchpoints). Referenced, not restated.

---

## 1. Goal & parity target

Restore legacy's **active/pending one-at-a-time funnel** for Action Required while **keeping** the multiplexer's richer responder engine (explicit state machine · per-item countdown · non-optimistic `respondAndAwait` submit). "Done" = the mux section presents exactly **one** fully-interactive item in an active slot, all other prompts as **minimized pending cards with position badges**, plus the section chrome legacy had — collapsible header, live `count`, "✓ No pending actions" empty state, keyboard nav (Y/N/C/P/Esc), horizontal pane-mode, and a section-toolbar visibility toggle — visually and behaviorally at parity with `notifications.html`'s `#action-required-section`.

This is **best-of-both, explicitly NOT either/or**: the funnel presentation wraps the existing responder; the responder engine is **not** discarded or rewritten.

## 2. Scope

This plan executes design call **(f)** verbatim.

**IN**
- Split `ActionRequiredRenderer`'s flat all-items list into **active (full responder)** + **pending (minimized cards)**.
- Active/pending **selection logic** in the store: designate one active id, the rest pending; promote-next on resolution.
- **Section chrome** in `multiplexer.html`: collapsible header with `⚠️ Action Required: <count>` + toggle, `#action-required-active-slot`, `#action-required-pending-queue`, `#action-required-empty` ("✓ No pending actions").
- **Minimized pending card** template — position badge (`#N`), type icon, truncated message, persona badge, timeout display; click → "respond to current first" tooltip (no queue-jump).
- **Keyboard nav** — Y/N/C/P keypress + Escape keydown, input-focus-guarded; attach on mount / detach on unmount.
- **Horizontal pane-mode** — lift the active content into the reading pane at a forced 50/50 split, restore on drain.
- **Section-toolbar entry** — add the missing action-required toggle to `SECTION_TOGGLES`.
- CSS for the new chrome + minimized cards, extending the existing mux action-required sheet.

**OUT**
- Rewriting / re-theming the interactive responder widget interior (`actionRequiredInteractive.ts`) — reused as-is for the active slot.
- The AR read-only↔interactive Oracle node parity proof — **carved** (deferred) per doc `02` §4 (D02 §B / DBR WS1). This plan must not regress that carve; it does not close it.
- TTS-coupled activation deferral (`if (!this.activeTTSItem)` gate at `notifications.js:16038`) — depends on the TTS-queue per-item model being restored first (plan `03-`). See §4 / §8.

## 3. Source anchors

### Legacy reference behavior (`html/notifications.html`, `js/notifications.js`)
| What | Anchor |
|---|---|
| Section shell: `.collapsible-section #action-required-section`, header `onclick="toggleSection('action-required-content')"`, `<h3>⚠️ Action Required: <span id="action-required-count">0</span></h3>`, toggle `#action-required-toggle ▼` | `notifications.html:562-567` |
| Active slot · pending queue · empty state ("✓ No pending actions") | `notifications.html:568-583` (`#action-required-active-slot:570`, `#action-required-pending-queue:575`, `#action-required-empty:580`) |
| Model fields: `keyboardListenerActive`, `actionRequiredQueue`, `activeActionRequiredId`, `_actionRequiredInPane` | `notifications.js:283`, `:291`, `:292`, `:299` |
| Add-to-funnel: activate-immediately-vs-defer + minimize-when-active | `notifications.js:16016-16063` (TTS-defer gate `:16038`) |
| `activateNextNotification()` — promote next, render full into active slot, start timer, recalc positions, exit pane on drain | `notifications.js:16073-16138` |
| `renderMinimizedNotificationDOM()` — position badge `#${queuePosition}`, icon, truncated msg, persona, timeout; id `action-required-minimized-${id}` | `notifications.js:16143-16186` |
| `formatTimeoutDisplay()` (≥60s → `Nm`, else `Ns`) | `notifications.js:16191-16196` |
| `showMinimizedTooltip()` — "Please respond to the current notification first" (no queue-jump) | `notifications.js:16201-16224` |
| `recalculateQueuePositions()` | `notifications.js:17412` |
| `updateActionRequiredCount()` — counts active/non-responded/non-expired; show/hide empty | `notifications.js:19456-19481` |
| `attachKeyboardListener()` — Y/N/C/P keypress + Esc keydown, input-guarded | `notifications.js:20016-20073` |
| `_enterActionRequiredPaneMode()` — horizontal only, lift `#action-required-content` into `#content-pane` body at 50/50, stash prior pane state | `notifications.js:12125-12162` |
| `_exitActionRequiredPaneMode()` — restore home + prior pane content + divider ratio | `notifications.js:12172-12205` |
| Layout-toggle calls enter/exit pane mode | `notifications.js:11959-11963` |
| localStorage restore (active slot + minimized pending + empty + count + keyboard + pane) | `notifications.js:15833-15928` |

### Multiplexer targets (add / edit)
| File | Current state | Change |
|---|---|---|
| `js/multiplexer/render/ActionRequiredRenderer.ts` | `renderAll()` (`:135-142`) loops `store.list()` and appends **every** item as a full responder widget (`buildWidgetFor` `:157-171`) — flat list, no active/pending split | **EDIT (core work)** — render active item into active-slot via existing `buildInteractiveWidget`; render pending items as minimized cards into pending-queue; drive count + empty-state + promote-on-resolve + keyboard nav + pane-mode |
| `js/multiplexer/render/templates/actionRequiredInteractive.ts` | Rich responder (yes_no / radio / checkbox / open_ended / batch) | **REUSE unchanged** — this is the responder we keep for the active slot |
| `js/multiplexer/render/templates/actionRequiredMinimized.ts` | does not exist | **ADD** — minimized pending-card template (position badge · icon · truncated msg · persona · timeout · tooltip) |
| `js/multiplexer/stores/ActionRequiredStore.ts` | `Map<idHash, ActorEntry>`; `list()` (`:192-194`) returns all; per-entry `setInterval` countdown started for **every** item on add (`startInterval` `:333-342`) | **EDIT** — add active-id designation, `getActive()` / `listPending()`, `promoteNext()`, count selector, position-recalc; gate countdown so **only the active** item ticks (legacy semantic, §4) |
| `html/multiplexer.html` (~`:110-111`) | `#action-required-section` is a **bare div** inside `#notifications-pane` | **EDIT** — replace with section chrome: header (count + toggle), `#action-required-active-slot`, `#action-required-pending-queue`, `#action-required-empty` |
| `js/multiplexer/render/templates/sectionToolbar.ts` (`SECTION_TOGGLES` `:35-42`) | omits action-required | **EDIT** — add `{ sectionId: "action-required-section", icon: "⚠️", title: "Action Required", testid: "multiplexer-section-toolbar-action-required" }` |
| `js/multiplexer/boot.ts` (`:309-315`) | mounts AR renderer on `#action-required-section` | **VERIFY** mount still resolves after chrome added; renderer now targets the slot children, not the bare root |
| `css/multiplexer/action-required.css` | styles the responder widget + states (`:43-90+`); no chrome / minimized / empty / count rules | **EDIT** — add header/count/active-slot/pending-queue/minimized/empty rules; single-source concern §8 |
| `css/multiplexer/reading-pane.css` (`:108`) | already has `.content-pane-body #action-required-section.in-reading-pane` | **REUSE** — pane-mode CSS hook already exists |

## 4. Dependencies & prerequisites

- **Inherited carve (must preserve, not close)**: AR read-only↔interactive node, doc `02` §4 (D02 §B / DBR WS1). Any node this plan touches inherits the open carve; Oracle Tier-2/3 on the responder interior stays carved.
- **Countdown-semantics reconciliation (design decision inside this plan)**: today the store starts a 1Hz `setInterval` for **every** entry on add (`ActionRequiredStore.ts:333`, `startInterval` `:336-342`). Legacy starts the timer **only on activation** (`activateNextNotification` → `startCountdownTimer`, `notifications.js:16128`); pending cards show a **static** timeout label via `formatTimeoutDisplay`. To match the funnel, gate live countdown to the active id only; pending cards render the static timeout. This is a store behavior change, not just a renderer change — see §5 W2 and the risk in §8.
- **TTS-defer gate is OUT (prereq on plan `03-`)**: legacy defers activation while TTS is playing (`notifications.js:16038`). The mux TTS queue per-item model is itself a restore target (plan `03-`, decision (e)). Until `03-` lands the per-item AudioStore queue, this plan activates immediately on arrival (no TTS gate). Cross-reference, do not duplicate.
- **Reading-pane integration (pane-mode)**: mux already ships `ReadingPaneStore` + `ReadingPaneRenderer` and a `.in-reading-pane` CSS hook (`reading-pane.css:108`). Pane-mode (W6) ports legacy's lift/restore onto that store rather than legacy's raw `#content-pane` DOM surgery — confirm the store exposes open/close + split-ratio control before committing W6 (§8 open question).
- **No new INI keys, no new endpoints.** Submit path unchanged (`POST /api/notify/response` via `respondAndAwait`, `ActionRequiredStore.ts:243`).
- **Event bus**: reuses existing `store_action_required_changed` (changeKinds added/responded/expired/cancelled/tick/offline-frozen/offline-resumed). A new `promoted` changeKind (or reuse of `added`) is needed to signal active-slot handoff — see §5 W2.

## 5. Work breakdown

### W1 — Section chrome in `multiplexer.html`
**What**: replace the bare `#action-required-section` div with the collapsible section structure: header (`⚠️ Action Required: <span id="action-required-count">0</span>` + collapse toggle), `#action-required-active-slot`, `#action-required-pending-queue`, `#action-required-empty` ("✓ No pending actions"). Keep `data-testid="multiplexer-action-required-section"`; add testids for the new nodes mirroring legacy (`notifications-action-active-slot` → `multiplexer-action-active-slot`, etc.).
**Files**: `html/multiplexer.html` (~`:110-111`).
**ACs**:
- *Structural*: section contains, in order, header → active-slot → pending-queue → empty; each carries a `multiplexer-*` testid. Count span starts `0`. Empty state visible when active-slot + pending-queue both empty.
- *Functional*: collapse delegated to the section-toolbar toggle (mux idiom, mirrors Fleet/Task-List per audit `04` §#6), **not** an inline `onclick` (legacy's `toggleSection` is a mux anti-pattern — see SectionToolbarRenderer).
- **Oracle**: T1 DOM-contract (node presence/order/testids) · T2 computed-style (header/empty typography).

### W2 — Store active/pending model
**What**: add to `ActionRequiredStore`: an `activeId: string | null`; `getActive()`, `listPending()` (FIFO order, active excluded); `promoteNext()` (designate next pending as active when active resolves/cancels/expires); `activeCount()` (non-responded/non-expired, mirrors `updateActionRequiredCount` `:19456`); position recalculation for pending. Gate the per-entry countdown so **only the active** entry runs its `setInterval` (move/condition `startInterval` at the add site `:333`); pending entries hold a static `timeout_seconds`. Emit a `promoted` changeKind (or reuse `added`) so the renderer re-renders both slots on handoff.
**Files**: `stores/ActionRequiredStore.ts`; `shared/types.ts` (extend `ActionRequiredChangeKind` if `promoted` added).
**ACs**:
- *Functional*: first arriving prompt becomes active and ticks; subsequent prompts go pending (static timeout), do not tick. On active → responded/expired/cancelled, `promoteNext()` activates the oldest pending and starts its tick. Drain → `activeId = null`, empty state.
- *Structural*: `getActive`/`listPending`/`activeCount` are pure selectors; existing `respond`/`respondAndAwait` untouched. Only-active-ticks invariant covered by a unit test asserting a single live interval.
- **Oracle**: n/a (pure logic) — gated by §6 unit suite at 100% L/B/F.

### W3 — Renderer split (core work)
**What**: rewrite `renderAll()` to (1) render `store.getActive()` through the **existing** `buildInteractiveWidget` (responder + countdown + failed-stripe — all current state-machine builders retained) into `#action-required-active-slot`; (2) render each `store.listPending()` item via the new minimized template (W4) into `#action-required-pending-queue`; (3) toggle `#action-required-empty`; (4) update `#action-required-count`. On `store_action_required_changed`: `tick` still patches the active countdown via `.textContent` only (preserve the no-RAF rule, `ActionRequiredRenderer.ts:288-291`); `responded`/`expired`/`cancelled` for the **active** id triggers `promoteNext()` + full re-render of both slots; pending-targeted changes re-render the pending queue only. Wire keyboard nav (W5) + pane-mode (W6) into mount/unmount.
**Files**: `render/ActionRequiredRenderer.ts`.
**ACs**:
- *Functional*: exactly one full responder visible (active slot); N−1 minimized cards (pending queue); resolving the active promotes the next; count + empty reflect state live. Atomic-swap / single-MutationObserver-entry discipline preserved per existing AC2c.
- *Structural*: active widget keeps `data-id-hash` + `data-testid="multiplexer-action-required"`; minimized cards carry `data-id-hash` + a distinct `data-testid="multiplexer-action-required-minimized"`. `phase6bOwner` ownership claim (`:104`) unchanged.
- **Oracle**: T1 DOM-contract (one active + N pending) · T2 computed-style · T3 geometry (slot stacking, card heights). Responder **interior** stays under the inherited carve (§4).

### W4 — Minimized pending-card template
**What**: new `actionRequiredMinimized.ts` building a card from `ActionRequiredItem` + a position int: `#N` position badge, type icon (yes_no ❓ / open_ended 💬 / multiple_choice 📋 / default 📢, per `notifications.js:16154-16158`), truncated message (≤60 chars → 57+"…", `:16150`), persona badge, static timeout label (`formatTimeoutDisplay` ported, `:16191`). Click → "Please respond to the current notification first" tooltip (no queue-jump, `:16201`). **Safe-write only** (`html` tagged template + `.textContent`), matching the `actionRequiredInteractive.ts` AC2e invariant — legacy's `card.innerHTML =` (`:16172`) must **not** be ported as innerHTML.
**Files**: `render/templates/actionRequiredMinimized.ts` (new); helper `formatTimeoutDisplay` (port).
**ACs**:
- *Functional*: position badge matches FIFO rank; tooltip appears on click and blocks queue-jumping; truncation + icon + timeout match legacy output.
- *Structural*: zero `.innerHTML`/`rawHTML`/`.outerHTML` (grep-test like `templates_action_required_interactive.test.ts`).
- **Oracle**: T1 (card sub-node contract) · T2 (badge/icon/timeout typography) · T3 (card geometry vs legacy `.action-required-minimized`).

### W5 — Keyboard navigation
**What**: port `attachKeyboardListener` (`:20016-20073`): keypress Y/N (submit yes/no on the active yes_no item), C (toggle comment), P (toggle pause); keydown Escape (cancel active). Guard: ignore when `document.activeElement` is INPUT/TEXTAREA; only act when an active item exists. Attach on first mount-with-items, **detach on unmount** (legacy never detaches — improve to avoid leaks across SPA nav).
**Files**: `render/ActionRequiredRenderer.ts` (or a small `actionRequiredKeyboard.ts` helper for testability).
**ACs**:
- *Functional*: Y/N submit the active yes_no via the responder's `onSubmit` path (→ `respondAndAwait`); Esc cancels active; keys are no-ops while typing in an input or when no active item.
- *Structural*: listeners removed on unmount (idempotent); no double-attach.
- **Oracle**: n/a — §6 unit/jsdom suite.

### W6 — Horizontal pane-mode
**What**: port `_enterActionRequiredPaneMode` / `_exitActionRequiredPaneMode` (`:12125-12205`) onto the mux `ReadingPaneStore`: on first active item while layout is horizontal, lift the active content into the reading pane at a forced 50/50 split, stashing prior pane content + divider ratio; on drain, restore home + prior content + ratio. Reuse the existing `.in-reading-pane` CSS hook (`reading-pane.css:108`).
**Files**: `render/ActionRequiredRenderer.ts`; possibly `stores/ReadingPaneStore.ts` (only if it lacks split-ratio/open-close API — confirm first, §8).
**ACs**:
- *Functional*: horizontal layout + active item → 50/50 pane; drain → prior pane state + divider restored; vertical layout → no pane-mode (inline). Idempotent enter/exit.
- *Structural*: no orphaned pane state after rapid arrive/drain cycles.
- **Oracle**: T3 geometry (50/50 split) · T4 pixel backstop (assembled pane).
- **GATING RISK**: largest unknown — may split to its own lane / defer if `ReadingPaneStore` integration is heavier than a thin adapter (§8).

### W7 — Section-toolbar entry
**What**: add the action-required toggle to `SECTION_TOGGLES` (`sectionToolbar.ts:35-42`). Confirm `SectionToolbarRenderer`'s delegated `.section-hidden` toggle + persisted-state logic already handles a new entry generically (it iterates the spec list).
**Files**: `render/templates/sectionToolbar.ts`.
**ACs**:
- *Functional*: toolbar shows a ⚠️ toggle that hides/shows `#action-required-section`; collapse-all/expand-all include it.
- *Structural*: existing toolbar tests extended for the 7th entry; testid `multiplexer-section-toolbar-action-required`.
- **Oracle**: T1 (button presence/order/testid) · T2 (active/dimmed styling).

### W8 — CSS
**What**: extend `css/multiplexer/action-required.css` with rules for the header (`⚠️` + count), `#action-required-active-slot`, `#action-required-pending-queue`, `.action-required-minimized` (+ `.minimized-position`/`-icon`/`-message`/`-timeout`), `.action-required-empty-state`, and the `.minimized-tooltip`. Match legacy geometry/typography. Keep the file's scope-leak protection (no global selectors, `#action-required-section`-scoped). **Single-source concern (§8)**: mandate #3 says style from `css/shared/notifications-surface.css`; the mux currently styles AR from the per-pane `css/multiplexer/action-required.css`. Reviewer call: extend the per-pane sheet (consistent with existing mux AR styling) vs hoist shared chrome into the shared sheet.
**Files**: `css/multiplexer/action-required.css` (+ possibly `css/shared/notifications-surface.css`).
**ACs**:
- *Structural*: stylelint scope-leak rule passes; no `.innerHTML`-dependent styling.
- **Oracle**: T0 CSS-hash (if shared sheet touched) · T2 computed-style · T4 pixel backstop.

## 6. Test strategy & venue routing

- **Unit / jsdom (:7999, AI-discretionary)** — TS via `c8 --100`:
  - `ActionRequiredStore` active/pending model: active designation, `promoteNext`, only-active-ticks invariant, count selector, position recalc, drain → null.
  - `ActionRequiredRenderer` split: one-active-N-pending render, promote-on-resolve, count/empty toggles, tick patches active only (no-RAF), atomic-swap discipline, keyboard nav (Y/N/C/P/Esc + input-guard + unmount-detach).
  - `actionRequiredMinimized.ts`: badge/icon/truncation/timeout output; safe-write grep test (no innerHTML); tooltip-on-click + no-queue-jump.
  - `sectionToolbar.ts`: 7th entry present/ordered/testid.
- **WebSocket smoke (:7999)** — `run-websocket-smoke-tests.sh`: confirm `notification_queue_update` (response_requested) still funnels into the active slot end-to-end.
- **E2E UI + visual (:8000, scheduled via `POST /api/test-suite/submit`, self-authorized on verified-idle)** — Playwright: funnel behavior (active slot + minimized pending + position badges + empty + count), keyboard nav, section-toolbar toggle, horizontal pane-mode 50/50, and the visual-regression snapshots for the assembled section. `--update-snapshots` rebaseline (§7).
- **Integration (:8000, scheduled — FINAL gate)** — full suite green before merge.
- **100% L/B/F**: every new/edited TS file at 100% lines/branches/functions (`c8 --100`); `# pragma`/`c8 ignore` only for genuinely-unreachable defensive branches with a same-line reason. No exceptions.

## 7. Oracle & visual parity

Per mandate #2 (methodology `2026.06.19-…/01-layout-parity-methodology.md`):
- **T0 CSS-hash** — only if `notifications-surface.css` (shared) is touched (W8 reviewer call).
- **T1 DOM-contract** — section chrome node set/order/testids (W1), one-active-N-pending invariant (W3), minimized sub-nodes (W4), toolbar 7th entry (W7).
- **T2 computed-style** — header/count/empty typography, minimized card + badge styling, toolbar button states.
- **T3 geometry** — active-slot/pending-queue stacking, minimized card heights vs legacy `.action-required-minimized`, pane-mode 50/50 split.
- **T4 pixel backstop** — assembled section (active + ≥2 pending + empty-toggled) and the horizontal pane-mode layout.
- **Carve**: the responder **interior** node carries the inherited AR read-only↔interactive carve (doc `02` §4) — Tier-2/3 on that node stay deferred; this plan must not regress the carve.
- **Golden captures needed**: new `:8000` legacy captures for (a) AR section with 1 active + N minimized pending + position badges, (b) empty state, (c) horizontal pane-mode 50/50. Capture cost noted per mandate #2.

## 8. Risks & open questions

1. **Countdown-semantics change (§4 / W2)** — moving from "every entry ticks" to "only active ticks" is a real store behavior change. Risk: existing store unit tests assume per-entry intervals. *Reviewer*: confirm gating live countdown to the active id is acceptable (it matches legacy + saves N−1 timers), and that pending cards showing a **static** timeout is the intended UX.
2. **Pane-mode integration depth (W6)** — does `ReadingPaneStore` already expose open/close + split-ratio control, or does W6 need new store API? If heavy, **split W6 to its own lane or defer** it as a fast-follow (the funnel is usable without horizontal pane-mode). *Open question for reviewers.*
3. **CSS single-source tension (W8)** — mandate #3 (style from `css/shared/notifications-surface.css`) vs the mux's existing per-pane `action-required.css`. *Reviewer*: extend per-pane (consistent) or hoist chrome to shared? This affects whether a T0 CSS-hash capture is needed.
4. **TTS-defer gate omitted (§4)** — legacy defers activation while TTS plays; restored only when plan `03-` lands the per-item AudioStore queue. Acceptable interim divergence? Confirm sequencing: this plan immediate-activates; `03-` re-introduces the gate.
5. **`promoted` changeKind vs reuse `added`** (W2) — adding a new changeKind touches `shared/types.ts` (a convergence-ish file). *Reviewer*: new kind (clearer) vs overload `added`?
6. **Keyboard-listener scope** — legacy attaches a document-level listener and never detaches; mux SPA nav makes leaks real. Plan detaches on unmount — confirm no regression vs legacy's persistent-listener behavior.
7. **Inherited carve boundary** — exactly which DOM node the AR read-only↔interactive carve covers (doc `02` §4 / D02 §B) must be re-confirmed so W3's Oracle tiers gate the right nodes and don't accidentally "close" a carve that's still owned elsewhere.

## 9. Lane decomposition & estimate

Suggested parallel lanes (worktrees per mandate #5; convergence files manager-serial-merged):

| Lane | Work items | Convergence-file touches | Rough size |
|---|---|---|---|
| **A — Store model** | W2 | `shared/types.ts` (if `promoted` added) — convergence, serial-merge | M (logic + unit suite) |
| **B — Renderer + minimized + keyboard** | W3, W4, W5 | none beyond `ActionRequiredRenderer.ts` (lane-owned) | L (core work) |
| **C — Chrome + toolbar + CSS** | W1, W7, W8 | `multiplexer.html` (convergence — coordinate with Tiberius/Rachel), `sectionToolbar.ts` (Rachel's `mux-section-toolbar-accordion-toggle` branch — **commit-held; coordinate**), shared CSS if hoisted | M |
| **D — Pane-mode** | W6 | `ReadingPaneStore.ts` (if extended) | M–L, **may defer** (§8.2) |

**Convergence callouts (mandate #5/#6)**:
- `multiplexer.html` and `sectionToolbar.ts` overlap **Rachel 🕊️**'s commit-held section-toolbar branch and **Tiberius 👑**'s full-parity build — coordinate the merge so the 7th toolbar entry + the AR chrome don't collide. Add the toggle on top of Rachel's branch if it lands first.
- Lane B depends on Lane A's selector API (`getActive`/`listPending`/`promoteNext`) — sequence A→B or stub the store interface for parallel start.
- Lane D is the schedule risk; recommend building A+B+C to a usable funnel first, then D (or defer D as a fast-follow if §8.2 resolves "heavy").

**Doc touchpoints (mandate #7)**: this is a section-chrome/funnel change to an existing pane — no CLAUDE.md §DOCUMENTATION TOUCHPOINTS row maps directly. Update the migration-discrepancies parity contract (this `05-build-plans/` corpus) + note the funnel restore in the AR design lineage (`09-phase6b-interactive-widgets-design.md`) so the responder-vs-funnel relationship is recorded.
