---
capability: reuse-stage-one-runner
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_stage1_run.RunnerRefused@c9be74222b
  - lupin_mcp.reuse_stage1_run.StandIn@7f14fd5a90
  - lupin_mcp.reuse_stage1_run.load_inputs@6b71b1cdb9
  - lupin_mcp.reuse_stage1_run.check_paths@3aec441b44
  - lupin_mcp.reuse_stage1_run.open_env@ac428f3caa
  - lupin_mcp.reuse_stage1_run.main@30c7223254
  - lupin_mcp.reuse_stage1_run.run_cli@d9364dc42b
  - lupin_mcp.reuse_stage1_run.cli@5cdd378f9b
---
# Reuse stage-one runner

One command per step of the stage-one run sheet. Every step builds the same driver environment from the same index. The probe arms come from [[reuse-stage-one-probe-plan]].

## Stand-in and live
- Without `--live` the transport is `StandIn`. It answers each candidate from a hash of its text, takes one attempt from the budget per post, and reports 40 output tokens per question.
- A stand-in run needs its own data folder and ledger. It marks the folder, and a live run refuses a marked folder.
- With `--live` the transport is the real one. A live run uses the real data folder and ledger only, and refuses a ledger that does not exist.
- `check_paths` settles which folder and ledger a run uses and creates nothing. `open_env` builds the driver environment, or refuses before creating anything.

## Inputs and commands
- `load_inputs` reads the index the way the tool path does. It refuses when the tree is not a lupin tree, the index is stale, a dependency is missing, or a page slug is listed twice.
- `main` runs one step: `status`, `ledger-init`, `canary`, `approve`, `arm`, `probe-plan`, `old-shape` or `report`. A probe plan on disk must still match single run 1 of its question.
- `ledger-init` is for a stand-in run only; the real ledger is created by hand.

## Refusals
- `RunnerRefused` means the runner would not start a step and opened nothing.
- `run_cli` runs a call as a command line. A listed refusal prints one line to the error stream and exits 2. Any other error propagates, so a crash is never read as a refusal.
- `cli` applies it to `main` for the runner's own refusals and the driver's: missing key, canary not approved, canary tripped and stage refused.
