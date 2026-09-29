#!/usr/bin/env python3
"""
Unit — per-device frame seq, last_seq resume, and ack trimming (row dc446601, part 2).

Mobile "live mode" needs a socket that can go away and come back without losing
frames. Part 1 gave each device ONE socket and a slot that identifies it across
reconnects; this is what the slot is FOR. Every frame to a slot-holding session
carries a monotonic `seq`, the server buffers them, the client reconnects with
`last_seq` and gets the backlog after it, and its `ack` trims what it has.

🔴 THE BUFFER IS KEYED ON THE SLOT, NOT THE SESSION, and that is the whole
design. A session id dies with its socket; the slot is what survives a reconnect,
so it is the only key a resume can be built on. It is also what makes the
supersede case correct — the successor inherits the buffer and the seq continues
instead of restarting, so a reconnecting client is never handed a second frame 1
carrying different contents.

🔴 AND `gap` IS THE PART THAT IS EASY TO GET SILENTLY WRONG. A partial replay
that does not announce itself is worse than no replay at all: the client believes
it is caught up and stops asking. So `gap` is true whenever the server cannot
PROVE continuity from `last_seq` — including the case where it holds no buffer at
all and `last_seq` is non-zero, which is what a server restart looks like from
the client's side. Reporting "nothing to replay, no gap" there would be a lie the
client has no way to detect.

Venue: :7999 (pure unit — WebSocketManager via __new__, no config, no server).
"""

import os
import sys
from collections import OrderedDict
from unittest.mock import AsyncMock, MagicMock

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.websocket_manager import WebSocketManager

DEFAULT_BUFFER_SIZE = 200
DEFAULT_MAX_SLOTS   = 64


def _manager( buffer_size=DEFAULT_BUFFER_SIZE, max_slots=DEFAULT_MAX_SLOTS ):
    mgr = WebSocketManager.__new__( WebSocketManager )
    mgr.active_connections      = {}
    mgr.session_to_user         = {}
    mgr.user_sessions           = {}
    mgr.user_to_email           = {}
    mgr.session_is_admin        = {}
    mgr.session_client_types    = {}
    mgr.cc_transcript_watchers  = {}
    mgr.session_device_slots    = {}
    mgr.session_timestamps      = {}
    mgr.session_subscriptions   = {}
    mgr.main_loop               = None
    mgr.single_session_per_user = False
    mgr.available_events        = { "job_state_transition", "notification_queue_update" }
    mgr.debug                   = False
    # An OrderedDict, because that is what __init__ builds and the LRU eviction
    # calls move_to_end/popitem on it. A plain dict here would not fail the
    # assertion under test — it would AttributeError from inside the emit path.
    mgr.device_frame_buffers    = OrderedDict()
    mgr.device_seq              = {}
    mgr.device_buffer_size      = buffer_size
    mgr.device_buffer_max_slots = max_slots
    return mgr


def _socket():
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


def _connect( mgr, session_id, user_id="u1", client_type="mobile", device_id="phone-A" ):
    ws = _socket()
    mgr.connect( ws, session_id, user_id, client_type=client_type, device_id=device_id )
    return ws


def _frames( ws ):
    """Every payload this socket was sent, in order."""
    return [ call.args[ 0 ] for call in ws.send_json.await_args_list ]


# ── Stamping ────────────────────────────────────────────────────────────────

class TestSeqStamping:

    @pytest.mark.asyncio
    async def test_frames_to_a_slot_holder_carry_a_monotonic_seq( self ):
        mgr = _manager()
        ws  = _connect( mgr, "s1" )
        for _ in range( 3 ):
            await mgr.emit_to_session( "s1", "job_state_transition", { "job_id": "j" } )
        assert [ f[ "seq" ] for f in _frames( ws ) ] == [ 1, 2, 3 ]

    @pytest.mark.asyncio
    async def test_a_session_with_no_slot_gets_no_seq( self ):
        # A web tab has nothing to resume, so stamping it would be a field that
        # means nothing and a buffer nobody drains.
        mgr = _manager()
        ws  = _connect( mgr, "wise penguin", client_type="web", device_id=None )
        await mgr.emit_to_session( "wise penguin", "job_state_transition", { "job_id": "j" } )
        assert "seq" not in _frames( ws )[ 0 ]

    @pytest.mark.asyncio
    async def test_seq_is_per_slot_not_global( self ):
        mgr = _manager()
        a = _connect( mgr, "s-a", device_id="phone-A" )
        b = _connect( mgr, "s-b", device_id="phone-B" )
        await mgr.emit_to_session( "s-a", "job_state_transition", { "n": 1 } )
        await mgr.emit_to_session( "s-b", "job_state_transition", { "n": 2 } )
        await mgr.emit_to_session( "s-a", "job_state_transition", { "n": 3 } )
        assert [ f[ "seq" ] for f in _frames( a ) ] == [ 1, 2 ]
        assert [ f[ "seq" ] for f in _frames( b ) ] == [ 1 ]

    @pytest.mark.asyncio
    async def test_emit_to_user_gives_each_slot_holder_ITS_OWN_seq( self ):
        # emit_to_user builds ONE message dict and sends it to every session. If
        # the seq were stamped onto that shared dict, two devices would receive
        # each other's numbers and the last writer would win — a bug that is
        # invisible with one device connected, which is how it would ship.
        mgr = _manager()
        a = _connect( mgr, "s-a", device_id="phone-A" )
        b = _connect( mgr, "s-b", device_id="phone-B" )
        await mgr.emit_to_session( "s-a", "job_state_transition", { "n": 0 } )
        await mgr.emit_to_user( "u1", "job_state_transition", { "n": 1 } )
        assert [ f[ "seq" ] for f in _frames( a ) ] == [ 1, 2 ]
        assert [ f[ "seq" ] for f in _frames( b ) ] == [ 1 ]

    @pytest.mark.asyncio
    async def test_the_buffered_frame_is_the_frame_the_client_saw( self ):
        # Buffer and wire must not diverge: a replay that differs from the
        # original is a resume that silently rewrites history.
        mgr = _manager()
        ws  = _connect( mgr, "s1" )
        await mgr.emit_to_session( "s1", "job_state_transition", { "job_id": "j7" } )
        sent = _frames( ws )[ 0 ]
        replayed, _gap = mgr.frames_since( ( "u1", "phone-A" ), 0 )
        assert replayed == [ sent ]


# ── Resume ──────────────────────────────────────────────────────────────────

class TestResume:

    @pytest.mark.asyncio
    async def test_frames_sent_while_the_socket_was_down_are_replayed( self ):
        mgr = _manager()
        _connect( mgr, "s1" )
        await mgr.emit_to_session( "s1", "job_state_transition", { "n": 1 } )
        mgr.disconnect( "s1" )
        # The device is gone, but the slot's buffer is not — that is the point.
        mgr.buffer_frame_for_slot( ( "u1", "phone-A" ), { "type": "job_state_transition", "n": 2 } )
        replayed, gap = mgr.frames_since( ( "u1", "phone-A" ), 1 )
        assert [ f[ "n" ] for f in replayed ] == [ 2 ]
        assert gap is False

    @pytest.mark.asyncio
    async def test_replay_is_in_order_and_only_after_last_seq( self ):
        mgr = _manager()
        _connect( mgr, "s1" )
        for n in range( 1, 6 ):
            await mgr.emit_to_session( "s1", "job_state_transition", { "n": n } )
        replayed, gap = mgr.frames_since( ( "u1", "phone-A" ), 2 )
        assert [ f[ "seq" ] for f in replayed ] == [ 3, 4, 5 ]
        assert gap is False

    @pytest.mark.asyncio
    async def test_a_client_already_current_gets_nothing_and_no_gap( self ):
        mgr = _manager()
        _connect( mgr, "s1" )
        await mgr.emit_to_session( "s1", "job_state_transition", { "n": 1 } )
        replayed, gap = mgr.frames_since( ( "u1", "phone-A" ), 1 )
        assert replayed == [] and gap is False

    @pytest.mark.asyncio
    async def test_a_fresh_client_replays_everything_held_without_a_gap( self ):
        mgr = _manager()
        _connect( mgr, "s1" )
        await mgr.emit_to_session( "s1", "job_state_transition", { "n": 1 } )
        replayed, gap = mgr.frames_since( ( "u1", "phone-A" ), 0 )
        assert len( replayed ) == 1 and gap is False

    @pytest.mark.asyncio
    async def test_evicted_frames_are_reported_as_a_GAP( self ):
        # THE CASE THAT MATTERS. The cap dropped frames the client never saw; a
        # replay that stayed quiet about it would leave the client believing it
        # was current.
        mgr = _manager( buffer_size=3 )
        _connect( mgr, "s1" )
        for n in range( 1, 6 ):
            await mgr.emit_to_session( "s1", "job_state_transition", { "n": n } )
        replayed, gap = mgr.frames_since( ( "u1", "phone-A" ), 1 )
        assert [ f[ "seq" ] for f in replayed ] == [ 3, 4, 5 ]
        assert gap is True, "frame 2 was evicted and the client must be told"

    def test_an_unknown_slot_with_a_nonzero_last_seq_is_a_GAP( self ):
        # What a server restart looks like from the client's side: it holds
        # last_seq=500 and the server holds nothing. "Nothing to replay, no gap"
        # would be a lie the client cannot detect.
        mgr = _manager()
        replayed, gap = mgr.frames_since( ( "u1", "phone-A" ), 500 )
        assert replayed == [] and gap is True

    def test_an_unknown_slot_with_last_seq_zero_is_NOT_a_gap( self ):
        # A fresh client has nothing to have missed. Without this the very first
        # connection of every device would report a gap and trigger a pointless
        # full refetch.
        mgr = _manager()
        replayed, gap = mgr.frames_since( ( "u1", "phone-A" ), 0 )
        assert replayed == [] and gap is False


# ── Ack ─────────────────────────────────────────────────────────────────────

class TestAck:

    @pytest.mark.asyncio
    async def test_ack_trims_everything_up_to_and_including_that_seq( self ):
        mgr = _manager()
        _connect( mgr, "s1" )
        for n in range( 1, 5 ):
            await mgr.emit_to_session( "s1", "job_state_transition", { "n": n } )
        mgr.ack_frames( "s1", 2 )
        replayed, gap = mgr.frames_since( ( "u1", "phone-A" ), 2 )
        assert [ f[ "seq" ] for f in replayed ] == [ 3, 4 ]
        assert gap is False

    @pytest.mark.asyncio
    async def test_acking_everything_leaves_a_later_resume_gapless( self ):
        # Trimming must not look like eviction: a client that acked up to 4 and
        # comes back at 4 is fully current, and reporting a gap would send it to
        # refetch everything it just confirmed.
        mgr = _manager()
        _connect( mgr, "s1" )
        for n in range( 1, 5 ):
            await mgr.emit_to_session( "s1", "job_state_transition", { "n": n } )
        mgr.ack_frames( "s1", 4 )
        replayed, gap = mgr.frames_since( ( "u1", "phone-A" ), 4 )
        assert replayed == [] and gap is False

    @pytest.mark.asyncio
    async def test_an_ack_beyond_the_newest_frame_is_harmless( self ):
        mgr = _manager()
        _connect( mgr, "s1" )
        await mgr.emit_to_session( "s1", "job_state_transition", { "n": 1 } )
        mgr.ack_frames( "s1", 9999 )
        replayed, gap = mgr.frames_since( ( "u1", "phone-A" ), 9999 )
        assert replayed == [] and gap is False

    @pytest.mark.asyncio
    async def test_an_ack_from_a_session_with_no_slot_is_a_no_op( self ):
        mgr = _manager()
        _connect( mgr, "wise penguin", client_type="web", device_id=None )
        mgr.ack_frames( "wise penguin", 5 )   # must not raise
        assert mgr.device_frame_buffers == {}

    @pytest.mark.asyncio
    async def test_an_ack_cannot_trim_another_devices_buffer( self ):
        mgr = _manager()
        _connect( mgr, "s-a", device_id="phone-A" )
        _connect( mgr, "s-b", device_id="phone-B" )
        await mgr.emit_to_session( "s-b", "job_state_transition", { "n": 1 } )
        mgr.ack_frames( "s-a", 99 )
        replayed, _gap = mgr.frames_since( ( "u1", "phone-B" ), 0 )
        assert len( replayed ) == 1


# ── The slot is what makes a resume possible ───────────────────────────────

class TestBufferOutlivesTheSocket:

    @pytest.mark.asyncio
    async def test_a_successor_inherits_the_buffer_and_the_seq_CONTINUES( self ):
        # The supersede case, and the reason the buffer is keyed on the slot. A
        # seq that restarted at 1 would hand the client a second frame 1 carrying
        # different contents, and its last_seq would silently mean two things.
        mgr = _manager()
        mgr.main_loop = MagicMock()
        mgr.main_loop.is_running.return_value = True
        _connect( mgr, "s-old" )
        await mgr.emit_to_session( "s-old", "job_state_transition", { "n": 1 } )
        new = _connect( mgr, "s-new" )
        await mgr.emit_to_session( "s-new", "job_state_transition", { "n": 2 } )
        assert [ f[ "seq" ] for f in _frames( new ) ] == [ 2 ]
        replayed, gap = mgr.frames_since( ( "u1", "phone-A" ), 0 )
        assert [ f[ "seq" ] for f in replayed ] == [ 1, 2 ]
        assert gap is False

    @pytest.mark.asyncio
    async def test_a_plain_disconnect_does_not_drop_the_buffer( self ):
        mgr = _manager()
        _connect( mgr, "s1" )
        await mgr.emit_to_session( "s1", "job_state_transition", { "n": 1 } )
        mgr.disconnect( "s1" )
        replayed, gap = mgr.frames_since( ( "u1", "phone-A" ), 0 )
        assert len( replayed ) == 1 and gap is False


# ── Bounding: the buffers outlive sessions, so they need their own ceiling ──

class TestBounding:

    @pytest.mark.asyncio
    async def test_a_slots_buffer_is_capped( self ):
        mgr = _manager( buffer_size=3 )
        _connect( mgr, "s1" )
        for n in range( 1, 11 ):
            await mgr.emit_to_session( "s1", "job_state_transition", { "n": n } )
        held, _gap = mgr.frames_since( ( "u1", "phone-A" ), 0 )
        assert [ f[ "seq" ] for f in held ] == [ 8, 9, 10 ]

    @pytest.mark.asyncio
    async def test_the_NUMBER_of_retained_slots_is_capped_too( self ):
        # Per-slot capping alone bounds nothing: the buffers deliberately survive
        # disconnect, so without this every device that ever connected keeps one
        # forever.
        mgr = _manager( buffer_size=5, max_slots=2 )
        for i in range( 4 ):
            sid = f"s{i}"
            _connect( mgr, sid, device_id=f"phone-{i}" )
            await mgr.emit_to_session( sid, "job_state_transition", { "n": i } )
            mgr.disconnect( sid )
        assert len( mgr.device_frame_buffers ) == 2

    @pytest.mark.asyncio
    async def test_the_LEAST_RECENTLY_USED_slot_is_the_one_evicted( self ):
        # Evicting the newest would make the cap actively harmful: the device most
        # likely to reconnect is the one whose backlog gets thrown away.
        mgr = _manager( buffer_size=5, max_slots=2 )
        for i in range( 2 ):
            _connect( mgr, f"s{i}", device_id=f"phone-{i}" )
            await mgr.emit_to_session( f"s{i}", "job_state_transition", { "n": i } )
        # Touch phone-0 so phone-1 becomes the least recently used.
        await mgr.emit_to_session( "s0", "job_state_transition", { "n": 99 } )
        _connect( mgr, "s2", device_id="phone-2" )
        await mgr.emit_to_session( "s2", "job_state_transition", { "n": 2 } )
        assert ( "u1", "phone-0" ) in mgr.device_frame_buffers
        assert ( "u1", "phone-2" ) in mgr.device_frame_buffers
        assert ( "u1", "phone-1" ) not in mgr.device_frame_buffers


# ── The endpoint seam ───────────────────────────────────────────────────────
#
# Everything above drives the manager. Every one of those cases stays green in a
# world where the endpoint never reads `last_seq`, never replays, and never
# handles `ack` — a component can be complete, correct, fully covered and never
# mounted. These enter through the real endpoint and the real receive loop.

class _StubMain:
    def __init__( self, manager ):
        self.websocket_manager = manager
        self.active_tasks      = {}
        self.app_debug         = False
        self.app_verbose       = False


class _ScriptedSocket:
    """Authenticates with the given auth_request, then yields `frames`, then drops."""

    def __init__( self, auth_message, frames=() ):
        self._auth   = auth_message
        self._frames = list( frames )
        self.sent    = []

    async def accept( self ): pass
    async def close( self, *a, **k ): pass
    async def send_json( self, payload ): self.sent.append( payload )
    async def receive_json( self ): return self._auth

    async def receive_text( self ):
        from fastapi import WebSocketDisconnect
        if not self._frames:
            raise WebSocketDisconnect()
        return self._frames.pop( 0 )


async def _drive( monkeypatch, mgr, session_id, auth_message, frames=() ):
    from unittest.mock import AsyncMock, Mock

    from cosa.rest.routers.websocket import websocket_queue_endpoint

    main_stub         = _StubMain( mgr )
    package_stub      = Mock()
    package_stub.main = main_stub
    monkeypatch.setitem( sys.modules, "lupin_app", package_stub )
    monkeypatch.setitem( sys.modules, "lupin_app.main", main_stub )
    monkeypatch.setattr( "cosa.rest.auth.verify_token",
                         AsyncMock( return_value={ "uid": "u1", "email": "a@b.c" } ) )
    socket = _ScriptedSocket( auth_message, frames )
    await websocket_queue_endpoint( websocket=socket, session_id=session_id )
    return socket


_MOBILE_AUTH = { "type": "auth_request", "token": "good",
                 "client_type": "mobile", "device_id": "phone-A" }


class TestTheEndpointResumes:

    @pytest.mark.asyncio
    async def test_the_endpoint_replays_the_backlog_and_marks_where_it_ends( self, monkeypatch ):
        mgr = _manager()
        for n in ( 1, 2, 3 ):
            mgr.buffer_frame_for_slot( ( "u1", "phone-A" ), { "type": "job_state_transition", "n": n } )

        socket = await _drive( monkeypatch, mgr, "s-resume", { **_MOBILE_AUTH, "last_seq": 1 } )

        replayed = [ f for f in socket.sent if f.get( "type" ) == "job_state_transition" ]
        assert [ f[ "seq" ] for f in replayed ] == [ 2, 3 ], (
            "the endpoint never replayed — every manager-level case above stays "
            "green in exactly that world"
        )
        marker = [ f for f in socket.sent if f.get( "type" ) == "resume_complete" ]
        assert len( marker ) == 1
        assert marker[ 0 ][ "replayed" ] == 2 and marker[ 0 ][ "gap" ] is False

    @pytest.mark.asyncio
    async def test_the_endpoint_reports_a_gap_the_client_can_act_on( self, monkeypatch ):
        mgr = _manager()
        socket = await _drive( monkeypatch, mgr, "s-gap", { **_MOBILE_AUTH, "last_seq": 500 } )
        marker = [ f for f in socket.sent if f.get( "type" ) == "resume_complete" ][ 0 ]
        assert marker[ "gap" ] is True and marker[ "replayed" ] == 0

    @pytest.mark.asyncio
    async def test_a_web_client_gets_no_resume_marker_at_all( self, monkeypatch ):
        # It holds no slot, so there is nothing to resume and no marker to confuse it.
        mgr = _manager()
        socket = await _drive( monkeypatch, mgr, "wise penguin",
                               { "type": "auth_request", "token": "good" } )
        assert not [ f for f in socket.sent if f.get( "type" ) == "resume_complete" ]

    @pytest.mark.asyncio
    async def test_a_junk_last_seq_is_treated_as_absent_not_trusted( self, monkeypatch ):
        # last_seq arrives over the wire. A string would raise inside frames_since
        # and take the auth path down with it; True is an int in Python and would
        # silently mean seq 1.
        for junk in ( "500", None, -1, True, 3.5 ):
            mgr = _manager()
            socket = await _drive( monkeypatch, mgr, "s-junk", { **_MOBILE_AUTH, "last_seq": junk } )
            marker = [ f for f in socket.sent if f.get( "type" ) == "resume_complete" ][ 0 ]
            assert marker[ "gap" ] is False, f"{junk!r} was trusted as a resume point"

    @pytest.mark.asyncio
    async def test_the_ack_verb_reaches_the_manager_through_the_receive_loop( self, monkeypatch ):
        import json as json_module
        mgr = _manager()
        for n in ( 1, 2, 3 ):
            mgr.buffer_frame_for_slot( ( "u1", "phone-A" ), { "type": "job_state_transition", "n": n } )

        await _drive( monkeypatch, mgr, "s-ack", { **_MOBILE_AUTH, "last_seq": 3 },
                      frames=[ json_module.dumps( { "type": "ack", "seq": 2 } ) ] )

        held, _gap = mgr.frames_since( ( "u1", "phone-A" ), 0 )
        assert [ f[ "seq" ] for f in held ] == [ 3 ], "the ack verb never reached ack_frames"

    @pytest.mark.asyncio
    async def test_a_junk_ack_seq_is_ignored_rather_than_raising( self, monkeypatch ):
        import json as json_module
        mgr = _manager()
        for n in ( 1, 2 ):
            mgr.buffer_frame_for_slot( ( "u1", "phone-A" ), { "type": "job_state_transition", "n": n } )

        await _drive( monkeypatch, mgr, "s-ack2", { **_MOBILE_AUTH, "last_seq": 2 },
                      frames=[ json_module.dumps( { "type": "ack", "seq": "2" } ),
                               json_module.dumps( { "type": "ack" } ) ] )

        held, _gap = mgr.frames_since( ( "u1", "phone-A" ), 0 )
        assert len( held ) == 2, "a junk ack trimmed the buffer"


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
