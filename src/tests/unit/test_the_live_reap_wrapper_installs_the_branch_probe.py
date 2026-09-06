#!/usr/bin/env python3
"""
The MCP wrapper must actually INSTALL the branch probe — not merely have one available.

WHY THIS FILE IS SEPARATE FROM THE OTHER TWO.

    test_the_reap_names_the_branch_it_leaves_behind.py   the probe is CORRECT
    test_the_real_reap_path_names_unmerged_work.py       dismiss_sessions CALLS a probe
    THIS FILE                                            the LIVE wrapper passes the REAL one

The middle file injects its own fake probe, so it passes even if `cosa_voice_mcp` never
wires one — and `cosa_voice_mcp.dismiss_sessions` is the only production entrypoint. That
is CLAUDE.md § IMPLEMENTED BUT NOT INSTALLED precisely: delete one line in the wrapper and
both other files stay green while every real reap goes back to silently orphaning branches.

The load-bearing assertion is not "a probe was passed" but "the probe passed is
`reap_branch.probe_seat_branches`" — a wrapper that wired some OTHER callable, or a
`lambda: {}`, would satisfy the weaker claim while measuring nothing.
"""
import asyncio
import functools
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


def _patch( cv_mcp, monkeypatch, captured ):
    """Stub the wrapper's host-side collaborators; spy on what the inner reap receives."""
    import lupin_mcp.session_spawner as ss

    def _spy( manager_session_id, **kw ):
        captured.update( kw )
        return { "dismissed": [], "remaining": [], "manager_session_id": manager_session_id }

    monkeypatch.setattr( cv_mcp, "_wait_for_sender_id", lambda: "sender" )
    monkeypatch.setattr( cv_mcp, "_get_cc_metadata",   lambda: { "session_id": "abc12345" } )
    monkeypatch.setattr( cv_mcp, "_spawn_config_mgr",  lambda: None )
    monkeypatch.setattr( ss, "resolve_manager_identity",
                         lambda meta, fallback_session_id=None: ( "mgr-sid", "Clayton" ) )
    monkeypatch.setattr( ss, "resolve_spawn_config",
                         lambda mgr: { "spawn_cap": 8, "ack_timeout_seconds": 120,
                                       "write_memento_default": True,
                                       "reap_memento_window_seconds": 1200,
                                       "reap_memento_min_bytes": 1000,
                                       "reap_memento_ask_timeout_sec": 45,
                                       "reap_memento_poll_interval_sec": 3 } )
    monkeypatch.setattr( ss, "dismiss_sessions", _spy )


def test_the_wrapper_installs_the_REAL_branch_probe( cv_mcp, monkeypatch ):
    """Delete the wiring line in cosa_voice_mcp and this reddens. Nothing else does."""
    from lupin_mcp import reap_branch

    captured = {}
    _patch( cv_mcp, monkeypatch, captured )
    asyncio.run( cv_mcp.dismiss_sessions.run( { "session_names": [ "x" ] } ) )

    probe = captured.get( "branch_probe_fn" )
    assert probe is not None, "the live wrapper wired NO branch probe — reaps orphan silently"
    # Not merely "something was passed" — the RIGHT thing was passed.
    assert isinstance( probe, functools.partial )
    assert probe.func is reap_branch.probe_seat_branches


def test_the_installed_probe_is_callable_on_a_real_identity_map( cv_mcp, monkeypatch ):
    """
    The wrapper builds it with no target_branch, on purpose — the module default reads
    $CONTEXT_TICK_TARGET_BRANCH, the same variable the context tick uses, so there is ONE
    definition of the working line. This proves that partial is actually invocable rather
    than merely well-shaped.
    """
    captured = {}
    _patch( cv_mcp, monkeypatch, captured )
    asyncio.run( cv_mcp.dismiss_sessions.run( { "session_names": [ "x" ] } ) )

    out = captured[ "branch_probe_fn" ]( { "seat": { "cwd": None, "persona": "P" } } )
    assert out[ "seat" ][ "status" ] in ( "no_cwd", "sweep_unavailable" )


def test_the_memento_seams_are_still_installed_beside_it( cv_mcp, monkeypatch ):
    """
    CONTROL. The branch probe was added next to two existing seams; this proves the patch
    added a seam rather than displacing one. Without it, a wiring edit that dropped the
    memento coordinator would pass every assertion above.
    """
    captured = {}
    _patch( cv_mcp, monkeypatch, captured )
    asyncio.run( cv_mcp.dismiss_sessions.run( { "session_names": [ "x" ] } ) )

    assert captured.get( "memento_coord_fn" )   is not None
    assert captured.get( "memento_recheck_fn" ) is not None
    assert captured.get( "reconcile_items_fn" ) is not None
