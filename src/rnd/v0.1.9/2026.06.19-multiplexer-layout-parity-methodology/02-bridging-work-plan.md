# 02 — Bridging Work Plan: To ~100% Functional + Layout Sync

**Date:** 2026-06-19 · **Deliverable 3 of 3** (reads from [`00-feasibility-report.md`](00-feasibility-report.md) + [`01-layout-parity-methodology.md`](01-layout-parity-methodology.md))

## Relationship to the 06-10 gap-bridge (build on, do not duplicate)

The [2026-06-10 gap-bridge](../../v0.1.8/2026.06.10-notifications-ui-multiplexer-gap-bridge/README.md) already
enumerated the **functional** gap (features F1–F12 + Layer-B blockers) and a parallel-lane plan to
close it. **This plan does not re-derive that work.** It adds the two things that effort lacked:

1. a **single-source CSS** strategy so the layout stops being a divergent copy (Doc 01 Pillar 1), and
2. an **automated layout oracle** so "looks the same" stops meaning "Rick looked at it" (Doc 01 Pillar 2).

In short: the 06-10 plan closes **Category 3** (missing DOM); *this* plan closes **Premise A +
Category 2** (CSS source + style reconciliation) and installs the **measurement** that gates both.

## Definition of done — "100%" decomposed into checkable gates

| Gate | Meaning | Verified by |
|---|---|---|
| **G0 — CSS single-sourced** | Contract surfaces styled from one shared sheet linked by both pages | Oracle **Tier 0** green |
| **G1 — Contract conformance** | Both clients emit the Layout-Contract skeleton on the canonical fixture | Oracle **Tier 1** green (both sides) |
| **G2 — Style parity** | Corresponding contract nodes have equal computed style | Oracle **Tier 2** green |
| **G3 — Geometry parity** | Corresponding contract nodes have equal box geometry | Oracle **Tier 3** green |
| **G4 — Structure parity** | Every legacy element is present (functional gaps closed) | Oracle Tier 1 **full-page** + the 06-10 feature checklist |
| **G5 — Pixel backstop** | Whole-page screenshot diff within threshold | Oracle **Tier 4** (`assert_snapshot`) |
| **G6 — Coverage** | New TS/Python at 100% lines/branches/functions | `pytest --cov` / `c8 --100` (CLAUDE.md §100% COVERAGE MANDATE) |

"~100% sync" = **G0–G3 + G5 green now** (style/layout parity on shared surfaces) and **G4 climbing
to green** as functional gaps close. G0–G3 are the *near-term* deliverable; G4 tracks the 06-10
schedule.

## Workstreams

### WS1 — CSS single-sourcing (Doc 01 Pillar 1) · unblocks G0

1. Extract the **contract surfaces** (page-frame + `.sender-card*` + `.date-accordion*` +
   `.sender-message*` + expired/abstract/progress) from `notifications.css` into
   `css/shared/notifications-surface.css`.
   > **Build-time refinement (2026-06-22, Clayton 😎 finding · Tiberius ruling):** `.action-required-*`
   > is **EXCLUDED from the shared sheet this slice.** The two clients use **disjoint** class sets —
   > legacy renders an *interactive* widget (`.action-required-notification/-header/-timer/-progress-bar…`),
   > the mux a *read-only* one (`.action-required-widget/-prompt/-response-type-badge/-countdown…`) whose
   > classes **do not exist in the monolith**. There is no shared selector to single-source byte-faithful,
   > so this is **Category-3 (functional divergence), not a CSS one.** Keep the mux's read-only
   > `.action-required-widget` rules in the mux-specific sheet; it folds into the shared sheet only once
   > the mux widget reaches **functional parity** with legacy (classes converge then) — WS4 / 06-10 lane,
   > oracle-gated. Rachel's full-page Tier 1 will report it as a MISSING structure-parity node (expected,
   > not a regression). Seam comment → WS4/action-required.
2. `multiplexer.html`: replace `page-frame.css` + `notifications-list.css` with the shared sheet
   (keep the multiplexer-specific sheets: `reading-pane`, `session-strip`, `jobs-pane`, …).
3. `notifications.html`: link the shared sheet; delete the now-duplicated rules from the monolith
   (or link shared *first* and let the monolith shrink incrementally to avoid a big-bang edit).
4. Scope the global resets (`*`, `body`, `h1`, `.container`) so they cannot bleed across pages
   (they are page-frame, already isolated in `page-frame.css` — fold that isolation into the shared
   sheet's structure).

**Risk:** specificity interaction with `reading-pane.css`'s
`body[data-layout-mode="horizontal"] … .container` override — already documented and preserved in
[page-frame.css:24-27](../../../lupin_app/static/css/multiplexer/page-frame.css); re-verify after the
move via Tier 2.

### WS2 — Layout Contract + reconcile the 4 Category-2 divergences · unblocks G1–G3

Author `css/shared/LAYOUT-CONTRACT.md` (the tuple set from Doc 01), then resolve each C2 row:

| C2 | Resolution (proposed — see Decisions) | Touch |
|---|---|---|
| C2-a persona badge (`<button.sender-persona-badge>` vs `<span.persona-badge>`) | Keep the button (no-globals/popover intent); add a CSS reset so the button is visually identical to the legacy span; widen the shared rule selector to the union | `notifications-surface.css`; no TS change |
| C2-b collapse mechanism (`.collapsed` vs `[data-collapsed]`) | Shared rule fires for **both** selectors (one-line union) | `notifications-surface.css` |
| C2-c inter-card spacing (`margin-bottom` vs `gap`) | Pick legacy `margin` model as the contract; encode once in shared sheet | `notifications-surface.css`; drop the `#sender-cards-container` gap override |
| C2-d message direction (always-`.incoming`) | **D3 → support `.outgoing` day-one.** `notificationItem.ts` gains a direction param; the store/adapter splits a responded notification into incoming-prompt + outgoing-response (mirror legacy `:14317-14330`). Load-time outgoing consumes existing `response_value` (F5-independent); live outgoing pulls F5 in. CSS already ported. | **In this slice (no longer pure CSS)** — TS: direction param + responded-split + Notification model (`response_value`); fixture gains a responded pair; live echo = F5 |

**C2-d is the one Category-2 item that is _not_ pure CSS** — it is a `notificationItem.ts` direction
param + a Notification-model/adapter responded-split, and its live half pulls the F5 user-send path
forward (D3). C2-a/b/c remain shared-sheet edits.

### WS3 — Build the oracle (Doc 01 Pillar 2) · the durable investment

1. **Canonical fixture + dual adapter** (`fixtures/notifications-parity-scenario.json` +
   legacy/mux adapters). Reuse the deterministic-timestamp idiom from the existing visual fixtures.
   **Must include a responded notification** so both clients render an incoming + outgoing pair (D3) —
   `.outgoing` styling is then under the oracle from day one.
2. **Golden-capture script** — drive legacy once, serialize contract subtree skeleton +
   computed-style + geometry to a **git-tracked** `fixtures/golden/notifications-legacy.golden.json`.
3. **Component-isolation harness page** — mounts one contract component for both clients at a fixed
   viewport.
4. **Tier 0–3 tests** under `src/tests/e2e_ui/` (golden-replay mode → :7999-eligible for the
   isolation tiers; full-page Tier 1 + Tier 4 ride :8000 scheduled).
5. **Wire `build-multiplexer.sh`** into the harness preamble so `boot.js` is fresh before browser
   tiers.

### WS4 — Close the structural (Category-3) gaps · unblocks G4

This is the 06-10 gap-bridge scope, **gated by the oracle**: as each feature lands (card chrome,
Reading Pane, CC-session strip, Commons, Fleet-Status, prediction vote, missed badge, the
`getCurrentUserEmail` send-path, auth token-key alignment), Tier 1 full-page conformance ticks
another contract node from MISSING → PRESENT, and Tiers 2–3 immediately prove its *styling* matches.
**No feature is "done" until its contract nodes pass the oracle** — that is the new acceptance bar
the 06-10 plan was missing.

> **Pulled forward (D3):** the `getCurrentUserEmail` **send-path (F5)** is no longer purely a WS4
> item. Its load-independent half (rendering a *responded* notification's answer as an outgoing
> bubble on page load) rides the **core slice** (WS2); its user-send capability is a prerequisite of
> day-one **live** `.outgoing` and is therefore pulled into scope, not deferred. Only the broader
> send/dictate UX polish remains a WS4 concern.

## Sequencing

```
WS1 (CSS single-source) ──► G0 ─┐
                                ├─► WS2 (contract + C2 reconcile) ──► G1–G3 on shared surfaces
WS3 (oracle harness) ──────────►┘         (gates everything downstream)
                                                    │
                                                    ▼
WS4 (Category-3 functional gaps, per 06-10) ──► G4 climbs to 100%, each step oracle-verified
```

- **WS1 + WS3 are independent** → parallelize (CSS edit vs harness build don't contend).
- **WS2 depends on WS1 + WS3** (needs the shared sheet to edit and the oracle to verify).
- **G0–G3 (style/layout parity on existing surfaces) is the near-term milestone.** Most already
  landed (Doc 00); C2-a/b/c are a focused shared-CSS session. **C2-d (day-one `.outgoing`, D3)
  enlarges it beyond pure CSS** — a renderer/model responded-split plus pulling the F5 user-send
  forward — so budget for that, not just a stylesheet edit.
- **G4 is the long pole**, owned by the 06-10 lane plan, now with oracle gating.

## Venue / test routing (per CLAUDE.md §TESTING VENUES)

| Activity | Venue | Why |
|---|---|---|
| Tier 0 (CSS hash) + unit-level contract/adapter tests | **:7999** | static / <2 min / no state mutation |
| Tier 1–3 component-isolation, golden-replay | **:7999** | read-only, <2 min, no monopoly |
| Tier 1 full-page + Tier 4 pixel sweep | **:8000 scheduled** | server monopoly + existing E2E UI lane; self-authorized on verified-idle :8000 |
| Golden recalibration (live dual-render) | **:8000 scheduled** | drives legacy live; monopoly |

`build-multiplexer.sh` runs in the preamble of any browser-tier job (not a server bounce).

## Decisions for ratification

> **✅ ALL RATIFIED — walkthrough 2026-06-22 (Tiberius 👑, session 704c71b2; Rick).** D1/D2/D4/D5/D6 ratified as recommended, with reviewer refinements A/B/C folded in (see riders below). D3 was already resolved by Rick 2026-06-20. Decisions Log: `TODO.md` (2026-06-22 block).

| # | Decision | Ruling |
|---|---|---|
| D1 | **CSS strategy** S1 / S2 / S3 (Doc 01) | **✅ S2 — shared extracted sheet.** **Rider A:** extract byte-faithful to the monolith; legacy links the shared sheet **BEFORE** its monolith (monolith still wins any cascade conflict) so the **parity reference cannot regress**; monolith de-duplication deferred to a later, separately-verified pass. |
| D2 | **C2-c spacing model** — legacy `margin` vs mux `gap` as the contract | **✅ Legacy `margin`** (`.collapsible-section { margin-bottom:30px }`); drop the drift-invented `#sender-cards-container { gap:8px }`. It is the parity target → oracle green by construction. |
| D3 | **C2-d message direction** — add a direction field vs ratify "inbound-only" | **RESOLVED (Rick, 2026-06-20) — `.outgoing` supported DAY-ONE, no deferral, no exemption.** Legacy renders outgoing on cold load by splitting a responded notification into prompt + response ([notifications.js:14317-14330](../../../lupin_app/static/js/notifications.js)); the multiplexer adopts the same from the start. **Load-time outgoing** is F5-independent → core slice (WS2). **Live outgoing** pulls the send-path (F5) **forward** into scope (not deferred). CSS already ported; work = direction param + responded-split + F5. (See D6 Rider B for how the live half sequences.) |
| D4 | **Oracle authority** — is Tier 2 (computed-style) the *definition* of done, with Tier 4 (pixel) advisory? | **✅ Yes** — Tier 2/3 gate; Tier 4 backstop, never blocks on AA noise. **WS3 rider:** Tier 2 asserts declarative layout props exactly but **NOT resolved `width`/`height`** (sub-pixel flex distribution → flaky); resolved geometry is left to Tier 3's tolerant ±1px check. |
| D5 | **Golden artifact home** — tracked path for goldens (since `io/test-suite/visual-baselines` is gitignored) | **✅ `src/tests/e2e_ui/fixtures/golden/`** (small JSON, git-tracked). **Rider C:** bake the shared-sheet content hash into each golden as a **staleness trip-wire** — under S2, legacy-contract drift IS a shared-sheet change, so hash drift fails the golden and forces recapture. |
| D6 | **Scope of this v0.1.9 slice** — land G0–G3 now and hand G4 to the 06-10 lane, or fold both into one push? | **✅ Land G0–G3 + the oracle now;** hand G4 to the 06-10 lane (oracle-gated). **Rider B:** load-time `.outgoing` (responded-split off the server's existing `response_value`, F5-independent) is in-slice and is **all the oracle needs** to verify `.outgoing` day-one; the **live-echo half (full F5 send-path) lands just behind** so a feature build cannot gate oracle-green. |

## Net

The brief's two asks become two durable mechanisms: **one stylesheet** (parity by construction) and
**one oracle** (parity by measurement). The feasibility question (Doc 00) is answered *yes*; this
plan is the route, and its first milestone — provable style/layout parity on the surfaces both
clients already render — is small, mostly-done, and gated by a test that never needs your eyes.
