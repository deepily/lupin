# Notifications-UI → Multiplexer Gap-Bridge (2026-06-10)

**Author:** Rachel 🕊️ (author for manager Tiberius 👑) · **Lane:** docs-only analysis + planning
**Engagement:** TOP-PRIORITY, Rick-directed 2026-06-10 — deprecate the JS notifications client by
**Sat 2026-06-14**; the multiplexer must absorb everything the JS client gained since the v0.1.7
merge anchor `26898e1` (2026-05-29).

## Documents

| # | Doc | What it answers |
|---|---|---|
| 00 | [Functional-change summary](00-functional-change-summary.md) | Every user-facing capability added to the JS notifications client since the anchor, grouped into 12 features (F1–F12), with commit refs, front-end surfaces, server deps, and E2E tests. |
| 01 | [Gap analysis](01-gap-analysis.md) | Which of F1–F12 the multiplexer has / partially has / lacks (read from TS source). Surfaces the **two gap layers**: interim features (Layer A) + pre-existing parity blockers (Layer B). |
| 02 | [Bridging work plan](02-bridging-work-plan.md) | **r2 (parallel Claude lanes).** Work packages WP0–WP15 in Claude-lane-hours (+ human), dependency spine, crew topology (worktree isolation, per-lane reviewer gating, `:8000` E2E cadence), Friday-night fallback cut-line, and the deprecation cutover checklist. Target = **full parity by Sat 2026-06-14**. |
| 03 | [Saturday cutover readiness](03-saturday-cutover-readiness.md) | **Go/no-go report (Clayton 😎, 2026-06-11).** Every checklist row status'd; the flip mechanics BUILT + held inactive behind new INI key `legacy notifications redirect enabled` (302 + `?classic=1` escape hatch, 100% L/B); 153 legacy E2E navigation sites future-proofed; Saturday GO procedure; batched Rick decision items. |

## TL;DR for Tiberius

- **All 12 interim features are ABSENT or non-functional-partial in the multiplexer.** Zero are fully present.
- The multiplexer paused at **Phase 6c** (notifications + jobs + action-required + persona + focus-tray
  core, 100% covered) and **never absorbed** the Reading Pane, CC-session strip, commons activity panel,
  Fleet-Status, messaging plane, prediction votes, missed badge, manager badges, a working sender-send
  path, or a login bounce.
- **Two gap layers:** Layer A = the 12 interim features; Layer B = pre-existing parity blockers
  (CC-session strip keystone, commons panel, auth token-key mismatch, sender-send TODO, Reading Pane).
- **r1 → r2 recalibration:** r1 sized in *human* engineer-days (~19.5d) and called Saturday "not
  credible." **Rick rejected the units, not the facts** — Claude lanes run 10–20× faster, so ~156
  human-hours ≈ **8–16 Claude-lane-hours**; parallelized, the wall-clock is the **Reading-Pane critical
  path (~2.2–4.4 lane-hrs)**. **Full parity by Saturday is credible.** Real long pole = `:8000` E2E
  serialization (monopolize) + `boot.ts` write-contention — handled via worktree isolation + a single
  integration owner.
- **Target = full parity by Sat 2026-06-14, hard redirect if green.** All 4 decisions ratified
  (full-parity bar; migrate to `lupin_*` keys; parallel lanes; Reading Pane in). **Friday-night
  fallback** = MVD-no-redirect (landing default, no redirect; ship redirect Monday), dropping the
  Reading Pane lane first, commons panel second, keeping blockers + quartet + strip family.
- **5 implementer lanes** proposed (Foundation → Strip keystone, Reading Pane, Commons panel, Quartet);
  Tiberius staffs.

## Sources

Anchor `26898e1`; commit diffs read directly; per-feature R&D docs under `src/rnd/v0.1.8/`; multiplexer
TS source under `src/lupin_app/static/js/multiplexer/`; multiplexer design docs under
`src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/`.
