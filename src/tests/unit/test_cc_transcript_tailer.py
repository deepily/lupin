#!/usr/bin/env python3
"""
A2.3, A2.5, A2.10 and A2.11 — the tailer's clear/rotation detection, lifecycle, and ring.

Plan: `src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md` §2 items 1, 5, 6, 7.
Module under test: `cosa/rest/cc_transcript_tailer.py`.

The two arms of A2.3, and why they are different mechanisms
----------------------------------------------------------
(a) PATH SWAP — the real `/clear`. The bridge is rewritten with a new `transcript_path` while
    `stable_session_id` stays put. The old file does NOT shrink; it stops growing. So the only
    thing that can notice is a re-resolve of the bridge.
(b) IN-PLACE TRUNCATION — genuine rotation, which a shrink check does see.

A tailer that implements only (b) passes (b) and FAILS (a) — and (a) is the case that actually
happens every time somebody runs `/clear`. `test_a_shrink_only_tailer_would_fail_the_path_swap_arm`
is the discriminator: it proves arm (a) is watching something, by demonstrating that the
shrink-only strategy misses it.

No live seat, no server
-----------------------
The bridge read and the emit are both injected, so every test here runs against a `tmp_path`
file and an in-memory emit recorder. Venue: :7999-eligible.
"""

import asyncio
import json
import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.cc_transcript_tailer import (
    APPEND_EVENT,
    DEFAULT_BACKLOG_TAIL_BYTES,
    DEFAULT_BLOCK_BUDGET_BYTES,
    DEFAULT_COALESCE_WINDOW_MS,
    DEFAULT_GRACE_SECONDS,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_RING_BUFFER_BYTES,
    STATE_ENDED,
    STATE_EVENT,
    STATE_LIVE,
    STATE_ROTATED,
    CcTranscriptTailer,
    SeatRing,
    epoch_for_path,
    load_settings,
    read_backlog,
    resolve_transcript_path,
)

SEAT = "449359bc-c735-4970-8fc0-e83b635c8548"


class EmitRecorder:
    """
    An in-memory stand-in for `emit_to_session`, recording every frame in order.

    Deliberately NOT a Mock: this asserts on payload CONTENT, and a Mock that accepts
    anything would answer the same however the tailer behaved.
    """

    def __init__( self ):
        self.frames = [ ]

    async def __call__( self, cc_session_id, event_name, payload ):
        self.frames.append( ( cc_session_id, event_name, payload ) )

    def of( self, event_name ):
        """Every payload emitted for one event name, in order."""
        return [ payload for _, name, payload in self.frames if name == event_name ]

    def states( self ):
        """The `state` value of every state frame, in order."""
        return [ payload[ "state" ] for payload in self.of( STATE_EVENT ) ]


def _write_records( path, count, start=0 ):
    """Append `count` assistant text records, each carrying its own index."""
    with open( path, "a" ) as f:
        for i in range( start, start + count ):
            f.write( json.dumps( {
                "type"      : "assistant",
                "timestamp" : "2026-09-27T18:00:00Z",
                "message"   : { "role": "assistant", "content": [ { "type": "text", "text": f"block {i}" } ] },
            } ) + "\n" )
    return os.path.getsize( path )


def _fast_settings( **overrides ):
    """Settings with the timers wound down so a test does not wait on wall-clock."""
    settings = {
        "poll_interval_seconds" : 0.01,
        "grace_seconds"         : 0,
        "coalesce_window_ms"    : 0,
        "backlog_tail_bytes"    : DEFAULT_BACKLOG_TAIL_BYTES,
        "block_budget_bytes"    : 0,
        "ring_buffer_bytes"     : DEFAULT_RING_BUFFER_BYTES,
    }
    settings.update( overrides )
    return settings


class BridgeStub:
    """
    A mutable stand-in for the session bridge, so a test can SWAP THE PATH mid-run.

    That swap is the whole point: it is what `/clear` does, and nothing else in the fixture
    surface can express it.
    """

    def __init__( self, transcript_path ):
        self.transcript_path    = str( transcript_path )
        self.stable_session_id  = SEAT
        self.reads              = 0

    def __call__( self, cc_session_id ):
        self.reads += 1
        return {
            "session_id"        : cc_session_id,
            "stable_session_id" : self.stable_session_id,
            "transcript_path"   : self.transcript_path,
        }


@pytest.fixture
def seat( tmp_path ):
    """A transcript file plus a bridge stub pointing at it."""
    path = tmp_path / f"{SEAT}.jsonl"
    path.write_text( "" )
    return path, BridgeStub( path )


# ── the epoch names the FILE ──────────────────────────────────────────────────

@pytest.mark.parametrize( "path,expected", [
    ( "/home/x/.claude/projects/p/57238c9d-c227-469e-b707-13b7752a7399.jsonl",
      "57238c9d-c227-469e-b707-13b7752a7399" ),
    ( "/tmp/a.jsonl", "a" ),
    ( "bare",         "bare" ),
    ( "",             "" ),
    ( None,           "" ),
] )
def test_the_epoch_is_derived_from_the_path( path, expected ):
    """
    The epoch NAMES THE FILE, because a `/clear` swaps the path while the seat id stays put.

    Parametrised so a failure says which shape broke.
    """
    assert epoch_for_path( path ) == expected


# ── A2.3(a): PATH SWAP is the /clear detector ─────────────────────────────────

def test_a_changed_transcript_path_resets_the_offset_and_bumps_the_epoch( seat ):
    """
    A2.3 arm (a) — the real `/clear`, driven exactly as the hook drives it.

    The bridge is rewritten with a NEW `transcript_path` while `stable_session_id` stays put;
    the old file is left intact, because a clear does not shrink it.
    """
    old_path, bridge = seat
    _write_records( old_path, 3 )

    tailer = CcTranscriptTailer( SEAT, EmitRecorder(), settings=_fast_settings(), bridge_reader=bridge )
    tailer.transcript_path = str( old_path )
    tailer.file_epoch      = epoch_for_path( old_path )
    tailer.offset          = 0

    first = tailer.poll_once()
    assert len( first[ "blocks" ] ) == 3
    assert tailer.offset > 0
    old_epoch = tailer.file_epoch

    # The clear: a NEW file at a NEW path, the old one untouched and NOT shorter.
    new_path = old_path.parent / "11111111-2222-3333-4444-555555555555.jsonl"
    new_path.write_text( "" )
    _write_records( new_path, 2, start=100 )
    assert os.path.getsize( old_path ) > 0, "the old file must remain — a clear does not truncate it"
    bridge.transcript_path = str( new_path )

    swapped = tailer.poll_once()
    assert swapped[ "rotated" ] is True
    assert tailer.offset    == 0
    assert tailer.file_epoch != old_epoch
    assert tailer.file_epoch == epoch_for_path( new_path )
    assert swapped[ "blocks" ] == [ ], "the swap frame must carry no blocks; the next poll reads the new file"

    after = tailer.poll_once()
    assert [ b[ "text" ] for b in after[ "blocks" ] ] == [ "block 100", "block 101" ]


def test_a_shrink_only_tailer_would_fail_the_path_swap_arm( seat ):
    """
    PROVE ARM (a) IS WATCHING SOMETHING — the discriminator A2.3 asks for.

    This reproduces the shrink-only strategy: never re-resolve the bridge, only watch for the
    file getting shorter. Under a real `/clear` it sees NOTHING — no rotation, no blocks, no
    epoch change — which is the pane silently freezing at the moment of the clear. The
    assertions below are what the defect looks like, so the arm above cannot be satisfied by a
    tailer that skips the re-resolve.
    """
    from cosa.utils.transcript_tail import tail_jsonl

    old_path, bridge = seat
    _write_records( old_path, 3 )

    # The shrink-only tailer: a frozen path and a shrink check.
    frozen_path = str( old_path )
    _, offset, rotated = tail_jsonl( frozen_path, 0 )
    assert rotated is False

    new_path = old_path.parent / "99999999-2222-3333-4444-555555555555.jsonl"
    _write_records( new_path, 5, start=200 )
    bridge.transcript_path = str( new_path )

    records, offset_after, rotated_after = tail_jsonl( frozen_path, offset )
    assert rotated_after is False, "a shrink check cannot see a clear — this is the defect"
    assert records       == [ ],   "and it reports nothing new, forever"
    assert offset_after  == offset

    # Meanwhile the real detector — a bridge re-resolve — sees it immediately.
    assert resolve_transcript_path( SEAT, bridge ) == str( new_path ) != frozen_path


def test_the_tailer_re_resolves_the_bridge_on_every_poll( seat ):
    """
    The re-resolve is per-poll, not once at start.

    A tailer that resolved only at `start()` would pass every test above that swaps the path
    before the first poll, and still freeze on a clear mid-session.
    """
    path, bridge = seat
    _write_records( path, 1 )
    tailer = CcTranscriptTailer( SEAT, EmitRecorder(), settings=_fast_settings(), bridge_reader=bridge )
    tailer.transcript_path = str( path )
    tailer.file_epoch      = epoch_for_path( path )

    before = bridge.reads
    tailer.poll_once()
    tailer.poll_once()
    tailer.poll_once()
    assert bridge.reads == before + 3, "the bridge was not re-read on every poll"


# ── A2.3(b): in-place truncation, and no replay ───────────────────────────────

def test_an_in_place_truncation_bumps_the_epoch_and_emits_no_replayed_record( seat ):
    """
    A2.3 arm (b) — genuine rotation.

    The discriminating property is the ABSENCE of a replay: raw `tail_session_file` re-reads
    from 0 and returns the whole file as new bytes, which would re-render the transcript as
    fresh output.
    """
    path, bridge = seat
    _write_records( path, 5 )

    tailer = CcTranscriptTailer( SEAT, EmitRecorder(), settings=_fast_settings(), bridge_reader=bridge )
    tailer.transcript_path = str( path )
    tailer.file_epoch      = epoch_for_path( path )
    tailer.poll_once()
    old_epoch = tailer.file_epoch

    path.write_text( "" )                                  # truncated in place, same path
    _write_records( path, 1, start=500 )

    rotated = tailer.poll_once()
    assert rotated[ "rotated" ] is True
    assert rotated[ "blocks" ] == [ ], "the replayed records were emitted — the silent-replay defect"
    assert tailer.file_epoch != old_epoch, "the epoch did not move, so a client would keep its stale offset"
    assert tailer.offset == 0


def test_a_rotation_clears_the_ring_so_it_cannot_serve_stale_offsets( seat ):
    """
    A ring surviving a rotation would answer a resume with blocks from the previous file.

    Offsets are only meaningful inside one epoch, so the ring must be epoch-scoped too.
    """
    path, bridge = seat
    _write_records( path, 4 )
    tailer = CcTranscriptTailer( SEAT, EmitRecorder(), settings=_fast_settings(), bridge_reader=bridge )
    tailer.transcript_path = str( path )
    tailer.file_epoch      = epoch_for_path( path )
    tailer.poll_once()
    assert tailer.ring.span() != ( None, None )

    path.write_text( "" )
    tailer.poll_once()
    assert tailer.ring.span() == ( None, None ), "the ring survived a rotation"


# ── the verbatim-path constraint ──────────────────────────────────────────────

def test_the_bridge_path_is_used_verbatim_and_never_rejoined( tmp_path ):
    """
    The path is opened exactly as the bridge wrote it.

    The container binds the host sessions dir to the SAME absolute path inside the container,
    which is why verbatim works; a path rejoined against a project root points at nothing.
    And `tail_jsonl` never raises, so the failure would be an EMPTY STREAM, not an error — a
    blank pane while every status frame says live. Constraint raised by Tiberius.
    """
    absolute = tmp_path / "abs" / f"{SEAT}.jsonl"
    absolute.parent.mkdir()
    _write_records( absolute, 2 )

    bridge = BridgeStub( absolute )
    assert resolve_transcript_path( SEAT, bridge ) == str( absolute )
    assert os.path.isabs( resolve_transcript_path( SEAT, bridge ) )


@pytest.mark.parametrize( "bridge_value", [ None, { }, { "transcript_path": "" }, "not a dict", 42 ] )
def test_an_unresolvable_bridge_yields_an_empty_path_not_an_exception( bridge_value ):
    """A seat that vanished mid-poll must not kill the tailer."""
    assert resolve_transcript_path( SEAT, lambda _: bridge_value ) == ""


def test_a_raising_bridge_reader_yields_an_empty_path( ):
    """A bridge read that throws is caught — the tailer degrades, it does not die."""
    def boom( _ ):
        raise RuntimeError( "bridge unreadable" )
    assert resolve_transcript_path( SEAT, boom ) == ""


def test_a_missing_transcript_reads_as_a_quiet_seat_which_is_the_documented_hazard( seat ):
    """
    ⚠️ Asserts the hazard's SHAPE, so it is on record rather than discovered in production.

    A path that does not exist is indistinguishable from a seat that is simply not printing.
    That is deliberate, and it is exactly why the verbatim rule above matters.
    """
    path, bridge = seat
    bridge.transcript_path = str( path.parent / "does-not-exist.jsonl" )
    tailer = CcTranscriptTailer( SEAT, EmitRecorder(), settings=_fast_settings(), bridge_reader=bridge )
    tailer.transcript_path = bridge.transcript_path
    tailer.file_epoch      = epoch_for_path( bridge.transcript_path )
    assert tailer.poll_once() is None


# ── the quiet cases ───────────────────────────────────────────────────────────

def test_nothing_new_yields_no_frame( seat ):
    """A quiet seat produces no append frame at all — not an empty one."""
    path, bridge = seat
    _write_records( path, 2 )
    tailer = CcTranscriptTailer( SEAT, EmitRecorder(), settings=_fast_settings(), bridge_reader=bridge )
    tailer.transcript_path = str( path )
    tailer.file_epoch      = epoch_for_path( path )
    assert tailer.poll_once() is not None
    assert tailer.poll_once() is None


def test_records_that_map_to_no_block_advance_the_offset_without_a_frame( seat ):
    """
    The 66% case: records that are not messages.

    The offset MUST still advance, or the tailer re-reads the same non-displayable records
    forever and never reaches the next real message.
    """
    path, bridge = seat
    with open( path, "a" ) as f:
        for i in range( 4 ):
            f.write( json.dumps( { "type": "attachment", "n": i } ) + "\n" )

    tailer = CcTranscriptTailer( SEAT, EmitRecorder(), settings=_fast_settings(), bridge_reader=bridge )
    tailer.transcript_path = str( path )
    tailer.file_epoch      = epoch_for_path( path )

    assert tailer.poll_once() is None
    assert tailer.offset == os.path.getsize( path ), "the offset stalled on non-displayable records"


# ── A2.11: the ring is BYTE-bounded and names its span ────────────────────────

def test_the_ring_reports_the_offset_span_it_holds( ):
    """
    A2.11 — the server can say which `from_offset` values it can serve.

    This is the property P7 names: a record-count ring cannot answer it at all.
    """
    ring = SeatRing( 1000 )
    assert ring.span()          == ( None, None )
    assert ring.can_serve( 0 )  is False

    ring.add( 0,   100, [ { "kind": "text", "text": "a" } ] )
    ring.add( 100, 250, [ { "kind": "text", "text": "b" } ] )
    assert ring.span()            == ( 0, 250 )
    assert ring.can_serve( 0 )    is True
    assert ring.can_serve( 250 )  is True
    assert ring.can_serve( 251 )  is False


def test_the_ring_evicts_by_bytes_and_its_span_follows( ):
    """
    Eviction is by byte span, and `span()` must never claim more than the ring holds.

    A ring whose span outran its contents would tell the server it can serve a `from_offset`
    it has already dropped — a resume answered with a gap.
    """
    ring = SeatRing( 200 )
    ring.add( 0,   100, [ { "text": "a" } ] )
    ring.add( 100, 200, [ { "text": "b" } ] )
    assert ring.span() == ( 0, 200 )

    ring.add( 200, 300, [ { "text": "c" } ] )              # now over budget — the front goes
    start, end = ring.span()
    assert end   == 300
    assert start == 100, "the evicted chunk is still being claimed"
    assert ring.can_serve( 0 ) is False


def test_a_chunk_larger_than_the_whole_ring_leaves_it_empty_rather_than_overfull( ):
    """
    A single huge tool result must not leave the ring claiming a span it cannot serve.

    Empty is the honest answer: it sends the client to REST, which can serve it.
    """
    ring = SeatRing( 100 )
    ring.add( 0, 5000, [ { "text": "enormous" } ] )
    assert ring.span() == ( None, None )
    assert ring.can_serve( 0 ) is False


def test_a_ring_of_zero_bytes_is_disabled_not_unbounded( ):
    """
    The one place 0 does NOT mean unbounded, stated because the budget's 0 does.

    A ring is a cache: 0 means "keep nothing", and everything goes to REST. Reading it as
    unbounded would make the server hold every byte of every watched seat.
    """
    ring = SeatRing( 0 )
    ring.add( 0, 100, [ { "text": "a" } ] )
    assert ring.span() == ( None, None )


def test_the_ring_serves_the_blocks_at_or_after_an_offset( ):
    """A resume inside the span is served from memory, with the next_offset to continue from."""
    ring = SeatRing( 1000 )
    ring.add( 0,   100, [ { "text": "a" } ] )
    ring.add( 100, 200, [ { "text": "b" } ] )
    ring.add( 200, 300, [ { "text": "c" } ] )

    blocks, next_offset = ring.blocks_from( 100 )
    assert [ b[ "text" ] for b in blocks ] == [ "b", "c" ]
    assert next_offset == 300

    blocks, next_offset = ring.blocks_from( 300 )
    assert blocks == [ ]
    assert next_offset == 300


def test_an_empty_ring_serves_nothing_and_says_so( ):
    """An empty ring returns the offset it was asked about, so the caller can go to REST."""
    assert SeatRing( 1000 ).blocks_from( 42 ) == ( [ ], 42 )


def test_the_tailer_records_each_chunk_into_its_ring( seat ):
    """The ring is wired to the poll, not merely instantiated."""
    path, bridge = seat
    _write_records( path, 3 )
    tailer = CcTranscriptTailer( SEAT, EmitRecorder(), settings=_fast_settings(), bridge_reader=bridge )
    tailer.transcript_path = str( path )
    tailer.file_epoch      = epoch_for_path( path )
    chunk = tailer.poll_once()
    assert tailer.ring.span() == ( chunk[ "offset" ], chunk[ "next_offset" ] )


# ── A2.5: lifecycle, and the frames the loop emits ────────────────────────────

@pytest.mark.asyncio
async def test_the_tailer_starts_where_the_client_asked_not_at_the_end( seat ):
    """
    `from_offset` is honoured. Starting at the current end would open a silent gap between
    the client's REST backlog fetch and its live watch.
    """
    path, bridge = seat
    _write_records( path, 5 )
    emit   = EmitRecorder()
    tailer = CcTranscriptTailer( SEAT, emit, settings=_fast_settings(), bridge_reader=bridge )

    tailer.start( from_offset=0 )
    try:
        await asyncio.sleep( 0.08 )
    finally:
        await tailer.stop()

    appended = emit.of( APPEND_EVENT )
    assert appended, "no append frame — the watch produced nothing"
    texts = [ b[ "text" ] for frame in appended for b in frame[ "blocks" ] ]
    assert texts == [ f"block {i}" for i in range( 5 ) ]
    assert appended[ 0 ][ "offset" ] == 0, "the tailer skipped ahead instead of starting at 0"


@pytest.mark.asyncio
async def test_the_first_frame_of_a_watch_is_a_live_state( seat ):
    """A2.10 — `live` is announced, so a client knows it is attached."""
    path, bridge = seat
    emit   = EmitRecorder()
    tailer = CcTranscriptTailer( SEAT, emit, settings=_fast_settings(), bridge_reader=bridge )
    tailer.start()
    try:
        await asyncio.sleep( 0.05 )
    finally:
        await tailer.stop()
    assert emit.states()[ 0 ] == STATE_LIVE


@pytest.mark.asyncio
async def test_an_append_frame_carries_the_whole_wire_contract( seat ):
    """
    Every field §3 publishes. A missing one is a client crash and would show up nowhere else.
    """
    path, bridge = seat
    _write_records( path, 2 )
    emit   = EmitRecorder()
    tailer = CcTranscriptTailer( SEAT, emit, settings=_fast_settings(), bridge_reader=bridge )
    tailer.start()
    try:
        await asyncio.sleep( 0.08 )
    finally:
        await tailer.stop()

    frame = emit.of( APPEND_EVENT )[ 0 ]
    assert set( frame ) == { "cc_session_id", "file_epoch", "offset", "next_offset", "blocks", "ts" }
    assert frame[ "cc_session_id" ] == SEAT
    assert frame[ "file_epoch" ]    == epoch_for_path( path )
    assert frame[ "next_offset" ]   > frame[ "offset" ]
    assert frame[ "ts" ]


@pytest.mark.asyncio
async def test_a_frame_flushed_after_a_quiet_poll_still_ends_where_the_read_ended( seat ):
    """
    With a real coalesce window, the flush happens on a LATER poll than the read, and that
    later poll finds nothing new. The frame must still carry the end of what was read.

    Every other loop test here runs `coalesce_window_ms=0`, which flushes on the same
    iteration as the read and so can never reach this path. The live server runs 300 ms.
    Measured on :8000 job ts-11c25f8a (2026-10-03): a frame at 18686 arrived with
    next_offset 18686 for a 44776-byte file, and three integration tests went red on it.
    A client applies `chunk.offset != last_next_offset` and would re-fetch on every frame.
    """
    path, bridge = seat
    size   = _write_records( path, 5 )
    emit   = EmitRecorder()
    tailer = CcTranscriptTailer( SEAT, emit, settings=_fast_settings( coalesce_window_ms=60 ),
                                 bridge_reader=bridge )

    tailer.start( from_offset=0 )
    try:
        await asyncio.sleep( 0.3 )
    finally:
        await tailer.stop()

    frames = emit.of( APPEND_EVENT )
    assert len( frames ) == 1, f"expected the five records in one coalesced frame, got {len( frames )}"
    assert ( frames[ 0 ][ "offset" ], frames[ 0 ][ "next_offset" ] ) == ( 0, size ), (
        f"the frame says it ends at {frames[ 0 ][ 'next_offset' ]}; the file ends at {size}"
    )


@pytest.mark.asyncio
async def test_offsets_chain_across_frames_with_no_gap( seat ):
    """
    Each frame starts where the previous one ended.

    The client's gap rule is `chunk.offset != last_next_offset`, so a server that does not
    chain makes every client drop every frame and re-fetch forever.
    """
    path, bridge = seat
    emit   = EmitRecorder()
    tailer = CcTranscriptTailer( SEAT, emit, settings=_fast_settings( coalesce_window_ms=0 ),
                                 bridge_reader=bridge )
    tailer.start()
    try:
        for i in range( 3 ):
            _write_records( path, 1, start=i )
            await asyncio.sleep( 0.05 )
    finally:
        await tailer.stop()

    frames = emit.of( APPEND_EVENT )
    assert len( frames ) >= 2, f"only {len( frames )} frame(s) — cannot test chaining"
    for previous, following in zip( frames, frames[ 1: ] ):
        assert following[ "offset" ] == previous[ "next_offset" ], (
            f"gap: frame starts at {following[ 'offset' ]}, previous ended at {previous[ 'next_offset' ]}"
        )


@pytest.mark.asyncio
async def test_start_is_idempotent_and_stop_is_safe_to_call_twice( seat ):
    """
    A2.5(a) — the lifecycle edges.

    A second `start()` must not create a second poll loop on the same seat, and `stop()` must
    be safe on an already-stopped tailer, because both happen under reconnect churn.
    """
    path, bridge = seat
    tailer = CcTranscriptTailer( SEAT, EmitRecorder(), settings=_fast_settings(), bridge_reader=bridge )

    tailer.start()
    first_task = tailer._task
    tailer.start()
    assert tailer._task is first_task, "a second start() created a second loop"
    assert tailer.running is True

    await tailer.stop()
    assert tailer.running is False
    await tailer.stop()                                    # must not raise


@pytest.mark.asyncio
async def test_stopping_a_tailer_that_never_started_is_a_no_op( seat ):
    """The reap path must tolerate a tailer that never ran."""
    _, bridge = seat
    tailer = CcTranscriptTailer( SEAT, EmitRecorder(), settings=_fast_settings(), bridge_reader=bridge )
    await tailer.stop()
    assert tailer.running is False


@pytest.mark.asyncio
async def test_no_frame_is_emitted_after_stop( seat ):
    """
    The stop actually stops. A tailer that kept polling after its last watcher left is the
    silent burn P3 describes.
    """
    path, bridge = seat
    emit   = EmitRecorder()
    tailer = CcTranscriptTailer( SEAT, emit, settings=_fast_settings(), bridge_reader=bridge )
    tailer.start()
    await asyncio.sleep( 0.05 )
    await tailer.stop()

    count_at_stop = len( emit.frames )
    _write_records( path, 5 )                              # new content AFTER the stop
    await asyncio.sleep( 0.08 )
    assert len( emit.frames ) == count_at_stop, "the tailer kept polling after stop()"


# ── A2.10: the state producers ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ended_is_produced_by_its_own_signal_not_by_the_tailer_stopping( seat ):
    """
    A2.10 — `ended` needs a producer, and the grace period is not it.

    The grace period fires when the last WATCHER leaves, never when the SEAT leaves. So a
    viewer watching a seat that exits would otherwise see a pane that merely stops, which is
    indistinguishable from a quiet seat.
    """
    path, bridge = seat
    emit   = EmitRecorder()
    tailer = CcTranscriptTailer( SEAT, emit, settings=_fast_settings(), bridge_reader=bridge )

    tailer.start()
    await asyncio.sleep( 0.05 )
    await tailer.stop()
    assert STATE_ENDED not in emit.states(), "stopping the tailer produced `ended` on its own"

    await tailer.mark_seat_ended()
    assert emit.states()[ -1 ] == STATE_ENDED
    assert emit.of( STATE_EVENT )[ -1 ][ "cc_session_id" ] == SEAT


@pytest.mark.asyncio
async def test_a_quiet_seat_never_produces_ended( seat ):
    """The negative arm: quiet is not ended, and the pane must not claim otherwise."""
    path, bridge = seat
    emit   = EmitRecorder()
    tailer = CcTranscriptTailer( SEAT, emit, settings=_fast_settings(), bridge_reader=bridge )
    tailer.start()
    try:
        await asyncio.sleep( 0.1 )                         # several polls, no writes
    finally:
        await tailer.stop()
    assert STATE_ENDED not in emit.states()


@pytest.mark.asyncio
async def test_rotation_is_announced_as_its_own_state_frame( seat ):
    """
    A2.10 — `rotated` reaches the client as a FRAME.

    A2.3 asserts the epoch bump and the absence of a replay; neither of those is the signal.
    Without the frame the client keeps a stale offset against a new file.
    """
    path, bridge = seat
    emit   = EmitRecorder()
    tailer = CcTranscriptTailer( SEAT, emit, settings=_fast_settings(), bridge_reader=bridge )
    tailer.transcript_path = str( path )
    tailer.file_epoch      = epoch_for_path( path )

    await tailer.announce_rotation()
    frame = emit.of( STATE_EVENT )[ -1 ]
    assert frame[ "state" ]      == STATE_ROTATED
    assert frame[ "file_epoch" ] == epoch_for_path( path )
    assert set( frame ) == { "cc_session_id", "file_epoch", "state" }


# ── the settings, and their homes ─────────────────────────────────────────────

def test_the_defaults_are_the_documented_values( ):
    """
    Pins the six defaults, so a change is a deliberate edit with a test to update.

    Three are Rick's rulings (coalesce = Q7, backlog tail = Q6); three are implementer
    defaults standing in for the open sub-questions.
    """
    assert DEFAULT_POLL_INTERVAL_SECONDS == 0.25
    assert DEFAULT_GRACE_SECONDS         == 30
    assert DEFAULT_COALESCE_WINDOW_MS    == 300
    assert DEFAULT_BACKLOG_TAIL_BYTES    == 65536
    assert DEFAULT_BLOCK_BUDGET_BYTES    == 8192
    assert DEFAULT_RING_BUFFER_BYTES     == 262144


def test_load_settings_reads_every_dial_from_the_config_manager( ):
    """
    All six come from the INI, not from constants — the unresolved-HOMES requirement (T8).

    The stub returns a distinct value per key, so a dial wired to the wrong key is visible
    rather than masked by a shared default.
    """
    calls = { }

    class ConfigStub:
        def get( self, key, default=None, return_type=None ):
            calls[ key ] = return_type
            return { "cc transcript poll interval seconds" : 1.5,
                     "cc transcript watcher grace seconds"  : 11,
                     "cc transcript coalesce window ms"     : 22,
                     "cc transcript backlog tail bytes"     : 33,
                     "cc transcript block budget bytes"     : 44,
                     "cc transcript ring buffer bytes"      : 55 }[ key ]

    settings = load_settings( ConfigStub() )
    assert settings == {
        "poll_interval_seconds" : 1.5,
        "grace_seconds"         : 11,
        "coalesce_window_ms"    : 22,
        "backlog_tail_bytes"    : 33,
        "block_budget_bytes"    : 44,
        "ring_buffer_bytes"     : 55,
    }
    assert calls[ "cc transcript poll interval seconds" ] == "float"
    assert calls[ "cc transcript ring buffer bytes" ]     == "int"


def test_load_settings_falls_back_to_the_defaults_when_no_config_is_reachable( monkeypatch ):
    """
    A tailer that cannot start is worse than one running on defaults.

    Forces the import of the shared config accessor to fail, which is the only way the
    fallback arm is reachable.
    """
    import builtins
    real_import = builtins.__import__

    def refuse( name, *args, **kwargs ):
        if name == "cosa.rest.dependencies.config":
            raise ImportError( "no config in this context" )
        return real_import( name, *args, **kwargs )

    monkeypatch.setattr( builtins, "__import__", refuse )
    settings = load_settings( None )
    assert settings[ "poll_interval_seconds" ] == DEFAULT_POLL_INTERVAL_SECONDS
    assert settings[ "ring_buffer_bytes" ]     == DEFAULT_RING_BUFFER_BYTES


def test_a_config_manager_that_resolves_is_used_when_none_is_passed( monkeypatch ):
    """The None path resolves the shared singleton rather than silently using defaults."""
    import cosa.rest.cc_transcript_tailer as module

    class ConfigStub:
        def get( self, key, default=None, return_type=None ):
            return 7

    monkeypatch.setitem( sys.modules, "cosa.rest.dependencies.config",
                         type( "M", (), { "get_config_manager": staticmethod( lambda: ConfigStub() ) } ) )
    settings = module.load_settings( None )
    assert settings[ "grace_seconds" ] == 7


def test_the_tailer_loads_settings_when_none_are_given( seat ):
    """A tailer built without explicit settings still has all six dials."""
    _, bridge = seat
    tailer = CcTranscriptTailer( SEAT, EmitRecorder(), bridge_reader=bridge )
    assert set( tailer.settings ) == {
        "poll_interval_seconds", "grace_seconds", "coalesce_window_ms",
        "backlog_tail_bytes", "block_budget_bytes", "ring_buffer_bytes",
    }


# ── the budget reaches the blocks ─────────────────────────────────────────────

def test_the_block_budget_from_the_settings_reaches_the_emitted_blocks( seat ):
    """
    The dial is wired, not merely read.

    A budget that loads correctly and is never passed to the mapper is the failure this
    catches — and it would look identical in a settings test.
    """
    path, bridge = seat
    with open( path, "a" ) as f:
        f.write( json.dumps( {
            "type"    : "assistant",
            "message" : { "role": "assistant", "content": [ { "type": "text", "text": "z" * 400 } ] },
        } ) + "\n" )

    tailer = CcTranscriptTailer( SEAT, EmitRecorder(),
                                 settings=_fast_settings( block_budget_bytes=50 ),
                                 bridge_reader=bridge )
    tailer.transcript_path = str( path )
    tailer.file_epoch      = epoch_for_path( path )
    block = tailer.poll_once()[ "blocks" ][ 0 ]
    assert len( block[ "text" ] ) == 50
    assert block[ "truncated" ] is True


# ── read_backlog: the three directions, one door ──────────────────────────────

def test_read_backlog_tail_bytes_reads_backwards( seat ):
    """The open path — ruling Q6's last-N-bytes."""
    path, _ = seat
    _write_records( path, 20 )
    size = os.path.getsize( path )

    tail = read_backlog( path, tail_bytes=size // 2 )
    head = read_backlog( path, since_offset=0, max_bytes=size // 2 )
    assert tail[ "offset" ] > head[ "offset" ], "tail_bytes read forward"
    assert tail[ "next_offset" ] == size
    assert tail[ "file_epoch" ]  == epoch_for_path( path )
    assert tail[ "blocks" ][ -1 ][ "text" ] == "block 19"


def test_read_backlog_before_offset_pages_earlier( seat ):
    """The load-earlier path."""
    path, _ = seat
    _write_records( path, 20 )
    size = os.path.getsize( path )
    tail = read_backlog( path, tail_bytes=size // 2 )

    earlier = read_backlog( path, before_offset=tail[ "offset" ], max_bytes=0 )
    assert earlier[ "offset" ] == 0
    assert earlier[ "next_offset" ] == tail[ "offset" ]
    assert earlier[ "blocks" ][ 0 ][ "text" ] == "block 0"


def test_read_backlog_since_offset_is_the_forward_repair( seat ):
    """The gap-repair path."""
    path, _ = seat
    _write_records( path, 6 )
    first = read_backlog( path, since_offset=0, max_bytes=120 )
    rest  = read_backlog( path, since_offset=first[ "next_offset" ], max_bytes=0 )
    assert rest[ "offset" ] == first[ "next_offset" ]
    assert rest[ "next_offset" ] == os.path.getsize( path )


def test_read_backlog_applies_the_budget_and_names_the_epoch( seat ):
    """The REST door budgets its blocks too, and reports the epoch they belong to."""
    path, _ = seat
    with open( path, "a" ) as f:
        f.write( json.dumps( {
            "type"    : "assistant",
            "message" : { "role": "assistant", "content": [ { "type": "text", "text": "q" * 300 } ] },
        } ) + "\n" )
    body = read_backlog( path, since_offset=0, budget=25 )
    assert body[ "blocks" ][ 0 ][ "truncated" ] is True
    assert len( body[ "blocks" ][ 0 ][ "text" ] ) == 25
    assert body[ "file_epoch" ] == epoch_for_path( path )


def test_read_backlog_on_a_missing_file_is_empty_not_an_error( tmp_path ):
    """A seat with no transcript answers empty, so the route returns 200 with nothing."""
    body = read_backlog( tmp_path / "gone.jsonl", since_offset=0 )
    assert body[ "blocks" ] == [ ]
    assert body[ "offset" ] == 0
    assert body[ "next_offset" ] == 0


def test_read_backlog_defaults_to_the_forward_read_when_given_nothing( seat ):
    """No direction named is the forward read from 0 — the least surprising default."""
    path, _ = seat
    _write_records( path, 3 )
    body = read_backlog( path )
    assert body[ "offset" ] == 0
    assert len( body[ "blocks" ] ) == 3


def test_the_three_directions_are_checked_in_a_stated_order( seat ):
    """
    Passing two directions is a caller error; the contract says the first wins.

    Asserted so the precedence is a decision on record rather than an accident of the `if`
    chain's order.
    """
    path, _ = seat
    _write_records( path, 20 )
    size = os.path.getsize( path )
    both = read_backlog( path, tail_bytes=size // 2, since_offset=0 )
    assert both[ "offset" ] > 0, "since_offset won over tail_bytes"


# ── the default bridge reader, and the loop's own exit ────────────────────────
#
# Both arms below were found by reading the coverage report's Missing column: every test above
# injects a bridge, so the REAL session-bridge import was never exercised, and every stop()
# cancels the task, so the loop's own `while self._running` exit was never taken. Honest
# account of provenance — neither gap was reasoned to.

def test_the_default_bridge_reader_is_the_real_per_seat_session_bridge_read( monkeypatch, tmp_path ):
    """
    With no reader injected, the resolver uses `session_bridge.find_session_by_id`.

    That function is the PER-SEAT read. `get_session_metadata()` resolves only the CALLING
    process and cannot answer for another seat, so wiring the wrong one would make every seat
    report the server's own transcript — a plausible-looking pane showing the wrong session.

    🔴 AND IT MUST BE CALLED exact=True, check_pid=False (row 27760534, 2026-09-28). The
    default prefix match can return a twin-prefix seat's transcript, and the pid check reads
    every host seat as dead from inside the container — which is how the live roster came to
    mark every seat unwatchable.
    """
    import lupin_cli.claude_code.hooks.lib.session_bridge as bridge_module

    transcript = tmp_path / "bridge.jsonl"
    transcript.write_text( "{}\n" )
    seen = { }

    def fake_find( session_id, *args, **kwargs ):
        seen[ "id" ]     = session_id
        seen[ "kwargs" ] = kwargs
        return { "transcript_path": str( transcript ) }

    monkeypatch.setattr( bridge_module, "find_session_by_id", fake_find )
    assert resolve_transcript_path( SEAT ) == str( transcript )
    assert seen[ "id" ] == SEAT
    assert seen[ "kwargs" ] == { "exact": True, "check_pid": False }


def test_a_bridge_path_this_process_cannot_see_is_not_watchable( tmp_path ):
    """
    A bridge can name a file this process cannot read — in the container, a path outside
    every mount. Liveness is answered by the file, so such a seat resolves to "".
    """
    missing = tmp_path / "nowhere" / "gone.jsonl"
    assert resolve_transcript_path( SEAT, lambda _: { "transcript_path": str( missing ) } ) == ""


def test_an_unimportable_session_bridge_yields_an_empty_path( monkeypatch ):
    """
    The tailer must degrade rather than explode where the bridge module is unavailable.

    Reached only with no injected reader, which is why every other test misses it.
    """
    import builtins
    real_import = builtins.__import__

    def refuse( name, *args, **kwargs ):
        if name == "lupin_cli.claude_code.hooks.lib.session_bridge":
            raise ImportError( "not importable here" )
        return real_import( name, *args, **kwargs )

    monkeypatch.setattr( builtins, "__import__", refuse )
    assert resolve_transcript_path( SEAT ) == ""


@pytest.mark.asyncio
async def test_the_loop_exits_on_its_own_when_running_goes_false( seat ):
    """
    The loop's own exit, taken without a cancel.

    `stop()` cancels the task, so the `while self._running` condition failing is never
    exercised by the lifecycle tests — yet it is the path taken if anything else clears the
    flag. A loop that only ever ends by cancellation would leave this untested and, if it
    spun instead of exiting, would burn a core silently.
    """
    path, bridge = seat
    emit   = EmitRecorder()
    tailer = CcTranscriptTailer( SEAT, emit, settings=_fast_settings(), bridge_reader=bridge )
    tailer.start()
    await asyncio.sleep( 0.03 )

    task = tailer._task
    tailer._running = False                                # clear the flag WITHOUT cancelling
    await asyncio.wait_for( task, timeout=1.0 )
    assert task.done()
    assert task.cancelled() is False, "the loop was cancelled rather than exiting on its own"
