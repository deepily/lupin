---
capability: prediction-failure-visibility
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.prediction_engine.failure_visibility.is_failure_reason@4607587432
  - cosa.agents.prediction_engine.failure_visibility.log_failure@c15ef99bbd
  - cosa.agents.prediction_engine.failure_visibility.name_failure@f0f31e6faf
---
# Prediction failure visibility

Silent prediction failures become named abstention reasons. The engine ([[prediction-engine]]) calls this module only when `prediction engine failure visibility enabled` is true, and is off by default. Everything here is pure naming and logging.

## What it does
- `name_failure` gives a predictor's reason its failure name. `no_embedding` becomes `embedding_missing`. `no_similar_cases` with the class name of a swallowed store exception becomes `store_error: <class>`. Any other reason, and None, come back unchanged.
- `is_failure_reason` is True for `embedding_missing`, `store_write_failed` and any `store_error: <class>`, and False for everything else.
- `log_failure` prints one line starting with `[PREDICTION-FAILURE]` and returns it. The notification id may be None for a failed answer-case write.
- With the switch off the engine keeps the old reasons and logs nothing.
