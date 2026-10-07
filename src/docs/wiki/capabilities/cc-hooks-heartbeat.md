---
capability: cc-hooks-heartbeat
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.heartbeat_decision.decide_heartbeat@0a25f3eecf
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.is_honored@7ea3872543
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.is_fresh@fd8168b6e6
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.write_hold@bb3dcea194
  - lupin_cli.claude_code.hooks.lib.heartbeat_work_owed.evaluate_work_owed@2c8a7585a5
  - lupin_cli.claude_code.hooks.lib.heartbeat_poke_cap.increment_poke_count@ca446d6ab7
  - lupin_cli.claude_code.hooks.lib.heartbeat_poke_mute.read_poke_mute@8366058817
  - lupin_cli.claude_code.hooks.lib.heartbeat_user_gates.pokeable_gates@e620aade55
---
# Stop-hook heartbeat

When a Claude Code seat stops, `stop.py` asks whether it still owes work and, if so, blocks the stop with a poke. `decide_heartbeat` is the pure decision; the rest of the `heartbeat_*` modules gather its inputs. [[heartbeat-arbiter]] is the fleet-side watcher of the same hold files; [[cc-session-bridge]] supplies persona and role.

## Decision order (`decide_heartbeat`)
- If the verdict's signals include `needs_verification` or `outstanding_user_gate`, hold checks are skipped. The seat goes straight to the cap check.
- Otherwise a fresh hold with a non-blank `reason` is honored: no poke, outcome `honored`.
- If not honored, a hold whose `work_owed` is `false` ends it as `not_owed`. A hold that says owed while the oracle finds nothing ends as `suppressed_stale_declared_owed`, with no poke. Otherwise the oracle verdict decides.
- Owed and `poke_count >= cap` gives `cap_reached` (no poke; the caller only writes a `heartbeat_cap_reached` log record, no user notify). Under the cap it returns `{"decision":"block","reason":...}`, and the caller bumps the count.

## Holds
- A hold is `.heartbeat-hold-<session_id>.json`, written atomically by `write_hold`. `write_hold` refuses a blank reason and a non-positive or non-numeric `ttl_seconds`; the default ttl is 900 s.
- Fresh means the age is under `ttl_seconds`, measured from the file's mtime when the reader stamped one, else from `held_at`.
- Declare one with `python3 -m lupin_cli.claude_code.hooks.lib.heartbeat_hold_io write|read|clear`, not by hand. `write` reads the hold back through the Stop hook's own search. If the hold would not be honored, it restores the previous file (or deletes the new one when none existed) and exits 3; an existing hold carrying extra fields is refused with exit 6.

## What counts as owed (`evaluate_work_owed`)
- Signals, in fixed order: `todo_in_progress`, `todo_unstarted`, `pending_decision`, `unanswered_inbound_question`, `outstanding_delegation`, `needs_verification`, `outstanding_user_gate`, `surface_operator_gates`, `spinup_nudge`. Owed means at least one fired. In `stop.py`, `unanswered_inbound_question` counts only when `count_inbound_questions_as_owed` is true; it defaults to false.
- `stop.py` takes owned rows from the task store when `heartbeat.owed_source_from_store` is on (see [[task-store]]), else replays `TaskCreate`/`TaskUpdate` from the transcript. A store that cannot be read counts as 0 owed and marks the result unknown.
- A user gate is due only when it is not answered and not deferred by a future `next_chase_ts` or a store-side user deferral. It must also not be past its re-ask cap with no chase, and it was either never asked or last asked at least its re-ask interval (default 600 s) ago.

## Caps, mute and switches
- Settings come from the `heartbeat` block of `~/.claude/settings.json`. `enabled` defaults to false; `poke_cap` defaults to 1 and a non-positive or non-int value raises, which `stop.py` treats as no poke.
- Mute: `poke_output_enabled: false` in settings, or `muted: true` in `heartbeat-poke-mute.json` (a missing or malformed file reads as not muted). A muted seat skips every lookup, but a non-empty substitute message is still sent as a poke (counted against the cap) until the cap. A file mute supplies its own message when settings has none.

## When not to use it
- To park a seat, write a hold with the verb.
- For fleet-side stall detection, use [[heartbeat-arbiter]].
