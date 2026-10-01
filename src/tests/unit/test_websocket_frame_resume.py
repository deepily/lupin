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
    mgr.resuming_sessions       = set()
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
    mgr.device_buffers_over_cap = False
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

class TestMariasResumeFindings:
    """
    María's review of part 2, 2026-09-29. F1: resume_complete.seq must be the server's
    CURRENT seq, or a client whose numbering restarted underneath it discards every new
    frame as already seen. F2: a live frame must never overtake the replay.
    """

    @staticmethod
    def _recorder():
        sent = []
        async def send( frame ): sent.append( frame )
        return sent, send

    @pytest.mark.asyncio
    async def test_f1_after_a_restart_the_client_is_told_the_servers_seq_not_its_own( self ):
        mgr = _manager()                                    # a fresh process: nothing held
        ws  = _connect( mgr, "s1" )
        assert mgr.begin_resume( "s1" ) is True
        sent, send = self._recorder()
        complete = await mgr.replay_and_resume( "s1", 500, send )
        assert sent == [ complete ]
        assert ( complete[ "seq" ], complete[ "gap" ], complete[ "replayed" ] ) == ( 0, True, 0 )
        await mgr.emit_to_session( "s1", "job_state_transition", { "n": 1 } )
        assert [ f[ "seq" ] for f in _frames( ws ) ] == [ 1 ]   # 1 > the re-based 0: accepted

    @pytest.mark.asyncio
    async def test_f1_a_numbering_reset_under_a_held_slot_replays_everything_as_a_gap( self ):
        mgr  = _manager()
        slot = ( "u1", "phone-A" )
        _connect( mgr, "s1" )
        for n in range( 3 ): await mgr.emit_to_session( "s1", "e", { "n": n } )
        mgr.device_frame_buffers.pop( slot ); mgr.device_seq.pop( slot )   # LRU eviction
        for n in range( 2 ): await mgr.emit_to_session( "s1", "e", { "n": n } )
        _connect( mgr, "s2" )                               # supersedes s1, same slot
        mgr.begin_resume( "s2" )
        sent, send = self._recorder()
        complete = await mgr.replay_and_resume( "s2", 3, send )
        assert [ f[ "seq" ] for f in sent[ :-1 ] ] == [ 1, 2 ]
        assert ( complete[ "seq" ], complete[ "gap" ] ) == ( 2, True )

    @pytest.mark.asyncio
    async def test_f1_a_current_client_gets_the_current_seq_and_no_gap( self ):
        mgr = _manager()
        _connect( mgr, "s1" )
        for n in range( 2 ): await mgr.emit_to_session( "s1", "e", { "n": n } )
        _connect( mgr, "s2" )
        mgr.begin_resume( "s2" )
        sent, send = self._recorder()
        complete = await mgr.replay_and_resume( "s2", 2, send )
        assert sent == [ complete ] and ( complete[ "seq" ], complete[ "gap" ] ) == ( 2, False )

    @pytest.mark.asyncio
    async def test_f1_seq_is_the_servers_even_when_the_client_is_behind_an_emptied_buffer( self ):
        # The one case where "where the replay ended" and "the server's seq" differ: acks
        # emptied the buffer at 5, and a client resumes from 3. Nothing can be replayed,
        # so the cursor stays at 3 — and a client re-basing on 3 would accept a replayed
        # 4 and 5 that do not exist while the next real frame is 6.
        mgr = _manager()
        _connect( mgr, "s1" )
        for n in range( 5 ): await mgr.emit_to_session( "s1", "e", { "n": n } )
        mgr.ack_frames( "s1", 5 )
        _connect( mgr, "s2" )
        mgr.begin_resume( "s2" )
        sent, send = self._recorder()
        complete = await mgr.replay_and_resume( "s2", 3, send )
        assert sent == [ complete ]
        assert ( complete[ "seq" ], complete[ "gap" ] ) == ( 5, True )

    @pytest.mark.asyncio
    async def test_f2_a_frame_emitted_mid_replay_arrives_after_it_in_order( self ):
        mgr = _manager()
        _connect( mgr, "s1" )
        for n in range( 3 ): await mgr.emit_to_session( "s1", "e", { "n": n } )
        ws2 = _connect( mgr, "s2" )
        mgr.begin_resume( "s2" )
        sent = []
        async def send( frame ):
            sent.append( frame )
            if len( sent ) == 1:                            # a live emit lands mid-replay
                await mgr.emit_to_session( "s2", "e", { "n": "live" } )
        complete = await mgr.replay_and_resume( "s2", 0, send )
        seqs = [ f.get( "seq" ) for f in sent if f.get( "type" ) != "resume_complete" ]
        assert seqs == [ 1, 2, 3, 4 ]                      # the live frame came after the replay
        assert ws2.send_json.await_count == 0               # nothing went out unheld
        assert complete[ "seq" ] == 4 and "s2" not in mgr.resuming_sessions

    @pytest.mark.asyncio
    async def test_f2_a_frame_emitted_before_the_replay_is_held_and_sent_once( self ):
        mgr = _manager()
        ws  = _connect( mgr, "s1" )
        mgr.begin_resume( "s1" )
        await mgr.emit_to_session( "s1", "e", { "n": "early" } )
        assert ws.send_json.await_count == 0
        sent, send = self._recorder()
        await mgr.replay_and_resume( "s1", 0, send )
        assert [ f.get( "seq" ) for f in sent ] == [ 1, 1 ]  # the frame, then resume_complete at seq 1
        assert sent[ -1 ][ "type" ] == "resume_complete"
        await mgr.emit_to_session( "s1", "e", { "n": "after" } )
        assert [ f[ "seq" ] for f in _frames( ws ) ] == [ 2 ]   # released: live again

    @pytest.mark.asyncio
    async def test_f2_a_frame_emitted_while_resume_complete_is_on_the_wire_follows_it( self ):
        mgr = _manager()
        _connect( mgr, "s1" )
        mgr.begin_resume( "s1" )
        sent = []
        async def send( frame ):
            sent.append( frame )
            if frame.get( "type" ) == "resume_complete":
                await mgr.emit_to_session( "s1", "e", { "n": "late" } )
        await mgr.replay_and_resume( "s1", 0, send )
        assert [ ( f[ "type" ], f[ "seq" ] ) for f in sent ] == [ ( "resume_complete", 0 ), ( "e", 1 ) ]

    @pytest.mark.asyncio
    async def test_the_fan_out_holds_too_and_still_counts_the_device_as_reached( self ):
        mgr = _manager()
        ws  = _connect( mgr, "s1" )
        mgr.begin_resume( "s1" )
        await mgr.emit_to_user( "u1", "job_state_transition", { "n": 1 } )
        assert ws.send_json.await_count == 0
        assert [ f[ "seq" ] for f in mgr.device_frame_buffers[ ( "u1", "phone-A" ) ] ] == [ 1 ]

    @pytest.mark.asyncio
    async def test_a_session_with_no_slot_is_never_held( self ):
        mgr = _manager()
        _connect( mgr, "wise penguin", client_type="web", device_id=None )
        assert mgr.begin_resume( "wise penguin" ) is False
        sent, send = self._recorder()
        assert await mgr.replay_and_resume( "wise penguin", 0, send ) is None and sent == []

    def test_disconnect_releases_the_hold( self ):
        mgr = _manager()
        _connect( mgr, "s1" )
        mgr.begin_resume( "s1" )
        mgr.disconnect( "s1" )
        assert "s1" not in mgr.resuming_sessions


class TestAHoleBetweenReplayAndHeldFramesIsAnnounced:
    """
    Row c044d46f (María's follow-up a). The per-device buffer is bounded, so frames emitted while
    the replay is on the wire can be evicted before they are sent. A next frame whose seq is not
    cursor + 1 means seqs in between are gone, and the client must be told to refetch.

    Every case drives real eviction: `buffer_size=3`, and a send hook that emits live frames
    through the real `emit_to_session` while the replay is in flight.
    """

    @staticmethod
    def _completes( sent ):
        return [ f for f in sent if f.get( "type" ) == "resume_complete" ]

    @staticmethod
    def _emit( mgr, session_id, count ):
        async def go():
            for n in range( count ): await mgr.emit_to_session( session_id, "e", { "n": n } )
        return go()

    @pytest.mark.asyncio
    @pytest.mark.parametrize( "emitted,missing", [ ( 5, 2 ), ( 4, 1 ) ], ids=[ "two_frames_lost", "exactly_one_frame_lost" ] )
    async def test_a_hole_found_during_the_replay_turns_gap_true_on_the_one_resume_complete( self, emitted, missing ):
        mgr = _manager( buffer_size=3 )
        _connect( mgr, "s1" )
        await self._emit( mgr, "s1", 3 )                       # seq 1..3 held
        _connect( mgr, "s2" )
        mgr.begin_resume( "s2" )
        sent = []
        async def send( frame ):
            sent.append( frame )
            if len( sent ) == 1: await self._emit( mgr, "s2", emitted )   # live frames evict what the replay has not sent
        complete = await mgr.replay_and_resume( "s2", 0, send )

        seqs = [ f[ "seq" ] for f in sent if f.get( "type" ) != "resume_complete" ]
        assert seqs[ :3 ] == [ 1, 2, 3 ]
        assert seqs[ 3 ] == 3 + missing + 1, f"expected {missing} seq(s) missing after 3, got {seqs}"
        assert complete[ "gap" ] is True, "a hole was crossed and the client was told it is current"
        assert len( self._completes( sent ) ) == 1, "the replay-phase hole should ride the one resume_complete"

    @pytest.mark.asyncio
    async def test_no_hole_no_gap_and_exactly_one_resume_complete( self ):
        """The control: a live frame mid-replay with room in the buffer changes nothing."""
        mgr = _manager( buffer_size=50 )
        _connect( mgr, "s1" )
        await self._emit( mgr, "s1", 3 )
        _connect( mgr, "s2" )
        mgr.begin_resume( "s2" )
        sent = []
        async def send( frame ):
            sent.append( frame )
            if len( sent ) == 1: await self._emit( mgr, "s2", 5 )
        complete = await mgr.replay_and_resume( "s2", 0, send )
        assert [ f[ "seq" ] for f in sent if f.get( "type" ) != "resume_complete" ] == list( range( 1, 9 ) )
        assert complete[ "gap" ] is False
        assert len( self._completes( sent ) ) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize( "emitted", [ 5, 4 ], ids=[ "two_frames_lost", "exactly_one_frame_lost" ] )
    async def test_a_hole_after_resume_complete_is_followed_by_a_second_one_before_the_frames( self, emitted ):
        mgr = _manager( buffer_size=3 )
        _connect( mgr, "s1" )
        mgr.begin_resume( "s1" )
        sent = []
        async def send( frame ):
            sent.append( frame )
            if frame.get( "type" ) == "resume_complete" and frame[ "gap" ] is False:
                await self._emit( mgr, "s1", emitted )         # seq 1..N while the first complete is on the wire; the oldest are evicted
        first = await mgr.replay_and_resume( "s1", 0, send )

        assert first[ "gap" ] is False, "the first resume_complete cannot know about a hole that had not happened yet"
        kinds = [ ( f[ "type" ], f[ "seq" ], f.get( "gap" ) ) for f in sent ]
        kept  = list( range( emitted - 2, emitted + 1 ) )      # the buffer holds the newest 3
        assert kinds == [
            ( "resume_complete", 0, False ),
            ( "resume_complete", emitted, True ),              # the second, BEFORE the frames past the hole
            *[ ( "e", seq, None ) for seq in kept ],
        ], kinds
        assert "s1" not in mgr.resuming_sessions

    @pytest.mark.asyncio
    async def test_a_second_hole_does_not_announce_twice( self ):
        mgr = _manager( buffer_size=3 )
        _connect( mgr, "s1" )
        mgr.begin_resume( "s1" )
        sent = []
        async def send( frame ):
            sent.append( frame )
            if frame.get( "type" ) == "resume_complete" and frame[ "gap" ] is False:
                await self._emit( mgr, "s1", 5 )
            elif frame.get( "seq" ) == 3:
                await self._emit( mgr, "s1", 5 )               # evicts again while the first hole's frames are going out
        await mgr.replay_and_resume( "s1", 0, send )
        assert [ f[ "gap" ] for f in self._completes( sent ) ] == [ False, True ], "a gap=True must be sent once, not per hole"

    @pytest.mark.asyncio
    async def test_an_already_announced_gap_is_not_announced_again_after_resume_complete( self ):
        """`gap` True on the first resume_complete already tells the client to refetch."""
        mgr = _manager( buffer_size=3 )
        _connect( mgr, "s1" )
        mgr.begin_resume( "s1" )
        sent = []
        async def send( frame ):
            sent.append( frame )
            if frame.get( "type" ) == "resume_complete": await self._emit( mgr, "s1", 5 )
        await mgr.replay_and_resume( "s1", 500, send )         # last_seq beyond the server's: a restart, gap True from the start
        assert [ f[ "gap" ] for f in self._completes( sent ) ] == [ True ]


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
        assert mgr.ack_frames( "s1", 9999 ) == 1          # empties the buffer, raises nothing
        assert list( mgr.device_frame_buffers[ ( "u1", "phone-A" ) ] ) == []
        # Resuming from the newest seq the server issued is current: no gap.
        assert mgr.frames_since( ( "u1", "phone-A" ), 1 ) == ( [], False )
        # Resuming from a seq the server NEVER issued means the numbering restarted
        # under the client (María's F1): continuity is unprovable, so it is a gap.
        assert mgr.frames_since( ( "u1", "phone-A" ), 9999 ) == ( [], True )

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
        mgr.disconnect( "s1" )                 # eligible: a connected slot is never evicted
        _connect( mgr, "s2", device_id="phone-2" )
        await mgr.emit_to_session( "s2", "job_state_transition", { "n": 2 } )
        assert ( "u1", "phone-0" ) in mgr.device_frame_buffers
        assert ( "u1", "phone-2" ) in mgr.device_frame_buffers
        assert ( "u1", "phone-1" ) not in mgr.device_frame_buffers


class TestEvictionNeverTakesAConnectedSlot:
    """
    The LRU ranks by emit recency, so a quiet phone that is still connected ranks OLDEST — and was
    the first slot evicted, taking its seq and backlog with it while its socket was open.
    """

    @pytest.mark.asyncio
    async def test_a_quiet_connected_device_survives_while_busy_disconnected_ones_are_evicted( self ):
        mgr = _manager( buffer_size=5, max_slots=2 )
        _connect( mgr, "quiet", device_id="phone-quiet" )
        await mgr.emit_to_session( "quiet", "job_state_transition", { "n": 0 } )       # oldest, and live
        for i in range( 4 ):
            sid = f"busy{i}"
            _connect( mgr, sid, device_id=f"phone-busy{i}" )
            await mgr.emit_to_session( sid, "job_state_transition", { "n": i } )
            mgr.disconnect( sid )
        assert ( "u1", "phone-quiet" ) in mgr.device_frame_buffers, "the connected slot was evicted"
        assert mgr.device_seq[ ( "u1", "phone-quiet" ) ] == 1
        assert len( mgr.device_frame_buffers ) == 2
        assert ( "u1", "phone-busy3" ) in mgr.device_frame_buffers, "the newest disconnected slot should be the one kept beside it"

    @pytest.mark.asyncio
    async def test_when_every_slot_is_live_the_cap_is_exceeded_and_warns_ONCE( self, capsys ):
        mgr = _manager( buffer_size=5, max_slots=2 )
        for i in range( 4 ):
            _connect( mgr, f"s{i}", device_id=f"phone-{i}" )
            await mgr.emit_to_session( f"s{i}", "job_state_transition", { "n": i } )
        for _ in range( 3 ):   # more frames on live slots: no new crossing, no new warning
            await mgr.emit_to_session( "s0", "job_state_transition", { "n": 9 } )
        assert len( mgr.device_frame_buffers ) == 4, "every live slot keeps its buffer, bounded by connections"
        assert capsys.readouterr().out.count( "exceed the ceiling" ) == 1

    @pytest.mark.asyncio
    async def test_the_next_write_after_holders_disconnect_brings_it_back_down_and_re_arms_the_warning( self, capsys ):
        mgr = _manager( buffer_size=5, max_slots=2 )
        for i in range( 4 ):
            _connect( mgr, f"s{i}", device_id=f"phone-{i}" )
            await mgr.emit_to_session( f"s{i}", "job_state_transition", { "n": i } )
        capsys.readouterr()
        for i in range( 3 ): mgr.disconnect( f"s{i}" )
        _connect( mgr, "s9", device_id="phone-9" )
        await mgr.emit_to_session( "s9", "job_state_transition", { "n": 9 } )
        assert len( mgr.device_frame_buffers ) == 2
        assert ( "u1", "phone-3" ) in mgr.device_frame_buffers and ( "u1", "phone-9" ) in mgr.device_frame_buffers
        assert mgr.device_buffers_over_cap is False
        assert "exceed the ceiling" not in capsys.readouterr().out
        # crossing again warns again
        for i in ( 10, 11 ):
            _connect( mgr, f"s{i}", device_id=f"phone-{i}" )
            await mgr.emit_to_session( f"s{i}", "job_state_transition", { "n": i } )
        assert capsys.readouterr().out.count( "exceed the ceiling" ) == 1


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


async def _drive( monkeypatch, mgr, session_id, auth_message, frames=(), socket=None ):
    from unittest.mock import AsyncMock, Mock

    from cosa.rest.routers.websocket import websocket_queue_endpoint

    main_stub         = _StubMain( mgr )
    package_stub      = Mock()
    package_stub.main = main_stub
    monkeypatch.setitem( sys.modules, "lupin_app", package_stub )
    monkeypatch.setitem( sys.modules, "lupin_app.main", main_stub )
    monkeypatch.setattr( "cosa.rest.auth.verify_token",
                         AsyncMock( return_value={ "uid": "u1", "email": "a@b.c" } ) )
    socket = socket if socket is not None else _ScriptedSocket( auth_message, frames )
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


class _DyingSocket( _ScriptedSocket ):
    """Sends fine until `die_on` arrives, then raises like a socket that dropped mid-backlog."""

    def __init__( self, auth_message, die_on, close_raises=False ):
        super().__init__( auth_message )
        self.die_on       = die_on
        self.closes       = []
        self.close_raises = close_raises

    async def send_json( self, payload ):
        if payload.get( "type" ) == self.die_on:
            raise RuntimeError( "socket died mid-replay" )
        self.sent.append( payload )

    async def close( self, *a, **k ):
        self.closes.append( k )
        if self.close_raises: raise RuntimeError( "already closed" )


class TestAResumeFailureIsNotAnAuthFailure:
    """
    Row 3bafdf12. `replay_and_resume` used to run inside the auth try, so a send that failed
    mid-replay was answered with auth_error and a 4001 close — which the mobile client reads as
    "refresh the token or sign out". Driven through the real endpoint AND the real manager, with
    a socket that dies while the backlog is going out.
    """

    def _seeded( self ):
        mgr = _manager()
        for n in ( 1, 2, 3 ):
            mgr.buffer_frame_for_slot( ( "u1", "phone-A" ), { "type": "job_state_transition", "n": n } )
        return mgr

    @pytest.mark.asyncio
    @pytest.mark.parametrize( "die_on", [ "job_state_transition", "resume_complete" ] )
    async def test_a_mid_replay_send_failure_closes_1011_and_sends_no_auth_error( self, monkeypatch, capsys, die_on ):
        mgr    = self._seeded()
        socket = _DyingSocket( { **_MOBILE_AUTH, "last_seq": 0 }, die_on )

        await _drive( monkeypatch, mgr, "s-die", None, socket=socket )

        assert not [ f for f in socket.sent if f.get( "type" ) == "auth_error" ], socket.sent
        assert [ f[ "type" ] for f in socket.sent ][ 0 ] == "auth_success", "auth itself must still have succeeded"
        assert "connect" not in [ f[ "type" ] for f in socket.sent ], "the endpoint carried on into the message loop after a failed resume"
        assert socket.closes and all( c[ "code" ] == 1011 and c[ "reason" ] == "resume_failed" for c in socket.closes ), socket.closes
        assert all( c[ "code" ] != 4001 for c in socket.closes )
        assert "s-die" not in mgr.active_connections, "a failed resume left the session registered"

        out = capsys.readouterr().out
        assert "ERROR resume replay failed for session [s-die]: RuntimeError: socket died mid-replay" in out
        assert "Token verification failed" not in out, "the failure was still logged as an auth failure"

    @pytest.mark.asyncio
    async def test_a_close_that_also_fails_is_swallowed( self, monkeypatch ):
        mgr    = self._seeded()
        socket = _DyingSocket( { **_MOBILE_AUTH, "last_seq": 0 }, "resume_complete", close_raises=True )
        await _drive( monkeypatch, mgr, "s-die2", None, socket=socket )    # must not raise
        assert len( socket.closes ) == 1

    @pytest.mark.asyncio
    async def test_a_replaced_socket_is_not_deregistered_by_the_failed_resume( self, monkeypatch ):
        """A newer connection under the same id owns the registry entry; this socket's failure must not evict it."""
        mgr    = self._seeded()
        socket = _DyingSocket( { **_MOBILE_AUTH, "last_seq": 0 }, "resume_complete" )
        usurper = object()
        real_connect = mgr.connect
        def connect_then_get_replaced( *a, **k ):
            real_connect( *a, **k )
            mgr.active_connections[ "s-die3" ] = usurper
        monkeypatch.setattr( mgr, "connect", connect_then_get_replaced )

        await _drive( monkeypatch, mgr, "s-die3", None, socket=socket )

        assert mgr.active_connections.get( "s-die3" ) is usurper

    @pytest.mark.asyncio
    async def test_the_healthy_resume_is_unchanged( self, monkeypatch ):
        mgr    = self._seeded()
        socket = await _drive( monkeypatch, mgr, "s-ok", { **_MOBILE_AUTH, "last_seq": 1 } )
        assert [ f[ "type" ] for f in socket.sent if f.get( "type" ) in ( "auth_error", "resume_complete" ) ] == [ "resume_complete" ]


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
