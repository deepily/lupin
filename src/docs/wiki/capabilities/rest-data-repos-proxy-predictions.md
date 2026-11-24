---
capability: rest-data-repos-proxy-predictions
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.rest.db.repositories.proxy_decision_repository.ProxyDecisionRepository@cea15ec3cb
  - cosa.rest.db.repositories.proxy_decision_repository.TrustStateRepository@ddeeee6a9c
  - cosa.rest.db.repositories.prediction_decision_repository.PredictionDecisionRepository@6d8c5b6a79
  - cosa.rest.db.repositories.prediction_log_repository.PredictionLogRepository@8e030e215a
  - cosa.rest.db.repositories.prediction_log_repository.legacy_similarity_clause@e36d553cbc
  - cosa.rest.db.repositories.prediction_log_repository.legacy_confidence_clause@3978238c95
---
# Decision proxy and prediction repositories

Four repositories hold what the decision proxy decided, how far it is trusted, and how well it predicted. The policy that uses them is in [[decision-proxy]] and [[prediction-engine]]; the base class is in [[db-repositories]].

## What it does
- `ProxyDecisionRepository.log_shadow` records an observe-only decision with action `shadow`. `log_decision` records the action it is given, and sets `ratification_state` to `pending` when ratification is required, else `not_required`. `log_shadow` goes through `log_decision`, and takes `decision_value`, the proxy's forecast, which stays empty when not given. Both take `rule_agreement`, True, False or None.
- `iter_answered_newest_first( domain, category )` streams decisions whose metadata records an answer source, newest first, fetched in batches of 20.
- `get_pending` lists pending decisions oldest first, and `get_pending_summary` counts them by category and trust level. `ratify` sets `approved` or `rejected` with who and when.
- `find_similar( question, domain, category, limit=5 )` is a word match, not a vector search. It keeps rows of that domain and category whose stored question contains, ignoring case, each of the first three words longer than three characters. It returns an empty list when the question has no such word. Newest first.
- `TrustStateRepository` looks rows up by user email, domain and category. `update_after_ratification` adds one to the totals and to the successful or rejected count. It also records the decision under today's UTC date in `decision_history` and drops days past the retention window. A row written before that column is first seeded with its old totals. Its `blr_state` argument stores the BLR trust model's state as given. `None` clears it, and the default leaves the stored value alone.
- `PredictionDecisionRepository.find_similar` returns `( similarity, row )` pairs by dot-product search over the question embedding, with optional category, origin and response-type filters. Its `threshold` is a fraction from 0 to 1, default 0.75, unlike the 0 to 100 snapshot searches. The threshold drops rows after the limit is applied, so fewer than `limit` pairs can come back.
- `PredictionLogRepository.log_prediction` writes the guess and `update_outcome` the actual value. `record_seen` stores the first render time, the first fold-open time and the draft answer at reveal. The draft is kept only by the call that stores the fold time. `get_accuracy_summary` returns counts, accuracy rate and category and type breakdowns over a day window (30 by default). It leaves out two kinds of legacy row. One was scored with a similarity above 1 (`legacy_similarity_clause`), the other stores a confidence above 1 (`legacy_confidence_clause`). Their counts come back as `excluded_legacy_similarity` and `excluded_legacy_confidence`. The summary also carries `by_abstention_reason`, the row count per named abstention reason, most frequent first. It uses the same filters, and rows with no reason are not counted. With `prediction engine comment match report enabled` true it also returns `comment_match`, the stance-only and stance-and-comment counts and rates over yes/no scored rows. With it off the key is absent. `set_three_way_shadow( notification_id, stance )` stores the three-way challenger's stance on an ask's forecast row. It returns False when there is no row and changes no other column. `field_forecasts` is now one of the ledger columns `log_prediction` accepts; any column outside that set raises `ValueError`.

## Don't
- Don't call `delete_pending` on a ratified decision. It raises `ValueError`; only pending ones can go.
- Don't call `delete_all` outside a test. It is a test reset that empties `prediction_decisions` and returns the count. The caller commits.
- Don't read `accuracy_rate` as covering every prediction. It divides by the scored rows (`accuracy_match` present) and is `null`, with `status` `insufficient data`, when none are. Rows with `forecast_source` `test_override` are left out of every count. `GET /api/prediction-engine/accuracy` serves it to admins.

## Invariants
- `get_or_create` makes a trust row at level 1 with zero counts. `update_after_ratification`, `update_trust_level` and `update_circuit_breaker_state` all go through it.
- `ratify` and `update_outcome` return `None` for an id that is not found. `update_outcome` and `get_by_notification_id` raise `ValueError` for a notification id that is not a UUID string.
- Trust updates take a user email, domain and category, and create the row through `get_or_create` when it is missing.
- `find_similar` in `PredictionDecisionRepository` multiplies its threshold by 100 and clamps scores.
