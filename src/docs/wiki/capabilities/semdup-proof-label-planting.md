---
capability: semdup-proof-label-planting
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.semdup.proof.label_prep.make_ask@0076219645
  - cosa.repo.semdup.proof.label_prep.unfence@2a3159ebb3
  - cosa.repo.semdup.proof.label_prep.script_shape@c4d58adb38
  - cosa.repo.semdup.proof.label_prep.write_sentence@2786d3c46d
  - cosa.repo.semdup.proof.label_prep.plant_one@c66809464e
  - cosa.repo.semdup.proof.label_prep.plant_all@934ac50855
  - cosa.repo.semdup.proof.label_prep.rewrite_record@a964a7d0bd
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
- `write_sentence` asks for the one-sentence need of a stripped definition. It retries up to the writer's attempt limit, naming the last failure kinds, and returns None when none passes the form check.
- `plant_one` plants one pair. A Fable rewrite goes through `plant_rewrite` with the banned words. An Opus work-alike is written from the need sentence alone. It must parse and differ in shape from the original.
- A definition with no resolvable need, or a rewrite that fails, comes back as a `failed` result naming the cause, and the run goes on.
- `plant_all` plants in waves until the count is reached or the originals run out. Every third original is an Opus work-alike. The rest are Fable rewrites.
- `rewrite_record` extracts the first definition from a rewrite, written at the original's own file path so nothing in the record says it was planted. `checked` turns a result into a failure when that extraction raises.
