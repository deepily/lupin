# 07 — Cascade Revision-Handoff (mux-consolidation build-plan review)

**Date**: 2026-07-01 · **Manager/Synthesizer**: Tiberius 👑 (session b75d199b) · **Status**: Step-9 artifact — pending cold-context test + light review → `implementation_handoff_ready`
**Input plan**: [06-consolidation-build-plan.md](06-consolidation-build-plan.md) (§7 RULED by Rick 2026-07-01; reviewed as cascade `cascade-mux-consolidation`, store item `c88f45f1`)
**Cast**: Rachel 🕊️ (author) · Cheech 🌿 (S1 usability/reuse) · Clayton 😎 (S2 viability/fitness) · Sam 🎙️ (S3 ownership) · María 🌸 (steward, observer-only) · Tiberius 👑 (manager)

## §1 Purpose

Single entry point for the implementer picking up the consolidation build. The plan under build is **06 as amended in-file plus the section-topic revision threads**; this doc consolidates what changed, why, and what to watch. Cold-context goal: implement without re-reading the cascade topics.

## §2 Cascade telemetry

| Metric | Value |
|---|---|
| Sections | 4/4 ACCEPTED (A frame · B finish · C skin · D prove) |
| Findings + riders classified | **39** (A 12 · B 8 · C 9 · D 10) |
| Author revision rounds | **100% closed at Round 1** (10 bundles, 0 Round-2s) |
| Votes / user escalations | 0 / **0** (Rick's spend: 4 passive pushes + 1 completion push) |
| Cross-section findings | 4 — all resolved as coordinated dual-surface fixes (no escalation; single-author-owns-both-texts rationale documented per instance) |
| Reviewer verification gates | 2 (Clayton D1 landing gate · Sam D Round-2) — both first-try PASS |
| Steward fidelity audits | **A/B/C/D all PASS** (firsthand: git-level file verification on B; independent tier-token grep on D matching the reviewer's zero-stale claim; consolidated steward verdict: CASCADE ORTHODOX) |
| Wall-clock | ~2h05 (incl. recovered 60-min stall — see §6.4); effective ~65 min |

## §3 Per-section revision summary

**Authoritative text rule**: for each section, the plan text = 06 (as amended in-file) interpreted through the section's `author_revision` posts on `cascade-mux-consolidation-<a|b|c|d>`. Where 06's original prose and a revision conflict, **the revision wins** (except the in-file 06 edits, which are already applied).

### §3.A — Section A (Lane 0 frame defects) — 12 findings
- **Port target (U-A1)**: EXTEND `shared/notifications-surface.css` (WS1 single-source; verbatim transcription from `notifications.css:126-160/514-516/2951-2953` with per-block source citations). **Never a new mux-only stylesheet.**
- **Colors (U-A2)**: per-section headers are SOLID `background-color` (base `#e9ecef`, AR **blue** `#0d6efd`, TTS green `#198754`) — "gradient" was a misnomer; sender-card gradients are a different surface and stay.
- **Selector re-key (F-Clay-A2)**: ID-keyed per-section variants re-key to mux ids (`#tts-queue-section…` → `#tts-pane .section-header`; AR unchanged; map per §2 divergence table).
- **Chevron (U-A3)**: session-only idiom = `toggleSenderCard`@605 / `toggleDateAccordion`@599 (NOT the localStorage-persistent `taskListCollapse.ts`).
- **0b reflow (F-Clay-A1)**: legacy source block `notifications.css:~5409-5640` (un-gated `:5616` toolbar-row, `:5632` container-padding, `:5438` btn variant); mux delta = pane-open gating (`reading-pane.css:117-187`); port UN-gated (no `.content-shell.pane-open` gate).
- **Visibility precedence (F-Clay-A3)**: persisted user choice (`.section-hidden` via `SectionToolbarRenderer.ts:152`) OVERRIDES HTML `hidden` (cold-start default only); cleared-storage pass/fail triplet specified.
- **Counts (F-Clay-A4 + pin)**: `.section-header-count` span; Notifications=~~UNREAD~~ **TOTAL** count; Jobs=total across 4 buckets (net-new source).
  > ⚠️ **FACTUAL FIX (2026-07-02, Rachel 🕊️ impl / Tiberius 👑 ruled — F-Sam-D1 transparent-factual-fix precedent).** This finding as transcribed said "Notifications=UNREAD count." Ground truth (Tiberius pulled legacy directly): `notifications.js:14417-14428` `updateTotalNotificationsCount()` sums `group.totalCount` into `#notifications-count` → legacy shows **TOTAL**, not unread. "UNREAD" was a transcription error (same class as the AR green→blue and tier-label fixes). Corrected to **TOTAL** in-file; implemented as `store.list().length` in `NotificationsHeaderRenderer.refresh()`. Substance of the count-chip contract is otherwise unchanged.
- **Verification (F-Sam-A1..A5)**: dist-freshness dischargeable ONLY by rebuild→served-bundle real-browser assert on :8000 (unit test covers logic only); CSS branches by per-mode computed-style assertions (c8 covers TS only); computed-style/geometry asserts run real-browser :8000-scheduled; F13 observable = boot.ts mount-order array; A's horizontal fidelity claim is discharged by **D's oracle** (named coupling, resolved).
- Open: **OSQ A-1** (does legacy's ▭/⊞ grid btn work at runtime? AI determines; gates 0b-AC3 scope AND D's horizontal golden capture — see F-Sam-D3).

### §3.B — Section B (Lane 1 finish) — 8 findings; files 03+04 amended
- **TTS (U-B1 → F-Clay-B1)**: CONSUME `stores/TtsQueueStore.ts` (exists, 213 LoC); build ONLY the render surface. Sub-plan 03 amended DOC-WIDE (all operative tables); event = `store_tts_queue_changed` (`TtsQueueStore.ts:195`). **03-WP1 OWNS** the `store_audio_ended → advance()` wiring (zero callers today — F-Clay-B2); 01/B4 consumes.
- **Jobs (U-B2)**: retry control uses distinct `.job-retry-button` (04:108); respect delete-before-toggle delegation (`JobsPaneRenderer.ts:~360`).
- **W6 filter-badge (F-Clay-B4, closes U-B3)**: hidden static badge + `TODO(plan-08)` seam ONLY; plan-08 branch NOT AUTHORED (no unreachable-branch coverage collision).
- **Filter posture (F-Clay-B3 → F-Sam-B1)**: `matchesNotificationFilter` (`NotificationStore.ts:80-84`) — all 3 branches AUTHORED on the `direction` axis and **MUST be unit-covered per-mode** (no exclusion, no ignore); ONLY the UI toggle is deferred (Rick's own-only scope). `NotificationStore.ts` is in the coverage target list (F-Sam-B2).
- Verify-only Fleet/Task = AI re-runs existing suites; never human.

### §3.C — Section C (Lane 2 skin revert) — 9 findings
- **Sweep (U-C2 → F-Clay-C1 → F-Sam-C1)**: AC-C1 = FIXED whole-family enumeration — all 11 Tailwind emerald hexes (50…950: `#ecfdf5 #d1fae5 #a7f3d0 #6ee7b7 #34d399 #10b981 #059669 #047857 #065f46 #064e3b #022c22`), `count==0`, dark-SURFACE (not dark-TEXT) clause, **plus PRESENCE assertions** at each mapped role.
- **Role map (grounded)**: AR widgets → `#28a745` family (`bg #d4edda`, `text #155724`, `border #c3e6cb`); TTS → `#198754` family (`bg #d1e7dd`, `text #0f5132`); **AR HEADER = BLUE `#0d6efd`** (U-C1 — the original table's "green" was wrong); AR bar = filled background (padding 15px 20px), NOT a 3px border.
- **Popover (U-C3)**: `senderCard.ts:105` popover REMOVED under Q2 (badge → legacy inline icon+name); documented Trigger-6 path if Rick ever wants retention.
- **Rebaseline (F-Clay-C2/C3 + F-Sam-C2/C3)**: AC-C4 = mechanized SANITY gate (exit-code 0 + dimension/spec match + delta-report subset of expected regions), 10% pixel threshold (`src/tests/README.md:154`) — NOT `GEOM_TOL_PX`; per-role regions aligned on re-keyed selectors; page-chrome masked. **Verdict of record = Tier-2 computed-style isomorphism** (re-pointed per F-Sam-D1); Tier-3/geometry disagreement re-opens C.
- Broadcast/focus bar = page-chrome (evidence-pinned): reverts under Q2 but proves via the fast-follow oracle, outside AC-C1's blocking sweep.

### §3.D — Section D (Lane 3 prove) — 10 findings; file 06 amended in-file
- **⚠️ TIER MAP (F-Sam-D1, factual fix)**: harness truth = **Tier 2 = computed-style isomorphism (the color/skin verdict) · Tier 3 = geometry ±1px (`GEOM_TOL_PX=1.0`)** — 06 §6/§7 corrected in-file with a visible marker; Q4 substance intact (both proofs mandatory on the 6 accordions).
- **Oracle EXTEND (not just run) (F-Clay-D2)**: new legacy golden captures for the post-A frame in BOTH modes + net-new horizontal harness cases (harness has ZERO horizontal coverage today) asserting center-shift + abstracts visible + AR widgets rendered (`.content-shell .container` / `.abstract` / `.action-required-widget` — F-Sam-D5); methodology per `../2026.06.19-multiplexer-layout-parity-methodology/`; tolerance = `GEOM_TOL_PX` (`test_tier2_tier3.py:71`).
- **Golden validity (F-Sam-D3)**: horizontal golden capture GATED on OSQ A-1 resolution (legacy must actually render Q1's horizontal state).
- **R5/H2 (U-D1/U-D2)**: DIAGNOSE-then-fix — the SenderStore population path and the `sys_time_update` subscription both exist; likely R5 root = cold-load hydration lacking `session_name` (`SenderStore.ts:140` → `notifications.py:2495`); H2 = verify-render + any missing frame EMISSION only.
- **Dist (F-Clay-D3 + F-Sam-D2)**: rebuild BEFORE any :8000 visual run (never mid-run); bundle-contains proven at the SERVING surface (HTTP-fetch the served bundle; TestClient, never curl), not just on-disk grep.
- **§9 coverage riders**: W6 plan-08 branch NOT AUTHORED (no ignore site) + filter predicate branches ARE covered (F-Sam-D4).
- **OSQ D-1**: venue health-check (EXECUTOR: AI, post-pgvector) gates scheduling the §1 drive-by (EXECUTOR: HUMAN — Rick's subjective design acceptance, deliberately user-owned, NOT convertible).

## §4 Cross-section ratifications
- A↔D: horizontal fidelity coupling (F-Sam-A3/F-Clay-D1) RESOLVED — D's oracle explicitly covers Q1 two-mode substance.
- B↔D: coverage postures symmetric (§9 states both).
- C↔D: AC-C4 sanity-gate vs Tier-2 verdict-of-record; Tier-2 wins on disagreement, C re-opens.
- All of Rick's D1–D3 + §7 Q1–Q4 rulings SURVIVE intact (two factual transcription fixes enforce them: AR green→blue; tier-label swap).

## §5 Post-cascade fold bundle (for the eventual commit)
Amended files (all working-tree, git-verified by steward): `05-build-plans/03-tts-queue-full-restore.md` · `05-build-plans/04-job-queues-mutation-gaps.md` · `06-consolidation-build-plan.md` · this doc (07) · topic threads remain the audit record. Commit is HELD to the standing pre-commit review + Rick's push word, per Lupin doctrine.

## §6 Workflow-guidance candidates (REQUIRED index — retro input)
1. **Grep-first-for-prior-art** (Cheech; U-A1/U-B1/U-D1): every proposed "new" store/renderer/path greps for an existing symbol first; prefer consume/diagnose-existing wording. → Author pre-handoff checklist candidate.
2. **Enumerate-the-whole-family** (Sam/Rachel; F-Clay-C1→F-Sam-C1, tier tokens): a `count==0` gate over a partial subset is a false-green generator; fix enumerates the complete family, never the found instances.
3. **Verify-at-the-serving-surface** (Sam; F-Sam-A1↔D2): build/unit checks never rule out a stale SERVED bundle.
4. **Hollow-mechanism tag-tracing** (Sam; A1/A2→C1→D1 family): Pass-2 traces tag→mechanism→provable-property, not tag presence.
5. **Transparent in-file factual fix over drifting side-note** (Rachel; F-Sam-D1): correcting ruled-wording transcription errors in-file with a visible marker beats banner-only fixes (which demonstrably don't propagate — F-Clay-B1).
6. **Undelivered-DM-to-parked-worker stall** (manager; §2 wall-clock): stage assignments to parked panes need a tmux-wake chaser; pane-state check (parked vs mid-turn) decides. → cascade workflow §6.4 candidate.
7. Sam's full ownership-lane telemetry: `kind=retro_input` post on the main topic (8 finding anchors).

## §7 Hand-off statement
The input plan is **cascade-revised in place** (06 + the three amended files + the four revision threads). The implementer builds Lanes 0→1→2→3 per §8 of 06 as revised, with this doc as the consolidated delta guide. **Build-time watch-items**: (i) horizontal-golden tolerance 1.0-vs-1.5 (wide reflow may behave fullpage-like); (ii) D5 selector-(i) `.pane-open` gating reconcile with 0b's pane-closed reflow; (iii) OSQ A-1 + OSQ D-1 resolve BEFORE their gated steps.

**Rick confirmations (2026-07-01 22:20, María-facilitated walkthrough — ALL THREE FYIs ACCEPTED, zero scope changes)**: (1) tier-label factual fix STANDS; (2) frozen own/others axis covered by his own-only scope + the direction-axis ruling — UI toggle stays deferred, NO build-scope add; (3) popover REMOVED per Q2 — **NO retention carve-out**. The plan stands exactly as cascade-revised.

**Remaining human gates**: Rick's §1 drive-by (after the OSQ D-1 health-check) + push/commit words. Nothing else is user-pending.
