---
capability: cc-hooks-heartbeat-gates
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.heartbeat_poke_cap.get_poke_count@0594829226
  - lupin_cli.claude_code.hooks.lib.heartbeat_poke_cap.reset_poke_count@e21f91d900
  - lupin_cli.claude_code.hooks.lib.heartbeat_poke_cap.is_cap_reached@75aad02c3f
  - lupin_cli.claude_code.hooks.lib.heartbeat_poke_mute.poke_mute_path@0a7a1eca23
  - lupin_cli.claude_code.hooks.lib.heartbeat_poke_mute.write_poke_mute@3f782914cd
  - lupin_cli.claude_code.hooks.lib.heartbeat_poke_mute.mute_message@9ac75cf9a9
  - lupin_cli.claude_code.hooks.lib.heartbeat_user_gates.make_gate@e395c07cde
  - lupin_cli.claude_code.hooks.lib.heartbeat_user_gates.is_chase_deferred@ddc9ec8a08
  - lupin_cli.claude_code.hooks.lib.heartbeat_user_gates.is_reask_capped@08811537f4
  - lupin_cli.claude_code.hooks.lib.heartbeat_user_gates.is_user_deferred@749358d639
  - lupin_cli.claude_code.hooks.lib.heartbeat_user_gates.open_gates@b8dc6419b6
  - lupin_cli.claude_code.hooks.lib.heartbeat_user_gates.due_gates@b9009c7e19
  - lupin_cli.claude_code.hooks.lib.heartbeat_user_gates.aged_open_gates@2213db339c
  - lupin_cli.claude_code.hooks.lib.heartbeat_user_gates.derive_user_chase_until@790515ac9f
  - lupin_cli.claude_code.hooks.lib.heartbeat_user_gates.upsert_gate@844e634c00
  - lupin_cli.claude_code.hooks.lib.heartbeat_user_gates.mark_answered@97e82e2468
  - lupin_cli.claude_code.hooks.lib.heartbeat_user_gates.stamp_asked@e3645a5198
  - lupin_cli.claude_code.hooks.lib.heartbeat_user_gates.bump_reask_count@e581cd9835
  - lupin_cli.claude_code.hooks.lib.heartbeat_user_gates.defer_to_chase@fecb01fb6b
---
# Heartbeat poke cap, mute and user gates
The Stop-hook heartbeat keeps a per-session poke counter, a fleet-wide mute file and pending-user-gate rows.
## What it does
- `get_poke_count` reads the session's poke count, `reset_poke_count` deletes it, and `is_cap_reached` compares it with a cap.
- `poke_mute_path` names the mute file, `write_poke_mute` sets the switch and records who set it.
- `mute_message` is the one line a seat sees in place of the poke while the switch is on.
- `make_gate` builds one pending-user-gate row with every field in a fixed order.
- `open_gates` returns the unanswered rows. `due_gates` returns the pokeable ones whose re-ask interval has elapsed.
- `aged_open_gates` returns open gates whose last ask is older than a fixed age.
- `is_chase_deferred`, `is_user_deferred` and `derive_user_chase_until` tell whether a scheduled chase postpones the re-ask.
- `is_reask_capped` is true when a gate spent its re-ask budget and no chase is scheduled.
- `upsert_gate`, `mark_answered`, `stamp_asked`, `bump_reask_count` and `defer_to_chase` edit the row list.
## Don't
- Do not hand-edit gate rows. Use the row functions, which keep the field order.
## Invariants
- The row functions are pure logic over the list passed in. Time is a parameter, not read inside.
