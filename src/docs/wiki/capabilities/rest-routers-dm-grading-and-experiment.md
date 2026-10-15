---
capability: rest-routers-dm-grading-and-experiment
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.routers.dm.get_dm_quality_judgment_enabled@6c5c3e3944
  - cosa.rest.routers.dm.get_dm_feedback_arm@ef4f5baf62
  - cosa.rest.routers.dm.get_dm_grade_audit@b1ca916f3e
  - cosa.rest.routers.dm.reset_dm_grade_audit@c7900016da
  - cosa.rest.routers.dm.format_dm_grade_notice@552cdd51a1
  - cosa.rest.routers.dm.push_dm_grade_to_sender@dd26d5fa6f
  - cosa.rest.routers.dm.reset_dm_experiment_state@4684816860
---
# DM grading and experiment switches

The helpers in `routers/dm.py` that decide how a DM is graded and how the grade gets back to the sender. Grading never delays a send. See [[rest-routers-dm-audit-counters]] and [[rest-routers-dm-send-get-and-list]].

## What it does
- `get_dm_quality_judgment_enabled` reads the INI key `dm quality judgment enabled` on each call. It is true only when the key is explicitly true, and false when the key is absent or unreadable.
- `get_dm_feedback_arm` returns `reject_on_overage` when `dm reject on overage` is true, and `signal_only` otherwise, including on a config error. It only labels corpus rows. No reject path acts on it yet.
- `get_dm_grade_audit` returns a copy of the deferred-grade counters: `accepted`, `refused`, `refused_under_pytest`, `pending` and `failed`. `reset_dm_grade_audit` zeroes them.
- Grades run on one background worker with at most 32 jobs waiting. Past that the grade is refused and the corpus row is written ungraded.
- `format_dm_grade_notice` makes the line `[grade for DM <id>] length … · directness … · tone … · overall …`. A dimension with no weight reads as withheld.
- `push_dm_grade_to_sender` pushes that line to the sender's seat as a low-priority task notification from `dm-quality-judge@lupin.deepily.ai`. It returns true only when pushed, and a departed seat is not an error.
- `reset_dm_experiment_state` empties the per-slot memory of each sender's last length-gate outcome.

## Don't
- Don't send a grade with `dm_send`. It would be graded in turn, forever.
- Don't read a zero `pending` as proof grading works. Under pytest every deferral is refused.

## Invariants
- A grade that cannot be pushed is dropped quietly. It never stops the worker.
