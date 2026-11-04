---
capability: reuse-real-stage-check
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_real_stage_check.RunRefused@6e0ab10c9c
  - lupin_mcp.reuse_real_stage_check.rank_of@5d1cde8a67
  - lupin_mcp.reuse_real_stage_check.check_need@b53bc2ad6d
  - lupin_mcp.reuse_real_stage_check.run_check@b6e8fbcf83
  - lupin_mcp.reuse_real_stage_check.summary_lines@90ff84fc70
  - lupin_mcp.reuse_real_stage_check.main@8906257e9f
---
# Reuse real-stage check

A command that asks the real candidate stage where it ranks a known target, on the real index and the live vector set. It measures the stage, not the Jev verdict. [[candidate-stage]] describes the stage.

## What it does
- `SEEDS` holds five hand-written needs, each naming one symbol that answers it. `run_check` refuses with `RunRefused` for fewer than five seeds or a target missing from the entries.
- `check_need` asks the stage for one shortlist. It reports the target's rank, the shortlist size and the entries not asked. It also checks that every id is an entry and none repeats. `rank_of` is the 1-based position, or `None`.
- A negative control asks the first seed with its target excluded. The check passes only if every seed is found, the control is absent, and the counts and manifest hash agree on every row.
- `summary_lines` prints one line per seed, the control and the overall result.

## Running it
- `main` builds the production stage for the current tree. It refuses with exit 2 when the index is unusable or the stage fails before anything is asked.
- Exit 0 means every target was in the shortlist and the control was absent. Exit 1 means a target was missing or the control was found.
- `--report` writes the full JSON report to a file.

## Limits
- The needs are easier than a seat's own wording. The index can hold symbols newer than the vector set.
- A rank inside the shortlist says nothing about whether Jev would choose the target.
