#!/usr/bin/env python3
"""
Listener process discovery + exclusive-flock primitives for the CC hook family.

Shared by:
    - register_session.py (F1 singleton spawn guard)
    - session_end.py      (F2 reap-all-matching listeners)
    - cc_notification_listener.py (F4 tmux injection mutex)

Root cause served: the documented `--continue` SessionStart double-fire spawned
TWO cc_notification_listener processes for one session; the bridge remembered
only the last PID, so SessionEnd orphaned one, and the duplicates raced each
other's two-step tmux injections (text, text, Enter, Enter) — silently
corrupting USER BROADCAST delivery.

See: src/rnd/v0.1.8/2026.06.10-broadcast-miss-duplicate-listener-root-cause.md
     src/rnd/v0.1.8/2026.06.11-broadcast-miss-f1-f4-implementation.md
"""

import fcntl
import os
import re
import subprocess
from contextlib import contextmanager
from pathlib import Path

from lupin_cli.claude_code.hooks.lib.sessions_dir import sessions_dir

# Row 8ccc20ab — the lock paths below resolve through `sessions_dir()` at CALL
# time, NOT through an import-time constant. That distinction is the row: a
# constant frozen at import keeps pointing at the real bridge directory even
# after a test redirects the seam, so `_spawn_listener` deposited
# `cc-listener-abc-123.spawn-lock` + `.stderr` into the operator's live directory
# while the contact detector (which globs `cc-*.json` only) reported no contact.
# There is deliberately no SESSION_DIR constant here any more — a patchable name
# nobody remembers to patch is what produced that.
LISTENER_MODULE_NAME = "cc_notification_listener"


def find_live_listener_pids( session_hash ):
    """
    Find every live CC notification listener serving the given session hash.

    Matches process command lines via `pgrep -f` against the pattern
    `cc_notification_listener.*--session-id <hash>` — ground truth for
    "a listener for this session exists", independent of what any bridge
    file remembers.

    Requires:
        - session_hash is a non-empty string (8-char session hash)

    Ensures:
        - Returns a sorted list of ints (PIDs), possibly empty
        - Excludes the calling process's own PID
        - Returns [] when pgrep is unavailable, times out, errors,
          or finds no match
        - Never raises exceptions

    Args:
        session_hash: 8-char CC session hash the listener was started with

    Returns:
        list[int]: sorted live listener PIDs, [] if none
    """
    if not session_hash:
        return [ ]

    try:
        result = subprocess.run(
            [ "pgrep", "-f", f"{LISTENER_MODULE_NAME}.*--session-id {session_hash}" ],
            capture_output=True, text=True, timeout=2
        )
    except ( subprocess.TimeoutExpired, FileNotFoundError, OSError ):
        return [ ]

    if result.returncode != 0:
        return [ ]

    pids = [ ]
    for token in result.stdout.split():
        try:
            pid = int( token )
        except ValueError:
            continue
        if pid != os.getpid():
            pids.append( pid )

    return sorted( pids )


@contextmanager
def exclusive_flock( lock_path ):
    """
    Hold an exclusive (blocking) flock on lock_path for the with-block.

    Fail-open by design: if the lock file cannot be created or locked, the
    block still runs — listener spawn and tmux injection must never be
    blocked by lock infrastructure (the hook layer's never-raise contract).
    Callers can inspect the yielded bool when lock-held matters.

    Requires:
        - lock_path is a string or Path naming a writable location

    Ensures:
        - Yields True when the exclusive lock is held, False on fail-open
        - Creates parent directories as needed
        - Releases the lock and closes the file on exit (best-effort)
        - Never raises exceptions from lock acquisition or release

    Args:
        lock_path: filesystem path of the lock file
    """
    lock_file = None
    try:
        os.makedirs( os.path.dirname( str( lock_path ) ), exist_ok=True )
        lock_file = open( lock_path, "w" )
        fcntl.flock( lock_file.fileno(), fcntl.LOCK_EX )
    except OSError:
        if lock_file is not None:
            try:
                lock_file.close()
            except OSError:   # pragma: no cover - close on an already-failed fd cannot be forced deterministically
                pass
            lock_file = None

    try:
        yield lock_file is not None
    finally:
        if lock_file is not None:
            try:
                fcntl.flock( lock_file.fileno(), fcntl.LOCK_UN )
                lock_file.close()
            except OSError:   # pragma: no cover - flock(LOCK_UN) + close on a descriptor this function itself opened and holds; OSError has no reachable cause here
                pass


def listener_spawn_lock( session_hash ):
    """
    Per-session-hash spawn lock — serializes the F1 check-then-spawn critical
    section across concurrent SessionStart hooks (the `--continue` double-fire).

    Requires:
        - session_hash is a non-empty string

    Ensures:
        - Returns the exclusive_flock context manager for
          sessions_dir()/cc-listener-{session_hash}.spawn-lock

    Args:
        session_hash: 8-char CC session hash

    Returns:
        context manager yielding bool (lock held)
    """
    return exclusive_flock( sessions_dir() / f"cc-listener-{session_hash}.spawn-lock" )


def tmux_injection_lock( tmux_session ):
    """
    Per-tmux-session injection mutex — keeps the two-step send-keys sequence
    (literal text, then Enter) atomic against any other lock-honoring injector,
    so concurrent injections cannot interleave keystrokes in one pane (F4).

    Requires:
        - tmux_session is a non-empty string (tmux session name)

    Ensures:
        - Returns the exclusive_flock context manager for
          sessions_dir()/tmux-inject-{sanitized}.lock
        - Sanitizes the session name to filename-safe characters

    Args:
        tmux_session: tmux session name

    Returns:
        context manager yielding bool (lock held)
    """
    sanitized = re.sub( r"[^A-Za-z0-9._-]", "_", tmux_session )
    return exclusive_flock( sessions_dir() / f"tmux-inject-{sanitized}.lock" )
