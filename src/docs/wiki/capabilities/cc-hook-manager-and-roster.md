---
capability: cc-hook-manager-and-roster
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.manager_figure.resolve_implicit_manager_figure@5d723e0a20
  - lupin_cli.claude_code.hooks.lib.manager_figure.is_manager_figure@947efc9c91
  - lupin_cli.claude_code.hooks.lib.manager_figure.classify_manager_figure_denial@9e283f3878
  - lupin_cli.claude_code.hooks.lib.roster_consistency.find_roster_disagreements@3fbd858354
  - lupin_cli.claude_code.hooks.lib.roster_consistency.format_roster_drift_block@e2e3fd1619
---
# Hook manager figure and roster

A seat is a manager figure when its bridge says it was spawned as a manager. It is also one when its persona is a named standing persona of the repo. Task-store writes need that.

## What it does
- `is_manager_figure( session_id )` is true when the bridge role is `manager`, or the implicit stamp on the bridge is true. It is the single gate.
- `resolve_implicit_manager_figure( persona_name )` computes the implicit source. It is true when a named entry of the `COSA_VOICE_PREFERRED_PERSONA__<PROJECT>` chain matches the persona. The `*` wildcard never counts.
- `register_session` calls it with the real environment and stamps the result on the bridge. The server has no such variables, so it reads the stamp.
- `classify_manager_figure_denial` says why a check failed: no session id, a stale bridge with no stamp, or a plain denial. It only shapes the message.
- `find_roster_disagreements` compares `COSA_VOICE_MANAGERS__<PROJECT>` with the persona chain, in order, per project.
- `format_roster_drift_block` renders any disagreement as SessionStart context, or an empty string when none.

## Don't
- Don't re-derive the implicit source on the server. Read the stamp.
- Don't treat an absent family as drift. A deployment may carry only one of the two.

## Invariants
- The manager test fails closed: a session whose manager-hood cannot be established does not write.
- Names compare by one canonical key, so "Mr. Radio" equals "mr radio".
