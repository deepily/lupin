---
capability: reuse-run-harness-start
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_harness.driver.image_of@292ecb1da0
  - lupin_mcp.reuse_harness.driver.run_dir_of@9fa8dc9b7c
  - lupin_mcp.reuse_harness.driver.make_key@28fd368a5d
  - lupin_mcp.reuse_harness.driver.build_ports@cdc5642ba2
  - lupin_mcp.reuse_harness.driver.execute@3390406653
  - lupin_mcp.reuse_harness.driver.dry_run@4b8f879f85
  - lupin_mcp.reuse_harness.driver.parse@3dec3d206b
  - lupin_mcp.reuse_harness.driver.main@a1e0465491
  - lupin_mcp.reuse_harness.log.RunLog@bed612fd92
  - lupin_mcp.reuse_harness.log.RunLog.write@d15f7ea029
---
# Reuse run harness: starting a run

This page covers the command and the files of a run. The run itself is described in [[reuse-run-harness]].

## The command
- `python -m lupin_mcp.reuse_harness` takes the repo, a data root, a run id, the arm, the model, the frozen sha and the cap.
- `main` builds the spec from the frozen commit. It then runs the arm, or with `--dry-run` it only proves the arm.
- A dry run cuts the tree, probes the four surfaces and removes the tree. It starts no server and no database.
- `build_ports` makes one fresh sender key per run. The server, the tests and the session share it.
- The image comes from `image_of`, which reads the test service of `docker-compose.yml`.

## The files
- A run lives in `<data root>/<arm label>/<run id>/`, so no folder says which arm made it.
- It holds `log.jsonl`, the junit reports and `result.json`. The semantic scorer reads `result.json`.
- `execute` refuses a second `result.json` in one folder. `RunLog` refuses a record with a key called `arm`.
- The run id must not name the arm.

## Don't
- Don't hand a run id that says `with` or `without`.
- Don't print the sender key. It lives in the environment of the processes that need it.
