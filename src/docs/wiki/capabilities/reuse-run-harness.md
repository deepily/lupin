---
capability: reuse-run-harness
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_harness.arms.build_session_config@5288cd90e4
  - lupin_mcp.reuse_harness.arms.verify_arm@25226f86a8
  - lupin_mcp.reuse_harness.errors.HarnessError@4673bfbe26
  - lupin_mcp.reuse_harness.run.run_one@e7fedaca3b
  - lupin_mcp.reuse_harness.run.check_spec@63ffc99848
  - lupin_mcp.reuse_harness.run.db_name@dc02553094
  - lupin_mcp.reuse_harness.run.container_name@ecf0d7e0ca
---
# Reuse run harness

`run_one` runs one arm of the reuse experiment (plan 3, section 7.3) from a fresh worktree to a stop. The code exists and is proven with stub ports. No real worktree, server or session port exists yet, so nothing here has driven a live run.

## What a run gets
- A worktree of the frozen server commit with an empty client folder. A run whose client folder holds anything is refused with `CLIENT_NOT_EMPTY` before a server starts.
- Its own server container and throwaway database. `db_name` and `container_name` derive both names from the run id, so two runs never share one. A server that hands back other names fails `DB_NOT_OWN`. A database that already holds rows fails `DB_NOT_FRESH`. The server and database are stopped on every exit, including a failure.

## The arm switch
- The four surfaces are `check_exists`, `fetch_similar`, `read_capability` and the `reuse-reviewer` skill. The arm with them (`with`) denies nothing. The arm without them denies the four and nothing else, and removes `.claude/skills/reuse-reviewer` from the worktree. `build_session_config` makes both; only `arm_label`, `deny_rules` and `remove_paths` differ.
- `record_search` is not one of the plan's four, so both arms may call it. Changing what an arm can call is Rick's decision.
- `verify_arm` calls each surface through the session port before any work. The arm without the tools must be refused on all four, or the run stops with `SURFACE_REACHABLE`. The arm with them must reach all four, or it stops with `SURFACE_MISSING`. It asks the session, and does not read the configuration back.
- The arm labels are `arm-kestrel` (with) and `arm-heron` (without). They are not ordinary words, because the blindness scrub list takes them.

## Stop and logs
- The session works in slices. Each slice is told the seat hours left under the cap and is followed by one test run, which is the verdict.
- The run stops at the first verdict where every test passes (`all_pass`). If not, it stops when seat hours reach the cap (`cap`), and if not, when the session says it has finished (`session_ended`). `all_pass` wins when it and the cap happen on the same verdict.
- A slice that uses no seat hours and has not finished fails `NO_PROGRESS`, because the loop would never end.
- One log record per verdict names the run, arm label, model id, server commit, seat hours so far and the pass count. One stop record follows.
- The result is `{ run, passing_tests, pass_rate, client_builds, stop, seat_hours }`. The scorer reads the first three and `client_builds`.

## Inputs and ports
- The spec holds `run_id`, `arm`, `model_id`, `server_commit`, `cap_seat_hours` and `test_ids`. `check_spec` refuses a missing key, an empty text field, a cap of zero or less, and an empty or repeated test list. The test ids come from the frozen build. The ports (`worktree`, `server`, `session`, `tests`, `log`) are listed in the module docstring of `run.py`.

## Don't
- Don't read `with` or `without` from a log. Use the arm label.
- Don't put a cap value in the code. It is the spec's.
- Don't expect pair scheduling here. One call is one run. The older fresh-needs run is a different thing: see [[reuse-fresh-needs-driver]].
