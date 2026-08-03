# Multiplexer Full-Parity Build — Implementation Plan (for cascaded review)

**Date:** 2026-06-22 · **Author:** Tiberius 👑 (session 704c71b2, for Rick) · **Status:** DRAFT — gated on cascaded review before any implementation (Rick's directive 2026-06-22).

## Decision of record

Rick ruled the Tier-3 cut-line on 2026-06-22: **FULL PARITY before flip** — the TS multiplexer must reach full functional parity with the legacy `notifications.js` client (all interim features F1–F12 **and** the Layer-B pre-existing gaps), every feature **oracle-gated**, before the default-surface cutover flips. No `?classic=1`-dependence for core features; the escape hatch + JS corpus remain (D2) but are not the parity strategy.

**Process gate (Rick):** this plan does NOT authorize implementation. It goes to an **explicit cascaded review group** first; implementation begins only after that review ratifies the plan.

## Inputs (read; do not re-derive)
- Gap analysis — F1–F12 + Layer-B: `src/rnd/v0.1.8/2026.06.10-notifications-ui-multiplexer-gap-bridge/01-gap-analysis.md`
- Cutover readiness (mechanics built, flag-gated) — `…/03-saturday-cutover-readiness.md`
- Layout-parity methodology + oracle + ratified D1–D6 — `src/rnd/v0.1.9/2026.06.19-multiplexer-layout-parity-methodology/{01,02}`

## Current baseline (from gap-analysis, source-verified)
- Multiplexer = strict store→renderer→transport TS (~10,183 LOC), no globals / no inline onclick, esbuild→`boot.js`, served at `/app/multiplexer`. Stopped at Phase 6c.
- **Every F1–F12 is ABSENT or non-functional-partial.** Fully present today: AR-interactive, jobs pane, persona modal, WS transport, conversation-mode pin.
- Cutover mechanics already built + held inactive behind INI `legacy notifications redirect enabled` (+ `?classic=1` hatch), `pages.py` 100% L/B.

## Workstream decomposition

### Lane 0 — Layer-B foundation (MANDATORY, unblocks everything)
- **L0a Auth alignment:** `AuthManager` reads `auth_token`; legacy uses `lupin_access_token`/`lupin_refresh_token` + redirects to `/app/auth/login?redirect=…` on missing token. Align storage keys + add the missing-token redirect. (Mandatory: a tokenless landing currently fails to authenticate.)
- **L0b Send-path (F5 core):** `getCurrentUserEmail()` never added (`boot.ts:307-320` wires `currentUserEmail:""`), so outbound `user_initiated_message` POST fails validation. Land it — prerequisite for any user-typed/dictated reply and for live `.outgoing` (D3).

### Lane 1 — CC-session strip subsystem (Layer-B hard blocker)
New per-session strip / focus-bar concept (the mux has `FocusTrayRenderer` but no strip). **Unblocks F3, F9, F10, F11:**
- F3 focus-mode card-height boost (CSS once strip + date-accordion DOM exist)
- F9 reap → focus-bar badge drop + broadcast refresh
- F10 spin-up persona symmetry + hover removal
- F11 focus-bar manager-lineage badge
Re-express F9/F10/F11 as store actions + `addEventListener` delegation (no globals/onclick).

### Lane 2 — Reading-Pane subsystem
- **F1** Master-Detail Reading Pane (iframe + bust-out + toggle + scroll-preserve) — brand-new pane subsystem; needs scroll-position persistence (currently only session-id + unread persisted).
- **F2** Action-Required lifted into the Reading Pane (AR interactive widgets already present; depends on F1).

### Lane 3 — Commons "Recent Activity" panel
New panel (broadcasts / peer activity). **Unblocks F4** (`shared/broadcast.ts` exists but inert — never `start()`-ed; revisit single-tab policy Q12).

### Lane 4 — Self-contained features (no strip/pane dependency — parallelizable early wins)
- **F12** read-only Fleet-Status table (8 cols, live-only toggle, polling) — `/api/arbiter/fleet-state` ready, pure new client surface.
- **F8** prediction-hint thumbs vote UI (re-express globals as store action).
- **F7** missed-while-away badge + Reset (boot already emits `page_hidden`/`page_visible`; no consumer).
- **F6** TTS preview-fraction slider (12.5%) — `TtsChromeRenderer` is transport-only today.

### Lane 5 — UI-surfacing + hardening follow-ons
- **Hydration-failure surfacing:** `JobsPaneRenderer` already `console.warn`s + emits `hydration_failed`, but **no consumer subscribes** → invisible in UI (Rachel finding). Add a consumer that surfaces it.
- **Browser-boot zero-console-error E2E** (`/app/multiplexer`) + history-hydrates-against-real-backend — the `:8000` half Rachel's `:7999` route-liveness test (7dba56cb) could not cover.
- **F5 insert-at-caret** decision (cutover-readiness FINDING): the mux paints transcription into a fresh textarea on `ready_to_send`; **re-record after edit overwrites user edits** (the exact legacy bug F5 fixed). Decide: port caret-splice vs. accept replace-on-re-record. **(Open — for reviewers.)**

## Oracle gating (acceptance bar — every feature)
Per ratified D4/D6: no feature is "done" until its contract nodes pass the oracle. As each lands, **Tier 1 full-page** ticks its node MISSING→PRESENT and **Tier 2/3** prove style/geometry. G4 (structure parity) climbs to 100%. Venue routing per the bridging plan (Tier 0–3 isolation `:7999`; Tier 1 full-page + Tier 4 pixel `:8000` scheduled). 100% L/B/F per WP (CLAUDE.md gate).

## Sequencing (dependency graph)
```
Lane 0 (auth + send-path) ──► everything
Lane 1 (CC-strip) ──► F3/F9/F10/F11
Lane 4 (self-contained) ── parallel with Lane 1 (no dependency) — early oracle-green wins
Lane 2 (Reading-Pane) + Lane 3 (commons) ── after/with Lane 1
Lane 5 (surfacing/hardening) ── trails each feature
        ▼
Full-page oracle green (G4=100%) ──► cutover mechanics (flag flip, already built)
```

## Cutover (already built — cutover-readiness)
Flip `legacy notifications redirect enabled = False→True` (one INI line) + `:8000` bounce; `:7999` auto-reloads. Landing card repoint transitively covered. Docs ride-along (row 5). `?classic=1` + JS corpus preserved (D2).

## Acceptance
- All F1–F12 functional in the multiplexer; Layer-B blockers (auth, send-path, strip, commons) closed.
- Oracle: G0–G3 green (already near), **G4 → 100%** (full structure parity), G5 pixel backstop green.
- 100% lines/branches/functions on all new TS/Python.
- Then: cutover flag flip on Rick's word.

## Open questions for the cascaded-review group
1. **Lane sizing / crew shape:** how many parallel implementer lanes, and where are the worktree-collision seams (strip vs. self-contained vs. pane)?
2. **F5 insert-at-caret:** port the caret-splice, or ratify replace-on-re-record as intended mux design? (cutover-readiness FINDING.)
3. **Reading-Pane (F1) scope:** full iframe+bust-out+scroll-preserve, or a reduced master-detail first pass?
4. **Commons panel single-tab policy (Q12):** does `broadcast.ts` get `start()`-ed, or is the panel poll-based?
5. **Effort estimate + cutover target date** — the gap-analysis judged single-push-by-Saturday "not credible"; what is the realistic milestone cadence?
6. **Is a `Workflow`/multi-agent cascaded review warranted**, or a `/plan-review-cascaded` reviewer panel?

## Next step (post-review)
On cascaded-review ratification: serialize lanes to the task store, spawn the implementer crew (worktree-isolated), oracle-gate each WP, manager review→merge-held, signal Rick for push.

---

## Cascaded Review — Round 1 (2026-06-22) · VERDICT: REQUEST CHANGES (do not ratify as-is)

Three independent lenses (Krishna 🦚 architecture · Sam 🎙️ scope · Extra-1 🪨 test/oracle). All REQUEST CHANGES. Findings to fold into Round-2 draft:

### CONVERGENT CRITICAL (all three lenses)
- **C-1 Foundation is consumed but never laned.** The plan gates every feature on the oracle + single-source CSS but allocates ZERO lanes to WS1 (CSS single-source → `notifications-surface.css`), WS2 (Layout Contract + C2-a/b/c reconcile + **C2-d `.outgoing` day-one** responded-split), WS3 (oracle Tier-2 computed-style + Tier-3 geometry). These are a **parallel v0.1.9 effort, partially complete** — Tiers 0/1 + golden-capture + cross-client conformance HELD GREEN (`fe3ab4da→191d4d41`); **Tier-2/3 REMAINING**, Rachel driving G4-verify `bfcb162c` now. **Fix:** add a **Lane -1 / Foundation + Prerequisites** section citing that effort's owner + commit status + a hard gating edge (Foundation → all feature lanes). NOT new scope — ratified D1/D4/D5/D6 work the draft dropped (matters under the no-new-board-work directive). Replace "G0–G3 already near" with a verifiable state (which C2 rows landed; is the oracle harness committed).

### Test/Oracle (Extra-1) — the acceptance bar is wrong
- **Hole A — oracle-green ≠ functional-done.** Tiers 1–3 + "G4 = structure parity" measure LAYOUT/DOM-PRESENCE; none prove a feature WORKS (F8 vote can pass all tiers and POST nothing). The plan conflates structure with functional parity — the bare-DOM false-pass the crew already burned on. **Fix:** add a per-feature **functional-E2E gate** distinct from the layout oracle, leveraging the EXISTING `test_multiplexer_*` suites (Clayton's 6/7, `ts-2c5e5deb` 64-pass; `prediction_vote` skipped) as receipts — don't re-derive.
- **Hole B — the boot E2E already exists, is mis-named, unrun, and has no console listener.** `test_multiplexer_cold_load_hydration.py::test_boot_has_zero_4xx_and_jobs_pane_hydrates` is held ">>> NOT YET RUN <<<" and only registers `page.on("response")` for 4xx — NO `console`/`pageerror` listener, so a JS error with no 4xx sails through green. **Fix:** reference (don't duplicate) + add console/pageerror capture + make its `:8000` execution an acceptance receipt.
- **Hole C — hydration_failed consumer has no acceptance test.** `JobsPaneRenderer.ts:173` emits it; zero subscribers (Rachel's finding confirmed). **Fix:** require a fault-injection negative-path E2E (stub `/api/job-history`→500 → assert the affordance is VISIBLE + the boot console guard catches the warn); this is the 100%-branch driver for the error branch.
- **Gap D — Tier-2/3 cannot prove the new features.** The golden captures ONLY the card contract subtree — ZERO nodes for cc-strip/fleet-status/reading-pane/vote/missed-badge. **Fix:** per feature, state Tier-2/3 applicability — extend the golden (a `:8000` legacy capture, hard legacy-harness cost) OR mark N/A and rest acceptance on Tier-1 presence + functional-E2E.
- **Gap E — no feature→contract-node map.** "Each feature ticks its node" but no list of which nodes belong to which F. **Fix:** ship a feature×contract-node matrix as a Phase-0 artifact; G4=100% becomes auditable.
- **Gap F — WS1 invalidates the golden.** D5 Rider C bakes `shared_sheet_hash` (=`8908ce6a`) into the golden; WS1 trips it → `:7999` replay tiers fail until a `:8000` recapture. **Fix:** schedule a golden recapture immediately after WS1.
- Minor: forbid `pragma: no cover` on Lane-5 fault branches (token-absent→redirect, hydration-reject→surface); require fault-injection unit tests.

### Architecture (Krishna)
- **C-2 Convergence-file collision.** Every lane registers in `boot.ts` + adds mounts/`<link>`s in `multiplexer.html`, and extends the typed EventBus union + StorageService. Worktree-isolated crews merge-conflict on these on nearly every lane. **Fix:** designate `boot.ts`/`multiplexer.html`/eventbus-types/StorageService as **manager-serial-merged** (a wiring-owner lands each lane's registration); cap parallel feature lanes at the convergence-bound (~3-4), NOT the new-file count.
- **H1 — "Lane 0 → everything" is false-fat.** L0a (auth-key) is a runtime LANDING gate, not a build gate; L0b (send-path) blocks only F5 + live `.outgoing`. **Fix:** split the edge.
- **H2 — C2-d `.outgoing` day-one missing entirely** (direction param + Notification `response_value` + responded-split). Load-time half is F5-independent (core slice); live half chains off L0b per D6 Rider B.
- **H3 — strip & reading-pane under-scoped.** Decide strip-store ownership (own store vs extend SenderStore → pinned subscription order) + VERIFY the server emits the strip's events (`session_reaped` F9 / `voice_persona_assigned` F10 / lineage F11 — unverified, unlike F12/F8) BEFORE spawning Lane 1. Spec the F1 iframe CSP story; note Lane2↔WS1 cascade contention (`body[data-layout-mode]` + `reading-pane.css` specificity).
- **M1** Lane 2/3 are parallel to Lane 1 (scheduling, not dependency). **M2** pull Lane-5 hydration-consumer + console-E2E to the FRONT (cross-cutting, catch integration breakage as features merge). **M3** F6 edits existing `TtsChromeRenderer` (collision-bound). **M4** F3 keys on `.date-accordion-messages` (a contract surface → WS1 sheet-placement decision).

### Scope (Sam)
- **GAP-2 — G4=100% contradicts the AR read-only-vs-interactive class-divergence carve-out** (doc 02 WS1: disjoint classes, MISSING-by-design until convergence). **Fix:** lane the AR functional convergence OR carve the node + drop the absolute 100% claim.
- **GAP-3** AR read-only open-ended stubs (`actionRequiredReadOnly.ts:101,109` `[text input — Phase 6]`) unlaned. **GAP-4** F8 confidence-display + F4 Show-more toggle need explicit ACs. **GAP-5** resolve whether the mux renders date-accordions today (blocks F3 + G1).

### New Open Questions (add to the list)
A. Foundation status — WS1/WS2/WS3 complete/parallel/in-scope? (the gating unknown). B. AR scope — converge classes or accept a carved MISSING node + drop 100%? C. Phase-7 (telemetry/CSP/Trusted-Types/**a11y**) — IN or OUT of "full parity"? (a11y may be a real parity item). D. Cache-bust — `multiplexer.html:237` loads UNHASHED `boot.js` with no `?v=`; stale-cache risk on a default-surface flip.

**Round-2 action:** Tiberius synthesizes the above into a revised draft → re-route to the same three lenses for re-review → then Rick ratification → then (and only then) implementation. Reviewers reaped; findings captured verbatim in dm-tiberius threads + above.
