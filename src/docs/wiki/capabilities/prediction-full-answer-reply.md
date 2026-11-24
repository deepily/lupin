---
capability: prediction-full-answer-reply
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.prediction_engine.context_baseline.build_full_user_prompt@9ccc5d54f0
  - cosa.agents.prediction_engine.context_baseline.parse_full@ea9edff1f0
  - cosa.agents.prediction_engine.full_answer.ReplyRefused@f55ca6b9db
  - cosa.agents.prediction_engine.full_answer.full_answer_enabled@0d31dce6c1
  - cosa.agents.prediction_engine.full_answer.option_ids_of@f866b9abfa
  - cosa.agents.prediction_engine.full_answer.parse_full_reply@68f10fa168
  - cosa.agents.prediction_engine.full_answer.stable_option_id@7f4c96f09e
---
# Prediction full-answer reply

The richer forecast reply: probabilities, conversational acts, conditions, chosen option ids and a whole-card chance. The baseline that calls it is in [[prediction-context-baseline]].

## What it does
- `full_answer_enabled` is True only when `prediction engine full answer reply enabled` is true. An unreadable setting reads as off and never raises.
- `stable_option_id( position_id, label )` is the position id, a dash and six hex digits of the label's sha-256. A changed label gives a new id.
- `option_ids_of( field )` returns one stable id per option of an episode field, in the card's order.
- `ReplyRefused` is a `ValueError` with a `reason`. Its text is `reason: detail`.
- `parse_full_reply( text, episode )` returns the forecast record, or raises `ReplyRefused`. Nothing is written.
- A reply that is not JSON, has probabilities outside 0 to 1, names an unknown option id or leaves out a field is refused. So is a reply that abstains.
- A yes/no record adds `value`, the likeliest stance, and its confidence is that stance's probability. A tie goes to yes, then no, then neither.
- A multiple-choice record adds `fields` and `answers`, the labels of the chosen options. A write-in or re-frame field is left out of `answers`.
- `build_full_user_prompt( episode, layers )` swaps the old reply format for this one. It lists each option's stable id when the options layer is on.
- `parse_full( text, episode )` calls `parse_full_reply`. A type outside the supported types raises `UnsupportedAsk`.
