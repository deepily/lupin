#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pins `task_store_client.fetch_board`, the board pager behind three scan scripts.

The pager asks for no more than the caller has room for and raises on a non-ok page.
It reports truncation. It takes its transport as a parameter, so each script keeps its patch seam.
"""

import os
import sys

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )

import pytest

from lupin_cli.claude_code.hooks.lib import task_store_client as tsc

SETTINGS = { "api_base_url": "http://store.test", "timeout_seconds": 3 }


def _pager( pages ):
    """Return ( request, calls ): a transport that answers the queued pages in order."""
    calls = [ ]
    queue = list( pages )
    def request( method, url, api_key, timeout, body=None ):
        calls.append( ( method, url, api_key, timeout ) )
        return queue.pop( 0 )
    return request, calls


def _page( ids, has_more=False ):
    return True, 200, { "tasks": [ { "id": i } for i in ids ], "has_more": has_more }


def test_one_page_returns_its_rows_and_no_truncation():
    request, calls = _pager( [ _page( [ "a", "b" ] ) ] )
    rows, truncated = tsc.fetch_board( SETTINGS, "key", 100, request=request )
    assert [ r[ "id" ] for r in rows ] == [ "a", "b" ] and truncated is False
    assert calls[ 0 ] == ( "GET", "http://store.test/api/tasks?include_terminal=true&unscoped_audit=true"
                                  "&hide_parked=false&limit=100&offset=0", "key", 3 )


def test_include_terminal_false_says_false_in_the_query():
    request, calls = _pager( [ _page( [ ] ) ] )
    assert tsc.fetch_board( SETTINGS, "key", 5, include_terminal=False, request=request ) == ( [ ], False )
    assert "include_terminal=false" in calls[ 0 ][ 1 ]


def test_later_pages_ask_for_the_room_left_and_advance_the_offset():
    request, calls = _pager( [ _page( [ "a", "b" ], has_more=True ), _page( [ "c" ] ) ] )
    rows, truncated = tsc.fetch_board( SETTINGS, "key", 3, request=request )
    assert [ r[ "id" ] for r in rows ] == [ "a", "b", "c" ] and truncated is False
    assert "limit=3&offset=0" in calls[ 0 ][ 1 ] and "limit=1&offset=2" in calls[ 1 ][ 1 ]


def test_a_cap_above_one_page_still_asks_for_only_a_page():
    request, calls = _pager( [ _page( [ "a" ] ) ] )
    tsc.fetch_board( SETTINGS, "key", 5000, request=request )
    assert f"limit={tsc.FETCH_BOARD_PAGE_SIZE}&" in calls[ 0 ][ 1 ] and tsc.FETCH_BOARD_PAGE_SIZE == 500


def test_hitting_max_rows_with_more_available_reports_truncation():
    request, calls = _pager( [ _page( [ "a", "b" ], has_more=True ) ] )
    rows, truncated = tsc.fetch_board( SETTINGS, "key", 2, request=request )
    assert len( rows ) == 2 and truncated is True and len( calls ) == 1


def test_an_empty_batch_stops_the_loop_even_when_has_more_is_set():
    request, calls = _pager( [ _page( [ ], has_more=True ) ] )
    assert tsc.fetch_board( SETTINGS, "key", 10, request=request ) == ( [ ], False )
    assert len( calls ) == 1


def test_a_non_positive_cap_still_asks_for_one_row():
    request, calls = _pager( [ _page( [ "a" ] ) ] )
    tsc.fetch_board( SETTINGS, "key", 0, request=request )
    assert "limit=1&" in calls[ 0 ][ 1 ]


@pytest.mark.parametrize( "page,expected", [
    ( ( False, 401, { "detail": "bad key" } ),   "HTTP 401: bad key" ),
    ( ( False, None, { "error": "refused" } ),   "HTTP None: refused" ),
    ( ( False, 500, { "other": 1 } ),            "HTTP 500: {'other': 1}" ),
] )
def test_a_non_ok_page_raises_rather_than_returning_an_empty_board( page, expected ):
    request, _calls = _pager( [ page ] )
    with pytest.raises( RuntimeError, match = "^" + expected.replace( "{", r"\{" ).replace( "}", r"\}" ) ):
        tsc.fetch_board( SETTINGS, "key", 10, request=request )


def test_without_a_request_argument_it_uses_the_module_request_looked_up_at_call_time( monkeypatch ):
    request, calls = _pager( [ _page( [ "a" ] ) ] )
    monkeypatch.setattr( tsc, "_request", request )
    assert tsc.fetch_board( SETTINGS, "key", 10 )[ 0 ] == [ { "id": "a" } ]
    assert len( calls ) == 1
