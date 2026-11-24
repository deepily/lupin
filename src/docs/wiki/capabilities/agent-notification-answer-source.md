---
capability: agent-notification-answer-source
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.utils.agent_notification_dispatcher.ConfirmationAnswer@56a57ccd2a
  - cosa.agents.utils.agent_notification_dispatcher.answer_source_is_human@571028b21f
  - cosa.agents.utils.agent_notification_dispatcher.answer_source_of@1c3acdfa0e
  - cosa.agents.utils.agent_notification_dispatcher.take_last_ask_answer_source@7465ffb44e
---
# Agent notification answer source

Records who gave an answer to an agent's question. The label is decided once, when the answer arrives, and read back later. Voice calls are in [[agent-voice-io]].

## What it does
- `answer_source_of( response )` returns `default` when the server applied the question's default, whatever else the response carries.
- With no stamp it returns `unattributed`. With a stamp the promotion gate accepts as the operator's it returns `human`. Any other stamp, such as an API key, is `not_operator`.
- `answer_source_is_human( source )` is True exactly when the source is `human`. It only reads the label back.
- `ConfirmationAnswer` keeps one yes/no answer whole: stance, comment, raw text, source and the server's `answered_by` stamp.
- The stance is `yes`, `no` or `neither`, or None for any other text. The source defaults to `unattributed`.
- `ConfirmationAnswer.approved` is True when the raw text starts with `yes`, the bool `ask_confirmation` has always returned.
- `take_last_ask_answer_source()` returns and forgets the label of the latest open-ended or multiple-choice answer in this task.
- It returns None when no such ask answered, when the ask raised, or on a second call.
