---
capability: prediction-complete-action-comparators
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.prediction_engine.accuracy_comparators.compare_complete_action_multiple_choice@fd27fe7184
  - cosa.agents.prediction_engine.accuracy_comparators.compare_complete_action_open_ended@1b98ecefff
  - cosa.agents.prediction_engine.accuracy_comparators.compare_complete_action_open_ended_batch@af27acf823
  - cosa.agents.prediction_engine.accuracy_comparators.compare_complete_action_yes_no@6da3551157
  - cosa.agents.prediction_engine.accuracy_comparators.decompose_atoms@3425168ac6
  - cosa.agents.prediction_engine.accuracy_comparators.predicted_answers_of@d515c69ef5
---
# Prediction complete-action comparators

Scores a forecast by the whole action, not by one field. The older per-field and similarity comparators are in [[prediction-accuracy-comparators]]. Each returns `( match, detail )`.

## What it does
- Every one returns `( None, ... )` when there is no answer to score. An abstention or empty forecast scores False with `abstained` set.
- `compare_complete_action_yes_no` checks the stance first. A wrong stance is False and never calls the judge.
- A right stance with the same condition, or none on either side, is True with no judge. Differing conditions go to the judge.
- With no judge, a case that needs one returns `( None, judge_required )`. The judge is called once per pair.
- `compare_complete_action_open_ended` is True for the same words. Different words go to the judge, and `similarity` sits beside the verdict.
- `compare_complete_action_open_ended_batch` needs every question to pass. A missing question is abstained and fails the card. With no judge, an undecided question gives `( None, judge_required )`.
- `compare_complete_action_multiple_choice` needs every field exact and none abstained. It takes a `judge` but never calls it.
- `predicted_answers_of( predicted )` returns the forecast's `answers` plus the write-in or re-frame text of each typed field. An `answers` entry is never replaced.
- `decompose_atoms` scores ( group, atom ) pairs and returns precision, recall, hits, contradictions, omissions and additions.
- A contradiction is a forecast atom in a single group where the answer gave another atom. The three flags are disjoint, so one miss counts once.
- Precision and recall read 1.0 for an empty side.
