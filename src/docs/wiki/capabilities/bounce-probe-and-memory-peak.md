---
capability: bounce-probe-and-memory-peak
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.bounce_busy_probe.classify@1ab50c5e04
  - scripts.bounce_busy_probe.probe@b6594de86b
  - scripts.bounce_busy_probe.main@3ba000ee73
  - scripts.derive_cc_memory_peak.derive@1149482d90
  - scripts.derive_cc_memory_peak.render@661275fd19
  - scripts.derive_cc_memory_peak.main@9a918dfead
---
# Bounce busy probe and memory peak

Two small operations helpers that turn a measurement into a decision.

## Bounce busy probe
- The probe is the running-job check for the dev-server bounce script. It reads the unauthenticated busy endpoint on `:7999`, which returns the in-flight agentic job count and the run queue size.
- `classify` is an or-trigger: it returns the busy code if either count is above zero, else the idle code. The run queue is delete-on-done, so neither count is non-zero on an idle box, and the guard does not fire spuriously.
- `probe` fetches the endpoint and returns the exit code the bounce script reads. It prints a one-line summary to stderr every time.
- Exit 0 means idle, so a bounce is safe. Exit 10 means busy, and the bounce refuses unless forced. Exit 20 means unreachable or malformed.
- On exit 20 the bounce fails open, because a broken probe must never block recovery of a wedged server.
- `main` uses the `BOUNCE_BUSY_URL` variable when set, else the default URL.

## Memory peak
- `derive` reduces the Claude Code memory watcher's report lines to a concurrency and memory peak, plus everything it could not see. It groups on the scope's anonymous memory, the quantity a cgroup cap acts on, and never sums per-process resident size.
- It counts sessions over all lines, not only groupable ones, and returns a usable count of zero rather than raising.
- `render` prints every peak beside the number of excluded lines and the session count, so a window's property is never read as the fleet's.
- A steady-state sample shows a cap is safe, never that it is unnecessary. `main` reads the log path from the first argument.
