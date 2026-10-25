---
capability: cc-hooks-heartbeat-owed
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.heartbeat_task_state.replay_task_state@f92c85d83d
  - lupin_cli.claude_code.hooks.lib.heartbeat_task_state.replay_task_subjects@edb47cd2ab
  - lupin_cli.claude_code.hooks.lib.heartbeat_task_state.owed_items_from_state@72c8f537a8
  - lupin_cli.claude_code.hooks.lib.heartbeat_task_state.is_empty_state@318772c7e3
  - lupin_cli.claude_code.hooks.lib.heartbeat_task_state.fetch_task_work_owed@7a2006ba35
  - lupin_cli.claude_code.hooks.lib.heartbeat_task_state.is_task_set_empty@1d57440042
  - lupin_cli.claude_code.hooks.lib.heartbeat_work_owed.format_owed_summary@c08eb51250
  - lupin_cli.claude_code.hooks.lib.heartbeat_work_owed.is_heartbeat_poke_prompt@6a0eba3f39
  - lupin_cli.claude_code.hooks.lib.heartbeat_work_owed.manager_needs_verification@8aa46ecb1f
  - lupin_cli.claude_code.hooks.lib.heartbeat_work_owed.manager_needs_spinup_check@8187ee9b12
  - lupin_cli.claude_code.hooks.lib.heartbeat_work_owed.manager_needs_question_surface@a67ec329f6
  - lupin_cli.claude_code.hooks.lib.heartbeat_work_owed.partition_inbound_by_age@fa1e232144
  - lupin_cli.claude_code.hooks.lib.heartbeat_work_owed.build_poke_reason@af912b305e
  - lupin_cli.claude_code.hooks.lib.heartbeat_settings.load_heartbeat_settings@68b0a625db
  - lupin_cli.claude_code.hooks.lib.idle_settings.load_idle_settings@71a047db85
  - lupin_cli.claude_code.hooks.lib.idle_waiter.run_waiter@6bbc3a66f9
  - lupin_cli.claude_code.hooks.lib.idle_waiter.main@b7ec81620a
---
# Heartbeat work-owed, task replay and idle settings
The heartbeat decides from the session's task state whether work is owed, and idle-aware Stop hooks read their settings and a deferred-ask waiter.
## What it does
- `replay_task_state` replays the transcript's Task tool calls into a status per task. `replay_task_subjects` maps task ids to subjects.
- `owed_items_from_state` derives the owed list from a replayed state. `is_empty_state` says whether there are no tasks.
- `fetch_task_work_owed` and `is_task_set_empty` replay the transcript and then do one of those two steps.
- `format_owed_summary` renders the poke's owed line. `build_poke_reason` composes the poke reason from a verdict.
- `is_heartbeat_poke_prompt` tells an injected liveness poke from user input.
- `manager_needs_verification`, `manager_needs_spinup_check` and `manager_needs_question_surface` are pure debounce checks for managers.
- `partition_inbound_by_age` splits inbound entries into fresh and stale.
- `load_heartbeat_settings` and `load_idle_settings` load defaults overlaid by `~/.claude/settings.json`.
- `run_waiter` is the idle-aware Stop hook's deferred-ask helper. `main` is its entry point.
## Don't
- Do not read the clock inside a debounce check. Pass `now_epoch` in.
## Invariants
- The waiter exits cleanly on every termination path.
