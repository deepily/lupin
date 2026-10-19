---
capability: cc-inbox-catchup
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.answer_catchup.reconcile_answers@32792bae1b
  - lupin_cli.claude_code.hooks.lib.answer_catchup.read_hwm@477407ca98
  - lupin_cli.claude_code.hooks.lib.answer_catchup.write_hwm@06b072680e
  - lupin_cli.claude_code.hooks.lib.answer_catchup.append_surfaced_id@62477c0e37
  - lupin_cli.claude_code.hooks.lib.answer_catchup.read_surfaced_log@020c8dcacd
  - lupin_cli.claude_code.hooks.lib.answer_catchup.surface_owed_answers@0603c9f91b
  - lupin_cli.claude_code.hooks.lib.dm_inbox_reconcile.reconcile_context@686e694b79
  - lupin_cli.claude_code.hooks.lib.dm_inbox_reconcile.read_hwm@805d2da4a0
  - lupin_cli.claude_code.hooks.lib.dm_inbox_reconcile.write_hwm@109a0be72b
  - lupin_cli.claude_code.hooks.lib.dm_inbox_reconcile.surface_dm_inbox@7d8b2b2286
---
# Late answer and DM inbox catch-up
Durable at-least-once paths that hand a session the answers and peer DMs it missed, surfaced as context and never as an interrupt.
## What it does
- `surface_owed_answers` fetches answers owed to the session's persona, drops those already surfaced, and returns the context text. It is called by the listener on connect and by the prompt hook.
- `reconcile_answers` is its pure core. It orders answers oldest first and moves the cursor to the latest `responded_at`.
- `read_hwm` and `write_hwm` load and save the high-water mark; `write_hwm` returns False on `OSError`.
- `append_surfaced_id` and `read_surfaced_log` keep a side-log so a live-surfaced answer is not shown twice.
- `surface_dm_inbox` does the same for peer DMs at the start of a turn. `reconcile_context` is its pure core, and its own `read_hwm` and `write_hwm` use `.dm-inbox-hwm-<sid8>.json`, where sid8 is the first eight characters of the session id.
## Don't
- Don't add first-run suppression to the answer path. A returning session must get everything owed.
- Don't read the listener's service-account user id for the fetch; use the persona.
## Invariants
- A failed fetch returns an empty string and leaves the mark where it was, so the next turn retries.
- The DM path seeds the mark on first use and surfaces nothing, so a live backlog is not replayed.
- Both paths never raise and cap the remembered ids.
