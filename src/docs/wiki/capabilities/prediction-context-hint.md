---
capability: prediction-context-hint
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.prediction_engine.context_hint.payload_for@3485c88ce5
  - cosa.agents.prediction_engine.context_hint.read_payload@76376fbf63
  - cosa.agents.prediction_engine.context_hint.ready_payload@d8b37901fb
  - cosa.agents.prediction_engine.context_hint.run_and_publish@f96a3eebaa
  - cosa.agents.prediction_engine.context_hint.settle_unfinished@910b5c07e7
  - cosa.agents.prediction_engine.context_hint.should_forecast@40bde81afe
---
# Prediction context hint

The baseline forecast as a card shows it ([[prediction-context-baseline]]). The card opens with its foundation hint ([[prediction-engine]]). With the display switch on it also carries a `context_forecast` payload that starts at the state `forecasting`.

## What it does
- `should_forecast` says whether a card gets the background forecast.
- `ready_payload` builds the payload of a ready forecast. `payload_for` turns the card's baseline row, or its absence, into the payload. No row reads forecasting until 30 seconds after the ask, then `forecast_timed_out`. A row with a reason reads `unavailable`; any other row reads ready.
- `read_payload` reads the payload for one card from the database. A fold opened later fetches it that way.
- `run_and_publish` runs the baseline job for one card, then sends one `prediction_hint_updated` event with the notification id and the current payload. With the display switch off nothing is sent and the job still runs. A failure of the job, the read or the send is printed and never raised, so it cannot reach the ask.
- `settle_unfinished` gives an answered card that has no baseline row its terminal state, writing one row with no forecast. A card with no `prediction_log` row never entered the notify forecast path, as with the podcast and un-park asks. Its reason is `forecast_not_started`. A card that has the row gets `forecast_timed_out`. A `forecast_not_started` row reads `unavailable` with that reason. A restart kills a job in flight before it writes. So the ledger holds a terminal state for every card the job was meant to forecast.
