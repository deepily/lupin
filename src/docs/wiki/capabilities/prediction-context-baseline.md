---
capability: prediction-context-baseline
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.prediction_engine.context_baseline.ContextBaseline@f3e9da6901
  - cosa.agents.prediction_engine.context_baseline.ContextBaseline.__init__@c7c1131960
  - cosa.agents.prediction_engine.context_baseline.ContextBaseline.build_prompts@fff26de8c0
  - cosa.agents.prediction_engine.context_baseline.ContextBaseline.complete@6e9f81b109
  - cosa.agents.prediction_engine.context_baseline.ContextBaseline.parse@c83171c5e3
  - cosa.agents.prediction_engine.context_baseline.UnsupportedAsk@c4702f89b3
  - cosa.agents.prediction_engine.context_baseline.build_user_prompt@68b87c6e05
  - cosa.agents.prediction_engine.context_baseline.context_display_enabled@0649358da6
  - cosa.agents.prediction_engine.context_baseline.context_forecast_enabled@bd504c1f06
  - cosa.agents.prediction_engine.context_baseline.context_gate@8c76035e8c
  - cosa.agents.prediction_engine.context_baseline.context_layers@3ffe0d8638
  - cosa.agents.prediction_engine.context_baseline.context_model@688819adda
  - cosa.agents.prediction_engine.context_baseline.context_timeout@2bc4632002
  - cosa.agents.prediction_engine.context_baseline.get_baseline@0d0d3df31c
  - cosa.agents.prediction_engine.context_baseline.open_ledger@485a866a4f
  - cosa.agents.prediction_engine.context_baseline.parse_reply@4d40196def
  - cosa.agents.prediction_engine.context_baseline.predictor_version@0b543d84e5
  - cosa.agents.prediction_engine.context_baseline.reset_baseline@01aa40c1cc
  - cosa.agents.prediction_engine.context_baseline.run_context_forecast@bc3a0256e4
---
# Prediction context baseline

The Haiku baseline forecast of one card, read from the card itself. It is the baseline job that the principles forecast ([[principles-forecast-arm]]) and the Opus twins ([[opus-twin-forecasts]]) are built on.

Its row goes to the sibling table ([[rest-prediction-arm-forecast]]), never to `prediction_log`.

## What it does
- `ContextBaseline` holds the baseline contract in one object: the model, the timeout, the error classes, `build_prompts`, `parse` and a cached call. `get_baseline` makes one per process on first use from the INI settings, and `reset_baseline` forgets it and its cap gate.
- The settings are INI keys under `prediction engine context ...`: the two switches, the model, the timeout, the cap, the layers and the ledger path. `context_forecast_enabled` and `context_display_enabled` treat an unreadable switch as off.
- `context_model`, `context_timeout` and `context_layers` raise on a missing or invalid value. A timeout of zero or less raises too.
- `build_user_prompt` builds the prompt in layers, each a field of the card. The layers are the question and fields, the options and mode, the title, abstract and links, and the asker's default and time budget. The default and the budget are inputs, never a label. A free-text field is marked as such, not forecast.
- `parse_reply` turns the model's reply into a typed forecast with a strict parser. It raises on a reply it cannot read, and on a list given for a field that takes one option. A response type other than yes/no or multiple choice raises `UnsupportedAsk`.
- `ContextBaseline` reads `prediction engine full answer reply enabled` once when built (shipped INI false). On, `build_prompts` and `parse` use `build_full_user_prompt` and `parse_full` (the `full_answer` reply format, with stable option ids; the type must be in `FULL_ANSWER_TYPES`, else `UnsupportedAsk`). Off, the prompt and parser are the old ones.
- `predictor_version( layers, full )` names the prompt and the parser, so a change to either is a new version. With `full` it also covers the `full_answer` module; with it off the value is the one given before that reply existed. `open_ledger` opens the call's ledger, one file per Claude Code binary version.
- `run_context_forecast` makes the forecast for one ask. It is `principles_forecast.run_arm` with the baseline arm and no principle block, so that function's switch, cap, single row per card and not-ready reasons hold. With the switch off nothing is read, called or written.
- `context_gate` makes the cap gate from its INI setting. A call is killed on timeout, and on an error result the child process is killed too.
