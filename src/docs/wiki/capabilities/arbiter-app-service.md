---
capability: arbiter-app-service
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_arbiter_app.app.create_app@2c27ae212f
  - lupin_arbiter_app.app.assemble_app@df46cef3de
  - lupin_arbiter_app.app.resolve_arbiter_project@fe9b6e048a
  - lupin_arbiter_app.app.build_dm_push_fn@0377eefee0
  - lupin_arbiter_app.app.create_production_app@d0cd09bc21
---
# Arbiter app service

This is the standalone out-of-band fleet watcher on port 8001. It runs apart from the dev and test servers, so a watcher fault cannot take them down and they cannot take it down.

## What it does
- `create_app` builds the FastAPI app with `GET /health` and `GET /state`. It starts every background loop it is given at boot and stops them in reverse at shutdown. A missing loop is skipped.
- `/health` always answers. Its `status` stays "ok" while the process answers; the `loops` map and the `degraded` flag show a dead loop.
- `/state` is the read-only composite of the loop sections in the 8001-local store. A section no loop has written yet reads as an explicit "awaiting" placeholder.
- `assemble_app` is the testable wiring. The fleet arbiter loop is always wired. The health watcher and the context-pressure writer are wired only when their INI switches are on.
- All loops write sections of one shared store. `assemble_app` makes no HTTP call and builds no job until the runner starts.
- `create_production_app` is the uvicorn factory target. It builds the config, the commons gateway and the outreach hops, then hands them to `assemble_app`.
- `build_dm_push_fn` returns the DM-push hop, or None when `arbiter outreach dm push enabled` is off. `resolve_arbiter_project` names the project, falling back to "lupin".

## Don't
- Don't import `cosa.rest` or call the dev server from this module. The fleet-stall path must work with that server down.
- Don't read `status` from `/health` as proof the loops run. Read `degraded`.
- Don't build the DM-push hop without a project. The server answers 422 and drops the push.

## Invariants
- `/health` does no I/O and never raises.
- The top-level `status` of `/state` is "ok" whenever the watcher answers, whatever the fleet health is.
