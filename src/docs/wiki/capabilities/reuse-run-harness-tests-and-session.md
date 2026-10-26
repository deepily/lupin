---
capability: reuse-run-harness-tests-and-session
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_harness.acceptance.Acceptance@9b5907d524
  - lupin_mcp.reuse_harness.acceptance.Acceptance.run@ffb05c068a
  - lupin_mcp.reuse_harness.session.events_of@ba73a03d6e
  - lupin_mcp.reuse_harness.session.blocks_of@e8adeb7fdd
  - lupin_mcp.reuse_harness.session.surface_answered@2de239f737
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
- Before each run it compares the tests, `src/cosa` and `src/lupin_app` with the frozen commit, tracked and untracked. A difference is `TESTS_TAMPERED`. The client folder is left out.
- A test passes only if every case of it passed. A skip, an error, a missing case or an unreadable report is not a pass.
- Pytest that did not finish is `TESTS_NOT_RUN`, never a set of failures.
- `client_builds` is the exit code of the build command, `npm run build` by default. The generic plan names none.

## The session
- A session is a headless `claude -p` process with project hooks off. Both arms get the same MCP config.
- `probe` asks a short session to call one surface. `surface_answered` reads the stream. A call that was not refused is an answer.
- `work` runs one slice. The first slice starts the session with the brief and later slices resume it.
- Seat hours are the wall time times the seats. Two own stops in a row mean it has finished.
- The builder's permission mode defaults to `bypassPermissions`. That default awaits a ruling.
