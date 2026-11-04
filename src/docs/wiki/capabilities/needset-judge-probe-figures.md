---
capability: needset-judge-probe-figures
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.judge_probe_read.accepted@ba187fc5a7
  - lupin_mcp.reuse_needset.judge_probe_read.newcombe@dade3c0c82
  - lupin_mcp.reuse_needset.judge_probe_read.index_results@3de67b3dc1
  - lupin_mcp.reuse_needset.judge_probe_read.repeats_of@6e4442affb
  - lupin_mcp.reuse_needset.judge_probe_read.figures@1bef63d345
  - lupin_mcp.reuse_needset.judge_probe_read.pairing_share@45eb3aa53e
  - lupin_mcp.reuse_needset.judge_probe_read.duplicate_figures@48fa92a55f
  - lupin_mcp.reuse_needset.judge_probe_read.arm_summary@c8e10a9f9f
  - lupin_mcp.reuse_needset.judge_probe_read.pair_status@e65703a685
---
# Need set: reading the judge probe, figures

Turns the report that `run_variant` writes ([[needset-judge-probe-arms]]) into the figures of plan 17.3 revision 6. It makes no model call, and it writes only the markdown file it is asked for. The comparisons are on [[needset-judge-probe-compare]].

## Accepted shares
- `accepted` is true when a plant's `p_overlap`, rounded to six places, is 0.30 or higher. A missing rating is false.
- `index_results` lays the report's rows out by arm, repeat and pair. `repeats_of` lists the repeat numbers an arm has.
- `figures` counts plants accepted per label for one arm and repeat, and gives D, the same-job rate minus the not-same rate.
- `newcombe` gives that difference with its 95 percent interval, from two Wilson intervals.

## Other readings
- `pairing_share` is the share of pairings where the same-job plant rates higher. Ties count one half.
- `duplicate_figures` is the second reading: a plant or original at 0.30 or higher.
- In the both-lines arm only the plant is read, because the original's own line is the need's purpose.
- `arm_summary` summarises one arm over its repeats.
- `pair_status` says whether a pair's plant counts as accepted in an arm. That needs a strict majority of the repeats that answered it.
