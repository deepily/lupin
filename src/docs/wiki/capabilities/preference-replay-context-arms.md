---
capability: preference-replay-context-arms
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.research.preference_replay.context_arms.arm_text@7cd0ed823e
  - cosa.research.preference_replay.context_arms.build_arm_texts@a18ca7c7b5
  - cosa.research.preference_replay.context_arms.build_cohort_arms@5a93a7bb9e
  - cosa.research.preference_replay.context_arms.notification_dict@617defc6cb
  - cosa.research.preference_replay.context_arms.question_text@2337e3658e
  - cosa.research.preference_replay.context_arms.read_arm_inputs@012dacacc0
  - cosa.research.preference_replay.context_arms_report.compare_arms@a4c0a9734a
  - cosa.research.preference_replay.context_arms_report.render_arm_report@bf0c906122
---
# Preference replay context arms

The text each context arm embeds, and the report that compares the arms ([[preference-replay-reports]]).

## What it does
- Arm Q is the question alone. Q+A adds the card's abstract, Q+O its options, Q+P the project and session, Q+H the previous answer on the thread. An ask with no rebuilt context falls back to the question.
- `question_text`, `arm_text` and `build_arm_texts` build the text, the last counting the fallbacks. `read_arm_inputs` and `notification_dict` read the notifications. `build_cohort_arms` builds every arm for every ask.
- `compare_arms( runs, operational_floor )` scores each arm against Q and always-yes by exact McNemar. `render_arm_report` adds coverage and reconciliations.
