---
capability: rest-preference-principle-tables
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.rest.postgres_models.PreferencePrinciple@312e0d50cf
  - cosa.rest.postgres_models.PreferenceEvidence@3d9108fa6c
---
# Preference principle and evidence tables

The two tables the principle learner writes. The job that fills them is in [[prediction-engine]].

## What it does
- `PreferencePrinciple` is a short conditional principle about one owner. It has a kind (`decision` or `ask_form`), a dimension, a statement, a rationale and a scope (`global` or `project:<name>`).
- Its `embedding` is a 768-dimension vector. It is comparable only within one `encoder_version`.
- Status is never stored. It is derived from the evidence rows.
- `continues_principle_id` names the earlier principle this one continues after a re-extraction. A ruling on the earlier principle then applies here.
- Only the extractor job writes it, and only when the model's relation names a principle of an earlier extractor version. The lowest id wins if several match.
- `PreferenceEvidence` is one timed piece of evidence for or against a principle. It is append-only. The relation is `supports`, `contradicts` or `refines`, and the source is `extractor` or `review_card`. Behind its switch the extractor also writes `uninformative`, which status ignores ([[principle-status-derivation]]).
- Six nullable columns are filled only by writers that know them, and are never backfilled. `source_key` names the one source behind a row, so status counts copies once. `condition_key` is the condition's stored key, so status makes no model call. `caveat` is a short warning for the forecaster. `decision_stage` is `who_decides` or `what_to_do_once_asked`. `antecedent` is the principle's antecedent as the extractor quoted it. `standing_quote` is the answer's own words stating a rule; NULL means an inferred refusal.
- One row exists per principle, notification, field, extractor version and source.
- Evidence is usable at an ask only when both `answered_at` and `extracted_at` are at or before it.
- `session_key` is stored when the row is written, so status can count sessions after the notification is pruned.

## Don't
- Don't add a foreign key from evidence to notifications. Pruning notifications must never remove evidence.
