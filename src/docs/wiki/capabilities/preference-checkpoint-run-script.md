---
capability: preference-checkpoint-run-script
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - scripts.preference_step9_checkpoint_run.final_run@0b427284d3
---
# Preference checkpoint run script
`src/scripts/preference_step9_checkpoint_run.py` is the script that made the committed checkpoint report. It is kept as a record, not as a tool to run again.

## What it does
- It takes one argument: the folder holding `step8_result.json`. The original read that file from its own scratchpad.
- It reads the live cohort, keeps the asks named in the frozen cohort file, and checks their hash against the freeze. It stops when the cohort has moved.
- It replays the engine at the frozen settings and asserts the final-window correct count equals the freeze's. It stops when they disagree.
- `final_run` cuts the replay records to one response type inside the final window. The yes/no baseline arms, always yes and prior majority, are summarised from it.
- It writes the checkpoint report, the cohort file, its manifest and the checkpoint file under `src/conf`. Then it checks that a matching snapshot passes and a planted mismatch is refused.

## Why it cannot simply be re-run
- It was run at commit `086f95590`. It calls `read_cohort( session )`, which later took a stored-vectors argument.
- Reproducing the Before column now needs that stored-vectors path.
- The frozen settings come from commit `ba045c7ce`. Run it from the repository root with `LUPIN_ROOT` and `PYTHONPATH` pinned to the tree.
