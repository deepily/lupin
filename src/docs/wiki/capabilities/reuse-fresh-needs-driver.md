---
capability: reuse-fresh-needs-driver
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_phase5_run.estimate_parts@ec2256ff8d
  - lupin_mcp.reuse_phase5_run.estimate_lines@362dff7594
  - lupin_mcp.reuse_phase5_run.needs_path@336bd07f0b
  - lupin_mcp.reuse_phase5_run.check_sha@072d9be828
  - lupin_mcp.reuse_phase5_run.load_items@f94edbf03d
  - lupin_mcp.reuse_phase5_run.flip_argv@386f51c786
  - lupin_mcp.reuse_phase5_run.sweep@fa59d6b256
  - lupin_mcp.reuse_phase5_run.main@06ff5d9a84
  - lupin_mcp.reuse_phase5_run.cli@1efb9cd071
---
# Reuse fresh-needs driver

The confirmation run on 30 fresh needs, built on the flip driver. It alone opens the reserved needs file; the shared reader refuses that file's hash to every other caller. The sample is on [[reuse-fresh-needs-sample]].

## Estimate and inputs
- `estimate_parts` gives the token estimate in three parts: the run, the canary and the full-sweep sample. The total is their sum.
- `estimate_lines` writes one line per part, then the total with dollars and tokens per need. It is an estimate, not a measurement.
- `needs_path` names the reserved file under the projects-data directory and reads nothing.
- `check_sha` accepts only a hash with the reserved prefix. `load_items` then reads the file as the one allowed caller.

## Steps
- `flip_argv` builds the flip driver's arguments with the settings fixed. They are the new question, the full route, five repeats, and the estimate of the run plus the canary.
- `sweep` runs one full-sweep search per sampled need as its own ledger run, apart from the repeats. It needs an approved canary, and a ceiling within the sample estimate times the estimate factor.
- `main` runs `check`, `estimate`, `sample`, `canary`, `approve`, `run`, `sweep` and `report`, and the same steps with a `stage-` prefix for the candidate stage. A step that spends is refused until the sample is recorded.
- `check` sends nothing. It lists each need whose excluded symbol is not a sendable entry of the index, and returns 2 if there is one.
- `report` also prints the recorded sample. `cli` turns the driver's refusals into one line and exit code 2.
