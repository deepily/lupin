---
capability: rest-data-repos-proxy-predictions
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.db.repositories.proxy_decision_repository.ProxyDecisionRepository@094813f6d3
  - cosa.rest.db.repositories.proxy_decision_repository.TrustStateRepository@8da1dfa0cf
  - cosa.rest.db.repositories.prediction_decision_repository.PredictionDecisionRepository@a2f2705ea5
  - cosa.rest.db.repositories.prediction_log_repository.PredictionLogRepository@59c7a3a2fc
---
# Decision proxy and prediction repositories

Four repositories hold what the decision proxy decided, how far it is trusted, and how well it predicted. The policy that uses them is in [[decision-proxy]] and [[prediction-engine]]; the base class is in [[db-repositories]].

## What it does
- `ProxyDecisionRepository.log_shadow` records an observe-only decision with action `shadow`. `log_decision` records the action it is given, and sets `ratification_state` to `pending` when ratification is required, else `not_required`.
- `get_pending` lists pending decisions oldest first, and `get_pending_summary` counts them by category and trust level. `ratify` sets `approved` or `rejected` with who and when.
- `find_similar( question, domain, category, limit=5 )` is a word match, not a vector search. It keeps rows of that domain and category whose stored question contains, ignoring case, each of the first three words longer than three characters. It returns an empty list when the question has no such word. Newest first.
- `TrustStateRepository` looks rows up by user email, domain and category. `update_after_ratification` adds one to the totals and to the successful or rejected count.
- `PredictionDecisionRepository.find_similar` returns `( similarity, row )` pairs by dot-product search over the question embedding, with optional category, origin and response-type filters. Its `threshold` is a fraction from 0 to 1, default 0.75, unlike the 0 to 100 snapshot searches. The threshold drops rows after the limit is applied, so fewer than `limit` pairs can come back.
- `PredictionLogRepository.log_prediction` writes the guess and `update_outcome` the actual value. `get_accuracy_summary` returns counts, accuracy rate and category and type breakdowns over a day window (30 by default).

## Don't
- Don't call `delete_pending` on a ratified decision. It raises `ValueError`; only pending ones can go.
- Don't call `delete_all` outside a test. It is a test reset that empties `prediction_decisions` and returns the count. The caller commits.
- Don't read `accuracy_rate` as covering every prediction. It divides by the ones that have an outcome.

## Invariants
- `get_or_create` makes a trust row at level 1 with zero counts. `update_after_ratification`, `update_trust_level` and `update_circuit_breaker_state` all go through it.
- `ratify` and `update_outcome` return `None` for an id that is not found. `update_outcome` and `get_by_notification_id` raise `ValueError` for a notification id that is not a UUID string.
- Trust updates take a user email, domain and category, and create the row through `get_or_create` when it is missing.
- `find_similar` in `PredictionDecisionRepository` multiplies its threshold by 100 and clamps scores.
