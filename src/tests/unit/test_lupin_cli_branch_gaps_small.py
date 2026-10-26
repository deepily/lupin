"""
Tests for the last uncovered branches in five small lupin_cli modules.

:7999-eligible: no network, no DB. Each test names the branch it reaches and asserts the behaviour on it.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import lupin_cli.claude_code.hooks.lib.cc_notification_listener as listener_module
from lupin_cli.claude_code.hooks.lib import heartbeat_work_owed as owed
from lupin_cli.claude_code.hooks.lib import task_store_drain as drain
from lupin_cli.claude_code.hooks.lib.cc_notification_listener import CCNotificationListener
from cosa.rest.task_store_owed import PARK_STATUS
from lupin_cli.notifications.notify_user import notify_user


def _listener():
    return CCNotificationListener(
        email="service@lupin.deepily.ai", password="service-pass", session_id_hash="abc12345",
        tmux_session="test tmux", host="localhost", port=7999, debug=False, verbose=False,
    )


class TestListenerPlainStringAnswer:

    def test_non_dict_answer_is_buffered_verbatim( self ):
        # response_value is a bare string -> the isinstance( dict ) arm is skipped, not unwrapped.
        l = _listener()
        with patch.object( l, "_buffer_message" ) as buf, patch.object( listener_module, "append_surfaced_id" ):
            l._handle_answer_responded( { "data": { "job_id": "abc12345", "notification_id": "n1", "response_value": "maybe" } } )
        assert buf.call_args.args[ 0 ][ "message" ].endswith( "context only] maybe" )


class TestJoinSeriesAndPriorityClause:

    def test_join_series_empty_is_empty_string( self ):
        assert owed._join_series( [] ) == ""

    def test_unknown_priority_only_has_no_start_with_pointer( self ):
        # only a priority outside _PRIORITY_ORDER -> rendered, but nothing to "start with".
        line = owed.format_owed_summary( { "queued": 2 }, { "PX": 2 } )
        assert line == "2 owed: 2 queued · 2 at PX"


class TestDrainParityDefaultClock:

    def test_now_none_resolves_the_clock_inside( self ):
        session = { "session_id": "sid12345", "transcript_path": "/t.jsonl", "persona_lower": "k", "project": "lupin" }
        res = drain.check_session_parity(
            { "api_base_url": "http://t:7999", "timeout_seconds": 1.0 }, "key", session,
            now                 = None,
            _replay             = lambda _p: {},
            _current_generation = lambda _sid, _bd: 0,
            _query              = lambda s, k, ck: None,
        )
        assert ( res[ "transcript_owed" ], res[ "store_owed" ], res[ "parity" ] ) == ( 0, 0, True )


class TestNotifyUserEmptyErrorBody:

    def test_http_error_with_empty_body_prints_no_error_line( self ):
        resp = MagicMock( status_code=500, text="" )
        with patch( "lupin_cli.notifications.notify_user.requests.post", return_value=resp ), \
             patch( "builtins.print" ) as pr:
            assert notify_user( "hi", target_user="a@b.c", server_url="http://x" ) is False
        printed = [ c.args[ 0 ] for c in pr.call_args_list ]
        assert printed == [ "✗ Failed to send notification: HTTP 500" ]


class TestDrainParityExplicitClock:

    def test_an_explicit_now_is_used_as_given_and_never_replaced( self ):
        # a row parked until one second after the injected instant is still parked; against the real clock it would be owed
        seen = [ ]
        session = { "session_id": "sid12345", "transcript_path": "/t.jsonl", "persona_lower": "k", "project": "lupin" }
        fixed = datetime( 2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc )
        res = drain.check_session_parity(
            { "api_base_url": "http://t:7999", "timeout_seconds": 1.0 }, "key", session,
            now                 = fixed,
            _replay             = lambda _p: { "1": "in_progress" },
            _current_generation = lambda _sid, _bd: 0,
            _query              = lambda s, k, ck: seen.append( ck ) or ( True, 200, { "tasks": [ { "status": PARK_STATUS, "next_chase_ts": "2026-01-02T03:04:06+00:00" } ] } ),
        )
        assert ( res[ "transcript_owed" ], res[ "store_owed" ], res[ "parity" ] ) == ( 1, 0, False )     # parked until 1s after the injected now
        assert len( seen ) == 1
