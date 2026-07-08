# Notifications → Multiplexer Migration Discrepancies

**Created**: 2026-06-25 (Mr. Radio 🦉)
**Branch**: `wip-v0.1.9-2026.06.21-bug-fix-implementation`
**Status**: 🔝 **#1 PRIORITY for the current bug-fix dev branch** (Rick, 2026-06-26)

> **Current authority (Rick, 2026-07-01)**: doc [`06` — consolidation build plan](06-consolidation-build-plan.md) is the live master plan. Rick **narrowed scope to finish + prove the 6 built accordions** (D1), **revert the modern skin → legacy uniform-light** (D2), and **dropped the menu-bar item** (present after all, D3). This **supersedes** the earlier "TOTAL 13/13 PARITY / port ALL 7 absent" ratification captured in §Master accordion inventory (design call (g), 2026-06-26).

## Purpose

A single holder for **every discrepancy** found between the legacy notifications client (`/app/notifications`, `notifications.js` + `notifications.html`) and the multiplexer reimplementation (`/app/multiplexer`, `multiplexer/**/*.ts` + `multiplexer.html`). The goal is to drive the multiplexer to **real layout-level parity** with the notifications client. Each discrepancy gets documented here (analysis → remediation → verification) until the two surfaces match.

## Contents

| # | Doc | Scope |
|---|-----|-------|
| 00 | this index | holder purpose + running discrepancy ledger + master accordion inventory |
| 01 | [Section-layout gap analysis + comparison methodology](01-mux-vs-legacy-notifications-section-gap-analysis.md) | section-level order divergence (broadcast / focus-bar / TTS-preview / Recent-Activity / per-message controls) + an 8-step scrupulous-comparison methodology |
| 02 | [Reconciliation with in-flight parity work](02-reconciliation-with-in-flight-parity-work.md) | B1–B5 vs the 06.22/06.24 builds: what's already done (`4b33ceb7`), what's net-new, and the **B1 ↔ `4b33ceb7` sibling-mount conflict** |
| 03 | [Interactive defects + visual-parity checklist](03-interactive-defects-progress-group-and-reading-pane.md) | **SWE remediation brief** (2026-06-30 A/B drill-down): 🐞 progress-group head rendered 176× per card (`notificationItem.ts:85`) + 🐞 Reading-Pane `URIError` on `%`-bearing abstracts (`ReadingPaneRenderer.ts:428`); **§5 15-row visual-parity checklist** — mux reads as unstyled scaffolding; **Action-Required (blue) + Playing (green) panels MVP-mandatory**, cramped headers / orphaned controls / missing CC-card chrome. Toggles + accordions verified GREEN. |
| 04 | [Remaining-accordions audit](04-remaining-accordions-audit.md) | source-level verdicts for the **other 12 accordions** (2 faithful ports · 3 partial/remapped · 7 absent) + new design calls (d)–(g) |
| 05 | [Adversarial parity gap matrix (2026-07-01, Sam 🎙️)](../2026.07.01-mux-vs-legacy-adversarial-parity-gap-matrix.md) | reconciliation of docs 00–04 vs **current wip `2a8defa0`** (post L1–L4): what's actually at parity now, confirmed residual gaps (R5 topic · H2 env/clock · R4 persona-name · R16 toolbar), the **verification-integrity crux** (snapshots rebaselined against the mux itself → tautological; Oracle Tier-2/3 vs legacy never run), and the 6-of-13 accordion scope-truncation |
| 06 | [Consolidation build plan (2026-07-01) — MASTER](06-consolidation-build-plan.md) | 🟡 DRAFT master plan superseding the Jul-1 decision brief. Rick's ratified **D1 finish+prove the 6 built accordions · D2 revert skin→legacy light · D3 menu-bar dropped**. Six lanes (0a header chrome · 0b layout-mode toggle · 0c ordering & default-visibility · 1 finish · 2 skin revert · 3 prove) with file/line anchors, ACs, test/venue matrix; **4 open questions** awaiting Rick's ruling. Narrows the 13/13 scope above. |

## Running discrepancy ledger

Tracked in detail in doc 01 (§0.2 + §2 + §4). Headline items:

| Area | Legacy (intended) | Multiplexer (actual) | Status |
|---|---|---|---|
| Section order | broadcast *(+ nested Recent-Activity)* → focus-bar *(+ TTS preview)* → sessions | focus-bar(top) → TTS(orphaned) → sessions → jobs → broadcast(bottom) → Recent-Activity(separate) | ❌ reordered |
| Recent-Activity history | nested **inside** the broadcast card | de-nested standalone `#commons-activity-pane` | ❌ de-nested |
| TTS preview | in section header, above focus bar | orphaned sibling below/outside the focus bar | ❌ mislocated |
| Section-header controls | count · filter-badge · history-dropdown · clear-all | appear absent (confirm not renamed) | ❓ likely missing |
| Per-message TTS controls | ⏸ pause / ⏹ stop / proxy-ratify | dropped (0 in mux) | ❌ missing |

## Resolved design calls (Rick, 2026-06-26) — remediation now UNBLOCKED

- **(a) RESTORE legacy order.** Focus-bar-at-top / broadcast-at-bottom is **accidental drift to undo**.
  Target top→bottom: **Broadcast card → Focus bar → Sessions**. → drives **B1**.
- **(b) RE-NEST Recent-Activity INSIDE the Broadcast card.** Standalone `#commons-activity-pane` is
  **not** acceptable; restore the legacy nesting. → drives **B1**.
- **(c) RESTORE per-message ⏸/⏹ + proxy-ratify-link** (→ **B4**) — with a **critical behavioral
  constraint from Rick**: *only the single bubble currently being spoken shows the controls.* The
  overwhelming majority of bubbles keep them hidden; exactly one is visible at a time, surfaced when
  TTS reaches that message. Legacy already works this way — it renders ⏸/⏹ on **every** message but
  **CSS-gates visibility to `li.is-playing-current`** (and `.is-paused-current` flips pause↔resume).
  The mux port **MUST** replicate this active-TTS-driven show/hide; a static per-bubble render is the
  **wrong** implementation. Verified mechanism: `notifications.js:14696` (render) + `:14733-14744`
  (click → pause/resume by `is-paused-current` class) + the `is-playing-current` CSS visibility gate.

## Master accordion inventory — the FULL per-accordion audit scope (2026-06-26)

Rick (2026-06-26): the left-hand vertical toolbar (`#section-toolbar`) is the **accordion selector** —
each icon shows/hides one top-level section. Only **Notifications** (the CC-session accordion) is
visible by default. **Parity is not one accordion — it is all of them**, stepped through one at a
time, verifying **functionality + layout** for each.

**Authoritative legacy inventory — 13 sections** (`notifications.html` toolbar `data-section`):

**Verdicts confirmed by source audit 2026-06-26 (doc 04).**

| # | Legacy `data-section` | Title | Mux equivalent | Verdict |
|---|---|---|---|---|
| 1 | `section-qa` | Q&A Interface | none | ❌ **TRULY ABSENT** (moderate port) |
| 2 | `section-job-submit` | Submit Agentic Jobs | none (jobs-pane can't submit) | ❌ **TRULY ABSENT** (highest build — 7 cards) |
| 3 | `action-required-section` | Action Required | folded into `notifications-pane` | ⚠️ **PARTIAL + RELOCATED** (lost active/pending model, count, kbd-nav, toolbar toggle) |
| 4 | `tts-queue-section` | TTS Queue | `tts-pane` (stub) | ⚠️ **REMAPPED/PARTIAL** (transport-only; lost per-item queue, clear-all, focus resume) |
| 5 | `section-notifications` | **Notifications (CC sessions)** | `notifications-pane` | 🔬 **ANALYZED** (docs 01/02) — B1–B5, plan `03-` pending |
| 6 | `section-fleet-status` | Fleet Status | `fleet-status-pane` | ✅ **FAITHFUL PORT — VERIFIED** (`93-` closure; 191/191 tests) |
| 7 | `section-task-list` | Task List | `task-list-pane` | ✅ **PORT + SUPERSET — VERIFIED** (read-only-contract superset ratified, ruling (d); `93-` closure) |
| 8 | `filter-settings-section` | Filter Settings (Admin) | none | ❌ **TRULY ABSENT** (coupled to #9 filter) |
| 9 | `section-queues` | Job Queues | `jobs-pane` | ⚠️ **PARTIAL** (display ok; delete/retry/time-window/pagination missing — "Phase 6b") |
| 10 | `section-time-saved` | Time Saved | none | ❌ **TRULY ABSENT** (APIs exist; moderate) |
| 11 | `section-status` | System Status | none (`fleet-status-pane`≠this) | ❌ **TRULY ABSENT** (high) |
| 12 | `section-direct-tts` | Direct TTS Test | none (`tts-pane`≠this) | ❌ **TRULY ABSENT** (low; likely intentional dev drop) |
| 13 | `section-debug` | Debug Info | none | ❌ **TRULY ABSENT** (very low; likely intentional) |

**Tally** (doc 04): 2 faithful ports · 3 partial/remapped with real regressions · **7 truly absent**
(3 likely-intentional dev/diagnostic drops; 4 user-facing needing a port decision).

**Design calls (d)–(g) RESOLVED** (Rick, 2026-06-26 `/plan-decide`; doc 04 §Resolved) — through-line
**TOTAL 13/13 PARITY**: (d) Action Required → **full funnel restore + rich responder** · (e) TTS Queue →
**full restore (chrome + per-item queue)**, prereq `AudioStore` multi-item extension · (f) Task List →
**keep edit/drop as documented superset** · (g) **port ALL 7 absent** (no obsolete drops).

**Build sequence (ratified):**
1. **CC-session (#5)** `03-` plan — B1–B5 (#1 priority).
2. **The 3 partials** — Action Required (funnel restore), TTS Queue (full restore), Job Queues (mutation gaps: delete/delete-all/retry/time-window/pagination/filter-badge).
3. **The 7 absent** — Q&A · Submit-Jobs · Time-Saved · Filter-Settings · Direct-TTS · Debug · System-Status.
(Fleet Status + Task List already at parity — Task List as an accepted superset.)

## Next steps

1. ✅ Resolve design calls (a)/(b)/(c) — **done** (Rick, 2026-06-26; see Resolved design calls above).
2. ✅ Reconcile B1–B5 vs in-flight work — **done** (doc 02). Net-new = B1/B2/B3/B4; B1 restructures `4b33ceb7`.
3. Draft the **CC-session remediation plan** (numbered `03-…`) on doc 01 §6 buckets B1–B5, now unblocked.
4. Step through the remaining 12 accordions (master inventory above); land a discrepancy doc per accordion (`04-…`).
4. (this folder) Land additional discrepancy docs as found (CSS/visual, behavior, event-wiring, etc.).
5. Execute under manage-don't-build; 100% L/B/F + visual rebaseline per mandates.

**Tracking**: P1 store task `d0a057b3`. Pinned in `TODO.md` (#1 priority).
