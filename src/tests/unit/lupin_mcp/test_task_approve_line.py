"""
Tests for the one-click approve bullet: the Python builder, the MCP impl and the MCP verb.

The builder is checked against a real row id and by exact string.
The impl is checked against a faked server answer.
The verb is checked for the arguments it hands the impl.

Venue: runs on :7999. It needs no server, no network and no writes.
"""
import pytest
import requests

import lupin_mcp.cosa_voice_mcp as cv
from cosa.rest.task_approve_link import approve_link_line
from lupin_mcp.task_store_tools import task_approve_line_impl

ROW   = "a3975cf4-c640-4659-9247-0a99fa8a5f4a"
BASE  = "http://localhost:7999"
KEY   = "ck_live_test_key"


class _Resp:
    """A canned requests response."""
    def __init__( self, status, body ):
        self.status_code = status
        self._body       = body
        self.text        = str( body )
        self.ok          = status < 400

    def json( self ):
        return self._body


@pytest.fixture
def server( monkeypatch ):
    """Answer every request with the canned response and record the URLs asked."""
    asked = []

    def install( response ):
        def _fake( method, url, **kwargs ):
            asked.append( url )
            return response
        monkeypatch.setattr( requests, "request", _fake )
        return asked

    return install


class TestApproveLinkLine:

    def test_exact_format_for_a_real_row_id( self ):
        assert approve_link_line( ROW, "Fix the thing" ) == f"- Fix the thing [approve ☐](/app/tasks/approve?row={ROW}) [📄](/app/tasks/view?row={ROW})"

    def test_title_whitespace_collapses_and_brackets_are_escaped( self ):
        line = approve_link_line( ROW, "[LUPIN] Fix:\n  two   lines" )
        assert line == f"- \\[LUPIN\\] Fix: two lines [approve ☐](/app/tasks/approve?row={ROW}) [📄](/app/tasks/view?row={ROW})"
        assert "\n" not in line

    @pytest.mark.parametrize( "bad", [ "a3975cf4", "", ROW.upper(), ROW.replace( "-", "" ), "{" + ROW + "}", ROW + "0" ] )
    def test_a_malformed_row_id_is_refused( self, bad ):
        with pytest.raises( ValueError, match = "full lowercase UUID" ):
            approve_link_line( bad, "t" )

    @pytest.mark.parametrize( "blank", [ "", "   ", "\n\t" ] )
    def test_a_blank_title_is_refused( self, blank ):
        with pytest.raises( ValueError, match = "blank" ):
            approve_link_line( ROW, blank )

    def test_non_strings_are_refused( self ):
        with pytest.raises( TypeError, match = "row_id" ):
            approve_link_line( 5, "t" )
        with pytest.raises( TypeError, match = "title" ):
            approve_link_line( ROW, None )


class TestTaskApproveLineImpl:

    def test_builds_the_line_from_the_fetched_title( self, server ):
        asked = server( _Resp( 200, { "id": ROW, "title": "Fix the thing" } ) )
        assert task_approve_line_impl( BASE, KEY, ROW ) == { "line": approve_link_line( ROW, "Fix the thing" ) }
        assert asked == [ f"{BASE}/api/tasks/{ROW}" ], "the title came from the by-id row fetch"

    def test_a_malformed_id_asks_the_server_nothing( self, server ):
        asked  = server( _Resp( 200, { "title": "x" } ) )
        result = task_approve_line_impl( BASE, KEY, "a3975cf4" )
        assert result[ "error" ] == "invalid_row_id"
        assert asked == []

    def test_a_missing_row_returns_the_servers_error_not_a_line( self, server ):
        server( _Resp( 404, { "detail": f"task {ROW} not found" } ) )
        result = task_approve_line_impl( BASE, KEY, ROW )
        assert "line" not in result
        assert f"task {ROW} not found" in str( result )

    def test_a_blank_title_row_is_reported_not_linked( self, server ):
        server( _Resp( 200, { "id": ROW, "title": "  " } ) )
        assert task_approve_line_impl( BASE, KEY, ROW )[ "error" ] == "blank_title"

    def test_no_api_key_returns_the_transport_error( self, server ):
        server( _Resp( 200, { "title": "x" } ) )
        result = task_approve_line_impl( BASE, None, ROW )
        assert "line" not in result


class TestTaskApproveLineVerb:

    def test_the_verb_hands_the_impl_the_server_context( self, monkeypatch ):
        captured = {}
        monkeypatch.setattr( cv, "_get_server_url", lambda: "http://stub:7999" )
        monkeypatch.setattr( cv, "_mcp_outbound_api_key", lambda: "ck_live_stub" )
        monkeypatch.setattr( cv, "task_approve_line_impl", lambda **kw: captured.update( kw ) or { "line": "L" } )
        assert cv.task_approve_line.fn( task_id = ROW ) == { "line": "L" }
        assert captured == { "api_base_url": "http://stub:7999", "api_key": "ck_live_stub", "task_id": ROW }
