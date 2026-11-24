---
capability: swe-team-stored-answers
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.swe_team.strategy_builder.stored_answers_for@877e017a3f
---
# SWE team stored answers

Reads a category's stored swe decisions back, so the engineering strategy can rebuild its re-frame history after a restart. The orchestrator is in [[swe-team-orchestrator]].

## What it does
- `stored_answers_for( category )` yields each answered row's `metadata_json` dict, newest first, from the swe decision rows.
- It reads no more rows than the caller pulls.
- A database failure is logged and the stream ends empty. It never propagates.
- `build_ini_engineering_strategy` passes it to `EngineeringStrategy` as `stored_answers`.
- The strategy uses it only when the neither-is-no-ruling switch is on.
