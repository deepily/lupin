#!/usr/bin/env python3
"""
Row 4559be88 — every tool_call block carries the tool's `name`, on REST and on WS.

Both doors funnel through `cc_transcript_mapper.map_records`: REST via
`read_backlog`, WS via `CcTranscriptTailer.poll_once` -> `_flush`. The tests enter at those
two doors, over REAL captured transcripts (`primary.jsonl`, `thinking.jsonl`), not a hand-
written record — the expected names are pinned to LITERALS taken from the fixtures'
`tool_use` blocks, never derived from the mapper's own output.

Venue: :7999-eligible — no server, no network, writes only under tmp_path, sub-second.
"""

import asyncio
import os
import shutil
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.cc_transcript_mapper import map_record, map_records
from cosa.rest.cc_transcript_tailer import CcTranscriptTailer, APPEND_EVENT, read_backlog

from test_cc_transcript_mapper import _read_jsonl   # noqa: E402  (the shared JSONL reader)

FIXTURE_DIR = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src", "tests", "fixtures", "cc_transcript" )
PRIMARY     = os.path.join( FIXTURE_DIR, "primary.jsonl" )
THINKING    = os.path.join( FIXTURE_DIR, "thinking.jsonl" )
SEAT        = "449359bc-c735-4970-8fc0-e83b635c8548"

# Literal census of the `tool_use` blocks in each captured file, counted from the raw JSONL
# on 2026-09-29 (not from the mapper).
PRIMARY_TOOL_NAMES  = [ "Bash", "mcp__cosa-voice___dm_send_fn", "mcp__cosa-voice___dm_send_fn", "mcp__cosa-voice__notify",
                        "Bash", "Bash", "Bash", "mcp__cosa-voice__task_amend", "mcp__cosa-voice___dm_send_fn" ]
THINKING_TOOL_NAMES = [ "Bash" ]


class _Recorder:
    """An in-memory `emit`, recording every frame in order."""
    def __init__( self ): self.frames = [ ]
    async def __call__( self, cc_session_id, event_name, payload ): self.frames.append( ( event_name, payload ) )


def _tool_calls( blocks ):
    return [ b for b in blocks if b[ "kind" ] == "tool_call" ]


@pytest.mark.parametrize( "path,expected", [ ( PRIMARY, PRIMARY_TOOL_NAMES ), ( THINKING, THINKING_TOOL_NAMES ) ] )
def test_the_mapper_names_every_tool_call_in_a_real_transcript( path, expected ):
    calls = _tool_calls( map_records( _read_jsonl( path ) ) )
    assert [ b.get( "name" ) for b in calls ] == expected
    assert len( expected ) > 0, "the census is empty, so the loop above proved nothing"


def test_the_name_and_the_chip_text_agree( ):
    for block in _tool_calls( map_records( _read_jsonl( PRIMARY ) ) ):
        assert block[ "text" ].startswith( f"{block[ 'name' ]}( " ), block[ "text" ][ :60 ]


def test_only_tool_calls_carry_a_name( ):
    blocks = map_records( _read_jsonl( PRIMARY ) )
    others = [ b for b in blocks if b[ "kind" ] != "tool_call" ]
    assert len( others ) > 0 and len( _tool_calls( blocks ) ) == len( PRIMARY_TOOL_NAMES )
    assert all( "name" not in b for b in others ), sorted( { b[ "kind" ] for b in others if "name" in b } )


def test_a_tool_call_with_no_name_falls_back_to_the_chips_word( ):
    for content in ( { "type": "tool_use" }, { "type": "tool_use", "name": "" }, { "type": "tool_use", "name": None } ):
        block = map_record( { "type": "assistant", "message": { "role": "assistant", "content": [ content ] } } )[ 0 ]
        assert block[ "name" ] == "tool" and block[ "text" ] == "tool(  )"


def test_rest_backlog_carries_the_name( tmp_path ):
    copy = tmp_path / f"{SEAT}.jsonl"
    shutil.copy( PRIMARY, copy )
    served = read_backlog( str( copy ), since_offset=0 )
    assert [ b[ "name" ] for b in _tool_calls( served[ "blocks" ] ) ] == PRIMARY_TOOL_NAMES


def test_the_ws_append_frame_carries_the_name( tmp_path ):
    copy = tmp_path / f"{SEAT}.jsonl"
    shutil.copy( PRIMARY, copy )
    bridge = lambda cc_session_id: { "session_id": cc_session_id, "stable_session_id": SEAT, "transcript_path": str( copy ) }
    emit   = _Recorder()
    tailer = CcTranscriptTailer( SEAT, emit, settings={
        "poll_interval_seconds": 0.01, "grace_seconds": 0, "coalesce_window_ms": 0,
        "backlog_tail_bytes": 65536, "block_budget_bytes": 0, "ring_buffer_bytes": 1 << 20,
    }, bridge_reader=bridge )
    tailer.transcript_path = str( copy )
    tailer.file_epoch      = SEAT
    tailer.offset          = 0

    polled = tailer.poll_once()
    asyncio.run( tailer._flush( 0, polled[ "next_offset" ], polled[ "blocks" ] ) )

    frames = [ payload for name, payload in emit.frames if name == APPEND_EVENT ]
    assert len( frames ) == 1
    assert [ b[ "name" ] for b in _tool_calls( frames[ 0 ][ "blocks" ] ) ] == PRIMARY_TOOL_NAMES
