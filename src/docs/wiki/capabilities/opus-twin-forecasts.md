---
capability: opus-twin-forecasts
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.prediction_engine.opus_twins.OpusBaseline@1ee1c5605d
  - cosa.agents.prediction_engine.opus_twins.baseline_gate@dd68319e38
  - cosa.agents.prediction_engine.opus_twins.opus_model@1d0b3d8c22
  - cosa.agents.prediction_engine.opus_twins.principles_gate@7bc82b3e7e
  - cosa.agents.prediction_engine.opus_twins.run_baseline_opus@556e55fb3e
  - cosa.agents.prediction_engine.opus_twins.run_principles_opus@6820c1850d
---
# Opus twin forecasts

Each learner forecast run again on Opus. A twin makes one call per ask, with no retry and at most one call in flight, under its own switch. It is never displayed. The shared path is in [[principles-forecast-arm]].

## What it does
- A twin is `run_arm` with another arm name, switch, version suffix and principle block. Only the model id differs from its Haiku arm, so a gap between them is a model gap.
- `OpusBaseline` is the baseline contract with its model id replaced by Opus's. `opus_model` reads that id from the INI file and raises when it is missing or blank, so a twin never falls back to another model.
- `baseline_gate` and `principles_gate` build each twin's own `CapGate`. The default is one call at a time. A missing or non-positive setting raises.
- `run_baseline_opus` repeats the baseline forecast on Opus with no principle block. The row is for the baseline twin's arm, with displayed false.
- `run_principles_opus` sends the baseline prompts plus the same principle block the Haiku arm gets. Its row carries both version suffixes.
- With the switch off, or the baseline contract None, nothing is read, called or written. A card past the cap gets a row with the capacity reason and no call.
- The Opus id is read only when the switch is on and a baseline exists. An off twin never touches that key.
- Both twins need the baseline contract. Without it they read the blocked reason and write nothing.
- Both twins take `limits`, passed on to `run_arm` unchanged.
