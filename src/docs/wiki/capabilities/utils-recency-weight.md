---
capability: utils-recency-weight
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.utils.recency_weight.recency_weight@ec7955b59e
---
# Recency weight

One helper in `cosa.utils.recency_weight` gives an old observation its half-life weight. The trust tracker and the three-way stance predictor both call it.

## What it does
- `recency_weight( age_seconds, half_life_days )` returns `exp( -0.693 * age / half_life )`, with the half life taken in seconds. It is 1.0 at age zero, about 0.5 at one half-life, and never rises above 1.0.
- A half life that is zero or negative raises `ValueError`.

## Don't
- Don't swap `0.693` for the exact natural log of 2. The trust tracker has always used the rounded figure, and every threshold built on its weights depends on it. The error is about 0.02% per half-life.
- Don't write another `exp( -ln2 * age / half_life )`. Callers import this one.

## Invariants
- It is pure: no clock read, no state.
- Callers: `trust_tracker` in `cosa.agents.decision_proxy` and `three_way_stance` in `cosa.agents.prediction_engine`.
