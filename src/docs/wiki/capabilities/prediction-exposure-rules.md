---
capability: prediction-exposure-rules
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.prediction_engine.exposure.classify_exposure@ced1c518d0
  - cosa.agents.prediction_engine.exposure.compare_draft_to_answer@c4b2706266
  - cosa.agents.prediction_engine.exposure.decode_answer_fields@e3bfe8cea3
  - cosa.agents.prediction_engine.exposure.observation_view@b3a4f9184e
  - cosa.agents.prediction_engine.exposure.option_ids_of@719453bfae
  - cosa.agents.prediction_engine.exposure.revealed_before_answer@e9d703d55f
  - cosa.agents.prediction_engine.exposure.switch_rate@75ff475c10
  - cosa.agents.prediction_engine.review_card.is_review_card@3dba668fd1
---
# Prediction exposure rules and the review-card marker

Pure rules for the forecast fold: was the final answer given unaided, or after the forecast could have changed it? Nothing here touches the database. The route that stores the two inputs is in [[rest-prediction-routes-and-outcome]].

## What it does
- `revealed_before_answer( fold_opened_at, answered_at )` is False when the fold never opened. It is True when the fold opened and the answer time is unknown. An equal time is too late to influence.
- `decode_answer_fields( response_type, stored )` decodes an answer or a draft, in any stored form, into picks per field. An unknown response type returns None, so a new type is never read as free text.
- For yes/no the entry is the stance alone, so a changed comment is not a different answer. Multiple-choice picks are sorted and blank picks dropped.
- `compare_draft_to_answer` compares a draft with the final answer field by field. Each field is same, switched or undrafted. The outcome is unreadable when either side cannot be decoded.
- `classify_exposure` gives one class per card. Unanswered wins first. A fold never opened, or opened at or after the answer, is unaided.
- A reveal with no draft is exposed. With a draft, a switch gives switched, and same gives unaided. Undrafted or unreadable gives exposed, because the answer may have formed after the reveal.
- `switch_rate( cards )` is the switched share of the cards whose switch could be measured, rounded to four places. It is None when none were measured.
- `option_ids_of( response_options )` gives `<header>#o1`, `<header>#o2` and so on, in displayed order. An id depends on header and position only, so a reworded label keeps it.
- `observation_view` returns a deep read-only mapping of one answer: the card as shown, option ids, raw response, source, actor, times and input route. A missing source reads None.
- `is_review_card( response_options )` is True only when the schema is an object whose `review_card` key is exactly True. A review card is the learner's own question and is never forecast or scored.

## Don't
- Don't decide exposure anywhere else. The summary, the extractor and the reports share these rules.
