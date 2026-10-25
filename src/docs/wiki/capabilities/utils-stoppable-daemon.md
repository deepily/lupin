---
capability: utils-stoppable-daemon
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.stoppable_daemon.StoppableDaemonMixin@464f5ebc29
---
# Stoppable daemon mixin

The start and stop of a polling daemon thread, given once to the classes that run one. The standalone arbiter imports it, so it uses the standard library only.

## What it does
- A class that owns a `_stop_event`, a `_thread` and a `THREAD_NAME` gets `start` and `stop` from the mixin. It must define `_enabled()` and `_loop()`.
- `start` spawns the daemon thread and returns `True`. It returns `False` and spawns nothing when the rollout flag is off or a thread is already alive.
- The flag is `_should_start`, which returns `_enabled()`. A class with a bigger gate overrides it.
- `stop` sets the stop event and joins a live thread for at most `timeout` seconds, 5 by default.

## Don't
- Don't read a `False` from `start` as a failure. It is the off switch of a disabled class.

## Invariants
- `stop` is safe on a class that never started, and safe to call twice.
- `start` clears the stop event before it spawns, so a stopped class can start again.
