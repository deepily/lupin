#!/usr/bin/env python3
"""
The live reap wrapper gives the seat teardown the path first and the seat name second.

Store id 74c1bf37-a3b3-4c3a-90db-5a5f05dcd084. `session_spawner.dismiss_sessions` calls
`seat_teardown_fn( session_name, cwd )`. `seat_teardown.retire_seat_worktree` takes
`( path, seat_name )`. The wrapper in `cosa_voice_mcp` passed it in unchanged. The session
name landed in `path`, no such directory exists, and every reaped seat's tree was kept as
`no_tree` with no notice.

Why nothing caught it: the end-to-end teardown test wraps the function in
`lambda n, c: retire( c, n )`. That swaps the arguments back, so the real wiring was never
under test. These tests take the callable the live wrapper installs and call it the way the
spawner does.

Seams driven for real: the `cosa_voice_mcp.dismiss_sessions` wrapper and, in the second test,
the real `retire_seat_worktree`. Faked: the inner reap, which only records what it receives.
"""
import asyncio
import importlib
import os
import sys

import pytest

_src = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src not in sys.path:
    sys.path.insert( 0, _src )


@pytest.fixture( scope="module" )
def cv_mcp():
    return importlib.import_module( "lupin_mcp.cosa_voice_mcp" )


def _installed_teardown( cv_mcp, monkeypatch ):
    """
    Run the live wrapper against a recording inner reap.

    Ensures:
        - returns the `seat_teardown_fn` the wrapper passed to the inner reap
    """
    import lupin_mcp.session_spawner as ss
    captured = {}

    def spy( manager_session_id, **kw ):
        captured.update( kw )
        return { "dismissed": [], "remaining": [], "manager_session_id": manager_session_id }

    monkeypatch.setattr( cv_mcp, "_wait_for_sender_id", lambda: "sender" )
    monkeypatch.setattr( cv_mcp, "_get_cc_metadata",   lambda: { "session_id": "abc12345" } )
    monkeypatch.setattr( cv_mcp, "_spawn_config_mgr",  lambda: None )
    monkeypatch.setattr( ss, "resolve_manager_identity", lambda meta, fallback_session_id=None: ( "mgr-sid", "Clayton" ) )
    monkeypatch.setattr( ss, "resolve_spawn_config",
                         lambda mgr: { "spawn_cap": 8, "ack_timeout_seconds": 120, "write_memento_default": True,
                                       "reap_memento_window_seconds": 1200, "reap_memento_min_bytes": 1000,
                                       "reap_memento_ask_timeout_sec": 45, "reap_memento_poll_interval_sec": 3 } )
    monkeypatch.setattr( ss, "dismiss_sessions", spy )
    asyncio.run( cv_mcp.dismiss_sessions.run( { "session_names": [ "x" ] } ) )
    return captured.get( "seat_teardown_fn" )


def test_the_installed_teardown_passes_the_cwd_as_the_path_and_the_name_as_the_seat( cv_mcp, monkeypatch ):
    from cosa.agents.shared import seat_teardown
    seen = []

    def recorder( path, seat_name=None, **kw ):
        seen.append( ( path, seat_name ) )
        return { "removed": False }

    monkeypatch.setattr( seat_teardown, "retire_seat_worktree", recorder )
    teardown = _installed_teardown( cv_mcp, monkeypatch )
    assert teardown is not None, "the live wrapper installed no seat teardown"

    teardown( "cc-author-rio-1", "/repo/.claude/worktrees/seat-cc-author-rio-1" )   # the order session_spawner calls it in

    assert seen == [ ( "/repo/.claude/worktrees/seat-cc-author-rio-1", "cc-author-rio-1" ) ]


def test_the_installed_teardown_names_the_seat_in_the_real_outcome( cv_mcp, monkeypatch ):
    teardown = _installed_teardown( cv_mcp, monkeypatch )

    outcome = teardown( "cc-author-rio-1", None )         # a seat whose cwd was never recorded

    assert outcome[ "seat" ] == "cc-author-rio-1"
    assert outcome[ "path" ] is None
    assert outcome[ "removed" ] is False
