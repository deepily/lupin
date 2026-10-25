---
capability: cc-board-sweep
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.board_sweep.persona_slug@eee8948a0d
  - lupin_cli.claude_code.hooks.lib.board_sweep.ledger_path@288c519f7c
  - lupin_cli.claude_code.hooks.lib.board_sweep.read_ledger@aefcea4d1e
  - lupin_cli.claude_code.hooks.lib.board_sweep.sweep_progress_line@d9e51484ca
  - lupin_cli.claude_code.hooks.lib.board_sweep.record_reviewed@3f0bd4e045
  - lupin_cli.claude_code.hooks.lib.board_sweep.rearm@198600e6c6
---
# Board sweep counter
A per-seat ledger the Stop hook reads to say how many owed rows the seat has still to review before it may stop.
## What it does
- `persona_slug` turns a persona name into a lowercase file-safe slug. `ledger_path` returns `board-sweep-<slug>.json`, or None for a blank persona.
- `read_ledger` loads one seat's ledger.
- `sweep_progress_line` builds the sentence the hook appends to its poke. The count remaining uses the live owed count, not the count at sweep start.
- It returns an empty string only when the seat has no ledger. A finished sweep, an unreadable ledger and an expired ledger each get their own loud line.
- `record_reviewed` marks row ids as reviewed. Creating the ledger needs a positive `total_at_start`, and an id outside the frozen start-set raises `ValueError`.
- `rearm` rebuilds a ledger for a fresh board. The new start-set is the union of the live ids and the prior reviewed ids.
## Don't
- Don't wire `rearm` into the Stop hook; it is a manual operator step.
## Invariants
- The reviewed count counts reviews, never drops, so dropping rows cannot finish a sweep.
- A ledger past its time limit reads as expired, and a future-stamped ledger counts as old too.
- A ledger without a frozen start-set is reported as unvalidated on every tick.
