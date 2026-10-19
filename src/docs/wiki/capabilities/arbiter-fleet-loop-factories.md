---
capability: arbiter-fleet-loop-factories
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_arbiter_app.fleet_arbiter_loop.build_fleet_arbiter_job_factory@5d4ae8b319
  - lupin_arbiter_app.fleet_arbiter_loop.janitor_repo_roots@4682ca2158
  - lupin_arbiter_app.fleet_arbiter_loop.make_escalation_notify_fn@d6e5981ffc
  - lupin_arbiter_app.fleet_arbiter_loop.make_refusal_notify_fn@32c290c4d7
  - lupin_arbiter_app.fleet_arbiter_loop.make_straggler_fn@fd6ee02101
  - lupin_arbiter_app.fleet_arbiter_loop.make_warmup_notify_fn@d47b9f1002
  - lupin_arbiter_app.fleet_arbiter_loop.make_worktree_janitor_fn@52fb385d16
---
# Arbiter fleet-loop factories

These builders feed the arbiter job that `FleetArbiterLoop` runs on the 8001 service. They cover the job factory, the escalation sinks, the worktree janitor and the straggler step. See [[heartbeat-arbiter]] for the loop.

## What it does
- `build_fleet_arbiter_job_factory` returns a factory. Each call builds a fresh `ArbiterConsumerJob` wired to the local store's `fleet_arbiter` section and a warm-up-wrapped escalation sink. Warm-up restarts on each recycle.
- `make_escalation_notify_fn` returns the escalation sink. It always posts to the durable commons topic, then adds the live push outcome, or "disabled" when no live hop exists. It never raises.
- `make_warmup_notify_fn` wraps a sink. While one job is inside its start period it suppresses escalations and returns a `suppressed_warmup` outcome, so the caller can journal it.
- `make_refusal_notify_fn` is the janitor's refusal sink. It posts the message and an abstract to the durable topic and gives the abstract to the live push as the card detail.
- `janitor_repo_roots` reads `arbiter worktree janitor repos`, translates each repo to a host path and dedupes. It returns the roots plus the names it could not resolve.
- `make_worktree_janitor_fn` returns a per-poll janitor covering every fleet repo. One repo raising is recorded in errors and the others are still swept.
- `make_straggler_fn` turns the refused set into one store row per tree refused over a day. It also archives rows for kept branches whose work had not landed.

## Don't
- Don't guess a repo path that did not resolve. It stays in `unresolved`.
- Don't leave the job's `worktree_janitor_fn` unset. `worktrees_swept` then reads 0 on every poll.

## Invariants
- A failing channel is an outcome value plus a log line, never an exception.
