---
capability: rest-data-repos-proxy-predictions
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.db.repositories.proxy_decision_repository.ProxyDecisionRepository@094813f6d3
  - cosa.rest.db.repositories.proxy_decision_repository.TrustStateRepository@8da1dfa0cf
  - cosa.rest.db.repositories.prediction_decision_repository.PredictionDecisionRepository@2b0033edfa
  - cosa.rest.db.repositories.prediction_log_repository.PredictionLogRepository@59c7a3a2fc
---
# Decision proxy and prediction repositories

Four repositories hold what the decision proxy decided, how far it is trusted, and how well it predicted. The policy that uses them is in [[decision-proxy]] and [[prediction-engine]]; the base class is in [[db-repositories]].

## What it does
- `ProxyDecisionRepository.log_shadow` records an observe-only decision with action `shadow`. `log_decision` records `suggest`, `act` or `defer`, and sets `ratification_state` to `pending` when ratification is required, else `not_required`.
- `get_pending` lists pending decisions oldest first, and `get_pending_summary` counts them by category and trust level. `ratify` sets `approved` or `rejected` with who and when.
- `find_similar` is a word match, not a vector search: it requires the first three words longer than three characters to appear in the question.
- `TrustStateRepository` keeps one row per user, domain and category. `update_after_ratification` adds one to the totals and to the successful or rejected count.
- `PredictionDecisionRepository.find_similar` returns `( similarity, row )` pairs by dot-product search over the question embedding, with optional category, origin and response-type filters.
- `PredictionLogRepository.log_prediction` writes the guess and `update_outcome` the actual value. `get_accuracy_summary` returns counts, accuracy rate and category and type breakdowns over a day window (30 by default).

## Don't
- Don't call `delete_pending` on a ratified decision. It raises `ValueError`; only pending ones can go.
- Don't call `delete_all` outside a test. It empties `prediction_decisions` and does not flush.
- Don't read `accuracy_rate` as covering every prediction. It divides by the ones that have an outcome.

## Invariants
- `get_or_create` makes a trust row at level 1 with zero counts, and every `TrustStateRepository` update goes through it.
- `ratify`, `update_outcome` and the trust updates return `None` or a new row, never raise, for an id that does not exist.
- `find_similar` in `PredictionDecisionRepository` multiplies its threshold by 100 and clamps scores.
