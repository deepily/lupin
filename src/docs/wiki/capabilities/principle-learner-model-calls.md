---
capability: principle-learner-model-calls
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.principle_learner.opus_call.get_gate@fe23ef5757
  - cosa.agents.principle_learner.opus_call.reset_gates@1101eb9c4b
  - cosa.agents.principle_learner.opus_call.run_baseline_twin@235b26d33d
  - cosa.agents.principle_learner.opus_call.run_principles_twin@4cbbcd6ba2
  - cosa.agents.principle_learner.principles_call.get_gate@9f0330b1d0
  - cosa.agents.principle_learner.principles_call.provider_embedder@e5c8830bae
  - cosa.agents.principle_learner.principles_call.reset_gate@fb9c9c7b44
  - cosa.agents.principle_learner.principles_call.retrieval_versions@d93e84d931
  - cosa.agents.principle_learner.principles_call.run_principles_forecast@e4aecd0a25
  - cosa.agents.principle_learner.principles_call.run_quietly@c7ef7588fe
---
# Principle learner model calls

The learner's per-ask forecast calls. Each one is the baseline job ([[prediction-context-baseline]]) with one change. It takes the process's own baseline from `get_baseline`. It writes a row to the sibling table under its own arm name, never to `prediction_log`. Each has its own switch and cap gate, so none can take a slot from another.

## The principles call
- `run_principles_forecast` makes the principles forecast for one ask. It is `principles_forecast.run_b1` over the baseline, so the prompt is the baseline's plus the principle block ([[principles-forecast-arm]]). The principles are those of the encoder and extractor version the settings name now (`retrieval_versions`).
- `provider_embedder` makes the object the call embeds the card text with. `get_gate` returns the process's cap gate, made once so two asks share one cap, and `reset_gate` forgets it.
- `run_quietly` runs the call for the notify route as a held background task. It never lets a failure reach the ask. A failure is printed and the return is None.

## The Opus twins
- `run_baseline_twin` and `run_principles_twin` run each Haiku forecast again on Opus, one call per ask with no retry ([[opus-twin-forecasts]]). The principles twin adds the same principle block. A twin is never displayed. The model id is part of the ledger key, so a twin is never answered from its Haiku twin's cached reply.
- `get_gate` returns the twin's gate and holds one call in flight by default; `reset_gates` forgets them. A card past the cap gets a capped row.
- With a switch off nothing is read, called or written, and neither the baseline nor the embedder is built. A missing setting raises when the switch is on.
