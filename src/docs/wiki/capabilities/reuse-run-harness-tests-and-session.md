---
capability: reuse-run-harness-tests-and-session
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_harness.acceptance.Acceptance@80a0430e63
  - lupin_mcp.reuse_harness.acceptance.Acceptance.run@ffb05c068a
  - lupin_mcp.reuse_harness.session.events_of@ba73a03d6e
  - lupin_mcp.reuse_harness.session.blocks_of@e8adeb7fdd
  - lupin_mcp.reuse_harness.session.init_of@2a5948dc75
  - lupin_mcp.reuse_harness.session.surface_listed@0ce85043be
  - lupin_mcp.reuse_harness.session.surface_answered@7a7b53f83f
  - lupin_mcp.reuse_harness.session.Sessions@cb3f9ce009
  - lupin_mcp.reuse_harness.session.Sessions.bind@8cb4a647b1
  - lupin_mcp.reuse_harness.session.Sessions.probe@3edfcd37a2
  - lupin_mcp.reuse_harness.session.Sessions.work@c92e1a89e4
---
# Reuse run harness: the tests and the session

This page covers the acceptance test port and the session port. See [[reuse-run-harness]] for the run.

Named gap: no real `claude` command has been started. The deny rules and the hooks-off setting are proven against a fake command until the pilot.

## The acceptance tests
- `run` runs the frozen tests from the run's tree against the run's server. The URL and the sender key are in the environment.
- Before each run it compares the whole tree with the frozen commit: tracked, untracked and committed changes. Any change outside `src/lupin_app/static` is `TESTS_TAMPERED`.
- A file hidden from git by an assume-unchanged or skip-worktree flag is refused. The arm's own deletions are allowed. Ignored files are not examined.
- A test passes only if every case of it passed. A skip, an error, a missing case or an unreadable report is not a pass.
- Pytest that did not finish is `TESTS_NOT_RUN`, never a set of failures.
- `client_builds` is the exit code of `npm --prefix src/lupin_app/static run build`. The generic plan names none. A missing script scores false and the run goes on.
- The brief tells the builder to keep everything it creates, `package.json` included, inside the client folder.

## The session
- A session is a headless `claude -p` process with project hooks off. Both arms get the same MCP config.
- `probe` starts a short session and asks it to call one surface.
- `surface_answered` reads the init event's tool and skill lists first, so a model that declines the prompt proves nothing. A call that was not refused also counts.
- Output with no init event, or none with a tool list, is `PROBE_BLIND`. It is never read as a denial.
- `work` runs one slice. The first slice starts the session with the brief and later slices resume it.
- Seat hours are the wall time times the seats. Two own stops in a row mean it has finished.
- The builder's permission mode defaults to `bypassPermissions`. That default awaits a ruling.
