---
capability: orphan-bridge-reaper
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.shared.orphan_bridge_reaper.reconcile_orphan_bridges@52cfdd2ffe
---
# Orphan bridge reaper

`reconcile_orphan_bridges` removes session bridge files whose owners are dead and whose manager is gone, so the focus bar stops showing them as alive. The usual reap path only reaches a manager's own children.

## What it does
- It scans `cc-*.json` bridge files in the session directory and skips buffer and listener sidecar files.
- It reaps a bridge only when every host process id it carries is confirmed dead and its tmux session is gone.
- The bridge must also stay dead across at least `debounce_threshold` polls, two by default.
- On a reap it emits the persisted reaped marker and the tombstone, unlinks the bridge and clears the heartbeat hold.
- It returns lists named `reaped`, `skipped` and `errors`.
- The caller owns the `dead_polls_state` dictionary that carries the counters from one poll to the next.

## Invariants
- Inside a container it does nothing and leaves the state alone, because host process ids cannot be trusted there.
- Any live or unclear process id, or a tmux probe that fails, counts as alive and resets the counter.
- A step that raises is recorded under `errors` and never stops the sweep.
- An already reaped session is never emitted twice, and counters for vanished bridges are pruned.

## Don't
- Don't use it to reap a session you can still reach. `dismiss_sessions` is the door for those.
