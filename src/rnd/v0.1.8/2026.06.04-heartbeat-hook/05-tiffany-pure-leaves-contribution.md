# Heartbeat Hook + Arbiter — Tiffany 💍's Pure-Leaves Contribution

**Author:** Tiffany 💍 (Lupin session `d1554246`, pure-leaves implementer)
**Date:** 2026-06-05
**Role:** the pure, 100%-tested decision leaves across all three milestones (v1 hook → v2 oracle/idle → arbiter consumer), plus the cross-lane code reviews.

---

## What I shipped (all 100% line+branch+function)

### Heartbeat Hook v1 (committed `f304877`)
- `heartbeat_hold.py` — per-session declared-hold artifact (§0 #7 schema; atomic write; never-raise read).
- `heartbeat_work_owed.py` — pure work-owed oracle (§0 #3 signals).
- `heartbeat_poke_cap.py` — per-session poke-cap counter (§0 #6; separate budget from `MAX_STOP_BLOCKS`).
- `heartbeat_decision.py` — pure `decide_heartbeat` composition (the §0 5-step logic).
- `test_heartbeat_v1_composition.py` — the v1 adapter-contract test.

### Heartbeat Hook v2 (committed `fd3d9e7`)
- `heartbeat_events.py` extension — the `"idle"` beacon value + the pure edge-trigger helpers (`should_emit_idle` / `last_emitted_outcome` / `is_idle_transition`, sticky-until-superseded per §6.2 N4).
- `heartbeat_work_owed` 1:1 contract test — confirmed `evaluate_work_owed` consumes Rachel's `Task*`-replay output unchanged (no leaf change).
- Applied Rick's verbatim 3-condition poke wording (asserted char-for-char).

### Arbiter consumer — pure leaves (this commit, `src/cosa/agents/heartbeat_arbiter/`)
- `fleet_data_model.build_fleet_view` — events + commons_who → per-session view (liveness event-ts-PRIMARY / who-SECONDARY by session_id; state; holding_on; `stuck` = REPEATED cap_reached+owed ≥2; poke_pressure).
- `dependency_graph.build_graph` — who-waits-on-whom edges + functional-graph deadlock cycle detection (canonicalized).
- `ping_throttle` — `should_ping` / `edge_key` / `backoff_for_attempt` (escalating 60/300/900/3600) / `under_global_cap`.
- `idle_roster.build_roster` — HYBRID declared(`EVENT_IDLE`) ∪ inferred(alive+quiet), trust-labeled per Rick's §6.2 ruling.
- 4 unit suites — 37 tests, 100%.

## Working method (the through-line)
1. **Read the design before coding** — never built blind; locked seam shapes with the consumer (Rachel) *before* building (events schema, fleet-view shape, the two seam clarifications).
2. **All logic in pure, never-raises leaves** — so the gated `stop.py` / arbiter-wiring surface stayed thin; the user is never the tester.
3. **Independently `--cov-branch`-verified every "green"** — which caught what line-only / fixed-clock runs missed:
   - `heartbeat_settings.py:166` (Rachel's line-only "100%" was 98% branch).
   - `heartbeat_task_state.py:141` (same family).
   - Arbiter (c)-review finding #1: persona-vs-session_id dead lookup in `_auto_ping` (ping `reason` silently `"none"`).
   - Adjudicated Mr. Radio's F2 (backoff off-by-one) — leaf correct, fix is wiring `backoff_for_attempt(attempt-1)`.
4. **Never touched another's lane** — `stop.py` + arbiter wiring are Rachel's; I supplied leaves + signatures + reviews.

## Cross-references
- Design: `01`–`04` (this dir) + canonical PIP `2026.06.02-stop-hook-natural-heartbeat-poker.md` §0/§0.2/§0.3.
- Arbiter wiring + integration: Rachel's `05-arbiter-consumer-implementation.md` · Mr. Radio's `05-mr-radio-integration-testing-contribution.md`.
