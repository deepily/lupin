---
capability: forecaster-arms-registry
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.prediction_engine.forecaster_arms.opus_parse@51989acd62
  - cosa.agents.prediction_engine.forecaster_arms.own_parse@ce0addb2f9
---
# Forecaster arms registry

Lists the forecasters once, with the way each reaches the reply parser. A guard can then check that every one reads its reply through the baseline's parser.

## What it does
- `FORECASTER_ARMS` maps each arm name to a function that gives its parse function. The baseline, principles, both Opus twin arms and the answer history arm are listed.
- `own_parse( baseline )` returns `baseline.parse`. The baseline, principles and answer history arms use it.
- `opus_parse( baseline )` returns the parse of an `OpusBaseline` wrapped around the baseline. The two Opus twin arms use it.
- A forecaster added to the fleet is added to the registry.
- Related pages are [[prediction-context-baseline]], [[opus-twin-forecasts]] and [[principles-forecast-arm]].
