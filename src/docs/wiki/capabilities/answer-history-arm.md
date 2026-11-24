---
capability: answer-history-arm
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.prediction_engine.answer_history_forecast.answer_history_enabled@9bc9af68c9
  - cosa.agents.prediction_engine.answer_history_forecast.approx_tokens@9a2d98df73
  - cosa.agents.prediction_engine.answer_history_forecast.eligible_cases@291f580eee
  - cosa.agents.prediction_engine.answer_history_forecast.history_code_hash@84c6099ccb
  - cosa.agents.prediction_engine.answer_history_forecast.history_provider@91786fa024
  - cosa.agents.prediction_engine.answer_history_forecast.render_answer@e6d6aa3853
  - cosa.agents.prediction_engine.answer_history_forecast.render_history@760682d76f
  - cosa.agents.prediction_engine.answer_history_forecast.run_answer_history@49e415ed13
  - cosa.agents.prediction_engine.answer_history_forecast.version_suffix@870eb4e787
---
# Answer history arm

The baseline forecast plus the owner's earlier answers to similar questions, shown whole. It is the yardstick the principles arm has to beat. It runs through [[principles-forecast-arm]] with a block provider.

## What it does
- `answer_history_enabled` is True only when the INI key `principle learner answer history arm enabled` is true. It never raises, and the arm is off by default.
- `approx_tokens( text )` returns ceil( characters / 4 ). It is an estimate. A caller with a tokenizer passes its own counter.
- `render_answer( message, view )` shows one answer: the question, each field's options with ids, and the raw response as sorted-key JSON.
- The labeller's reading, the forecast and the meaning record are never shown. The asker's recommended option is marked.
- `render_history( entries, budget )` lays out whole answers, strongest first, and stops at the first one that does not fit. None is cut short.
- It returns `{ text, ids }`. With nothing that fits, text is empty and ids is empty.
- `eligible_cases` keeps a case answered by a human, owned by the ask's owner and not rejected. The answer and its meaning record must be at or before the ask.
- `history_provider` builds the `block_provider` for `run_arm`. It advances the store to the ask, ranks neighbours by `neighbours_of` and skips a notification that no longer exists.
- Its `principle_ids` are the shown notification ids, stored as the row's evidence ids.
- `history_code_hash` hashes the heading and the source of the render, eligibility and provider functions. `version_suffix` adds it to the baseline's version after `+answer-history-`.
- `run_answer_history` is `run_arm` for this arm with no principle block. With the switch off, nothing is read, called or written.
