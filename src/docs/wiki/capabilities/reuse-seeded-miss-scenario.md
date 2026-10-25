---
capability: reuse-seeded-miss-scenario
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_seeded_miss_e2e.RunRefused@6e0ab10c9c
  - lupin_mcp.reuse_seeded_miss_e2e.shortlist_of@ac3497615f
  - lupin_mcp.reuse_seeded_miss_e2e.record_miss@2cd0f44ba5
  - lupin_mcp.reuse_seeded_miss_e2e.mark_repaired@ba447aec54
  - lupin_mcp.reuse_seeded_miss_e2e.candidate_scenario@ef061881da
  - lupin_mcp.reuse_seeded_miss_e2e.run@cd7f4d4b05
  - lupin_mcp.reuse_seeded_miss_e2e.summary_lines@8b725b16bf
  - lupin_mcp.reuse_seeded_miss_e2e.main@dc614f95a7
---
# Reuse seeded-miss scenario

Seeds a miss, records it as a store row, rewrites a docstring and checks the repair by replaying the receipt. The stand-ins are on [[reuse-seeded-miss-stand-ins]].

## Scenario
- The need is to list the episodes of a podcast. The lookup runs the candidate stage and then Jev. The symbol's own docstring does not match the need, so it is missed.
- `candidate_scenario` detects the miss from a candidate-route receipt and repairs the docstring. It passes only if the receipt took the candidates route without the symbol and a rewrite that changed nothing returned `NO_INPUT_CHANGE`.
- It also needs a rewrite of the first docstring line to return `REPAIRED`, with no hit before and every run a hit after. The second check takes new draws, so it does not read the first check's cached answers.
- `shortlist_of` returns the ids of a public result's shortlist.

## Store rows
- `record_miss` writes one miss as a store row through the librarian and returns the title and outcome. The body carries the fenced miss block with repaired false.
- `mark_repaired` amends that row with a repaired block and returns true when the store took it.

## Running
- `run` runs the scenario and writes `report.json` and `misses.jsonl` in the work folder. The folder must be empty or absent, or it raises `RunRefused`.
- In dry mode a stand-in Jev answers from word overlap, nothing outside the work folder is written, and no HTTP call is made. With `--answers`, it replays a saved `jev-cache` and refuses any request that folder lacks.
- In live mode it asks the real Jev through the account ledger and needs a ledger, a ceiling and the key. The rows always go to an in-memory store.
- `summary_lines` returns a short table of the report. `main` returns 0 when every expectation held and 1 when one failed. A refusal prints one line and returns 2.

## What it does not prove
- The miss row and the rewrite are made by the script, not by a seat or the librarian. The stand-in is deterministic, so five repeats show the plumbing and not the model's flip rate.
