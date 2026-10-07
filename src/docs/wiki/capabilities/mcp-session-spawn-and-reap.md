---
capability: mcp-session-spawn-and-reap
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - lupin_mcp.session_spawner.spawn_sessions@a26fe8ca28
  - lupin_mcp.session_spawner.default_fleet_gate@7be2007211
  - lupin_mcp.session_spawner.dismiss_sessions@91d62ef199
  - lupin_mcp.session_spawner.list_spawned_sessions@47ba7c5ac6
  - lupin_mcp.reap_memento.seats_to_withhold@253ba85cda
  - lupin_mcp.self_respin_core.perform_self_respin@7b69144c56
---
# MCP session spawn and reap

A manager seat starts, lists and ends Claude Code seats through four MCP tools served by [[cosa-voice-mcp-server]]. The tools resolve identity and config, then call `session_spawner`.

## Spawn
- `spawn_sessions` refuses a count below 1, a count over the spawn cap (code default 8), or a fleet-cap breach; the tool returns `status: "error"`.
- `default_fleet_gate` allows a spawn when current total plus requested fits the fleet cap. If its census raises, the spawn is allowed.
- On a real spawn each child gets its own seat worktree. A falsy `project` puts the seat in the caller's cwd. Otherwise `project` resolves to a root: the caller's own tree for its own project, a sibling of the main checkout for any other. A missing provisioning script, a refused root or a provisioning failure leaves it in that resolved project root. An occupied slot skips to the next index. A dry run provisions nothing. An unresolvable `project` is refused, dry runs included.
- A child whose launch script exits non-zero is reported `failed`; the rest still launch, and only successes enter the manifest.
- Model is the `model` argument, else the INI per-role key, else the INI default key, else no `--model` flag.
- `seed_memento` is appended to the brief as text; the spawner never opens it. A truthy seed on a real spawn also arms a wake watch.

## Reap
- `dismiss_sessions` with no names reaps everything in this manager's manifest. Explicit names are not checked against the manifest.
- With `write_memento` on, the reap DMs seats whose memento is not yet verified and polls for one before killing anything. Seats whose bridge lacks a persona, session or cwd, or that have no bridge, are skipped. They are still killed and named in `memento_alarm`.
- Verified means the byte floor is met and the header parses. The header names that seat's session on its first 8 characters. `written_at` is aware, not in the future and in the window. A memento claiming work unmerged for a commit already in HEAD is `unproven_present`. That verdict comes only after the ask and poll time out. Mtime is ignored.
- `seats_to_withhold` keeps a seat alive on `prior_holder_present`, `unparseable_present` or `timeout_no_memento`. `unproven_present` is killed with a warning.
- A raising memento re-check disables the withhold. The MCP tool has no `force_kill` parameter.
- The branch probe reports unmerged commits but never withholds a kill. Read `memento_alarm` and `withhold_notice` first.
- Only reaped seats' non-terminal store rows are reconciled, except for personas named in `respin_personas`. A row is closed on a positive receipt. Otherwise it goes to its accountable manager, unless that manager is among the seats reaped in this batch, else to the reaping manager. A row that fits none is surfaced as unclassifiable. A seat with no resolvable bridge is not reconciled. If a withheld seat's persona was named in `respin_personas`, its slug lands in `retained_unmatched`.

## List and self re-spin
- `list_spawned_sessions` probes tmux for liveness and reads [[cc-session-bridge]] files for identity. Address a seat by persona only when `persona_state` is `allocated`.
- `self_respin` takes no session id; it resolves the seat from the bridge and refuses a guessed identity.
- It aborts unless the seat's own pressure reading is `over_budget`. It also aborts when a Last Call closes within 60 minutes; if that check cannot be read, it proceeds with a warning.
- It aborts unless the memento is at the seat's slot and carries this cycle's nonce line, fresh within the cycle window.
- A real "no" to its confirmation declines; an offline or timed-out ask counts as yes.
- It schedules the clear only after the observer marker and fire token read back.
- To replace a seat with a fresh session instead, use `dismiss_sessions` then `spawn_sessions` with `seed_memento`.
