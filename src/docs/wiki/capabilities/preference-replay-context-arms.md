---
capability: preference-replay-context-arms
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.research.preference_replay.context_arms.arm_text@7cd0ed823e
  - cosa.research.preference_replay.context_arms.build_arm_texts@a18ca7c7b5
  - cosa.research.preference_replay.context_arms.build_cohort_arms@5a93a7bb9e
  - cosa.research.preference_replay.context_arms.question_text@2337e3658e
  - cosa.research.preference_replay.context_arms.read_arm_inputs@012dacacc0
  - cosa.research.preference_replay.context_arms_report.compare_arms@a547540238
  - cosa.research.preference_replay.context_arms_report.render_arm_report@aac1b732b5
  - cosa.research.preference_replay.context_arms_report.main@f4a143edcb
  - cosa.research.preference_replay.context_arms_report.read_coverage@68f6892463
---
# Preference replay context arms

The text each context arm embeds, and the report that compares the arms ([[preference-replay-reports]]).

## What it does
- Arm Q is the question alone. Q+A adds the card's abstract, Q+O its options, Q+P the project and session, Q+H the previous answer on the thread. An ask with no rebuilt context falls back to the question.
- `question_text`, `arm_text` and `build_arm_texts` build the text, the last counting the fallbacks. `read_arm_inputs` reads the notifications, turning each row into a dict with `notification_dict` from [[prediction-history-recovery]]. `build_cohort_arms` builds every arm for every ask.
- `compare_arms( runs, operational_floor )` scores each arm against Q and always-yes by exact McNemar. `render_arm_report` adds coverage and reconciliations.
- Always-yes counts yes/no asks only, because it has no answer to a multiple-choice ask. Each arm's `vs_q_by_type` pairs it with Q for each answer type, and a second table prints them.
- `read_coverage( prefix )` reads each arm's four coverage counts from its side-file header. It raises `ValueError` when the reason counts do not add up or the arms hold different ask counts.
- `context_arms_report.main` builds the report from the committed per-ask files. Its header names the code sha, the floor and its source, and the exact command.
