---
capability: cc-heartbeat-events
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.heartbeat_events.events_path@c5d5973194
  - lupin_cli.claude_code.hooks.lib.heartbeat_events.emit_outcome@510b6be01e
  - lupin_cli.claude_code.hooks.lib.heartbeat_events.emit_idle_prompt@95c592ac95
  - lupin_cli.claude_code.hooks.lib.heartbeat_events.emit_reaped@5aa7285169
  - lupin_cli.claude_code.hooks.lib.heartbeat_events.emit_task_transition@073575b126
  - lupin_cli.claude_code.hooks.lib.heartbeat_events.read_events@6f7b4fb98a
  - lupin_cli.claude_code.hooks.lib.heartbeat_events.last_emitted_outcome@18dce77671
  - lupin_cli.claude_code.hooks.lib.heartbeat_events.should_emit_idle@5e6aaa389b
  - lupin_cli.claude_code.hooks.lib.heartbeat_events.is_idle_transition@967075231b
---
# Heartbeat event records
Fire-and-forget JSON Lines records, one file per session under `~/.claude/heartbeat-events/`, that the fleet arbiter reads later.
## What it does
- `events_path` gives the per-session file path. `read_events` returns that session's records.
- `emit_outcome` appends a record for `poked`, `honored`, `cap_reached` or `idle`. Any other outcome, including `not_owed`, writes nothing and returns False.
- `emit_idle_prompt` appends a `kind` `idle_prompt` record when Claude Code shows the idle prompt. It counts an idling session as alive.
- `emit_reaped` appends a `reaped` tombstone, so the arbiter can mark a torn-down session offline at once.
- `emit_task_transition` appends a `task_transition` record on each task-store write. It counts as progress.
- `last_emitted_outcome` scans from the tail and skips kind-tagged records, which carry no `outcome`.
- `should_emit_idle` is true unless the last outcome was already `idle`. `is_idle_transition` combines both for the caller.
## Don't
- Don't read `outcome` from the last record directly; a trailing kind-tagged record has none.
## Invariants
- An emit never raises into the poke path. It returns False on failure.
- Kind-tagged records feed recency signals only, never the arbiter's `state`.
- The files live in one fleet-wide folder, not the project root, so the arbiter can glob them.
