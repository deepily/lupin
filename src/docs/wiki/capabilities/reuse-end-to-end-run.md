---
capability: reuse-end-to-end-run
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_e2e.FrozenInputRefused@a7ba22dbb8
  - lupin_mcp.reuse_e2e.load_sample@3640e4490f
  - lupin_mcp.reuse_e2e.load_needs@0fb6821379
  - lupin_mcp.reuse_e2e.load_twins@e0da069eb0
  - lupin_mcp.reuse_e2e.read_search@da84661cfb
  - lupin_mcp.reuse_e2e.incomplete_causes@079c989e5f
  - lupin_mcp.reuse_e2e.wilson@e1346267be
  - lupin_mcp.reuse_e2e.mcnemar_exact@f383c680a6
  - lupin_mcp.reuse_e2e.figures@2db02df5bd
  - lupin_mcp.reuse_e2e.paired@caf7902b28
  - lupin_mcp.reuse_e2e_run.E2EEnv@e53f8b9208
  - lupin_mcp.reuse_e2e_run.run_searches@7e4f74847a
  - lupin_mcp.reuse_e2e_run.run_canary@8ed6d17a54
  - lupin_mcp.reuse_e2e_run.canary_line@9a7603fa09
  - lupin_mcp.reuse_e2e_run.run_line@9bff2299df
  - lupin_mcp.reuse_e2e_run.approve_canary@a5b07a25ff
  - lupin_mcp.reuse_e2e_run.run_full@916dfe8fcc
  - lupin_mcp.reuse_e2e_run.ask_old@403795f2f2
  - lupin_mcp.reuse_e2e_run.ask_new@91c8a03e86
  - lupin_mcp.reuse_e2e_run.ask_candidates@ab9f2ef798
  - lupin_mcp.reuse_e2e_run.report_lines@13e069b6d9
  - lupin_mcp.reuse_e2e_run.main@bba91f7d58
  - lupin_mcp.reuse_e2e_run.cli@c35d01d01a
---
# Reuse end-to-end run
The end-to-end run sweeps the whole catalogue for each of 100 sampled members, once per question, and compares the questions. A run is one ledger run with one token ceiling. See [[reuse-token-ceiling-and-spend-ledger]].
- `load_sample`, `load_needs` and `load_twins` read the frozen sample, need sentences and twin manifest. Each hash is checked first. The sample has 58 exact-cluster and 42 near-only members, in that order. A mismatch raises `FrozenInputRefused`.
- `read_search( result, twins )` reads one finished search: whether a twin is on the shortlist, ranked first, or in the nearest ten.
- `incomplete_causes` names why a search is incomplete, apart: the ceiling, the ledger, `CALL_FAILED`, `MALFORMED_ANSWER`, then the sweep's own. A complete search gives an empty list.
- `wilson( k, n )` is the 95% Wilson interval. `mcnemar_exact` is the exact two-sided McNemar p of two discordant counts.
- `figures( searches, questions )` gives each question's counts and headline figures, with an incomplete search counted as a miss. `paired` compares two questions on the members both ran.
- `ask_old`, `ask_new` and `ask_candidates` are the asks: a full sweep with the old or new question, and the old one through the candidate stage. Each leaves the member out.
- `E2EEnv` holds what the runner takes from outside: the ledger, the asks and a transport factory. Results go to `<data>/e2e-results/`.
- `run_searches` runs every member's searches in order as one ledger run and writes the result file whole. `run_canary` asks the first five members and writes the numbers a person reads. `canary_line` and `run_line` give one line on what it found and how a run ended.
- `approve_canary( env, by, why )` records that a person read the canary. `run_full` runs the rest, and raises `CanaryNotApproved` without that.
- `report_lines` writes the fixed statement, each question's figures with intervals and the paired result. `main` runs one step and `cli` turns a refusal into one line and exit code 2.
