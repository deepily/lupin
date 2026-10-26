---
capability: reuse-run-harness-server
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_harness.server.port_is_free@603d8c79fd
  - lupin_mcp.reuse_harness.server.answers_health@7778a3f827
  - lupin_mcp.reuse_harness.server.Servers@299a962366
  - lupin_mcp.reuse_harness.server.Servers.start@33d8132258
  - lupin_mcp.reuse_harness.server.Servers.seed@2ffeb04bf3
  - lupin_mcp.reuse_harness.server.Servers.db_is_fresh@ede7a8e084
  - lupin_mcp.reuse_harness.server.Servers.stop@5af39feeb8
  - lupin_mcp.reuse_harness.databases.maintenance_url@d29db16e84
  - lupin_mcp.reuse_harness.databases.Databases@f83e8e3596
  - lupin_mcp.reuse_harness.databases.Databases.create@061b558a4a
  - lupin_mcp.reuse_harness.databases.Databases.drop@40c6095256
  - lupin_mcp.reuse_harness.databases.Databases.is_fresh@a304b69d2e
  - lupin_mcp.reuse_harness.databases.Databases.provision_sender_key@616ace0e98
---
# Reuse run harness: the server and database

This page covers the container and database each run owns. See [[reuse-run-harness]] for the run.

## The container
- `start` creates the run's database, starts one container on `127.0.0.1` in ports 18000 to 18999, and waits for `/health`.
- The container reads the run's tree, an empty `.env`, and `DB_NAME` for the run's database. Secrets go in by name, so no value is in an argument.
- A failed start removes the container and the database. Any leftover is noted on the failure.
- `stop` removes the container, then the database. It tries the second whatever the first does.

## The database
- `create` clones `lupin_template_vector`. `drop` closes the harness role's sessions, then drops.
- `is_fresh` is true when `users` and `notifications` hold no rows.
- `seed` runs after that check. It stores one service account and the bcrypt hash of the run's sender key.
- `maintenance_url` uses the test-role login only. It never falls back to the dev or prod login.
- `port_is_free` and `answers_health` are the default port probe and health probe.

## Don't
- Don't seed before the fresh check. The account would make the database look used.
