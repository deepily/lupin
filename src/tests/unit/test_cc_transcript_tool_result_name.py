#!/usr/bin/env python3
"""
Row 687310b7 — a tool_result block carries the `name` of the tool_call it answers.

The result lands in a LATER record than its call, and on the live path often in a later
POLL, so the pairing index must outlive one message and one poll. It must NOT outlive the
file it indexes, and it must never guess: a result whose call is not in view gets no `name`.

Every case enters at the real doors — `read_backlog` (REST) and `CcTranscriptTailer.poll_once`
(WS) — over the real captured transcripts, and the expected names are LITERALS counted from the
raw fixture JSONL, never taken from the mapper's own output.

Venue: :7999-eligible — no server, no network, writes only under tmp_path, sub-second.
"""

import json
import os
import shutil
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import cosa.rest.cc_transcript_mapper as mapper
from cosa.rest.cc_transcript_mapper import map_record, map_records, remember_tool_name
from cosa.rest.cc_transcript_tailer import CcTranscriptTailer, read_backlog

from test_cc_transcript_mapper import _read_jsonl   # noqa: E402  (the shared JSONL reader)

FIXTURE_DIR = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src", "tests", "fixtures", "cc_transcript" )
PRIMARY     = os.path.join( FIXTURE_DIR, "primary.jsonl" )
THINKING    = os.path.join( FIXTURE_DIR, "thinking.jsonl" )
SEAT        = "449359bc-c735-4970-8fc0-e83b635c8548"

# Counted from the raw JSONL, 2026-09-29: primary.jsonl has nine tool_use blocks and EIGHT
# tool_results (its last call, a dm_send, has no result inside the captured window).
PRIMARY_RESULT_NAMES  = [ "Bash", "mcp__cosa-voice___dm_send_fn", "mcp__cosa-voice___dm_send_fn", "mcp__cosa-voice__notify",
                          "Bash", "Bash", "Bash", "mcp__cosa-voice__task_amend" ]
THINKING_RESULT_NAMES = [ "Bash" ]


def _results( blocks ):
    return [ b for b in blocks if b[ "kind" ] == "tool_result" ]


def _names( blocks ):
    return [ b.get( "name" ) for b in _results( blocks ) ]


def _record_with_block( records, block_type ):
    """The first captured record carrying a content block of this type, and its index."""
    for index, record in enumerate( records ):
        content = ( record.get( "message" ) or {} ).get( "content" )
        if isinstance( content, list ) and any( isinstance( b, dict ) and b.get( "type" ) == block_type for b in content ):
            return index, record
    raise AssertionError( f"no {block_type} record in the fixture" )


# ── the pairing, over the real captured transcripts ───────────────────────────────────────

@pytest.mark.parametrize( "path,expected", [ ( PRIMARY, PRIMARY_RESULT_NAMES ), ( THINKING, THINKING_RESULT_NAMES ) ] )
def test_every_result_in_a_real_transcript_carries_its_calls_name( path, expected ):
    assert _names( map_records( _read_jsonl( path ) ) ) == expected
    assert len( expected ) > 0, "the census is empty, so the assertion above proved nothing"


def test_only_a_tool_result_gets_a_paired_name_and_a_tool_call_keeps_its_own( ):
    blocks = map_records( _read_jsonl( PRIMARY ) )
    assert all( "name" not in b for b in blocks if b[ "kind" ] in ( "text", "thinking" ) )
    assert all( "name" in b for b in blocks if b[ "kind" ] == "tool_call" )


def test_a_result_whose_call_is_not_in_view_gets_no_name_at_all( ):
    """The backlog window that starts after the call: drop the record holding the first tool_use."""
    records         = _read_jsonl( PRIMARY )
    first_call, _   = _record_with_block( records, "tool_use" )
    window          = records[ first_call + 1 : ]
    named           = _names( map_records( records ) )
    windowed        = _results( map_records( window ) )
    assert named[ 0 ] == "Bash"
    assert "name" not in windowed[ 0 ], "an orphan result was given a name"
    assert [ b.get( "name" ) for b in windowed[ 1: ] ] == PRIMARY_RESULT_NAMES[ 1: ], "orphaning one result disturbed the others"


@pytest.mark.parametrize( "raw", [
    { "type": "tool_result", "tool_use_id": "toolu_never_called", "content": "x" },
    { "type": "tool_result", "content": "no id at all" },
    { "type": "tool_result", "tool_use_id": None, "content": "null id" },
    { "type": "tool_result", "tool_use_id": 7, "content": "non-string id" },
    { "type": "tool_result", "tool_use_id": [ "toolu_1" ], "content": "unhashable id" },
] )
def test_an_unpairable_result_never_gets_a_guessed_name( raw ):
    block = map_record( { "type": "user", "message": { "role": "user", "content": [ raw ] } } )[ 0 ]
    assert "name" not in block


@pytest.mark.parametrize( "call", [
    { "type": "tool_use", "id": "toolu_a" },
    { "type": "tool_use", "id": "toolu_a", "name": "" },
    { "type": "tool_use", "id": "toolu_a", "name": None },
] )
def test_a_call_that_never_named_itself_does_not_lend_its_placeholder_to_the_result( call ):
    """The chip says "tool" for a nameless call; copying that onto the result would be a guess as a fact."""
    records = [
        { "type": "assistant", "message": { "role": "assistant", "content": [ call ] } },
        { "type": "user",      "message": { "role": "user", "content": [ { "type": "tool_result", "tool_use_id": "toolu_a", "content": "x" } ] } },
    ]
    blocks = map_records( records )
    assert blocks[ 0 ][ "name" ] == "tool"          # the call block itself: unchanged behaviour
    assert "name" not in blocks[ 1 ]


def test_a_call_and_its_result_inside_one_record_still_pair( ):
    record = { "type": "assistant", "message": { "role": "assistant", "content": [
        { "type": "tool_use", "id": "toolu_1", "name": "Read", "input": {} },
        { "type": "tool_result", "tool_use_id": "toolu_1", "content": "x" },
    ] } }
    assert [ b.get( "name" ) for b in map_record( record ) ] == [ "Read", "Read" ]


def test_a_caller_supplied_index_persists_across_calls_and_is_mutated_in_place( ):
    records        = _read_jsonl( PRIMARY )
    call_index, _  = _record_with_block( records, "tool_use" )
    result_index, _ = _record_with_block( records, "tool_result" )
    index          = { }
    map_records( records[ : result_index ], tool_names=index )
    assert index, "the caller's dict was not the one used"
    assert _names( map_records( records[ result_index : result_index + 1 ], tool_names=index ) )[ 0 ] == "Bash"
    assert "name" not in _results( map_records( records[ result_index : result_index + 1 ] ) )[ 0 ], "with no shared index the same result must be an orphan"


# ── the index is bounded, oldest out ─────────────────────────────────────────────────────

def test_the_index_evicts_the_oldest_pairing_past_its_cap( monkeypatch ):
    monkeypatch.setattr( mapper, "TOOL_NAME_CAP", 2 )
    index = { }
    for n in ( 1, 2, 3 ): remember_tool_name( index, f"toolu_{n}", f"Tool{n}" )
    assert list( index ) == [ "toolu_2", "toolu_3" ]

    records = [ { "type": "assistant", "message": { "role": "assistant", "content": [
                  { "type": "tool_use", "id": f"toolu_{n}", "name": f"Tool{n}", "input": {} } ] } } for n in ( 1, 2, 3 ) ]
    records.append( { "type": "user", "message": { "role": "user", "content": [
        { "type": "tool_result", "tool_use_id": "toolu_1", "content": "old" },
        { "type": "tool_result", "tool_use_id": "toolu_3", "content": "new" } ] } } )
    results = _results( map_records( records ) )
    assert "name" not in results[ 0 ], "an evicted pairing still answered"
    assert results[ 1 ][ "name" ] == "Tool3"


@pytest.mark.parametrize( "tool_use_id,name", [ ( None, "Bash" ), ( "", "Bash" ), ( 5, "Bash" ), ( "toolu_1", None ), ( "toolu_1", "" ), ( "toolu_1", 5 ) ] )
def test_remember_ignores_anything_that_is_not_a_pair_of_non_empty_strings( tool_use_id, name ):
    index = { }
    remember_tool_name( index, tool_use_id, name )
    assert index == { }


# ── the live door: a call and its result split across two POLLS ──────────────────────────

def _tailer( transcript, bridge_path=None ):
    holder = { "path": str( bridge_path or transcript ) }
    bridge = lambda cc_session_id: { "session_id": cc_session_id, "stable_session_id": SEAT, "transcript_path": holder[ "path" ] }
    tailer = CcTranscriptTailer( SEAT, None, settings={
        "poll_interval_seconds": 0.01, "grace_seconds": 0, "coalesce_window_ms": 0,
        "backlog_tail_bytes": 65536, "block_budget_bytes": 0, "ring_buffer_bytes": 1 << 20,
    }, bridge_reader=bridge )
    tailer.transcript_path = str( transcript )
    tailer.file_epoch      = SEAT
    tailer.offset          = 0
    return tailer, holder


def _append( path, *records ):
    with open( path, "a" ) as f:
        for record in records: f.write( json.dumps( record ) + "\n" )


def test_a_call_in_one_poll_names_its_result_in_the_next( tmp_path ):
    records         = _read_jsonl( PRIMARY )
    call_i, call    = _record_with_block( records, "tool_use" )
    result_i, result = _record_with_block( records, "tool_result" )
    path            = tmp_path / f"{SEAT}.jsonl"
    path.write_text( "" )
    tailer, _       = _tailer( path )

    _append( path, call )
    first = tailer.poll_once()
    assert [ b[ "kind" ] for b in first[ "blocks" ] ] == [ "tool_call" ] * len( first[ "blocks" ] )

    _append( path, result )
    second = tailer.poll_once()
    assert _names( second[ "blocks" ] ) == [ "Bash" ], second[ "blocks" ]


def test_a_result_polled_alone_is_an_orphan_and_carries_no_name( tmp_path ):
    """The live watch that began after the call (start(from_offset) mid-file)."""
    records       = _read_jsonl( PRIMARY )
    _, result     = _record_with_block( records, "tool_result" )
    path          = tmp_path / f"{SEAT}.jsonl"
    path.write_text( "" )
    tailer, _     = _tailer( path )
    _append( path, result )
    assert "name" not in _results( tailer.poll_once()[ "blocks" ] )[ 0 ]


def test_a_path_swap_forgets_the_old_files_calls( tmp_path ):
    """`/clear` is a new file at a new path: a call in the old one cannot answer a result in the new."""
    records          = _read_jsonl( PRIMARY )
    _, call          = _record_with_block( records, "tool_use" )
    _, result        = _record_with_block( records, "tool_result" )
    old              = tmp_path / f"{SEAT}.jsonl"
    old.write_text( "" )
    tailer, holder   = _tailer( old )
    _append( old, call )
    tailer.poll_once()
    assert tailer.tool_names, "precondition: the call was indexed"

    new = tmp_path / "11111111-2222-3333-4444-555555555555.jsonl"
    new.write_text( "" )
    holder[ "path" ] = str( new )
    assert tailer.poll_once()[ "rotated" ] is True
    assert tailer.tool_names == { }

    _append( new, result )
    assert "name" not in _results( tailer.poll_once()[ "blocks" ] )[ 0 ]


def test_an_in_place_truncation_forgets_the_calls_too( tmp_path ):
    records          = _read_jsonl( PRIMARY )
    _, call          = _record_with_block( records, "tool_use" )
    path             = tmp_path / f"{SEAT}.jsonl"
    path.write_text( "" )
    tailer, _        = _tailer( path )
    _append( path, call )
    tailer.poll_once()
    assert tailer.tool_names

    path.write_text( "" )                                 # truncated in place: offset now beyond the end
    assert tailer.poll_once()[ "rotated" ] is True
    assert tailer.tool_names == { }


def test_start_begins_with_an_empty_index( tmp_path ):
    import asyncio

    async def go():
        path = tmp_path / f"{SEAT}.jsonl"
        path.write_text( "" )
        tailer, _ = _tailer( path )
        tailer.tool_names[ "stale" ] = "Leftover"
        tailer.start( from_offset=0 )
        try:
            assert tailer.tool_names == { }
        finally:
            await tailer.stop()
    asyncio.run( go() )


# ── the two doors agree ──────────────────────────────────────────────────────────────────

def test_rest_and_ws_name_the_same_results_over_the_same_transcript( tmp_path ):
    records = _read_jsonl( PRIMARY )
    path    = tmp_path / f"{SEAT}.jsonl"
    shutil.copy( PRIMARY, path )

    rest = _names( read_backlog( str( path ), since_offset=0 )[ "blocks" ] )

    ws_path = tmp_path / "ws" / f"{SEAT}.jsonl"
    ws_path.parent.mkdir()
    ws_path.write_text( "" )
    tailer, _ = _tailer( ws_path )
    ws = [ ]
    for start in range( 0, len( records ), 3 ):           # three records per poll, splitting call/result pairs across polls
        _append( ws_path, *records[ start : start + 3 ] )
        polled = tailer.poll_once()
        if polled: ws.extend( _names( polled[ "blocks" ] ) )

    assert rest == PRIMARY_RESULT_NAMES
    assert ws   == PRIMARY_RESULT_NAMES
