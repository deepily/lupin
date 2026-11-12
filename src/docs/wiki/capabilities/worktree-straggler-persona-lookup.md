---
capability: worktree-straggler-persona-lookup
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.shared.worktree_straggler_tickets.registered_persona_slugs@48e147d05a
  - cosa.agents.shared.worktree_straggler_tickets.leading_persona@c5aaf68eec
  - cosa.agents.shared.worktree_straggler_tickets.live_unspawned_persona@34a8635a49
---
# Worktree straggler persona lookup

The persona steps inside `resolve_creator`, which finds the owner of a refused tree or archived branch. See [[worktree-straggler-tickets]].

## What it does
- `registered_persona_slugs` reads the persona names from the `cc session voice persona pool` key. It returns an empty list when the config cannot be read.
- `leading_persona` returns the longest registered persona that a tree or branch name begins with. It judges whole hyphen-delimited words, so `mr-radio-x` goes to `mr radio` and `mr` never matches `mrs-x`.
- `live_unspawned_persona` returns a persona when a live seat holds it, none of its live seats was spawned and no lineage resolves. Such a seat is a manager and owns its own branches.

## Invariants
- None of these raises. A failed read gives an empty list or `None`, never a guess.
