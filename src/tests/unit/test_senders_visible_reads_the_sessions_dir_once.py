"""
SENDERS-VISIBLE READS THE SESSIONS DIRECTORY ONCE, AND OFF THE EVENT LOOP — row 41da77bb.

Measured 2026-09-10 on :7999: an unwindowed GET /api/notifications/senders-visible took
51.9 s for Rick's 5,180 senders, and /health waited 40 s behind it. Two causes, one arm each:

  · SLOW — every sender ran 2-3 full scans of ~/.claude/sessions (7,475 entries, 3.92 ms a
    scan). `_stamp_sender_personas` must scan once per request and still produce the
    records the per-sender helpers produced. The parity arm compares it to those helpers
    on the same fixture, and a literal pins one side so the parity is not a tautology.
  · FREEZES EVERYTHING — the blocking body ran inline in an `async def` on the server's
    only worker. The loop arm proves the event loop keeps ticking while the body runs.

Fixture: a real temp sessions directory read through the real `session_bridge` functions,
with `_can_trust_host_pids` pinned False (the container's case: bridge pids are host pids).
"""

import asyncio
import json
import time

import pytest

import cosa.rest.routers.notifications as N
import lupin_cli.claude_code.hooks.lib.session_bridge as sb


WORKER  = "11111111-aaaa-4aaa-8aaa-000000000001"
MANAGER = "22222222-bbbb-4bbb-8bbb-000000000002"
ROOT    = "33333333-cccc-4ccc-8ccc-000000000003"
HIDDEN  = "44444444-dddd-4ddd-8ddd-000000000004"   # only ever written into skipped files

WORKER_PERSONA  = { "name": "rio", "icon": "⚡", "color": "#111111", "voice_id": "v-rio" }
MANAGER_PERSONA = { "name": "mr radio", "icon": "🦉", "color": "#FFA000", "voice_id": "v-radio" }


def _sender( session_id ):
    return f"claude.code@lupin.deepily.ai#{session_id[ :8 ]}"


class _CountingDir:
    """SESSION_DIR stand-in that counts full-directory scans and delegates the rest."""

    def __init__( self, real ):
        self.real  = real
        self.globs = 0

    def exists( self ):
        return self.real.exists()

    def glob( self, pattern ):
        self.globs += 1
        return self.real.glob( pattern )


@pytest.fixture
def sessions( tmp_path, monkeypatch ):
    def write( name, payload ):
        ( tmp_path / name ).write_text( payload if isinstance( payload, str ) else json.dumps( payload ) )

    write( "cc-111.json", { "session_id": WORKER, "voice_persona": WORKER_PERSONA, "spawned_by": MANAGER } )
    write( "cc-222.json", { "session_id": MANAGER, "stable_session_id": MANAGER, "voice_persona": MANAGER_PERSONA } )
    write( "cc-333.json", { "session_id": ROOT } )
    write( "cc-listener-9.json", { "session_id": HIDDEN, "voice_persona": WORKER_PERSONA } )
    write( "cc-buffer-1.json", { "session_id": HIDDEN, "voice_persona": WORKER_PERSONA } )
    write( "cc-444.json", "{ not json" )

    counting = _CountingDir( tmp_path )
    monkeypatch.setattr( sb, "SESSION_DIR", counting )
    monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: False )
    return counting


def _activities( *session_ids ):
    return [ { "sender_id": _sender( sid ) if sid else sid } for sid in session_ids ]


# ---------------------------------------------------------------------------
# SLOW — one scan, same records
# ---------------------------------------------------------------------------

def test_the_indexed_stamp_matches_the_per_sender_helpers_on_every_kind_of_sender( sessions ):
    """
    🔴 THE PARITY ARM. Both sides read the same fixture through real code: the old
    per-sender helpers, and the new one-index stamp. A worker, its manager, a root seat
    with no persona, a sender whose only bridge is a skipped listener file, an unknown
    id, and ids with no session part at all.
    """
    kinds = [ WORKER, MANAGER, ROOT, HIDDEN, "deadbeef-0000-0000-0000-000000000000" ]
    activities = _activities( *kinds ) + [ { "sender_id": "no-hash-here" }, { "sender_id": None }, {} ]

    expected = [
        ( N._voice_persona_for_sender_id( a.get( "sender_id" ) ), N._manager_persona_for_sender_id( a.get( "sender_id" ) ) )
        for a in activities
    ]
    N._stamp_sender_personas( activities )
    actual = [ ( a[ "voice_persona" ], a[ "manager_persona" ] ) for a in activities ]

    assert actual == expected


def test_the_worker_gets_its_own_persona_and_its_managers_badge( sessions ):
    """
    The literal under the parity arm. Without it, parity would also hold if BOTH paths
    returned None for everyone — a fixture the old helpers could not read would pass.
    """
    activities = _activities( WORKER, ROOT, HIDDEN )
    N._stamp_sender_personas( activities )
    worker, root, hidden = activities

    assert worker[ "voice_persona" ][ "name" ] == "rio"
    assert worker[ "voice_persona" ][ "icon" ] == "⚡"
    assert worker[ "manager_persona" ] == { "icon": "🦉", "color": "#FFA000", "name": "mr radio", "initial": "M" }
    assert root[ "voice_persona" ] is None and root[ "manager_persona" ] is None
    assert hidden[ "voice_persona" ] is None, "a listener/buffer file was read as a bridge"


def test_fifty_senders_cost_one_directory_scan( sessions ):
    """
    🔴 THE COST ARM, with its positive control first: the per-sender helpers over the
    same fifty senders must show the instrument can count — at least two scans each.
    """
    activities = _activities( *( [ WORKER ] * 50 ) )

    for a in activities:
        N._voice_persona_for_sender_id( a[ "sender_id" ] )
        N._manager_persona_for_sender_id( a[ "sender_id" ] )
    assert sessions.globs >= 100, f"control: the counter saw only {sessions.globs} scans for the old path"

    sessions.globs = 0
    N._stamp_sender_personas( activities )
    assert sessions.globs == 1, f"stamping 50 senders scanned the sessions directory {sessions.globs} times"


def test_an_empty_sender_list_scans_nothing( sessions ):
    N._stamp_sender_personas( [] )
    assert sessions.globs == 0


def test_without_the_bridge_helpers_every_persona_is_none( sessions, monkeypatch ):
    monkeypatch.setattr( N, "_build_live_bridge_index", None )
    activities = _activities( WORKER )
    N._stamp_sender_personas( activities )
    assert activities[ 0 ][ "voice_persona" ] is None
    assert activities[ 0 ][ "manager_persona" ] is None
    assert sessions.globs == 0


def test_without_the_badge_helper_the_voice_persona_still_resolves( sessions, monkeypatch ):
    monkeypatch.setattr( N, "_manager_badge_for", None )
    activities = _activities( WORKER )
    N._stamp_sender_personas( activities )
    assert activities[ 0 ][ "voice_persona" ][ "name" ] == "rio"
    assert activities[ 0 ][ "manager_persona" ] is None


def test_a_worker_whose_manager_has_no_bridge_gets_no_badge( sessions ):
    ( sessions.real / "cc-222.json" ).unlink()
    activities = _activities( WORKER )
    N._stamp_sender_personas( activities )
    assert activities[ 0 ][ "voice_persona" ][ "name" ] == "rio"
    assert activities[ 0 ][ "manager_persona" ] is None


def test_a_malformed_bridge_body_yields_no_badge_rather_than_raising( sessions, monkeypatch ):
    def boom( index, session_id, exact=False ):
        raise RuntimeError( "index lookup failed" )

    entry = ( sessions.real / "cc-111.json", { "spawned_by": MANAGER } )
    monkeypatch.setattr( N, "_find_in_bridge_index", boom )
    assert N._manager_persona_from_bridge( [], entry ) is None


def test_a_legacy_persona_gets_a_display_name_and_a_modern_one_is_left_alone():
    legacy = N._voice_persona_from_bridge( ( None, { "voice_persona": { "name": "mr radio" } } ) )
    modern = N._voice_persona_from_bridge( ( None, { "voice_persona": { "name": "rio", "display_name": "Rio!" } } ) )
    assert "display_name" in legacy
    assert modern[ "display_name" ] == "Rio!"


def test_a_legacy_persona_without_the_display_name_helper_is_returned_as_stored( monkeypatch ):
    monkeypatch.setattr( N, "_display_name_for", None )
    assert N._voice_persona_from_bridge( ( None, { "voice_persona": { "name": "rio" } } ) ) == { "name": "rio" }


# ---------------------------------------------------------------------------
# THE INDEX ITSELF — the match rule find_session_path_by_id has always used
# ---------------------------------------------------------------------------

def test_the_index_skips_listener_buffer_and_unreadable_files_in_glob_order( sessions ):
    index = sb.build_live_bridge_index()
    names = sorted( path.name for path, _data, _ids in index )
    assert names == [ "cc-111.json", "cc-222.json", "cc-333.json" ]


def test_the_index_is_empty_when_the_sessions_directory_is_missing( tmp_path, monkeypatch ):
    monkeypatch.setattr( sb, "SESSION_DIR", tmp_path / "absent" )
    assert sb.build_live_bridge_index() == []


def test_a_dead_pid_is_skipped_when_host_pids_can_be_trusted( sessions, monkeypatch ):
    monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: True )
    monkeypatch.setattr( sb, "_is_pid_alive", lambda pid: pid != 111 )
    names = sorted( path.name for path, _data, _ids in sb.build_live_bridge_index() )
    assert "cc-111.json" not in names
    assert "cc-222.json" in names


def test_matching_is_full_id_or_eight_character_prefix_unless_exact( sessions ):
    index = sb.build_live_bridge_index()
    assert sb.find_in_bridge_index( index, MANAGER )[ 0 ].name == "cc-222.json"
    assert sb.find_in_bridge_index( index, MANAGER[ :8 ] )[ 0 ].name == "cc-222.json"
    assert sb.find_in_bridge_index( index, MANAGER[ :8 ], exact=True ) is None
    assert sb.find_in_bridge_index( index, MANAGER, exact=True )[ 0 ].name == "cc-222.json"
    assert sb.find_in_bridge_index( index, "" ) is None
    assert sb.find_in_bridge_index( index, "99999999" ) is None


def test_find_session_path_by_id_still_stops_at_the_first_match( sessions ):
    """
    The delegated single lookup is lazy: it walks the generator only as far as its hit.
    A second bridge claiming the same id, sorted after the first, must never be returned.
    """
    ( sessions.real / "cc-999.json" ).write_text( json.dumps( { "session_id": WORKER } ) )
    first = next( path for path, _d, ids in sb.iter_live_bridges() if WORKER in ids )
    assert sb.find_session_path_by_id( WORKER ) == first
    assert sb.find_session_path_by_id( "" ) is None


# ---------------------------------------------------------------------------
# FREEZES EVERYTHING — the loop keeps ticking while the body runs
# ---------------------------------------------------------------------------

def test_the_event_loop_keeps_running_while_senders_visible_works( monkeypatch ):
    """
    🔴 THE LOOP ARM. The body is replaced by a 0.3 s blocking sleep. A ticker on the same
    loop must advance many times during it. Called inline, as before the fix, the sleep
    would hold the loop and the ticker would advance at most once or twice.
    """
    def slow_body( user_email, hours, include_hidden, exclude_own_jobs ):
        time.sleep( 0.3 )
        return [ { "sender_id": "x", "args": [ user_email, hours, include_hidden, exclude_own_jobs ] } ]

    monkeypatch.setattr( N, "_visible_senders_sync", slow_body )

    async def scenario():
        ticks = 0
        done  = False

        async def ticker():
            nonlocal ticks
            while not done:
                await asyncio.sleep( 0.01 )
                ticks += 1

        tick_task = asyncio.create_task( ticker() )
        await asyncio.sleep( 0 )
        result = await N.get_visible_senders( user_email="rick@example.com", hours=None, include_hidden=True, exclude_own_jobs=False )
        done = True
        await tick_task
        return result, ticks

    result, ticks = asyncio.run( scenario() )
    assert result == [ { "sender_id": "x", "args": [ "rick@example.com", None, True, False ] } ]
    assert ticks >= 10, f"the event loop advanced only {ticks} times during a 0.3 s body — it was blocked"


def test_the_sender_session_suffix_parses_every_shape():
    assert N._sender_session_suffix( "claude.code@lupin.deepily.ai#c7333045" ) == "c7333045"
    assert N._sender_session_suffix( "a#b#c" ) == "b#c"
    assert N._sender_session_suffix( "x#   " ) is None
    assert N._sender_session_suffix( "no-hash" ) is None
    assert N._sender_session_suffix( None ) is None
