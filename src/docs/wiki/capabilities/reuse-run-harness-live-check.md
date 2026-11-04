---
capability: reuse-run-harness-live-check
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_harness.live_check.plan_text@5c31e6206d
  - lupin_mcp.reuse_harness.live_check.boot_check@5320687518
  - lupin_mcp.reuse_harness.live_check.parse@26d283fd73
  - lupin_mcp.reuse_harness.live_check.main@d3f0327be2
---
# Reuse run harness: the live check

The harness is proven against simulators. This script is the first time the real CLI and a real container run together, before a pilot is paid for. The run itself is in [[reuse-run-harness]].

## The command
- `python -m lupin_mcp.reuse_harness.live_check` takes the repo, a data root, a frozen sha, a model id and an optional `--mcp-config`.
- Without `--execute` it prints the plan with the exact command and starts nothing. `plan_text` builds it.
- The sha only has to hold the acceptance tests and be on main. It need not be Rick's freeze.

## What `--execute` does
- Each arm goes through `driver.dry_run` with the real CLI: four short probe sessions per arm. A wrong answer on any surface stops the check with its code.
- The init event of each arm's latest probe is written under `<data root>/live-check/`, named by the arm label. Scrub it before it is committed as a fixture.
- `boot_check` then starts one run server and database, seeds the sender key, samples the container and runs the acceptance tests once. With no client they are expected to fail. That proves they reach the server.
- It removes the server, the database and the tree on every exit. `gone_after_stop` is true when a sample taken afterwards finds no container.
- `live-check.json` holds the answers per surface and the boot result.

## Don't
- Don't run it with `--execute` without the plan's go: it pays for 8 probe sessions.
- Don't read a passing boot as a passing client. No client exists yet.
