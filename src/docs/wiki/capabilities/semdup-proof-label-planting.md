---
capability: semdup-proof-label-planting
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.semdup.proof.label_prep.make_ask@0076219645
  - cosa.repo.semdup.proof.label_prep.unfence@2a3159ebb3
  - cosa.repo.semdup.proof.label_prep.script_shape@c4d58adb38
  - cosa.repo.semdup.proof.label_prep.write_sentence@5c3199a7f7
  - cosa.repo.semdup.proof.label_prep.plant_one@604b42448c
  - cosa.repo.semdup.proof.label_prep.plant_all@934ac50855
  - cosa.repo.semdup.proof.label_prep.rewrite_record@a964a7d0bd
  - cosa.repo.semdup.proof.label_prep.top_up_alikes@0583e2db29
  - cosa.repo.semdup.proof.label_prep.checked@c0154de3ac
  - cosa.repo.semdup.proof.label_prep.select_pools@db9488d51a
---
# Duplicate checker proof: planting for the labelling packets

`label_prep.py` prepares the proof's blind labelling packets. This page covers the planted half: choosing originals and writing rewrites. Packets, the answer key and the command are on [[semdup-proof-label-packets]]. The planting rules are on [[semdup-proof-plant]].

## Model calls
- `make_ask( complete, model )` wraps the async model call as the sync `ask( system, user )` that planting takes. It runs each call to the end and removes a code fence from the reply.
- `unfence` strips one fence that wraps the whole reply, and otherwise only strips whitespace.
- `script_shape` returns the shingle set of the first function in script source, read by the TypeScript compiler. A source that does not parse alone is tried inside a class body. It returns None when neither holds a function.

## Planting
- `select_pools` drops definitions that carry a scrub token, and nested ones (`<locals>`). It draws twice the planted count and splits the draw into script and Python lists.
- `write_sentence` asks for the one-sentence need of a stripped definition. It returns the sentence and the failure kinds of each rejected try, or None and those kinds when the attempt limit is reached. Each retry names the last failure kinds, the own words found in the last sentence and its length.
- `plant_one` plants one pair. A Fable rewrite goes through `plant_rewrite` with the banned words. An Opus work-alike is written from the need sentence alone. It must parse and differ in shape from the original.
- A definition with no resolvable need, or a rewrite that fails, comes back as a `failed` result naming the cause, and the run goes on. A work-alike with no passing sentence reports the failure kinds of its tries.
- `plant_all` plants in waves until the count is reached or the originals run out. Every third original is an Opus work-alike. The rest are Fable rewrites.
- `top_up_alikes` adds Opus work-alikes until each language group holds a third of its share, up to six waves per group. It tries originals that failed as work-alikes once before new ones, and saves after every wave. A group that runs out stays short.
- `rewrite_record` extracts the first definition from a rewrite, written at the original's own file path so nothing in the record says it was planted. `checked` turns a result into a failure when that extraction raises.
