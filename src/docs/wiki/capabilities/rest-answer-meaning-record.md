---
capability: rest-answer-meaning-record
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.rest.postgres_models.AnswerMeaning@4abc48675f
  - cosa.rest.db.repositories.answer_meaning_repository.AnswerMeaningRepository@990802e021
  - cosa.rest.db.repositories.answer_meaning_repository.AnswerMeaningRepository.add@13f78f3acc
  - cosa.rest.db.repositories.answer_meaning_repository.AnswerMeaningRepository.get@00466886bc
  - cosa.rest.db.repositories.answer_meaning_repository.AnswerMeaningRepository.versions@b29df3a0fd
  - cosa.rest.db.repositories.answer_meaning_repository.MeaningAlreadyRecorded@c3ec75d106
  - cosa.rest.db.repositories.answer_meaning_repository.kinds_in@f3cb6fe364
---
# Answer meaning records

A versioned reading of what a stored answer meant, kept apart from what was literally said. It sits beside the forecast rows in [[rest-prediction-arm-forecast]].

## What it does
- `AnswerMeaning` is one row per `( notification_id, schema_version, annotator )`. A new version or annotator is a new row.
- The table has no foreign key to notifications, so pruning notifications never removes a reading.
- `AnswerMeaningRepository.add` validates source, kinds, acts, alignment and unknowns against fixed lists. It flushes the row without committing.
- `add` raises `MeaningAlreadyRecorded` when the key already has a row, and leaves that row as it was. It raises `ValueError` for a value off its list.
- `get( notification_id, schema_version, annotator )` returns the one row under a key, or `None`.
- `versions( notification_id )` returns every reading of one notification, oldest first by `annotated_at`.
- `kinds_in( meaning )` returns the native kinds of the field entries joined with the unknowns, as a set.

## Don't
- Don't update or delete a meaning row. The repository only adds and reads.
