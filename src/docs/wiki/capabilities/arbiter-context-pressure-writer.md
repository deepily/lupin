---
capability: arbiter-context-pressure-writer
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_arbiter_app.context_pressure_writer.build_context_pressure_section@2f6023abac
  - lupin_arbiter_app.context_pressure_writer.ContextPressureWriterLoop@1fc1857cdd
---
# Arbiter context-pressure writer

This is the standing publisher of fleet context headroom on port 8001. Each tick it reads the sensors and writes one section, `context_pressure`, into the 8001-local store.

## What it does
- `ContextPressureWriterLoop` runs on a daemon thread. Each tick calls `poll_once`, then sleeps. `start` spawns the thread and `stop` signals it and joins.
- `poll_once` assesses the fleet, applies the budget transform and writes the section. It returns True only when the section was written.
- The budget policy maps a 1M window to 0.50 and a 200K window to 0.75. Any other size uses the default.
- `budget_ceiling_tokens` is the window times its fraction. Headroom is the ceiling minus occupancy, and it is signed and never clamped.
- Both `occupancy_tokens` and `next_prompt_estimate` are published, each with its own headroom. The current headroom, not the forward one, sets `status`.
- `status` is `over_budget` when the current headroom is below zero.
- `build_context_pressure_section` returns `generated_at`, `policy`, `personas`, `unnamed_seats` and `summary`. A named worker keys the persona map. A nameless live worker goes to `unnamed_seats`.
- An idle or dead worker publishes `occupancy_tokens: null`, and so does an active one with no assistant turn yet. No false zero is written.

## Don't
- Don't read a null occupancy as zero headroom used.
- Don't expect it to notify anyone. It writes the store only and emits nothing to commons.

## Invariants
- A failed assess is logged as `assess_error` and the earlier section stays. Stale beats absent.
- One bad tick never ends the loop.
