#!/usr/bin/env python3
"""
Unit tests for the shared transcript-JSONL reader (transcript_reader.py).

Covers read_transcript (parse/skip-malformed/skip-non-dict/missing/None/OSError)
and iter_tool_uses (assistant-only, content-list-only, tool_use-only, name
filter, input coercion, file order). Hermetic — tmp JSONL files only.

Venue: :7999-eligible / local — pure module, tmp-dir only, sub-second.
"""
import json
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib import transcript_reader as tr


def _write( tmp_path, lines ):
    p = tmp_path / "t.jsonl"
    p.write_text( "\n".join( lines ) )
    return str( p )


def _assistant( blocks ):
    return json.dumps( { "type": "assistant", "message": { "role": "assistant", "content": blocks } } )


# ── read_transcript ───────────────────────────────────────────────────────────

def test_read_parses_dict_lines_skips_noise( tmp_path ):
    p = _write( tmp_path, [
        json.dumps( { "type": "user", "x": 1 } ),
        "",                                   # blank
        "   ",                                # whitespace
        "{not valid json",                    # malformed
        json.dumps( [ 1, 2, 3 ] ),            # non-dict JSON
        json.dumps( "a string" ),             # non-dict JSON
        json.dumps( { "type": "assistant" } ),
    ] )
    objs = list( tr.read_transcript( p ) )
    assert [ o.get( "type" ) for o in objs ] == [ "user", "assistant" ]


def test_read_missing_file_returns_empty( tmp_path ):
    assert list( tr.read_transcript( str( tmp_path / "nope.jsonl" ) ) ) == [ ]


@pytest.mark.parametrize( "bad", [ None, "", 0 ] )
def test_read_falsey_path_returns_empty( bad ):
    assert list( tr.read_transcript( bad ) ) == [ ]


def test_read_oserror_returns_empty( tmp_path, monkeypatch ):
    """A path that exists but errors on open → empty, never raises."""
    p = _write( tmp_path, [ json.dumps( { "type": "user" } ) ] )

    def boom( *a, **k ):
        raise OSError( "disk gone" )

    monkeypatch.setattr( "builtins.open", boom )
    assert list( tr.read_transcript( p ) ) == [ ]


# ── iter_tool_uses ────────────────────────────────────────────────────────────

def test_iter_tool_uses_all_in_order( tmp_path ):
    p = _write( tmp_path, [
        _assistant( [
            { "type": "text", "text": "hi" },
            { "type": "tool_use", "name": "TaskCreate", "input": { "subject": "a" }, "id": "1" },
            { "type": "tool_use", "name": "Bash", "input": { "command": "ls" }, "id": "2" },
        ] ),
        _assistant( [
            { "type": "tool_use", "name": "TaskUpdate", "input": { "taskId": "1", "status": "completed" }, "id": "3" },
        ] ),
    ] )
    tools = list( tr.iter_tool_uses( p ) )
    assert [ t[ 0 ] for t in tools ] == [ "TaskCreate", "Bash", "TaskUpdate" ]
    assert tools[ 0 ][ 1 ] == { "subject": "a" }
    assert tools[ 0 ][ 2 ] == "1"


def test_iter_tool_uses_name_filter( tmp_path ):
    p = _write( tmp_path, [
        _assistant( [
            { "type": "tool_use", "name": "TaskCreate", "input": {}, "id": "1" },
            { "type": "tool_use", "name": "Bash", "input": {}, "id": "2" },
            { "type": "tool_use", "name": "TaskUpdate", "input": { "taskId": "1", "status": "pending" }, "id": "3" },
        ] ),
    ] )
    names = [ t[ 0 ] for t in tr.iter_tool_uses( p, names={ "TaskCreate", "TaskUpdate" } ) ]
    assert names == [ "TaskCreate", "TaskUpdate" ]


def test_iter_skips_non_assistant_and_bad_shapes( tmp_path ):
    p = _write( tmp_path, [
        json.dumps( { "type": "user", "message": { "content": [
            { "type": "tool_use", "name": "TaskCreate", "input": {}, "id": "u" } ] } } ),  # user → skipped
        json.dumps( { "type": "assistant", "message": "not-a-dict" } ),                     # message not dict
        json.dumps( { "type": "assistant", "message": { "content": "not-a-list" } } ),      # content not list
        _assistant( [
            "not-a-dict-block",                                                             # block not dict
            { "type": "text", "text": "x" },                                               # not tool_use
            { "type": "tool_use", "name": "Read", "id": "r" },                              # no input → {}
        ] ),
    ] )
    tools = list( tr.iter_tool_uses( p ) )
    assert tools == [ ( "Read", { }, "r" ) ]


def test_iter_input_non_dict_coerced_to_empty( tmp_path ):
    p = _write( tmp_path, [
        _assistant( [ { "type": "tool_use", "name": "X", "input": [ "list" ], "id": "i" } ] ),
    ] )
    assert list( tr.iter_tool_uses( p ) ) == [ ( "X", { }, "i" ) ]


def test_iter_none_path_empty():
    assert list( tr.iter_tool_uses( None ) ) == [ ]


# ── smoke entrypoint ──────────────────────────────────────────────────────────

def test_quick_smoke_test_passes():
    assert tr.quick_smoke_test() is True
