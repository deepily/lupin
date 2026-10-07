---
capability: cc-session-bridge
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.sessions_dir.sessions_dir@40d97ca400
  - lupin_cli.claude_code.hooks.lib.session_bridge.atomic_write_json@304ee933db
  - lupin_cli.claude_code.hooks.lib.session_bridge.canonical_persona_key@1f4c521dcb
  - lupin_cli.claude_code.hooks.lib.session_bridge.find_session_path_by_id@2eb138d772
  - lupin_cli.claude_code.hooks.lib.session_bridge.find_active_sessions@f77c7d857b
  - lupin_cli.claude_code.hooks.lib.session_bridge.touch_bridge_mtime@6b55fa5d1b
---
# Claude Code session bridge

One JSON file per running Claude Code process, named `cc-<pid>.json`, carries the seat's session ids and voice persona. Hooks, the MCP server and fleet scanners mostly read and write it through `session_bridge.py`. Hook timing lives in [[cc-hooks-heartbeat]]; persona allocation in [[voice-persona-allocation]].

## Where the files live
- `sessions_dir()` returns `LUPIN_HOOK_SESSIONS_DIR` when it is set and non-empty, otherwise `~/.claude/sessions`. It reads the environment on every call.
- `session_bridge.SESSION_DIR` is that value captured once at import, so a changed variable reaches only a freshly started process. In-process tests patch the module name instead.
- Scanners glob `cc-*.json` and skip any name containing `buffer` or `listener`. The one exception is the working-directory step of `_find_session_file`, which does not skip them.

## Making a write safe
- Use `atomic_write_json( path, data )` for any bridge write. It writes a temp file in the target's directory, sets mode 0660, then `os.replace`s it over the target. A reader sees a whole old or whole new document.
- It returns `False` on `OSError`, `TypeError` or `ValueError`, prints the path and error to stderr, removes the temp file, and never raises. Check the return: a hook that ignores it fails silently apart from that stderr line.
- The setters (`set_voice_persona`, `set_user_id`, `set_owner_user_id` and the like) read the file, change one field and write through it. They return `False` when no live bridge matches the id.
- Two topic writers bypass `atomic_write_json`: the MCP `set_session_topic` and the notification listener's topic update both rewrite the file with a plain `open( "w" )` (bug row 767d7ad9).

## Canonical persona key
- `canonical_persona_key( name )` is the one key for matching `owner_persona` rows. It delegates to `lupin_mcp.persona_normalization`.
- It strips accents, lowercases, and turns every run of characters outside `a-z0-9` into one space, then trims the ends. "Mr. Radio", "mr_radio" and "mr-radio" all give `mr radio`.
- `None`, a non-string, or an empty string gives `""`. Applying it twice gives the same result as once.

## What counts as live
- Process id: a bridge whose filename pid fails `os.kill( pid, 0 )` is dead. Inside a container (`/.dockerenv` exists) most scanners skip that check, but `find_session_by_id` (unless `check_pid=False`) and the working-directory step of `_find_session_file` still apply it.
- `find_session_path_by_id` and `find_active_sessions` apply that pid check. Lookup matches a full id or the first 8 characters, and `exact=True` requires the full id.
- `touch_bridge_mtime()` bumps the mtime of one bridge and returns `False` instead of raising. It finds the file by parent pid, then grandparent pid, then a live bridge with the same working directory, which may belong to another seat.
- `find_active_sessions` drops a bridge older than `stale_threshold_seconds` (default 43200) unless its pid is proven alive. A pid-less name or a container run therefore relies on mtime alone.
- Aged-out bridges, kept or dropped, go into the `stale_out` list when one is passed. A live bridge it cannot parse, or that has no session id, goes into `unreadable_out`.

## When not to use it
- Do not resolve "my own id" by working directory. `get_claude_session_id_with_source()` returns the source with the id. `cwd_fallback` may name another seat that shares your directory; only `env`, `ppid` and `grandparent` are your own.
