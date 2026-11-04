---
capability: seat-lifecycle
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.session_spawner.spawn_sessions@b171adfb7f
  - lupin_mcp.fleet_size_cap.refusal_for_spawn@fcde12d493
  - lupin_mcp.fleet_cap_admission.admit@ffa2c208c8
  - lupin_mcp.memento_slot.verify_memento_at_slot@2e43f572b6
  - lupin_mcp.self_respin_core.perform_self_respin@7b69144c56
  - lupin_mcp.reap_memento.seats_to_withhold@253ba85cda
---
# Seat lifecycle

A seat is spawned under a fleet cap, writes a memento, then is re-spun or reaped. This page says which `lupin_mcp` module owns each step.

## Order of events
- The order is cap check in the tool, admission in the launcher, a memento, then a re-spin or a reap that waits on that memento.
- Tool-level detail for spawn, list and reap is in [[mcp-session-spawn-and-reap]]; seat trees are in [[worktree-lifecycle]].

## Spawn and cap
- `session_spawner` builds the launch command and calls the cap check before launching anything.
- `fleet_size_cap` reads the cap fresh from the configuration file, clamped between 1 and the configured ceiling.
- `refusal_for_spawn` returns nothing when current total plus requested fits the cap.
- Otherwise it returns a message with the cap, the total, the manager and worker split, and the free seats.
- `fleet_cap_admission` runs at launch time in the launcher process and holds a lock across concurrent launches.
- `admit` counts live sessions plus reservations not yet materialised, and refuses at the cap, writing nothing.
- `respin_credit` lets one same-persona launch through under skeleton crew; a credit lasts fifteen minutes and is spent once.

## Memento
- `memento_slot` derives where a seat's memento must sit from repo root, persona, session and slot.
- `verify_memento_at_slot` fails if the caller's path is not that slot, then runs the reap's own proof on it.
- `memento_merge_claim` flags a negative merge claim that names a commit already in HEAD; claims with no commit id pass.

## Self re-spin
- `perform_self_respin` aborts unless the seat has a tmux session and an `over_budget` context reading. It also needs no Last Call closing within an hour and a memento at its slot that verifies. It then asks for a go and schedules a detached clear.
- `verify_memento_content` needs this cycle's nonce line, a fresh timestamp and a body above the substance floor.

## Reap
- `dismiss_sessions` calls `reap_memento` first: `seats_to_withhold` keeps a seat alive when its work is not provably saved.
- `reap_branch.probe_seat_branches` reports commits a seat leaves behind. It never raises and says when it could not look.
