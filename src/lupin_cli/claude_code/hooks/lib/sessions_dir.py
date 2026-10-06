"""
The single resolution point for the session-bridge directory.

Why it exists: `register_session.py` once resolved its directory as a bare
`os.path.expanduser( "~/.claude/sessions" )`, with no env override and nothing a test could
patch. A unit test driving the real `main()` with a fixture payload therefore wrote into the
operator's live bridge directory. Where the pid it read was a running `claude`, the fixture
was merged into that seat's bridge: `session_id` rewritten, `session_topic` dropped, `cwd`
and `transcript_path` replaced. Any caller that forgot to redirect `$HOME` hit production.

The victim need not be the runner. `session_bridge._find_session_file()` falls back to
globbing `cc-*.json`, sorting by mtime descending, and taking the first bridge whose `cwd`
matches. A caller outside its own `claude` process (tmux wrapper, `nohup`, detached script,
CI) therefore selects the most recently active peer seat sharing that cwd.

The shape copies `hook_common._logs_dir()`, which got the same seam after test emissions
polluted the real hook-log directory with synthetic rows.

The variable is `LUPIN_HOOK_SESSIONS_DIR`, not `LUPIN_SESSIONS_DIR`. `tmux-server.service`
pins the latter to the real directory for the out-of-tree tool `reconcile-bridges.py`, and
the tmux server, every `claude` and every pytest run inherit it. A resolver preferring it
would ignore `$HOME` and silently defeat the lever existing tests use. The first draft did
that and a pytest run deposited a fixture-valued bridge into the live directory. The new name
is unclaimed and in the `LUPIN_HOOK_*` family of `LUPIN_HOOK_LOG_DIR`, unset in production.
This module does not read `LUPIN_SESSIONS_DIR`: two authorities over one directory caused it.

Call-time consumers (`register_session`, `stop`, `session_end`, `subagent_governance`,
`listener_processes`, `dm_inbox_reconcile`) call `sessions_dir()` directly, so the variable
redirects their next resolution at any time. Import-time constants (`session_bridge.SESSION_DIR`,
`hook_common.SESSION_DIR`, `cc_notification_listener.SESSION_DIR`, `idle_waiter._LOG_DIR`,
`board_sweep.SWEEP_DIR`, `session_spawner.SESSION_DIR`) derive from it. So it governs any
freshly started process. It does not govern an in-process test that sets it after import.
Those modules keep a patchable module-level name for that case. The `listener_processes` lock and stderr
paths resolve at call time. A pinned constant let `_spawn_listener` write `.spawn-lock`
and `.stderr` files into the live directory, unseen by a detector globbing only `cc-*.json`. Production leaves the variable unset; the default is byte-identical to the
old value, so the container's `~/.claude/sessions` bind-mount is unaffected.
"""

import os

from pathlib import Path


def sessions_dir():
    """
    Return the session-bridge directory, resolved at call time from the environment.

    Resolving at call time means an override is honored whatever the import order, as in
    `hook_common._logs_dir()`. The variable is `LUPIN_HOOK_SESSIONS_DIR`, not
    `LUPIN_SESSIONS_DIR`, which `tmux-server.service` pins to the real directory.

    Requires:
        - (none)

    Ensures:
        - `LUPIN_HOOK_SESSIONS_DIR` set and non-empty returns Path( that ), the test and CI override
        - otherwise returns Path( expanduser( "~/.claude/sessions" ) ), the production default,
          byte-identical to the old hardcoded value, with `$HOME` read at call time so
          redirecting it keeps working as before
        - Never raises

    Returns:
        Path: the directory holding cc-*.json bridges and their siblings
    """
    override = os.environ.get( "LUPIN_HOOK_SESSIONS_DIR" )
    if override:
        return Path( override )
    return Path( os.path.expanduser( "~/.claude/sessions" ) )
