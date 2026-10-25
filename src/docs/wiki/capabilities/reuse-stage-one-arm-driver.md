---
capability: reuse-stage-one-arm-driver
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_stage1.retry_index@bb75e81b71
  - lupin_mcp.reuse_stage1.StageRefused@114fa611ec
  - lupin_mcp.reuse_stage1.CanaryNotApproved@ec40eb09bb
  - lupin_mcp.reuse_stage1.CanaryTripped@fcf8dad2bc
  - lupin_mcp.reuse_stage1.DriverRefused@5d965368a1
  - lupin_mcp.reuse_stage1.KeyMissing@41c3da8608
  - lupin_mcp.reuse_stage1.Stage1Env@a77c229754
  - lupin_mcp.reuse_stage1.run_name@9d0b8728f2
  - lupin_mcp.reuse_stage1.stage_remaining@700b1cb0c8
  - lupin_mcp.reuse_stage1.run_arm@2c67db5247
  - lupin_mcp.reuse_stage1.run_canary@795226ec12
  - lupin_mcp.reuse_stage1.approve_canary@c0d8c9d0ed
---
# Reuse stage-one arm driver

Runs each arm of the stage-one measurement as its own ledger run and writes a results file. The three-way question is asked in arms that must not share answers. The driver sends nothing itself, because the transport is a factory. [[reuse-stage-one-runner]] is the command line over it.

## Arms and names
- The arms are single runs, a canary, packs of 10, 50 and 200, the page arms and six probe arms. Each arm has its own run index, so no two share a cached answer.
- `run_name` gives `s1-q<question>-<arm>`, plus `-a<attempt>` for a retry. `retry_index` gives a rerun an index no other arm or attempt uses, so a rerun reads none of the answers before it.
- `Stage1Env` holds the root, data folder, ledger and transport factory. Results go to the `stage1-results` folder under the data folder.
- `stage_remaining` is the stage's token total less what runs named `s1-` hold in the ledger, so it survives a restart.

## Running an arm
- `run_arm` runs one arm and writes its results file however it ends. An arm that runs out of attempts, ceiling or ledger is recorded incomplete with its reason and not raised.
- Every check runs before anything is sent. They cover the question and arm, the probe, the worker count, repeated entry ids and, for a live run, the key. A ceiling above what the stage has left raises `StageRefused`.
- Only an arm its ceiling stopped may run again, as attempt 2 or 3 with a reason and the same entries. An attempt limit above the arm's cap raises `BAD_BUDGET`.
- `DriverRefused` means a step was refused before spending: no ledger run opened and no name used. `KeyMissing` is the same refusal for a live transport with no key.

## Canary
- `run_canary` sends the first ten entries as one request and writes a report with `approved` empty. It records each stop number that was crossed: output per entry over the limit, usage over the reserve, a refusal or a model mismatch.
- `approve_canary` records who approved and why. A canary that tripped raises `CanaryTripped` and is never approved. Every arm but the first single run and the canary raises `CanaryNotApproved` until its question's canary is approved.
