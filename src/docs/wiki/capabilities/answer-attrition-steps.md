---
capability: answer-attrition-steps
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - scripts.answer_attrition_table.derived_units@fa7b890338
  - scripts.answer_attrition_table.writer_units@0390a7bc09
  - scripts.answer_attrition_table.StubStore@25f97456f8
  - scripts.answer_attrition_table.stored_decision@42482941c2
  - scripts.answer_attrition_table.store_units@716bbb3d40
  - scripts.answer_attrition_table.vote_units@fbdf06cbe6
  - scripts.answer_attrition_table.neighbour_units@8dc8e076b3
  - scripts.answer_attrition_table.blank_episode@3e56aa011d
  - scripts.answer_attrition_table.prompt_units@c1116557f6
  - scripts.answer_attrition_table.perfect_forecast@a6212dc8d3
  - scripts.answer_attrition_table.score_units@0fb7a30f78
  - scripts.answer_attrition_table.with_source@af886440f7
  - scripts.answer_attrition_table.timeout_steps@ed1bed3f8a
---
# Answer attrition table: the pipeline steps

How the attrition table decides which units of an answer survive each pipeline step. Each step's column in the table names the symbol it measured. Reading and units are in [[answer-attrition-reading]].

## Decoding and writing
- `derived_units` counts the units in `derive_answer`'s output. An unread answer has none.
- `writer_units` keeps a derived unit only when its field has an entry in `field_answers` and the entry's text still holds it.

## The lookup forecaster
- `stored_decision` runs the real `PredictionEngine._store_decision` on `StubStore`, which only records what it is handed. `store_units` reads the units back from that stored value.
- `vote_units` keeps a stance, or a pick that matches an offered label, because those are what the lookup counts as a vote.
- `neighbour_units` is what `three_way_stance.neighbours_of` reads from a stored yes/no decision: the stance and any comment.

## The model forecasters and the scorers
- `prompt_units` plants each unit's text in a `blank_episode` and keeps the units that change the model forecasters' prompt. It compares two prompts, so a label the card already prints is not counted.
- `score_units` probes the real scorers with forecasts built from the answer, starting from `perfect_forecast`. It also counts typed text scored as a miss with the per-field switch off, and left out with it on.

## Timeouts
- `timeout_steps` decides whether a timeout survives decoding and writing. It compares the row with a copy marked as an on-screen answer, made by `with_source`.
