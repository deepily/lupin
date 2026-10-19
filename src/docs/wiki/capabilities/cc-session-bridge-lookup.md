---
capability: cc-session-bridge-lookup
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.session_bridge.get_claude_session_id@39e9635908
  - lupin_cli.claude_code.hooks.lib.session_bridge.get_claude_session_id_with_source@f5070bc230
  - lupin_cli.claude_code.hooks.lib.session_bridge.wait_for_session_id@924c638322
  - lupin_cli.claude_code.hooks.lib.session_bridge.wait_for_session_id_with_source@ba5858585f
  - lupin_cli.claude_code.hooks.lib.session_bridge.clear_cached_session_id@970adedbe8
  - lupin_cli.claude_code.hooks.lib.session_bridge.resolve_stable_session_id@9b7baf6bd4
  - lupin_cli.claude_code.hooks.lib.session_bridge.get_session_metadata@3c6d242d49
  - lupin_cli.claude_code.hooks.lib.session_bridge.find_session_by_id@90b80fbd6d
  - lupin_cli.claude_code.hooks.lib.session_bridge.find_session_by_tmux@cf17b12fe1
  - lupin_cli.claude_code.hooks.lib.session_bridge.iter_live_bridges@2b9bd66694
  - lupin_cli.claude_code.hooks.lib.session_bridge.build_live_bridge_index@4a8bd7a59d
  - lupin_cli.claude_code.hooks.lib.session_bridge.find_in_bridge_index@41052aef07
  - lupin_cli.claude_code.hooks.lib.session_bridge.project_from_bridge_cwd@1e59bc3d38
  - lupin_cli.claude_code.hooks.lib.session_bridge.resolve_project_name@30b81e488c
  - lupin_cli.claude_code.hooks.lib.session_bridge.build_sender_id_for_cc@70417dc04d
---
# Claude Code session bridge lookups
How a hook or server finds its own session id, finds another seat's bridge, and names the project. Bridge file layout and safe writes are in [[cc-session-bridge]].
## What it does
- `get_claude_session_id()` tries the `CLAUDE_SESSION_ID` variable, then the bridge found by parent or grandparent pid, then a working-directory guess, then a generated id.
- `get_claude_session_id_with_source()` also returns where the id came from. Only a cwd guess is not cached, because it may name another seat.
- `wait_for_session_id()` polls for the bridge until a timeout, then returns the generated fallback. Its `_with_source` twin reports the source.
- `clear_cached_session_id()` drops the cache, for example after a context clear rewrote the bridge.
- `resolve_stable_session_id()` swaps a transient id for the bridge's `stable_session_id`, and returns the input when none is found. `get_session_metadata()` returns the whole bridge dict.
- `find_session_by_id()` matches a full id or an 8-character prefix; `exact=True` demands the full id. `check_pid=False` skips liveness and picks the newest file.
- `find_session_by_tmux()` matches the `tmux_session` field and skips dead pids.
- `iter_live_bridges()` yields each live bridge once; `build_live_bridge_index()` snapshots them and `find_in_bridge_index()` matches against that list.
- `project_from_bridge_cwd()` and `resolve_project_name()` take the project from the cwd stored at SessionStart, resolving worktrees to their owner repo.
- `build_sender_id_for_cc()` builds `claude.code@<project>.deepily.ai#<8 hex>` and returns `None` on any failure.
## Don't
- Do not call `find_session_by_id()` in a loop over many ids. Take one index and match against it.
- Do not use a prefix match for an irreversible self-aimed action such as a clear. Pass `exact=True`.
## Invariants
- Every function here returns a fallback value and never raises.
