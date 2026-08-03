# Multiplexer Full-Parity — Feature → Contract-Node Matrix (Phase-0 acceptance artifact)

**Date:** 2026-06-22 · **Author:** Krishna 🦚 (verification lane, session `0d69e015`, for Tiberius 👑 mgr `704c71b2`) · **Status:** RECEIPTS-BACKED — every cell below is reproduced, not asserted.

## Purpose

This is the Phase-0 artifact the Round-2 plan (`02-round2-revised-plan.md` §B, Gap E) calls for: a map of **F1–F12 → their contract-node tuple set**, ticking **PRESENT (Tier-1)** / **Tier-2-green (computed-style)** / **Tier-3-green (geometry)** / **MISSING-or-CARVED** per node, so the cutover gate **"G4 = 100% of LANED contract nodes"** becomes the objective sum of ticked rows rather than a trust claim.

It folds the Round-1 review's Gap D resolution: **the layout-parity golden captures ONLY the notification sender-card contract subtree** (`src/tests/e2e_ui/parity_oracle.py` — `CONTRACT_SKELETON_JS` / `CONTRACT_STYLE_GEOM_JS`). New feature *surfaces* (fleet table, commons panel, reading-pane chrome, TTS slider, missed badge, session-strip, vote controls) have **no legacy golden counterpart** → their Tier-2/3 cells are **N/A-by-construction** and acceptance rests on **Tier-1 structural presence (their own renderer/template unit suites at 100% L/B/F) + functional unit tests**, exactly as Gap D prescribes. Extending the golden to those surfaces (a `:8000` legacy capture) is a tracked fast-follow, not a v0.1.9 cutover blocker.

---

## What "contract node" means here (the oracle's vocabulary)

The Layout-Parity Oracle (`src/tests/parity_oracle/`) defines the **laned** contract nodes — the only nodes for which a legacy golden exists and against which Tier-2 (computed-style isomorphism) and Tier-3 (±1px geometry) can run. From `CONTRACT_STYLE_GEOM_JS` + `CONTRACT_SKELETON_JS`:

| Node key | Tier-1 presence assert | Tier-2/3 covered |
|---|---|---|
| `card:<sid>` | `.sender-card[data-sender-id]` | ✅ (card height **carved** on CC `#`-sids) |
| `card:<sid>>header` | `.sender-card-header` | ✅ |
| `.sender-card-dates` | present | ✅ (via accordion children) |
| `.sender-persona-badge` | persona'd sender only | ✅ (header region) |
| `card>acc[i]>header` | `.date-accordion-header` | ✅ |
| `card>acc[i]>date-text` | `.date-text` | ✅ |
| `card>acc[i]>messages` | `.date-accordion-messages` | ✅ |
| `.date-count`, `.date-toggle` | present | structural (Tier-1) |
| `card>msg[i]` | `.sender-message` | ✅ (CC dates-region `dy` anchored) |
| `card>msg[i]>time` | `.message-time` | ✅ |
| `card>msg[i]>text` | `.message-text` | ✅ |
| message `direction` | `.incoming` / `.outgoing` | ✅ (Tier-1 + golden-conformance) |
| message `.expired-badge`, `.abstract-indicator` | present | structural (Tier-1) |

**Canonical fixture** (`notifications-parity-scenario.json`) mounts **two** cards:
- **`claude.code@lupin.deepily.ai#parity01`** — persona'd **CC-session** card (sid carries `#`) → the **carve set** (Tier-3 voice-region carve, see below).
- **`lupin-arbiter-app-8001`** — persona-less **external** card (no `#`) → **FULL absolute-geometry parity, no carve**.

---

## Reproduction receipts (this lane, HEAD `6df6825e`)

All runs reproduced read-only against pristine HEAD. The `:7999`-served bundle was proven byte-identical to a pristine-HEAD worktree build (`boot.js` sha `d87e363e942b` in both `/tmp/mux-verify-wt` and the served `dist/`), so the oracle run is a faithful HEAD reproduction with zero concurrent-worker contamination.

### Per-lane unit + coverage (reproduce-not-trust on the 6 "audit-done" lanes)

Method per lane: `npx tsx --test <lane files>` + `npx c8 --100 --include='…/multiplexer/**/*.ts' --exclude=boot.ts`.

| Lane (file prefix) | Feature(s) | Tests | Pass/Fail | Lane-owned source @ 100% L/B/F |
|---|---|---|---|---|
| `session_strip_*` | F3/F9/F10/F11 (CC-strip) | 72 | 72 / 0 | ✅ `SessionStripStore`, `SessionStripRenderer`, `sessionStripIcon` |
| `reading_pane_*` | F1/F2 (Reading-Pane) | 90 | 90 / 0 | ✅ `ReadingPaneStore`, `ReadingPaneRenderer` |
| `commons_*` | F4 (Commons panel) | 88 | 88 / 0 | ✅ `CommonsStore`, `CommonsActivityRenderer`, `commonsActivityEntry` |
| `tts_preview_*` | F6 (preview slider) | 28 | 28 / 0 | ✅ `TtsPreviewSliderRenderer`, `ttsPreviewSlider` |
| `missed_*` | F7 (missed badge) | 25 | 25 / 0 | ✅ `MissedStore`, `MissedBadgeRenderer`, `missedBadge` |
| `fleet_*` + `fleet_model` | F12 (Fleet-Status) | 73 | 73 / 0 | ✅ `FleetStatusStore`, `FleetStatusRenderer`, `fleetModel`, `fleetStatusTable` |
| **card-surface** (`templates_sender_card`/`notification_item`/`date_accordion`) | contract-node renderers | 40 | 40 / 0 | ✅ `senderCard`, `notificationItem`, `dateAccordion` |
| **testkit** (`parity_harness`/`parity_fixture`) | oracle harness/adapter | 11 | 11 / 0 | ✅ `parityHarness`, `parityFixture` |
| **TOTAL** | | **427** | **427 / 0** | — |

> **c8 "All files" note (expected, not a gap):** each scoped run reports an "All files" aggregate of ~81–98% because the directory-wide `--include` pulls in shared deps (`html.ts`, `dom.ts`, `types.ts`, `EventBus.ts`, etc.) that a *single* lane only partially exercises. The correct per-lane bar is **lane-owned source files at 100% L/B/F** — met by every lane above. Shared deps reach 100% under their own lanes' suites.

### Layout-Parity Oracle (`src/tests/parity_oracle/`, `:7999`, component-isolation)

`python -m pytest src/tests/parity_oracle/ -v` → **10 passed, 1 skipped** (`test_golden_capture` is the capture script, gated on `LUPIN_PARITY_CAPTURE=1` — skipping is correct).

| Oracle test | Tier | Result |
|---|---|---|
| `test_tier0_css_source_identity` | Tier 0 (CSS source identity) | ✅ PASS |
| `test_tier1_mux_emits_contract_skeleton` | Tier 1 (DOM contract) | ✅ PASS |
| `test_tier1_responded_split_and_badges_present` | Tier 1 | ✅ PASS |
| `test_tier1_outgoing_direction_conformance` | Tier 1 (direction) | ✅ PASS |
| `test_tier2_computed_style_isomorphism` | **Tier 2 (core proof, NO allowlist)** | ✅ PASS |
| `test_tier3_geometry_isomorphism` | **Tier 3 (±1px, voice-region carved)** | ✅ PASS |
| `test_mux_matches_golden_card_and_message_structure` | golden conformance | ✅ PASS |
| `test_mux_matches_golden_message_widgets` | golden conformance | ✅ PASS |
| `test_mux_matches_golden_message_direction` | golden conformance | ✅ PASS |
| `test_golden_shared_sheet_hash_is_current` | golden freshness | ✅ PASS |
| `test_capture_legacy_golden` | capture (gated) | ⏭ SKIP (expected) |

**Every laned contract node is Tier-2 computed-style isomorphic and Tier-3 geometry-isomorphic to the legacy golden, with NO allowlist exemptions** (WS1 border-left, WS2/C2-d direction, and WS2/WS4 `.date-text` rename seams are all closed → proven matches per the module notes in `test_tier2_tier3.py`).

---

## The matrix — F1–F12 → contract nodes

Legend: **PRESENT** = Tier-1 structural node renders; **T2** = Tier-2 computed-style green; **T3** = Tier-3 geometry green; **N/A** = no legacy golden node for this surface (Gap D — rests on Tier-1 + functional unit tests); **CARVE** = laned but deliberately excluded from a tier with a tracked reason.

| F | Feature | Contract-node tuple set | PRESENT (T1) | T2 (style) | T3 (geom) | MISSING / CARVED |
|---|---|---|---|---|---|---|
| **F1** | Master-Detail Reading-Pane | `ReadingPaneRenderer` surface (pane/toggle/detail) — **non-golden** | ✅ own suite (90 tests) | N/A | N/A | golden-extension fast-follow (Gap D) |
| **F2** | Action-Required in pane | AR widgets (`actionRequiredInteractive`/`ReadOnly`) — **non-golden** | ✅ own suite | N/A | N/A | **AR read-only↔interactive class-divergence node CARVED by design** (round-2 §B; disjoint classes until functional convergence — tracked sub-lane) |
| **F3** | Focus-mode card-height boost | `card:<sid>` height; `card>acc[i]>{header,date-text,messages}` | ✅ accordions PRESENT | ✅ (accordion nodes) | ✅ shape (dy-anchored) | **CC `#`-card total height CARVED at T3** (carve (b) — focus-boost spans the carved voice-input region; external card height fully proven) |
| **F4** | Commons "Recent Activity" panel | `CommonsActivityRenderer` / `commonsActivityEntry` — **non-golden** | ✅ own suite (88 tests) | N/A | N/A | golden-extension fast-follow |
| **F5** | Send-path / responded-split direction | `card>msg[i]` `.incoming`/`.outgoing`; synthetic `…-response` row | ✅ Tier-1 direction PASS | ✅ | ✅ | none — **fully proven** (synthetic outgoing row matches legacy) |
| **F5-v** | CC-card inline voice-input row | `.cc-voice-input` row between header & dates — **legacy node, mux rebuild in flight** | ⛔ absent from isolation harness | — | **CARVE** | **TEMPORARY Tier-3 voice-region carve** (carves (a) dates-region `dy`-anchor + (b) CC card height). Lift once the voice-input-row rebuild (concurrent lane) matches legacy. Round-2 §E. |
| **F6** | TTS preview-fraction slider | `TtsPreviewSliderRenderer` / `ttsPreviewSlider` — **non-golden** | ✅ own suite (28 tests) | N/A | N/A | golden-extension fast-follow |
| **F7** | Missed-while-away badge + Reset | `MissedBadgeRenderer` / `missedBadge` — **non-golden** | ✅ own suite (25 tests) | N/A | N/A | golden-extension fast-follow |
| **F8** | Prediction-hint vote UI | `predictionVoteControls` — **non-golden; build in flight** | ⛔ in-flight (concurrent lane) | N/A | N/A | being built (not this verification lane) |
| **F9** | Reap → strip badge drop | `SessionStripRenderer` strip nodes — **non-golden** | ✅ own suite (session_strip 72) | N/A | N/A | golden-extension fast-follow |
| **F10** | Spin-up persona symmetry | `.sender-persona-badge` (golden) **+** strip icon (`sessionStripIcon`, non-golden) | ✅ persona_badge T1 PASS + own suite | ✅ (badge/header region) | ✅ | strip-side icon node N/A (non-golden) |
| **F11** | Manager-lineage badge | strip lineage badge (`sessionStripIcon`) — **non-golden** | ✅ own suite | N/A | N/A | not a distinct golden card node (golden skeleton checks `persona_badge` only) |
| **F12** | Read-only Fleet-Status table | `FleetStatusRenderer` / `fleetStatusTable` / `fleetModel` — **non-golden** | ✅ own suite (73 tests) | N/A | N/A | golden-extension fast-follow |

---

## G4 readout — "100% of LANED contract nodes"

**LANED contract nodes** = the notification sender-card surface (the only golden-backed nodes). Status: **100% Tier-1 PRESENT, 100% Tier-2 computed-style isomorphic, 100% Tier-3 geometry isomorphic** (±1px), with exactly two **documented, tracked carves**, both on the persona'd **CC `#`-card only** (the persona-less external card is fully proven, no carve):

1. **CC voice-input region (F5-v) — TEMPORARY carve.** Tier-3 carve (a) re-anchors CC dates-region `dy` to the dates-region origin and carve (b) excludes the CC card's total height. Reason: legacy stacks a ~51px `.cc-voice-input` mic/text/send row between header and dates; the mux rebuild of that row is a concurrent in-flight lane (round-2 §E). **Lift the carve** (restore full CC absolute geometry incl. card height) once the rebuilt row matches legacy. Until then the carve **masks neither a regression nor a new divergence** — Tier-3 still fails loudly on any *other* node.
2. **F3 focus-mode card-height** rides the same carve (b): the focus-boost dimension is exactly the carved CC card height. The accordion/message **shape** below the header is fully Tier-3-proven (dy-anchored).

**Carved-by-design (not a v0.1.9 gate):** the **F2 AR read-only↔interactive class-divergence** node (disjoint classes until functional convergence — round-2 §B / Sam GAP-2). G4 is therefore correctly stated as **"100% of LANED contract nodes"**, never "100% over a node MISSING-by-design."

**Non-golden feature surfaces (F1, F4, F6, F7, F9, F11, F12, and F8 when landed):** accepted on **Tier-1 structural presence via their own renderer/template suites at 100% L/B/F + functional unit tests** (all green above). Tier-2/3 are **N/A-by-construction** pending the tracked golden-extension fast-follow (each needs a `:8000` legacy capture — Gap D / Gap F).

## Bottom line for the manager

- The 6 "audit-done" lanes are **PROVEN by reproduction**: 427/427 unit tests pass; every lane-owned source file is 100% L/B/F.
- The Layout-Parity Oracle is **fully green** on the laned notification-surface contract nodes (Tier 0/1/2/3 + golden conformance), with two documented CC-card carves (voice-input region TEMPORARY; AR class-divergence by-design) — **no undocumented divergence, no silent carve**.
- **No "already-done" lane failed its tests or coverage.** Zero real findings against the audited lanes.
