---
capability: reuse-stage-one-probe-plan
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_stage1_probe.ProbeNotFound@c8146d05ab
  - lupin_mcp.reuse_stage1_probe.overlap_of@0771a4ccf6
  - lupin_mcp.reuse_stage1_probe.choose_probe@8f75af83b6
  - lupin_mcp.reuse_stage1_probe.random_neighbours@523fdc919a
  - lupin_mcp.reuse_stage1_probe.jaccard@fe405a54b4
  - lupin_mcp.reuse_stage1_probe.similar_neighbours@a0c76a8efd
  - lupin_mcp.reuse_stage1_probe.seed_for@289cda3363
  - lupin_mcp.reuse_stage1_probe.build_probe_plan@227c4a4428
  - lupin_mcp.reuse_stage1_probe.write_probe_plan@d867c27272
---
# Reuse stage-one probe plan

Chooses one boundary entry from a first single run and builds the six packs that test whether its answer depends on where it sits. Nothing here sends anything. [[reuse-stage-one-runner]] runs the arms.

## Choosing the probe
- `choose_probe` takes the results record of the `single1` arm. It returns the clean entry whose overlap, reuse plus extend, lies in the band 0.35 to 0.65 and is nearest 0.5. Ties go to the lowest id.
- A failed, unasked or not-reached entry is never chosen. A record from another arm raises `ValueError`, and an empty band raises `ProbeNotFound`.
- `overlap_of` adds the reuse and extend probabilities of one answer.

## Neighbours
- `random_neighbours` draws 199 ids from the id-sorted other entries with a recorded whole-number seed, so the same seed repeats the draw.
- `seed_for` gives 20261007 plus the question number for questions 1 to 4. No caller picks a seed.
- `jaccard` scores two texts by their lower-case word sets. `similar_neighbours` returns the 199 entries closest to the probe by that score, best first, with ties to the lowest id and no model.

## The plan
- `build_probe_plan` returns the plan and six arms. The probe is the same in all six. It sits first, in the middle and last in a pack of 200, once among random neighbours and once among near ones.
- Each neighbour list is fixed across the three places. The plan records the seed, probe, overlap, band, target, neighbour rule and both id lists.
- `write_probe_plan` writes the plan file for the question whole or not at all. An existing plan raises `FileExistsError`, so a plan is never replaced after the fact.
