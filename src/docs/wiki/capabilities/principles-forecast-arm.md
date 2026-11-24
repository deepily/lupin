---
capability: principles-forecast-arm
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.prediction_engine.principles_forecast.CapGate@82e86aad1b
  - cosa.agents.prediction_engine.principles_forecast.check_baseline@d869a4ef78
  - cosa.agents.prediction_engine.principles_forecast.card_text@5be118980c
  - cosa.agents.prediction_engine.principles_forecast.concurrency_cap@d37390c64c
  - cosa.agents.prediction_engine.principles_forecast.principles_forecast_enabled@6af619ae07
  - cosa.agents.prediction_engine.principles_forecast.read_cap@e6185c263b
  - cosa.agents.prediction_engine.principles_forecast.run_arm@ac1d4c9481
  - cosa.agents.prediction_engine.principles_forecast.run_b1@960238fc6e
  - cosa.agents.prediction_engine.principles_forecast.switch_enabled@46cb445fd3
  - cosa.agents.prediction_engine.principles_forecast.with_principles@eb7580c939
---
# Principles forecast arm

The baseline forecast job plus a block of applicable principles. The model and prompts are the baseline's. Only the principle block differs. The result goes to `prediction_arm_forecast` under its own arm name ([[rest-prediction-arm-forecast]]).

## What it does
- The baseline job, `ContextBaseline`, is passed in as `c0`. With `c0` None the arm reads blocked and writes nothing. `check_baseline` raises `TypeError` naming every missing or misshapen member of the contract.
- `switch_enabled( key )` is True only when the INI key is true, and never raises. It reads through the shared `read_switch`. An unreadable setting prints one line and counts as off. `principles_forecast_enabled` reads the arm's own switch, off by default.
- `read_cap( key )` returns a positive int. A missing, blank or non-positive value raises. `concurrency_cap` reads this arm's own cap, so it cannot take a slot from the baseline.
- `CapGate` counts calls in flight. `try_enter` refuses at once past the limit and never queues. `leave` gives the place back.
- `card_text( episode )` is `episode_view.card_text`: the title, the abstract and each field prompt, one per line. It is what principles are searched by.
- `with_principles( system, user, block )` adds the block to the user prompt after the block's own `heading` (else the default heading) and changes nothing else. With no principles the prompt equals the baseline's.
- `run_arm` makes one arm's forecast for one ask and stores one row. Its status is ran, not_run, capacity or failed.
- With the switch off, or `c0` None, nothing is read, called or written. A card that already has its row is left alone.
- Past the cap, one row with no forecast and the capped reason is written, and no model is called. Otherwise one call goes out with no retry.
- A failure gathering inputs stores one row with an `input_error` reason. The cap place is always given back.
- `run_arm` takes `limits`, None or `{ bound, multiplier }`. None reads the INI file for each ask. A replay passes it so a frozen run never rereads the file.
- `run_arm` and `_prepare` take an optional `block_provider( session, episode )` returning `{ text, principle_ids, heading }`. It replaces the principle selection: the block comes from the provider, read in the same session and as of the same ask. Its ids are stored as the row's evidence ids. The answer history arm (`answer_history_forecast`, switch `principle learner answer history arm enabled`, off) uses it to show the owner's earlier answers whole.
- A full-answer reply the parser refuses stores the refusal's own reason and no forecast value.
- `run_b1` is `run_arm` fixed to the principles arm, with the principle block on.
