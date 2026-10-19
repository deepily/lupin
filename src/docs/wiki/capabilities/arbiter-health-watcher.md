---
capability: arbiter-health-watcher
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_arbiter_app.health_watcher.SystemClock@d82cd7c49e
  - lupin_arbiter_app.health_watcher.docker_inspect_health@8395eaf9a6
  - lupin_arbiter_app.health_watcher.docker_inspect_restart_count@fc9554f6d3
  - lupin_arbiter_app.health_watcher.docker_inspect_env@473f7ad88c
  - lupin_arbiter_app.health_watcher.assess_reload_blindness@6e042ca10a
  - lupin_arbiter_app.health_watcher.ContainerHealthTracker@e8b512386a
  - lupin_arbiter_app.health_watcher.RestartLoopTracker@04ab5b97f4
  - lupin_arbiter_app.health_watcher.HealthWatcherLoop@ea1fbeccba
---
# Arbiter health watcher

This is the container health watch of the 8001 arbiter service. Each poll inspects Docker health for every named container, tracks the changes it sees and escalates through an injected notify function.

## What it does
- `HealthWatcherLoop` runs on its own daemon thread. `poll_once` inspects each container, tracks and escalates, and returns True when at least one inspect worked. `run` loops it, `start` spawns the thread and `stop` joins it.
- `ContainerHealthTracker.observe` takes one status and returns the events to fire now. The first sighting is only a baseline.
- Two events exist. `enter_unhealthy` fires once per episode, and `flapping` fires when transitions in the window reach the threshold.
- `is_flapping` and `transitions_in_window` expose the same counts. A container on the flap-exclude list is never paged for flapping.
- `RestartLoopTracker.observe` takes Docker's `RestartCount`. It fires `crash_loop` once per episode when enough rises fall in the window. A drop to 0 means a recreate and resets the episode.
- The crash-loop check is not skipped for flap-excluded containers.
- `docker_inspect_health`, `docker_inspect_restart_count` and `docker_inspect_env` run a time-bounded `docker inspect`. They return None on any failure and never raise.
- `assess_reload_blindness` reports "blind" when uvicorn reload is on, because the reloader hides worker crashes from `RestartCount`. An env that cannot be read gives "unknown".
- After several polls in which every inspect fails, the watcher escalates that it is itself blind. `SystemClock` is the time seam.

## Don't
- Don't read Docker's own health log for transitions. The watcher tracks its own successive observations.
- Don't expect the health route to touch Docker. The watcher runs on its own thread.

## Invariants
- One bad container or one bad poll never ends the loop.
- Each escalation fires once per episode and re-arms on recovery.
