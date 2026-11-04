---
capability: reuse-fresh-needs-run
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_phase5_stage.stage_asks@68a0170cb4
  - lupin_mcp.reuse_phase5_stage.policy_name@493aa7ebe8
  - lupin_mcp.reuse_phase5_stage.estimate_lines@c57a833fd5
  - lupin_mcp.reuse_phase5_stage.run_policy@bf0b5a04c7
  - lupin_mcp.reuse_phase5_stage.check_results@97c0e10a99
  - lupin_mcp.reuse_phase5_stage.check_factor@606c44480b
  - lupin_mcp.reuse_phase5_stage.run_step@891b362c4f
---
# Reuse fresh-needs run through the candidate stage

Confirms the shipped candidate stage on needs written fresh. Each need gets one lookup on the candidates route, then five replays of it for the flip rate. The figures are on [[reuse-fresh-needs-figures]].

## Asks and policy
- `stage_asks` builds the lookup and one replay per repeat on the band driver's asks. Each ask checks the pinned vector-set hash before it sends, and an error result is returned as it is.
- The lookup's row holds the verdict, the sorted shortlist ids and the first ten ids of the stage's ranking. A replay's row holds its verdict and shortlist beside the overlaps.
- `policy_name` returns `band on` when a policy has a band, else `band off`. `run_policy` reads that word from a result file, or `not recorded` for a file that predates the switch.

## Estimate
- `estimate_lines` writes four lines: the run, the canary, the full-sweep sample and the total. The canary is the first needs of the run, so the total is the run plus the sample.
- The dollar figure is an estimate, not measured on the run.

## Guards
- `check_factor` refuses an over-estimate factor that is not a finite number above zero. A bool is refused too.
- `check_results` refuses a report over results that are not this run's. Each run must be on the pinned vector set and carry the sample hash. It must also hold the right number of asks per need and share one verdict policy.
- Runs with no policy word count as one policy with each other.

## Spending steps
- `run_step` runs the canary, its approval or the run. It refuses a ceiling above the estimate times the factor, and a stage on another vector set than the pin, before anything opens.
- An approval sends nothing and builds no stage. Results are named by the prefix and stamped with the sample hash, the stage, the needs hash and the policy word.
