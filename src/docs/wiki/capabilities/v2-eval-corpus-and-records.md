---
capability: v2-eval-corpus-and-records
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.v2_eval.is_utterance_line@64850c3a82
  - scripts.v2_eval.load_corpus@a967cde576
  - scripts.v2_eval.stratified_sample@9a63902b90
  - scripts.v2_eval.is_completed_ok@3fed225373
  - scripts.v2_eval.response_path@b529903299
  - scripts.v2_eval.response_route_reason@66935eb391
  - scripts.v2_eval.reported_route_reason@2cc1057a7c
  - scripts.v2_eval.response_status@7c0814bf6b
  - scripts.v2_eval.response_similarity@2f48dfb4dc
  - scripts.v2_eval.response_trace_id@9c21bce249
  - scripts.v2_eval.is_receptionist_degrade@b1672b3aad
  - scripts.v2_eval.is_outcome_observed@ea1876a9bf
  - scripts.v2_eval.matched_command@e5a5baf2a1
  - scripts.v2_eval.first_useful_ms@299e9b92a7
---
# CJ Flow v2 eval: corpus and record readers
`src/scripts/v2_eval.py` is the two-pass harness for the CJ Flow v2 router. The AI runs it on the `:8000` test server, never a person and never on `:7999`. This page covers the corpus and the readers of one record. The metrics are on [[v2-eval-metrics-and-guards]].
- `is_utterance_line` is true for a corpus line that is not blank or a comment. `load_corpus` returns `(utterance, expected_command)` pairs for the `simple` or `weather` corpus.
- `stratified_sample` draws a seeded random sample per command. The result depends only on the utterance set, the count and the seed, so a big command cannot dominate.
- `is_completed_ok` asks whether a call did the work, as the v1 arm does. A 200 whose body reports a route error does not count.
- `response_path`, `response_route_reason`, `response_similarity` and `response_trace_id` read one field of a record's response. Each gives None when the record is not ok.
- `reported_route_reason` and `response_status` read the same fields from any answered 200, ok or not. The error views use them.
- `is_receptionist_degrade` tells a request that reached the receptionist because nothing could serve it from a deliberate pick. Both carry path `receptionist`.
- `is_outcome_observed` is false for an async `waiting` answer, whose similarity and snapshot fields are absent, not negative.
- `matched_command` is the command a replayed snapshot is attributed to. `first_useful_ms` is the latency to first useful response, or None.
