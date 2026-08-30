#!/usr/bin/env python3
"""
Adversarial control for perform_self_respin's FIRE-TOKEN read-back guard
(self_respin_core.py, row 9e0678f6; Krishna nit 2).

The guard exists because a silent fire-token write failure would let the verb
report "scheduled" while the detached `/clear` self-cancels at the fire point
(`rm` fails → no send-keys). This control proves the guard actually GATES: when
the fire token does not survive read-back, the verb (a) schedules NOTHING and
(b) removes the observer marker it just wrote, so no DEAD alarm fires for a clear
that never scheduled.

Complements Tiffany's happy-path core coverage — this is the failure branch
(the uncovered 332-333) proven by execution against real temp files.

Venue: :7999-eligible / local — tmp files + injected seams, no server, no clear.
"""
import datetime
import json
import os
import sys

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_mcp.self_respin_core import perform_self_respin, build_nonce_line
from cosa.agents.heartbeat_arbiter.self_respin_observer import MARKER_PREFIX


# A memento body over MIN_MEMENTO_SUBSTANCE_BYTES (row 4cf9f9fd). The nonce-only
# husk a truncating stamp leaves is now REJECTED, so a stub memento in a test about
# something else has to look like a real one.
_REAL_BODY = ( "board state: row 4cf9f9fd, manager mr radio, venue :8000 idle, "
               "next act is the containment probe.\n" ) * 5

UTC     = datetime.timezone.utc
NOW     = datetime.datetime( 2026, 8, 14, 2, 0, 0, tzinfo=UTC )
from tests.helpers.memento_slot_seed import seed_root_slot


SESSION = "9662b5ac"
NONCE   = "11111111-2222-3333-4444-555555555555"


def test_fire_token_readback_failure_aborts_and_removes_marker( tmp_path ):
    """Token read-back fails → aborted, nothing scheduled, marker cleaned up."""
    base    = str( tmp_path )
    # A REAL slot, not a convenient path (row 8068c65e). This test is about the
    # fire-token read-back, so its memento must clear the placement + reap gates on
    # the way there — the same way a live seat's does.
    memento = seed_root_slot( tmp_path, "maria", SESSION, nonce_uuid=NONCE, nonce_ts=NOW, written_at=NOW )

    scheduled = []

    def schedule_fn( argv ):
        scheduled.append( argv )

    def write_json_fn( path, data ):
        with open( path, "w" ) as f:
            json.dump( data, f )

    def read_text_fn( path ):
        # Force ONLY the fire-token read-back to fail; memento + marker read normally.
        # str() because the slot check resolves a pointer's `current:` to a Path — the
        # live seam (_default_read_text) already accepts both.
        path = str( path )
        if path.endswith( ".token" ):
            return None
        return open( path ).read() if os.path.exists( path ) else None

    result = perform_self_respin(
        SESSION,
        persona          = "maria",
        memento_path     = memento,
        memento_nonce    = NONCE,
        pre_clear_status = "over_budget",
        pre_clear_pct    = 61.0,
        now              = NOW,
        base_dir         = base,
        repo_root        = base,
        resolve_tmux_fn  = lambda _s: "cc-author-maria-1",
        ask_fn           = lambda: "yes",
        schedule_fn      = schedule_fn,
        read_text_fn     = read_text_fn,
        write_json_fn    = write_json_fn,
    )


    assert result.status == "aborted"
    assert "fire token" in result.reason
    assert scheduled == []                                        # the /clear was NOT scheduled

    marker_path = os.path.join( base, f"{MARKER_PREFIX}{SESSION}.json" )
    assert not os.path.exists( marker_path )                      # marker removed → no false DEAD alarm


if __name__ == "__main__":
    import pytest
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
