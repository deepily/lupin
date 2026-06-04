#!/usr/bin/env python3
"""
Heartbeat Hook — per-session poke-cap counter.

The §0 decision #6 MANDATORY safety budget: a per-session count of how many
times the heartbeat has self-poked this session. **A SEPARATE budget from the
voice-driven `MAX_STOP_BLOCKS` counter** (`hook_common.py`) — the two caps
must never share a file or contaminate each other (María, 2026-06-04).

Mirrors the existing `hook_common` stop-counter pattern (file-backed, keyed
by the session_id prefix, never-raises on read/reset) but lives in its own
module and uses its own filename namespace.

Design authority (LOCKED): planning-is-prompting →
    src/rnd/2026.06.02-stop-hook-natural-heartbeat-poker.md §0 #6.

The counter file is ephemeral runtime state in /tmp (like the voice
stop-counter). `base_dir` is injectable for hermetic tests; production uses
the default /tmp.
"""
from pathlib import Path


DEFAULT_POKE_CAP = 3
COUNTER_DIR      = Path( "/tmp" )
COUNTER_TEMPLATE = "claude-hook-heartbeat-poke-count-{suffix}"


def _poke_count_path( session_id, base_dir=None ):
    """
    Path to this session's heartbeat poke-count file.

    Requires:
        - session_id is a string (may be empty)
        - base_dir is a path-like / string / None (None → /tmp)

    Ensures:
        - Returns Path = <base_dir>/claude-hook-heartbeat-poke-count-<suffix>
        - suffix is session_id[:8], or "00000000" for an empty session_id
    """
    suffix = session_id[ :8 ] if session_id else "00000000"
    base   = Path( base_dir ) if base_dir is not None else COUNTER_DIR
    return base / COUNTER_TEMPLATE.format( suffix=suffix )


def get_poke_count( session_id, base_dir=None ):
    """
    Read the current heartbeat poke count.

    Requires:
        - session_id is a string

    Ensures:
        - Returns the integer count, or 0 if the file is absent, unreadable,
          or non-integer
        - Never raises
    """
    try:
        path = _poke_count_path( session_id, base_dir=base_dir )
        if path.exists():
            return int( path.read_text().strip() )
    except ( ValueError, OSError ):
        pass
    return 0


def increment_poke_count( session_id, base_dir=None ):
    """
    Increment and persist the heartbeat poke count; return the new value.

    Requires:
        - session_id is a string

    Ensures:
        - Persists count+1 and returns it
        - Returns 1 on first call (file created)
        - Returns 0 on write failure (OSError) — never raises
    """
    try:
        count = get_poke_count( session_id, base_dir=base_dir ) + 1
        path  = _poke_count_path( session_id, base_dir=base_dir )
        path.write_text( str( count ) )
        return count
    except OSError:
        return 0


def reset_poke_count( session_id, base_dir=None ):
    """
    Reset the heartbeat poke count (delete the file). Idempotent.

    Requires:
        - session_id is a string

    Ensures:
        - Removes the counter file if present; no-op if absent
        - Never raises (OSError swallowed)
    """
    try:
        _poke_count_path( session_id, base_dir=base_dir ).unlink( missing_ok=True )
    except OSError:
        pass


def is_cap_reached( session_id, cap=DEFAULT_POKE_CAP, base_dir=None ):
    """
    Has this session reached/exceeded its heartbeat poke cap?

    Requires:
        - session_id is a string
        - cap is a positive int

    Ensures:
        - Returns True iff get_poke_count(session_id) >= cap
        - Never raises
    """
    return get_poke_count( session_id, base_dir=base_dir ) >= cap


def quick_smoke_test():
    """
    Self-contained, side-effect-free smoke test (uses a temp dir).

    Ensures:
        - Returns True if increment / cap / reset behave as designed;
          raises AssertionError otherwise.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        sid = "smoke123"
        assert get_poke_count( sid, base_dir=tmp ) == 0,        "fresh count should be 0"
        assert increment_poke_count( sid, base_dir=tmp ) == 1
        assert increment_poke_count( sid, base_dir=tmp ) == 2
        assert not is_cap_reached( sid, cap=3, base_dir=tmp ),  "2 < 3 should be under cap"
        assert increment_poke_count( sid, base_dir=tmp ) == 3
        assert is_cap_reached( sid, cap=3, base_dir=tmp ),      "3 >= 3 should hit cap"
        reset_poke_count( sid, base_dir=tmp )
        assert get_poke_count( sid, base_dir=tmp ) == 0,        "reset should zero the count"

    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"heartbeat_poke_cap smoke: {'PASS' if ok else 'FAIL'}" )
