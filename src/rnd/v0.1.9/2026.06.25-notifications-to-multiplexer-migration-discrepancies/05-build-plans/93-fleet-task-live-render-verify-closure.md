# Fleet #6 + Task List #7 — Live-Render Verify Closure (MVP set closer)

**Date**: 2026-06-29
**Verifier**: Mr. Radio 🦉 (session 2f4feb0a)
**Store task**: `91788c40` (verify-only; no build plan — both accordions already at parity)
**Scope ratification**: Rick Option A (2026-06-27) + `/plan-decide` rulings (d)/(f) (2026-06-26, doc `04` §Resolved)
**Sibling closures**: `91-00c-cascade-closure-synthesis.md` · `92-01-cascade-closure-synthesis.md`

> **✅ STATUS: VERIFIED — Fleet #6 and Task List #7 confirmed at parity. This CLOSES the MVP switchover-critical set** (00b accepted · 00c cascade closed · 01 cascade closed · Fleet #6 + Task #7 verified).

---

## §1 Purpose

The 4th and final item of the minimum-viable switchover set was a **verify-only** task — no build plan, because both accordions were already assessed at parity in the read-only audit (doc `04` §#6/#7). This note records the verification evidence + the **read-only-contract divergence** that ruling (d) ratified, so the parity contract is on record and the MVP set can be declared closed.

## §2 Verdict per accordion

### #6 Fleet Status — ✅ FAITHFUL READ-ONLY PORT (at parity)

- **Mux surface**: `fleet-status-pane` / `FleetStatusRenderer.ts`.
- **Port fidelity**: ports legacy `renderFleetStatus` (`notifications.js:8801-8910`) — the four §6.4 render states (sign-in / unreachable / empty / table), the live-only count, and the "updated HH:MM:SS TZ" stamp (`FleetStatusRenderer.ts` header cite). Pure model in `render/fleetModel.ts`; table/row/toggle DOM in `templates/fleetStatusTable.ts`; fetch/poll/toggle state in `FleetStatusStore`.
- **Contract**: READ-ONLY — display only, no mutating controls. Matches legacy exactly.
- **Only divergences**: cosmetic — header-accordion → toolbar-toggle, `<h2>`→`<h3>`. None functional.

### #7 Task List — ✅ PORT + SUPERSET (intentional contract divergence, ratified)

- **Mux surface**: `task-list-pane` / `TaskListRenderer.ts`.
- **Port fidelity**: owner-grouped table of OPEN (non-terminal) work; collapse-all relocated to the section header.
- **Divergence (RATIFIED, not a defect)**: the mux ADDS a Phase-2 optimistic-write surface — per-row priority/owner edit + drop-with-reason (`TaskListRenderer.ts:39-42` mutation interface; delegated change/click dispatch `:288+`). Legacy Task List is explicitly **read-only, NO mutating controls**.
- **Read-only-contract note (the deliverable)**: per Rick `/plan-decide` ruling **(d)** — *"Task List → KEEP edit/drop as a documented SUPERSET. Accept the mux's per-row priority/owner edit + drop-with-reason as an intentional divergence (task store = fleet control plane). Not a defect; update the parity contract to note Task List is deliberately a superset of legacy's read-only view."* This closure note IS that contract update: **the mux Task List is a deliberate superset of legacy's read-only view; the added mutation controls are the task-store control plane and are accepted, not a parity gap.**

## §3 Evidence (receipts)

- **Automated render verification**: `npx tsx --test` over the Fleet + Task List unit suites — **191/191 pass, 0 fail** (fleet_status_renderer · fleet_model · templates_fleet_status_table · fleet_status_store · task_list_renderer · task_list_model · task_list_collapse · templates_task_list_table · task_list_store). Covers the four Fleet render states, the Task owner-grouped table, collapse, and the Phase-2 edit/drop mutation paths.
- **Source cites** verified live on disk: `FleetStatusRenderer.ts` header (legacy port lines), `TaskListRenderer.ts:39-42`/`:288+` (superset controls).

## §4 The one non-automatable sliver (named, not silently deferred)

A true **subjective visual glance** — "does the rendered pane LOOK right pixel-for-pixel against legacy" — is the only layer the unit suite can't assert; it's Rick's visual judgment by definition. It is NOT a blocker for this closure: functional + structural parity is proven by the 191-test green + the renderer cites, and the layout-parity Oracle tiers (T0–T3) gate geometry separately. Flagged here for an optional Rick eyeball, per "user is never the tester — except genuinely subjective visual sign-off."

## §5 MVP switchover-critical set — CLOSED

| # | Plan | State |
|---|------|-------|
| 00b | F0 AudioStore/TtsQueueStore foundation | ✅ accepted as-is (Option A) |
| 00c | Phase-6 TTS playback engine | ✅ cascade closed (`91-…`) |
| 01 | CC-session Notifications B1–B5 | ✅ cascade closed (`92-…`) |
| #6/#7 | Fleet Status + Task List | ✅ **verified at parity (this note)** |

The review/verify side of the minimum-viable switchover is complete. Remaining downstream (not this task): the `eb84266b` B1 build-sequencing gate (per-card-collapse double-ownership with Rachel + Tiberius) before Plan 01 B1 BUILDS; corpus 02–11 fast-follow.

## §6 Read-only-contract note — DISPLAY surfaces are non-mutating (closes gate `21fdcd89`)

Added 2026-07-01 (Cheech 🌿), folded into the task-list copy-ID + Detail-column-move build (spec `src/rnd/v0.1.9/2026.07.01-tasklist-copy-id-and-detail-column-move.md`, Feature 3) because that build touches these exact surfaces. This is the last sub-item of the retired final-MVP-gate seat (plan-side task `21fdcd89`).

**Contract**: the **Fleet Status** table and the **Task List** table are *render-only display surfaces* — they PAINT task-store / fleet state and NEVER write it. Every display cell (ID · Title · Detail · Class · Status · Blocked by · Next chase · Accountable · Priority · Project) is non-mutating. The ONLY mutation surface is the trailing **Actions** column (priority select · owner-reassign select · drop-with-reason), whose controls the renderer dispatches through the optimistic-write interface (`TaskListRenderer.ts` `patchTask`/`dropTask`, §30 above / the ratified superset in §2). This is consistent with ruling (d): the mux Task List is a deliberate SUPERSET of legacy's read-only view; the added mutations are the task-store control plane, confined to the Actions column.

**F1 (click-to-copy ID) does NOT breach this contract**: the ID-cell click/Enter/Space handler READS the row's `data-task-id` and copies it to the clipboard — a pure read affordance with zero task-store write. The display surfaces remain non-mutating; copy is an egress convenience, not a mutation. Gate `21fdcd89` is closed.
