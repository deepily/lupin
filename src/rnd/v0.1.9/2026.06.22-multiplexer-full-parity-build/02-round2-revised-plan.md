# Multiplexer Full-Parity Build — Round-2 Revised Plan (for Rick's ratification)

**Date:** 2026-06-22 · **Author:** Tiberius 👑 (session 704c71b2, for Rick) · **Status:** REVISED DRAFT — folds all Round-1 cascaded-review findings (see `01-implementation-plan.md` §Cascaded Review Round 1). Rick ruled "I revise now, you ratify" (2026-06-22). Awaiting Rick ratification; re-review by the 3 lenses optional on his word.

## What changed vs Round 1 (the review's verdict was right)
Round 1 (all 3 lenses REQUEST CHANGES) exposed that the draft **consumed a parity oracle it never built or laned**, **measured layout instead of function**, and **ignored the convergence-file merge bottleneck**. This revision fixes all of that. The WS4 feature decomposition (F1–F12) was sound and is retained.

---

## A. Foundation FIRST (Lane -1) — the gate everything else needs

The oracle + single-source CSS is a **parallel v0.1.9 effort, partially complete** — NOT assumed-existing. Current verified state:
- **Tiers 0/1 + golden-capture + cross-client conformance: GREEN** (`fe3ab4da→191d4d41`).
- **Tier 2 (computed-style): GREEN** for the card chrome (Rachel's `bfcb162c` verify, merged `140dc3d8`).
- **Tier 3 (geometry): one real gap** — the persona'd CC card is ~51px short because legacy STACKS the session-id as a 2nd header row while the mux renders one flex row (a header-LAYOUT gap, captured; xfail reason narrowed).

**Lane -1 deliverables (gate the feature lanes):**
1. **WS1** CSS single-source extraction → `notifications-surface.css` (D1/S2, byte-faithful, legacy links shared sheet BEFORE its monolith).
2. **WS2** Layout Contract + reconcile C2-a/b/c **and C2-d `.outgoing` day-one** (responded-split: `notificationItem.ts` direction param + Notification-model `response_value` + adapter split — load-time half is F5-independent).
3. **WS3** finish Tier-2/3: close the 2-row-header geometry gap; **extend the golden** for every new feature that has a legacy counterpart (each needs a `:8000` legacy capture — the legacy-harness cost Doc 01 flagged).
4. **Cross-cutting, pulled to the FRONT (was mis-placed in Lane 5):** the `hydration_failed` **consumer** (JobsPaneRenderer emits it; zero subscribers today) + the **boot zero-console-error E2E** — so integration breakage is caught AS features merge, not at the end.

**Gating edge:** Foundation completion gates the **style/geometry half** of feature acceptance. Until Tier-2/3 exist for a feature's nodes, that feature can gate on Tier-1 structure + functional-E2E only — never claim "oracle-green" on a tier that isn't built.

---

## B. Acceptance bar — TWO gates per feature (the deep fix, Hole A)

Oracle-green ≠ functional-done. The layout oracle (Tier 1 presence + Tier 2/3 style/geometry) proves **structure**, not that a feature **works**. Every feature now has **two** acceptance gates:
1. **Layout oracle** — Tier-1 node MISSING→PRESENT; Tier-2/3 where a golden node exists or is extended (else explicitly N/A).
2. **Functional E2E** — handler-effect/behavioral assertions. **Leverage the existing `test_multiplexer_*` suites** (Clayton's 6/7, `ts-2c5e5deb` 64-pass; `prediction_vote` skipped) as receipts — do NOT re-derive. Add fault-injection negative-path tests (e.g. `/api/job-history`→500 → assert the surfaced failure is VISIBLE; token-absent→redirect). **No `pragma: no cover` on Lane-5 fault branches.**

**Feature→contract-node matrix (Phase-0 artifact):** map F1–F12 → their contract-node tuple set, so "G4 → 100%" is the sum of ticked rows — objectively auditable per WP. **G4 claim corrected:** "100% of LANED contract nodes." The Action-Required read-only-vs-interactive class-divergence node is **explicitly CARVED** (disjoint classes by design until functional convergence) with AR-convergence a tracked sub-lane — we do not claim 100% over a node that's MISSING-by-design.

---

## C. Convergence-file serialization (C2 — the parallelism constraint)

`boot.ts`, `multiplexer.html`, the typed EventBus event-union, and `StorageService` are touched by **every** lane (store/renderer registration, mount points/`<link>`s, new events `session_reaped`/`voice_persona_assigned`/vote/missed-count, F1 scroll + F7 missed-count storage). Worktree-isolated crews would merge-conflict on these constantly.

**Rule:** these 4 are **manager-serial-merged** via a dedicated **wiring-owner** who lands each lane's registration in sequence. New per-subsystem files stay worktree-parallel. **Parallel feature-lane cap = ~3–4** (the convergence bottleneck), NOT the new-file count.

---

## D. Corrected dependency graph (Krishna's NET)

```
Lane -1 FOUNDATION  [WS1 CSS · WS2 contract+C2-d · WS3 Tier2/3+golden-extend · L0a auth landing · hydration-consumer · console-E2E]
        │  (gates style/geometry half of all feature acceptance)
        ▼
   parallel (≤3–4, wiring-owner serial-merges boot.ts/multiplexer.html/eventbus/StorageService):
      • Lane 1  CC-session strip  → F3/F9/F10/F11   (PRE-REQ: decide strip-store ownership + VERIFY server emits session_reaped/voice_persona_assigned/lineage BEFORE spawn)
      • Lane 2  Reading-Pane      → F1/F2           (parallel to Lane 1 — scheduling, not dependency)
      • Lane 3  Commons panel     → F4              (parallel)
      • Lane 4  self-contained    → F6/F7/F8/F12    (parallel; F6 edits existing TtsChromeRenderer = collision-bound)
        │
        ▼
   L0b send-path (getCurrentUserEmail) → live `.outgoing` → oracle day-one `.outgoing` verify  (D6 Rider B)
        │
        ▼
   G0–G4 oracle green (laned nodes) + functional-E2E gate per feature  →  CUTOVER (INI flag flip + cache-bust)
```
- **L0a auth-key alignment** = a runtime LANDING prereq (split from the false-fat "Lane 0 → everything"); **L0b send-path** blocks only F5 + live `.outgoing`.

---

## E. My first-pass calls on the 3 product questions (for your ratification)

| # | Question | My call (ratify / redirect) | Rationale |
|---|---|---|---|
| 1 | **a11y** in/out of the parity bar? | **OUT of the cutover bar — with one exception** | Phase-7 (a11y/CSP/Trusted-Types) is designed-not-coded in BOTH the legacy interim client and the mux → not a regression. EXCEPTION: audit legacy for live `aria-*` affordances the mux would REGRESS; carry only those. Phase-7 proper = post-cutover roadmap. |
| 2 | **F5 insert-at-caret** — port vs accept replace-on-re-record? | **PORT the caret-splice** | Accepting replace-on-re-record reintroduces the exact 2026-06-01 regression (re-record after edit overwrites the user's edits) that F5 was created to fix. Cheap relative to the risk. |
| 3 | **Reading-Pane scope** — full vs reduced first pass? | **Reduced master-detail first pass** | Ship the core pane + toggle + AR-in-pane for parity; defer iframe-bust-out + full scroll-preserve as an oracle-gated fast-follow. The full iframe pane carries a Phase-7 CSP/sandbox cost; the master-detail core delivers the user-visible parity. |

**Other resolved opens:** Phase-7 (CSP/Trusted-Types/telemetry) = OUT (roadmap, stated explicitly). **Cache-bust** = add to the cutover lane (hashed `boot.js` or `?v=` bump — `multiplexer.html:237` loads unhashed today). **Commons single-tab (Q12)** = poll-based panel initially (do NOT `start()` `broadcast.ts` under single-tab); revisit. **date-accordion presence (GAP-5)** = verify in Foundation; if absent, Foundation builds it (Tier-1 contract node, also unblocks F3).

**OPEN — surfaced during Foundation (2026-06-22; tracked for Rick, non-blocking):** the persona'd CC-card **voice-input region**. Cheech's reproduce-not-trust (`--runxfail`) CORRECTED the charter's "2-row-header" misdiagnosis — the header node matches legacy exactly; the real ~51px gap is that legacy renders a full inline voice-input row (mic/text/send) between header and dates, while the mux uses a minimal store-driven **Record-button** flow (+ ratified F5 caret-splice) appended at card bottom. Tier-3 re-scoped to prove notification-SURFACE geometry (header + accordions + messages, anchored to the dates origin), CARVING the card-height/voice-region (documented, not golden-mask). **RESOLVED (Rick, 2026-06-22 at Foundation-green): MATCH LEGACY — full parity.** The mux REBUILDS legacy's inline voice-input row (mic/text/send between header and dates); the Record-button redesign does NOT stand. The ratified F5 caret-splice FOLDS INTO the rebuilt row (reconciled, not reverted). Consequence: the **Tier-3 voice-region carve is TEMPORARY** — lift it (restore full absolute-geometry parity on the CC card, un-anchor the dates-region dy + re-include card height) once the voice-input row matches legacy. This is a **feature item in the recorder/voice-input lane** (Lane 4-adjacent / F5 family). (Also: a genuine message-badge nesting bug — mux renders `.expired-badge`/`.abstract-indicator` as siblings stealing text width vs legacy nesting them inside `.message-text` — is being fixed legacy-faithful in this lane.)

---

## F. Crew shape & acceptance
- **Crew:** ~3–4 parallel feature-lane implementers + 1 wiring-owner (convergence-file integration) + independent reviewers; worktree-isolated for new files, serial-merge for convergence files. Off-peak scheduling for any batch runs.
- **Acceptance (cutover-ready):** all F1–F12 functional + Layer-B closed; per-feature **both** gates green (layout oracle on laned nodes + functional-E2E); 100% L/B/F on new TS/Python; AR node carved + tracked; cache-bust in place. THEN flag flip on Rick's word.

## G. Next step
On **Rick's ratification** (or redirect of any product call above): optional quick re-review by the 3 lenses → serialize lanes to the task store → spawn the worktree-isolated crew + wiring-owner → Foundation-first, then parallel feature lanes → two-gate each WP → manager review→merge-held → signal Rick for push. **No implementation until ratified.**
