# Reconciliation — CC-Session Discrepancies vs In-Flight Parity Work

**Date**: 2026-06-26 (this session, for Rick)
**Purpose**: Before drafting the CC-session remediation plan, reconcile the B1–B5 buckets (doc 01 §6)
against the already-ratified / in-execution parity efforts so we **do not duplicate or fight**
existing work. Read-only synthesis; cites docs under `src/rnd/v0.1.9/`.

Doc handles: **D01/D02/D04/D06** = `2026.06.22-multiplexer-full-parity-build/{01,02,04,06}`;
**DFB** = `2026.06.24-focus-bar-parity-build-plan.md`; **DGAP** =
`2026.06.24-notifications-multiplexer-focus-bar-parity-gap-list.md`; **DBR** =
`2026.06.19-multiplexer-layout-parity-methodology/02-bridging-work-plan.md`.

---

## 1. Coverage map — what's owned vs net-new

| Item | Owned already? | Where | Status | Verdict for our `03-` plan |
|---|---|---|---|---|
| **B1** — restore section order (Broadcast TOP → Focus bar → Sessions) + **re-nest Recent-Activity inside broadcast** | **No** | — | — | **NET-NEW — and CONFLICTS with `4b33ceb7`** (see §2). The meat of our plan. |
| **B2** — relocate TTS-preview slider into focus-bar header | **Component yes, placement no** | F6 (`TtsPreviewSliderRenderer`, D04 line 95) | F6 built, 100% L/B/F; **no placement contract** | **NET-NEW placement** over a done component. |
| **B3** — section-header controls (count · filter-badge · history-dropdown · clear-all) | **No** | — (D06 builds a *different* visibility toolbar) | — | **NET-NEW.** |
| **B4** — per-message ⏸/⏹ + proxy-ratify-link (active-bubble-gated) | **No** | — (`TtsChromeRenderer` is transport-only, D01 line 46) | — | **NET-NEW.** |
| **Broadcast-to-all compose port** | **Yes** | DFB Lane C (Krishna 🦚), extends gap-bridge F4 | **DONE — committed `4b33ceb7`**, e2e green, **push HELD for Rick** | Reuse; B1 restructures its mount. |
| **Per-CC-card collapse toggle** | **Yes (×2 — confirm)** | DFB Lane B (verified) **and** D06 (Rachel, branch `mux-section-toolbar-accordion-toggle`, commit-HELD) | DFB: "already wired, 11/11"; D06: commit-held, no ref | **Confirm it actually shipped** in the `4b33ceb7` tree vs sitting unmerged on D06's branch. |
| **Worker message-count badge silencing** | **Yes** | DFB Lane A (Clayton 😎) | **DONE — "LANE A FULLY CLOSED"**, folded into `4b33ceb7`, 20/20 e2e | Reuse; nothing to do. |

**Bottom line**: of the 7 ratified items, **B1/B3/B4 are fully net-new, B2 is net-new placement**, and
the other three (broadcast/collapse/worker-badge) are **already built and committed (`4b33ceb7`, push
held)**. Our `03-` plan owns **B1, B2, B3, B4, B5** only — and B1 must *restructure* `4b33ceb7`.

## 2. ⚠️ The B1 ↔ `4b33ceb7` conflict (must resolve in the plan)

DFB execution-log mounted `#broadcast-card-mount` **above** `#commons-activity` as **two siblings**
(the broadcast-port layout, committed `4b33ceb7`). Rick's B1 ruling wants the **opposite**:
Recent-Activity **nested inside** the broadcast card, the whole broadcast block at the **top**, focus
bar beneath. So B1 is not a greenfield add — it **edits freshly-committed, push-held code**. Because
that commit is *push-held for Rick*, we can restructure before it ever lands upstream (no revert of
pushed history needed). The `03-` plan must sequence B1 to land on top of / fold into `4b33ceb7`.

## 3. F1–F12 status (context — D04 matrix, read-only at HEAD `6df6825e`)

All of F1–F4, F5, F6, F7, F9–F12 **built, lane-owned files 100% L/B/F (427/427 unit tests)**; Oracle
Tier 0/1/2/3 green with two documented CC-card carves. **Only F8 (prediction-vote) and F5-v (inline
voice-input row) are not yet green** — both in-flight concurrent lanes. The CC-session card *surface*
itself is therefore largely parity-proven already; our B1–B4 work is about the **section-level
chrome around the cards** (order, nesting, header controls, per-message TTS), not the card interior.

## 4. Open carves we inherit

- **AR read-only↔interactive** node carved by design (D02 §B, DBR WS1) — any B-item touching
  Action-Required inherits this open carve.
- **CC-card total height (~51px)** Tier-3 carve, re-scoped into the F5-v voice-input rebuild (D02 §E).

## 5. Owners / branches in flight (don't collide)

- Full-parity build: mgr **Tiberius 👑** (`704c71b2`), verification **Krishna 🦚** (`0d69e015`),
  Foundation merged `3a5d87eb`.
- Section-toolbar + accordion-toggle: **Rachel 🕊️**, branch `mux-section-toolbar-accordion-toggle`,
  store task `f6dc0043`, **commit-held**.
- Focus-bar parity (broadcast/worker-badge/collapse): committed **`4b33ceb7`** on
  `wip-v0.1.9-2026.06.21-bug-fix-implementation`, store item `34466d69`, **push held for Rick**.

## 6. Net result — what the `03-` remediation plan must own

1. **B1** — section reorder + Recent-Activity re-nest, **restructuring `4b33ceb7`'s sibling mount**.
2. **B2** — move the (already-built) TTS-preview slider into the focus-bar section header.
3. **B3** — build section-header controls (count · filter-badge · history-dropdown · clear-all).
4. **B4** — per-message active-TTS-gated ⏸/⏹ + proxy-ratify-link (mechanism pinned in `00-index.md`).
5. **B5** — CSS / Oracle Tier-2/3 pass + golden rebaseline, gated last.

**Pre-req confirmations before plan execution**: (i) per-card collapse actually shipped in `4b33ceb7`
(not stranded on D06's branch); (ii) coordinate with Tiberius's crew so B1's restructure of `4b33ceb7`
doesn't collide with an unpushed follow-up.
