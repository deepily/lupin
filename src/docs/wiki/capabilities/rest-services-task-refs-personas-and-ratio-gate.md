---
capability: rest-services-task-refs-personas-and-ratio-gate
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.task_store_rules.classify_task_ref@dc1fc8e4e4
  - cosa.rest.task_store_rules.hyphenate_compact_prefix@8012462ec6
  - cosa.rest.task_store_rules.persona_from_created_by@cee2de9232
  - cosa.rest.task_store_rules.session_id_from_created_by@d8886f669b
  - cosa.rest.task_store_rules.build_persona_advisory@f52c483918
  - cosa.rest.task_store_rules.epic_key_advisory@3932f0fdbb
  - cosa.rest.task_store_rules.ratio_gate_advisory@88dc30be51
  - cosa.rest.task_store_rules.ratio_gate_reading@2e7355b70f
  - cosa.rest.task_store_rules.ratio_gate_headroom@05c9325e5c
  - cosa.rest.task_store_rules.ratio_gate_close_needed@92aa9acd17
  - cosa.rest.task_store_rules.ratio_loop_headroom@ca1080927a
---
# Task refs, persona fields and the ratio gate

Pure helpers in `task_store_rules` for naming a row, naming its owner, and limiting how fast new rows arrive. See [[task-store]].

## What it does
- `classify_task_ref( ref )` returns `( "full", UUID )`, `( "prefix", lowercase hex )` for 4 or more hex characters, or `( "invalid", None )`. Hyphens are allowed in a prefix. Junk is never a prefix, so caller text never builds a `LIKE` pattern.
- `hyphenate_compact_prefix` puts the 8-4-4-4-12 hyphens back so a compact prefix matches stored ids. Both prefix lookups share it.
- `persona_from_created_by( created_by )` strips a trailing 6 or more hex session id from `"<persona> <sid>"` and canonicalizes the rest. `session_id_from_created_by` returns that tail or `None`.
- `build_persona_advisory( owner, manager, known_keys )` returns `( advisory, marker )` for off-roster persona fields, or `( None, None )`. It never rejects.
- `epic_key_advisory( correlation_key )` is `None` for an `epic:` or `cc-task:` key and otherwise names `epic:unassigned` as a legal answer.
- `ratio_gate_advisory( created, closed, priority, correlation_key, allow_below )` returns a refusal string or `None`. `ratio_gate_reading` is the log line for a permit, with `n/a` when nothing is closed.
- `ratio_gate_headroom` counts how many more ordinary creates the gate admits, and `ratio_gate_close_needed` how many closures it needs. Both ask the gate rather than repeating its rule.
- `ratio_loop_headroom` is one less than the gate headroom by ruling.

## Don't
- Don't pass `allow_below=None` from new code; the router passes the live threshold so gate and endpoint agree.
- Don't "fix" the one-less loop headroom. It is a ruling.

## Invariants
- The gate judges each create against the counts before it lands, so the create that reaches the threshold is admitted.
