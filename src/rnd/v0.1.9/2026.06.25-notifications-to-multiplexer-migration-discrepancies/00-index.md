# Notifications → Multiplexer Migration Discrepancies

**Created**: 2026-06-25 (Mr. Radio 🦉)
**Branch**: `wip-v0.1.9-2026.06.21-bug-fix-implementation`
**Status**: 🔝 **#1 PRIORITY for the current bug-fix dev branch** (Rick, 2026-06-26)

## Purpose

A single holder for **every discrepancy** found between the legacy notifications client (`/app/notifications`, `notifications.js` + `notifications.html`) and the multiplexer reimplementation (`/app/multiplexer`, `multiplexer/**/*.ts` + `multiplexer.html`). The goal is to drive the multiplexer to **real layout-level parity** with the notifications client. Each discrepancy gets documented here (analysis → remediation → verification) until the two surfaces match.

## Contents

| # | Doc | Scope |
|---|-----|-------|
| 00 | this index | holder purpose + running discrepancy ledger |
| 01 | [Section-layout gap analysis + comparison methodology](01-mux-vs-legacy-notifications-section-gap-analysis.md) | section-level order divergence (broadcast / focus-bar / TTS-preview / Recent-Activity / per-message controls) + an 8-step scrupulous-comparison methodology |

## Running discrepancy ledger

Tracked in detail in doc 01 (§0.2 + §2 + §4). Headline items:

| Area | Legacy (intended) | Multiplexer (actual) | Status |
|---|---|---|---|
| Section order | broadcast *(+ nested Recent-Activity)* → focus-bar *(+ TTS preview)* → sessions | focus-bar(top) → TTS(orphaned) → sessions → jobs → broadcast(bottom) → Recent-Activity(separate) | ❌ reordered |
| Recent-Activity history | nested **inside** the broadcast card | de-nested standalone `#commons-activity-pane` | ❌ de-nested |
| TTS preview | in section header, above focus bar | orphaned sibling below/outside the focus bar | ❌ mislocated |
| Section-header controls | count · filter-badge · history-dropdown · clear-all | appear absent (confirm not renamed) | ❓ likely missing |
| Per-message TTS controls | ⏸ pause / ⏹ stop / proxy-ratify | dropped (0 in mux) | ❌ missing |

## Open design calls (need Rick) — gate the remediation plan

- **(a)** Is the focus-bar-at-top + broadcast-at-bottom layout an **intentional** mux redesign, or accidental drift to undo?
- **(b)** Re-nest Recent-Activity **inside** the broadcast card, or is a standalone pane acceptable?
- **(c)** Are the per-message **pause/stop** TTS controls still wanted?

## Next steps

1. (this folder) Land additional discrepancy docs as found (CSS/visual, behavior, event-wiring, etc.).
2. Resolve design calls (a)/(b)/(c).
3. Draft the **remediation/implementation plan** (numbered `02-…`) on top of doc 01 §6 buckets B1–B5.
4. Execute under manage-don't-build; 100% L/B/F + visual rebaseline per mandates.

**Tracking**: P1 store task `d0a057b3`. Pinned in `TODO.md` (#1 priority).
