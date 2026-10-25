---
capability: cc-hook-idle-beacon
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.notification.beacon_idle_message@7862fadb9a
---
# Hook idle beacon

The notification hook sends an idle beacon when a seat waits for input. This capability picks its wording from what the seat owes.

## What it does
- `beacon_idle_message( owed, owed_unknown, total_owed, idle_msg )` returns the beacon text.
- When the owed state is unknown it returns the neutral `idle_msg`. Unknown is not idle, so the beacon makes no claim about owed work.
- When work is owed it returns "Idle, but N item(s) owed", with the plural when N is not 1.
- When work is owed but the count is zero, it returns "Idle, but work owed". That is the case of a signal with no referent.
- Otherwise it returns `idle_msg`. That includes a determinate not-owed state and an honoured hold.
- The flags come from the Stop hook's owed-state resolver, and the wording matches the Stop idle announcement.

## Don't
- Don't compute the owed flags here. Take them from the Stop hook's resolver, so the beacon and the Stop announcement agree.

## Invariants
- Precedence is unknown first, then owed, then idle.
- It never raises.
