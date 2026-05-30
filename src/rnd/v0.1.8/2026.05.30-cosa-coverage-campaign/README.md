# CoSA 100%-Coverage Campaign — Documentation Home

This directory is the home for all documentation of the CoSA 100%-coverage grandfathering-ramp campaign (started 2026-05-30). Various facets of the endeavor — the plan, baseline, execution logs, the heartbeat-poker run config, per-tier closures — accrue here over time.

## Index

| Doc | Purpose | Status |
|---|---|---|
| [`00-campaign-plan.md`](00-campaign-plan.md) | Formal plan of action — all ratified decisions (D1–D8, heartbeat, fleet, reviewer; D4 tiering resolved off evidence) | ✅ ratified 2026-05-30 |
| `01-baseline-and-denominator.md` | Baseline + denominator analysis (corrected 45.3% line / 34.8% branch; gap triage) | ⏳ currently at `../2026.05.30-cosa-100pct-coverage-baseline.md` — **relocates here once Tiffany's combined-coverage run completes** (she's actively appending to it now; moving it mid-write would orphan her edits) |
| [`02-cold-start-runbook.md`](02-cold-start-runbook.md) | **▶ THE standalone execution doc** — cold manager + fresh workers run the whole campaign from this file alone (goal, tiers, exact poker invocation/run-config, gates, revert, contingencies). Absorbs the reserved poker-run-config slot (§7). | ✅ drafted 2026-05-30 (María) |
| `9N-*-execution-log.md` | Per-tier execution logs (paired with the plan, BFE pattern) | 🔜 as tiers run |

## Conventions
- Numbered prefixes: `00`–`0N` design/plan; `9N` execution logs/closures.
- Same-dir relative links (so the set is portable as a unit).
- Cross-refs to the Lupin TODO top entry ("CoSA 100%-coverage grandfathering ramp gate").
