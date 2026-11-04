---
capability: needset-forced-judge-in-pack
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.forced_judge.places_for@edc21c777b
  - lupin_mcp.reuse_needset.forced_judge.judge_row_in_pack@9baa20c696
  - lupin_mcp.reuse_needset.forced_judge.pack_place@3c286a76d1
  - lupin_mcp.reuse_needset.forced_judge.in_pack_figures@071a79c492
  - lupin_mcp.reuse_needset.forced_judge.with_plant_line@4fcf935326
  - lupin_mcp.reuse_needset.forced_judge.expand_jobs@11e4a0489f
  - lupin_mcp.reuse_needset.forced_judge.in_pack_run_index@36fd3eb114
  - lupin_mcp.reuse_needset.forced_judge.judge_job@bb8f5db7d0
  - lupin_mcp.reuse_needset.forced_judge.summarize_in_pack@cc611f9faf
---
# Need set: the forced judge, in_pack variant

The `in_pack` variant of [[needset-forced-judge]] asks each drafted pair with the plant inside the 128 places. Every pair is asked, because a plant asked among the real places needs no miss. It runs two arms and two repeats.

## One question
- `places_for` chooses the real places that stand beside one row's plant.
- `judge_row_in_pack` asks the 127 best real places and the plant in a single question. The plant is never asked alone and nothing is widened.
- A plant the real shortlist already held is asked all the same.
- `pack_place` records where the plant fell among the asked ids, in id order.
- `in_pack_figures` reads whether the plant survives the verdict's cut shortlist, its rank among answered places, and how many other places reach the threshold.

## Arms and repeats
- The `baseline` arm asks the plant as the control built it. The `plant_line` arm gives it its purpose line through `with_plant_line`.
- `expand_jobs` lists one job per pair, arm and repeat. It skips the plant_line arm for a plant with no line.
- `in_pack_run_index` numbers each cell so no two share a cache key.
- `judge_job` asks one cell with fresh posts, using a template that ends in that number.
- `summarize_in_pack` counts pairs, answers, accepts and survivors per `arm/repeat` cell and label. The cells are never pooled.
