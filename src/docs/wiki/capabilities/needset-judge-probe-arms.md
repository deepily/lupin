---
capability: needset-judge-probe-arms
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.judge_probe.shaped_id@51a1fe79d6
  - lupin_mcp.reuse_needset.judge_probe.variant_template@411167f840
  - lupin_mcp.reuse_needset.judge_probe.id_collision@8ac0619693
  - lupin_mcp.reuse_needset.judge_probe.arm_inputs@b775c4cb8d
  - lupin_mcp.reuse_needset.judge_probe.repeat_template@6d06a602cb
  - lupin_mcp.reuse_needset.judge_probe.plan_requests@198373227e
  - lupin_mcp.reuse_needset.judge_probe.body_hash@ee5b2569c8
  - lupin_mcp.reuse_needset.judge_probe.distinct_bodies@c597f16f93
  - lupin_mcp.reuse_needset.judge_probe.ask_request@348cef6dcc
  - lupin_mcp.reuse_needset.judge_probe.run_variant@16b51a4728
  - lupin_mcp.reuse_needset.judge_probe.tally@55ed302b3c
  - lupin_mcp.reuse_needset.judge_probe.summarize_variant@ecef601f5d
  - lupin_mcp.reuse_needset.judge_probe.parse_args@a7c12639bc
  - lupin_mcp.reuse_needset.judge_probe.variant@2d807b295c
  - lupin_mcp.reuse_needset.judge_probe.main@2c3d0a5b41
  - lupin_mcp.reuse_needset.judge_probe.run_cli@2b9e55e56d
---
# Need set: the judge probe, four arms

Asks the judge about each pair's plant and original in one pack, under four arms and three repeats. The replay is on [[needset-judge-probe-replay]], the read on [[needset-judge-probe-compare]].

## The arms
- `baseline` is the plant as id and signature, with the production template. `plant_line` gives it its purpose line.
- `shaped_id` also gives it the id the index would give it. The function `shaped_id` builds that id from the plant's file and name.
- `both_lines` adds the original's line to the instructions. `variant_template` builds that template.
- `id_collision` says whether a shaped id equals another entry's id; such a pair has no arm. `arm_inputs` chooses an arm's plant record and template.

## Asking
- `repeat_template` ends a template with a run-index token, so each repeat posts its own body. `plan_requests` lists one request per pair, arm and repeat.
- `body_hash` hashes a request body, and `distinct_bodies` raises if two requests would post the same body.
- `ask_request` posts one request straight to the transport, never reading the cache, and reads both ratings.
- `run_variant` asks every request under the call cap and writes `judge-probe-variant-report.json`. A cap, budget or error stop keeps the finished results.
- `tally` counts plants accepted per label. `summarize_variant` counts accepts per arm and repeat, with proof that the posts were fresh.

## The command
- `parse_args` reads the line. `variant` plans the run and, with `--live`, asks the judge. `main` runs the replay or the variant. `run_cli` prints the result as JSON.
