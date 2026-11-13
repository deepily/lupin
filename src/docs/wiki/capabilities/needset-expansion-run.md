---
capability: needset-expansion-run
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.expansion_run.read_env_file@41fa00e29a
  - lupin_mcp.reuse_needset.expansion_run.need_rows@95fc296169
  - lupin_mcp.reuse_needset.expansion_run.control_rows@09f54fdafb
  - lupin_mcp.reuse_needset.expansion_run.FullResident@cfc241e68c
  - lupin_mcp.reuse_needset.expansion_run.FullResident.search@08e31de8e9
  - lupin_mcp.reuse_needset.expansion_run.FullStage@e747c07d22
  - lupin_mcp.reuse_needset.expansion_run.FullStage.__init__@6f2301c712
  - lupin_mcp.reuse_needset.expansion_run.lists_for@640a073a0b
  - lupin_mcp.reuse_needset.expansion_run.plan_of@f3155766c9
  - lupin_mcp.reuse_needset.expansion_run.run_live@7785bf4f62
  - lupin_mcp.reuse_needset.expansion_run.parse_args@6bdf166fcf
  - lupin_mcp.reuse_needset.expansion_run.collect_rows@9a2d99a23f
  - lupin_mcp.reuse_needset.expansion_run.main@cdb903d39d
  - lupin_mcp.reuse_needset.expansion_run.exit_status@e0995b5ff4
  - lupin_mcp.reuse_needset.expansion_run.run_cli@2b9e55e56d
---
# Need set: expansion run

Wires [[needset-expansion-replay]] to the real model and the real search. The known-answer needs are rebuilt from an earlier run's saved answers, so only the expansion replies are new calls.

## Rows
- `collect_rows` rebuilds the attribution and yield needs with the saved answers of [[needset-yield-trace]], then the control originals with `control_rows`. A seed or pair with no saved answer is listed and left out.
- `need_rows` takes each seed as its known answer. `control_rows` takes the original's index id as the known answer and the need the control drafted from the original.

## Search
- `FullResident` and `FullStage` answer in this process with every list whole. The parent cuts each list to its first twenty, which would hide a rank past twenty.
- `lists_for` searches one query text and returns each source's list. The query vector comes from this run's own cache folder or from the run's embedding client. Embeddings are not counted and never reach the live folder.

## Running
- `plan_of` counts the rows by group, the replies still to ask, the stage budget and the embeddings needed.
- `run_live` runs the replay under the call cap, charges each reply to the `expansion` stage, and writes `expansion-report.json`. A cap or budget stop keeps the finished rows. Any other error writes the report and is then raised.
- `main` without `--live` reads files only. The context gets a transport that refuses every request, so no spend-ledger run is begun. `read_env_file` takes the run name and the other settings from the earlier run's `run-env.sh`. The name is only a label, because no Jev request is made.
- `parse_args`, `exit_status` and `run_cli` read the line, give 1 for a failure and 3 for a cap or budget stop, and print the result.
