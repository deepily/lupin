---
capability: cc-hold-fields-and-janitor
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.ttl_is_usable@1599662a96
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.hold_cargo_keys@0f313446bb
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.classify_hold_file@e2766ae372
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.report_hold_files@6b74087d05
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.prune_stale_hold_files@2ca0ffc6af
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.declared_work_owed@436e436c9b
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.get_pending_user_gates@0edf9c1f57
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.get_last_looked_in_ts@c3dda82ac2
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.get_last_spinup_check_ts@66b8d02bf3
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.get_last_surfaced_questions_ts@0b3bd6926b
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold_warn.should_warn_unusable_ttl@d7ac8d674f
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold_warn.clear_warn_state@a89269a63f
---
# Hold fields, janitor and ttl warning
Accessors for a hold's fields and the janitor that reclaims dead hold files. It also holds the one-time warning for a hold whose ttl cannot defend a session.
## What it does
- `declared_work_owed` returns the hold's boolean `work_owed`, else None. `get_pending_user_gates` returns the gate list, else an empty list.
- `get_last_looked_in_ts`, `get_last_spinup_check_ts` and `get_last_surfaced_questions_ts` return the debounce stamps, or None when absent or not a string.
- `ttl_is_usable` is true only for a numeric `ttl_seconds`; a boolean, null or missing value is not usable.
- `hold_cargo_keys` lists keys outside the hold schema. Such a file is a memento wearing a hold's name.
- `classify_hold_file` is the one keep-or-prunable rule. It touches nothing and keeps unreadable, live, young, unprovable-age and cargo-bearing files.
- `report_hold_files` classifies every hold it can reach and deletes nothing. It reports counts, unreachable roots and misplaced paths.
- `prune_stale_hold_files` deletes only what `classify_hold_file` calls prunable, and returns the pruned paths.
- `should_warn_unusable_ttl` is true at most once per session and hold version, when the hold's ttl is unusable. `clear_warn_state` resets that marker.
## Don't
- Don't delete a cargo-bearing file unless cargo triage is done and deletion is explicitly allowed.
## Invariants
- The report and the prune share one rule, so the dry run cannot drift from the delete.
- With no authoritative live-session set, the janitor keeps the file.
- A session with no hold is never warned.
