---
capability: bounded-cc-client-base
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.shared.bounded_cc_client.BoundedCCClientBase@9b06e8b1b7
  - cosa.agents.shared.bounded_cc_client.BoundedCCCostEstimate@8ccbf81751
  - cosa.agents.shared.bounded_cc_client.temperature_to_steer@9717f6c47b
---
# Bounded Claude Code client base

The shared base of the podcast, presentation and deep research clients in [[generator-sdk-clients]]. The podcast and presentation clients keep their own `_call_api`, because the two start `stop_reason` differently.

## What it does
- `BoundedCCClientBase.__init__( config, debug, verbose, sdk_available )` raises `ImportError` when the SDK flag is false. Otherwise it keeps the config, or a new `CONFIG_CLASS()` when none is given, and makes the cost estimate. A `COST_ESTIMATE_CLASS` of `None` leaves `cost_estimate` as `None`.
- With `debug` it prints two banner lines. The second is `_banner_model_line()`: by default the `BANNER_NOUN` and the model in the `BANNER_FIELD` setting, and a client can override it.
- `_call_typed` forwards one named call to the client's `_call_api` with the model, call type, prompts, token limit and temperature.
- `call_with_json_output` calls the `JSON_MODEL_FIELD` model at temperature 0.5 with call type `json_output`. It returns the object the client's `_recover_json` finds.
- `BoundedCCCostEstimate` holds token, call and cost totals. `add_usage` adds one call's tokens and its price estimate. `price_pair` picks the Opus or Sonnet prices by model name, and the presentation estimate overrides it to add Haiku. `add_sdk_cost` adds the SDK's per-call cost. `get_summary` returns one line of text that says the figure is covered by the Max plan.
- `temperature_to_steer( temperature, high, low, high_steer, low_steer )` turns the old per-call temperature into one prompt sentence. It returns `high_steer` at or above `high`, `low_steer` at or below `low`, and an empty string between. The deep research, podcast and presentation clients each bind their own cut-offs and wording to it as `_temperature_to_steer`.

## Don't
- Don't read `total_sdk_cost_usd` as a bill. It is telemetry, and the plan covers it.

## Invariants
- `call_with_json_output` raises `ValueError` when no object can be recovered. It substitutes no default.
- A subclass sets `CONFIG_CLASS`, `COST_ESTIMATE_CLASS`, the banner and JSON model settings and `_logger`. It defines `_call_api` and `_recover_json` when it uses `_call_typed` or `call_with_json_output`.
- `ResearchAPIClient` tracks cost in its `CostTracker`, so it sets `COST_ESTIMATE_CLASS` to `None`. It keeps its own `call_with_json_output`, which takes a model and a call type.
