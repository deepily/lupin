#!/usr/bin/env python3
"""
Heartbeat Hook: scoped loud-at-read for a hold that cannot defend anything.

Why this exists: a hold with an absent or unusable ttl_seconds is not fresh (heartbeat_hold.py, the ttl guard).
So it is not honored, and the session is poked despite having declared a hold.
Twenty-two sessions did this and were poked for four weeks with nothing said.
A loud write path alone catches none of them, because they hand-wrote their holds and never called `write_hold`.
An alarm wired to a path the failures do not take cannot fire.

Cardinality is why this is safe. The objection to a loud reader was spam on every legacy file.
That mixes up two readers.
    [the hook]    read_hold_resilient( session_id, cwd ) reads one file, its own.
    [the janitor] base.glob( HOLD_GLOB ) reads all files.
The hook never touches a legacy file. So there is one warning, to the one session whose hold is dead.
It arrives at the moment that session is poked because of it. The janitor stays silent and counts.
It is rate-limited to once per (session, hold-mtime): a rewritten hold that is still broken earns one more warning, never a stream.

State is ephemeral /tmp runtime state keyed by session-id prefix, like heartbeat_poke_cap.
`base_dir` is injectable so tests are hermetic and never touch the real /tmp.
"""
from pathlib import Path

from lupin_cli.claude_code.hooks.lib.heartbeat_hold import (
    HOLD_MTIME_ANNOTATION, ttl_is_usable,
)


WARN_STATE_DIR      = Path( "/tmp" )
WARN_STATE_TEMPLATE = "claude-hook-heartbeat-hold-ttl-warned-{suffix}"
NO_MTIME_SENTINEL   = "no-mtime"


def _warn_state_path( session_id, base_dir=None ):
    """
    Path to this session's "already warned about an unusable ttl" marker.

    Requires:
        - session_id is a string (may be empty)
        - base_dir is a path-like / string / None (None → /tmp)

    Ensures:
        - Returns Path = <base_dir>/claude-hook-heartbeat-hold-ttl-warned-<suffix>
        - suffix is session_id[:8], or "00000000" for an empty session_id
          (mirrors heartbeat_poke_cap._poke_count_path and uses its own filename
          namespace; the two must never share a file)
    """
    suffix = session_id[ :8 ] if session_id else "00000000"
    base   = Path( base_dir ) if base_dir is not None else WARN_STATE_DIR
    return base / WARN_STATE_TEMPLATE.format( suffix=suffix )


def _hold_version_key( hold ):
    """
    The rate-limit key: which version of this hold have we already warned about?

    Requires:
        - hold is a dict

    Ensures:
        - Returns the host-real mtime annotation as a string when the reader
          stamped one, so a rewritten but still broken hold is a new version and
          earns exactly one fresh warning
        - Returns NO_MTIME_SENTINEL when no mtime was stamped (a stat failure or
          hand-built dict), degrading to strict once-per-session, never to a stream
        - Never raises
    """
    mtime = hold.get( HOLD_MTIME_ANNOTATION )
    if isinstance( mtime, bool ) or not isinstance( mtime, ( int, float ) ):
        return NO_MTIME_SENTINEL
    return repr( float( mtime ) )


def should_warn_unusable_ttl( session_id, hold, base_dir=None ):
    """
    Should the hook emit one warning that this hold's ttl cannot defend the session?

    Requires:
        - session_id is a string
        - hold is the read_hold_resilient result (dict) or None
        - base_dir is a path-like / string / None (None → /tmp)

    Ensures:
        - Returns False when there is no hold. A session that never declared one
          is not being silently betrayed by it; it is simply pokeable, as designed
        - Returns False when the hold's ttl is usable (the overwhelmingly common
          case, so zero cost on the healthy path)
        - Returns True at most once per (session, hold-version), recording the
          version so the next Stop on the same broken hold is silent
        - A state-file read failure is treated as "not yet warned" (warn once).
          A state-file write failure still warns. The tradeoff is deliberate:
          an unwritable /tmp is itself pathological, and the alternative is
          restoring the four-week silence this closes. The output is one
          structured line in the hook's own event log, never a user-facing ding
        - Never raises
    """
    if not hold or ttl_is_usable( hold ):
        return False

    version = _hold_version_key( hold )
    path    = _warn_state_path( session_id, base_dir=base_dir )
    try:
        if path.exists() and path.read_text().strip() == version:
            return False                               # already warned for THIS version
    except OSError:
        pass                                           # unreadable marker → treat as un-warned

    try:
        path.write_text( version )
    except OSError:
        pass                                           # can't persist → warn anyway (see Ensures)
    return True


def clear_warn_state( session_id, base_dir=None ):
    """
    Forget that this session was warned (idempotent) — the test/reset seam.

    Requires:
        - session_id is a string

    Ensures:
        - Removes the marker file if present; no-op if absent
        - Never raises (OSError is swallowed)
    """
    try:
        _warn_state_path( session_id, base_dir=base_dir ).unlink( missing_ok=True )
    except OSError:
        pass


def quick_smoke_test():
    """
    Self-contained, side-effect-free smoke test (uses a temp dir).

    Ensures:
        - Returns True if the warn-once-per-version semantics hold; raises
          AssertionError otherwise.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        sid    = "warn1234"
        broken = { "session_id": sid, "reason": "r", HOLD_MTIME_ANNOTATION: 1000.0 }
        good   = { "session_id": sid, "reason": "r", "ttl_seconds": 900 }

        assert should_warn_unusable_ttl( sid, None, base_dir=tmp ) is False,  "no hold must not warn"
        assert should_warn_unusable_ttl( sid, good, base_dir=tmp ) is False,  "usable ttl must not warn"
        assert should_warn_unusable_ttl( sid, broken, base_dir=tmp ) is True, "broken ttl must warn once"
        assert should_warn_unusable_ttl( sid, broken, base_dir=tmp ) is False, "must not warn twice"

        # A REWRITTEN but still-broken hold (new mtime) → exactly one more warning.
        rewritten = dict( broken, **{ HOLD_MTIME_ANNOTATION: 2000.0 } )
        assert should_warn_unusable_ttl( sid, rewritten, base_dir=tmp ) is True,  "new version must warn"
        assert should_warn_unusable_ttl( sid, rewritten, base_dir=tmp ) is False, "same version must not repeat"

        clear_warn_state( sid, base_dir=tmp )
        assert should_warn_unusable_ttl( sid, rewritten, base_dir=tmp ) is True, "cleared state must re-warn"

    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"heartbeat_hold_warn smoke: {'PASS' if ok else 'FAIL'}" )
