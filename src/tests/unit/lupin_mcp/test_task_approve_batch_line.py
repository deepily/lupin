"""
Tests for the one-click batch bullet: the Python builder, the MCP impl and the MCP verb.

The builder is checked by exact string against real-shaped row ids.
The impl is checked for its error shape, and for asking the server nothing.
The verb is checked for the arguments it hands the impl.

Venue: runs on :7999. It needs no server, no network and no writes.
"""
import pytest
import requests

import lupin_mcp.cosa_voice_mcp as cv
from cosa.rest.task_approve_link import approve_batch_line, parse_batch_row_ids
from lupin_mcp.task_store_tools import task_approve_batch_line_impl

A = "a3975cf4-c640-4659-9247-0a99fa8a5f4a"
B = "0b1c2d3e-4f50-4a61-8b72-93a4b5c6d7e8"


class TestParseBatchRowIds:

    def test_ids_come_back_in_order( self ):
        assert parse_batch_row_ids( [ B, A ] ) == [ B, A ]
        assert parse_batch_row_ids( ( A, B ) ) == [ A, B ]

    @pytest.mark.parametrize( "bad", [ "a3975cf4", "", A.upper(), A.replace( "-", "" ), "{" + A + "}" ] )
    def test_a_malformed_id_is_refused( self, bad ):
        with pytest.raises( ValueError, match = "full lowercase UUID" ):
            parse_batch_row_ids( [ A, bad ] )

    def test_an_empty_list_is_refused( self ):
        with pytest.raises( ValueError, match = "empty" ):
            parse_batch_row_ids( [] )

    def test_a_duplicate_id_is_refused( self ):
        with pytest.raises( ValueError, match = "appears twice" ):
            parse_batch_row_ids( [ A, B, A ] )

    def test_types_are_refused( self ):
        with pytest.raises( TypeError, match = "row_ids" ):
            parse_batch_row_ids( A )
        with pytest.raises( TypeError, match = "row_id " ):
            parse_batch_row_ids( [ A, 5 ] )


class TestApproveBatchLine:

    def test_exact_approve_line( self ):
        assert approve_batch_line( [ A, B ] ) == (
            f"- 2 held rows [approve all 2 ☐](/app/tasks/approve?rows={A},{B}&move=queued) [📋](/app/tasks/view?rows={A},{B})"
        )

    def test_exact_drop_line_encodes_the_reason( self ):
        line = approve_batch_line( [ A ], "dropped", "  duplicate (refile)\n& more " )
        assert line == (
            f"- 1 held rows [drop all 1 ☐](/app/tasks/approve?rows={A}&move=dropped&reason=duplicate%20%28refile%29%20%26%20more) [📋](/app/tasks/view?rows={A})"
        )

    def test_a_bad_move_is_refused( self ):
        with pytest.raises( ValueError, match = "move must be" ):
            approve_batch_line( [ A ], "done" )

    @pytest.mark.parametrize( "reason", [ None, "", "   ", 5 ] )
    def test_a_drop_without_a_real_reason_is_refused( self, reason ):
        with pytest.raises( ValueError, match = "non-blank reason" ):
            approve_batch_line( [ A ], "dropped", reason )

    def test_an_approve_with_a_reason_is_refused( self ):
        with pytest.raises( ValueError, match = "no reason" ):
            approve_batch_line( [ A ], "queued", "why" )

    def test_bad_ids_are_refused( self ):
        with pytest.raises( ValueError ):
            approve_batch_line( [ "a3975cf4" ] )


class TestImpl:

    def test_returns_the_line_and_asks_the_server_nothing( self, monkeypatch ):
        def _boom( *a, **k ): raise AssertionError( "the impl must not touch the network" )
        monkeypatch.setattr( requests, "request", _boom )
        assert task_approve_batch_line_impl( [ A, B ] ) == { "line": approve_batch_line( [ A, B ] ) }

    def test_a_drop_passes_move_and_reason_through( self ):
        assert task_approve_batch_line_impl( [ A ], "dropped", "dup" ) == { "line": approve_batch_line( [ A ], "dropped", "dup" ) }

    @pytest.mark.parametrize( "ids", [ [], [ "a3975cf4" ], [ A, A ], A ] )
    def test_every_bad_batch_is_an_error_dict( self, ids ):
        out = task_approve_batch_line_impl( ids )
        assert out[ "error" ] == "invalid_batch"
        assert out[ "detail" ] != ""


class TestVerb:

    def test_the_verb_hands_its_arguments_to_the_impl( self, monkeypatch ):
        seen = {}
        def _fake( **kwargs ):
            seen.update( kwargs )
            return { "line": "x" }
        monkeypatch.setattr( cv, "task_approve_batch_line_impl", _fake )
        out = cv.task_approve_batch_line.fn( task_ids = [ A, B ], move = "dropped", reason = "dup" )
        assert out == { "line": "x" }
        assert seen == { "task_ids": [ A, B ], "move": "dropped", "reason": "dup" }
