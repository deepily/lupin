---
capability: heartbeat-respin-wake-verdict
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.heartbeat_arbiter.respin_wake_check.WakeAssessment@82b4344088
  - cosa.agents.heartbeat_arbiter.respin_wake_check.WakeVerdict@2899da545b
  - cosa.agents.heartbeat_arbiter.respin_wake_check.classify_wake@ff65a0f718
  - cosa.agents.heartbeat_arbiter.respin_wake_check.render_alert@cc70e7066a
  - cosa.agents.heartbeat_arbiter.respin_wake_check.check_respin_wake@0f2c67d063
  - cosa.agents.heartbeat_arbiter.respin_wake_check.verify_respin_wake@247d6a8122
  - cosa.agents.heartbeat_arbiter.respin_wake_check.start_wake_watch@238f098f6e
  - cosa.agents.heartbeat_arbiter.respin_wake_check.arm_watches_for_spawn@ee2df92edd
---
# Heartbeat re-spin wake verdict

After a re-spin fires, this check decides whether the successor woke and read the right memento, and tells the firing manager when it did not. It reads the receipts described in [[heartbeat-respin-boot-receipts]].

## What it does
- `WakeVerdict` has eight values. `RETURNED` and `PENDING` are quiet. The others alarm: `DEAD_NO_WAKE`, `SEED_NOT_CONSUMED`, `STALE_SLOT`, `STALE_MEMENTO`, `WRONG_PERSONA` and `MALFORMED_RECEIPT`.
- `WakeAssessment` carries the verdict, the reason, the alarm flag, the seat identity and the memento path.
- `classify_wake` is pure. A receipt dated at or before `fired_at` counts as none, so the predecessor's boot cannot pass the check.
- With no receipt it is `PENDING` until 90 seconds past the fire time, then `DEAD_NO_WAKE`.
- With a receipt it checks in order: no memento resolved, another persona's record, a mirror copy, then a record older than an hour. A record with no written time is not stale.
- A persona mismatch needs both names known and no shared slug.
- `render_alert` writes the manager's line: verdict, identity, reason and the file opened. It words three identity cases differently: known, only a tmux name, nothing.
- `check_respin_wake` polls until the verdict settles or the deadline passes. It never sleeps past the deadline.
- `verify_respin_wake` calls `alert_fn` once on an alarm. A failing `alert_fn` is swallowed so the verdict is still returned.
- `start_wake_watch` runs that on a daemon thread and returns it at once.
- `arm_watches_for_spawn` arms one watch per record with status `spawned`, keyed on the tmux session name. A caller-supplied `base_dir_for` points each watch at the spawned seat's own data root.

## Don't
- Do not read `DEAD_NO_WAKE` as proof of death. A receipt in the wrong directory looks the same. The misplaced-receipt finder separates the two.
