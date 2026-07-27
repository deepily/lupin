"""
The ONE resolution point for the session-bridge directory — store row `8ccc20ab`.

🔴 WHY THIS MODULE EXISTS — measured, 2026-07-27.

`register_session.py` Phase 2 resolved its directory as a bare
`os.path.expanduser( "~/.claude/sessions" )` — **hardcoded, with no env
override, no injectable parameter, and no module constant a test could
patch.** A unit test drove the real `main()` with a fixture payload; Phase 2
wrote into the operator's LIVE bridge directory, keyed on a pid that
`_resolve_cc_pid()` read off the real process tree. Where that pid was a
running `claude`, the read-modify-write MERGED the fixture into that seat's
own bridge: a running worker's `session_id` rewritten to `abc-123`, its
`session_topic` dropped, `cwd` and `transcript_path` replaced by fixture
values. Three live seats at once, and it re-fired within two minutes of a
manual restore.

⇒ **A test could not reach a fake directory because there wasn't one to
reach.** The absence of a seam is not a neutral omission — it routes every
caller that forgets to redirect `$HOME` straight into production.

⚠️ AND THE VICTIM NEED NOT BE THE RUNNER. `session_bridge._find_session_file()`
falls back to globbing `cc-*.json`, sorting by mtime DESC, and returning the
first bridge whose stored `cwd` matches the caller's. A caller NOT nested under
its own `claude` process — a tmux wrapper, `nohup`, a detached script, CI —
therefore selects **the most recently active PEER seat sharing that cwd**. Every
instance observed on 2026-07-27 was self-inflicted; that is a property of where
those runners happened to be standing, not of the defect.

## THE SHAPE, AND WHY THIS ONE
`hook_common._logs_dir()` was given exactly this seam on 2026-07-07 (row
`6fc8d78d`) after test emissions polluted the real hook-log directory with
1,259 synthetic rows. That lesson was learned in one module and never carried
to this one — so this is the repo's own already-proven shape, not a novel one.

## 🔴 WHY THE VARIABLE IS `LUPIN_HOOK_SESSIONS_DIR` AND **NOT** `LUPIN_SESSIONS_DIR`
The obvious name is taken, and taking it would have made this file a REGRESSION
rather than a fix. Measured 2026-07-27:

    $ systemctl --user show tmux-server.service -p Environment
    Environment=… LUPIN_SESSIONS_DIR=/home/rruiz/.claude/sessions

`~/.config/systemd/user/tmux-server.service:36` pins `LUPIN_SESSIONS_DIR` to the
REAL directory for `~/.local/bin/reconcile-bridges.py` (an out-of-tree operator
tool, 2026-07-14). The tmux server inherits it, every `claude` inherits it from
the tmux server, and every pytest run inherits it from `claude`.

⇒ A resolver that PREFERS `LUPIN_SESSIONS_DIR` therefore resolves to the real
directory **no matter what `$HOME` says** — silently defeating `$HOME`
redirection, which is the isolation lever the existing tests actually use.
The first draft of this module did exactly that, and one pytest run of
`test_register_session_no_bridge_witness.py` immediately deposited a
fixture-valued `cc-1332865.json` into the operator's live bridge directory —
a bridge the pre-change code would NOT have written.

⇒ **The name is the fix.** `LUPIN_HOOK_SESSIONS_DIR` is unclaimed (verified
against the live environment, the systemd units, `~/.local/bin`, and the repo)
and is the same `LUPIN_HOOK_*` family as the proven `LUPIN_HOOK_LOG_DIR`, which
is correctly UNSET in production. `$HOME` redirection keeps working exactly as
it did before this module existed; the new variable is an ADDITIONAL, explicit,
greppable lever, never a hijack of an existing one.

⚠️ This module deliberately does NOT read `LUPIN_SESSIONS_DIR`. That variable
belongs to the out-of-tree reconciler; two authorities over one directory is
what produced the collision above, and honoring it here would re-create it.

## WHAT IS AND IS NOT SEAMED — do not overclaim either half
- **Call-time consumers** (`register_session`, `stop`, `session_end`,
  `subagent_governance`, `listener_processes`, `dm_inbox_reconcile`) call
  `sessions_dir()` directly. For those, setting `LUPIN_HOOK_SESSIONS_DIR` at ANY
  time — including from inside a running test — redirects the very next
  resolution.
- **Import-time constants** (`session_bridge.SESSION_DIR`,
  `hook_common.SESSION_DIR`, `cc_notification_listener.SESSION_DIR`,
  `idle_waiter._LOG_DIR`, `board_sweep.SWEEP_DIR`, `session_spawner.SESSION_DIR`)
  are now DERIVED from this function, so the env var governs any freshly-started
  process — which is what every hook, listener and spawner actually is. ⚠️ It does
  **not** govern an in-process test that sets the variable AFTER the module is
  imported; those modules keep their patchable module-level name for that case,
  and ~200 existing tests use it.

⚠️ `listener_processes` had NO constant left in place, deliberately. Its
import-time `SESSION_DIR` stayed pinned to the real directory after a test
redirected `$HOME`, so `_spawn_listener` kept depositing
`cc-listener-<id>.spawn-lock` and `.stderr` into the operator's live directory
— unseen, because the contact detector guarding that test globs `cc-*.json`
and those two files are not `.json`. A receipt narrower than its claim reads
true anyway. Those two lock paths now resolve at CALL time.

## PRODUCTION LEAVES IT UNSET
The default is byte-identical to what every one of those sites resolved before,
so the container's `~/.claude/sessions` bind-mount is unaffected.
"""

import os

from pathlib import Path


def sessions_dir():
    """
    Runtime-resolved session-bridge directory (row 8ccc20ab).

    Resolved at CALL time — NOT bound to an import-time constant — so an
    override is honored regardless of import order. Mirrors
    `hook_common._logs_dir()` deliberately; see this module's docstring.

    ⚠️ The variable is `LUPIN_HOOK_SESSIONS_DIR`, **not** `LUPIN_SESSIONS_DIR` —
    the latter is pinned to the REAL directory by `tmux-server.service` and
    inherited by every session in the fleet, so honoring it here would defeat
    `$HOME` redirection instead of adding a seam. See the module docstring.

    Requires:
        - (none)

    Ensures:
        - LUPIN_HOOK_SESSIONS_DIR set (non-empty) → Path( that )  (test/CI override)
        - else → Path( expanduser( "~/.claude/sessions" ) )   (production default,
          byte-identical to the pre-seam hardcoded value; `$HOME` is read at CALL
          time, so redirecting HOME keeps working exactly as it did before)
        - Never raises

    Returns:
        Path: the directory holding cc-*.json bridges and their siblings
    """
    override = os.environ.get( "LUPIN_HOOK_SESSIONS_DIR" )
    if override:
        return Path( override )
    return Path( os.path.expanduser( "~/.claude/sessions" ) )
