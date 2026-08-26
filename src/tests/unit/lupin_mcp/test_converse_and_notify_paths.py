"""
Unit tests for the outcome paths of `converse`, `notify` / `_notify_impl`, and
`_parse_multiple_choice_response`.

WHAT THESE PATHS HAVE IN COMMON
They are the branches taken when something did not go to plan: a request that
fails validation, an ask that timed out, a response that would not parse, a
session bridge that could not be read. Each one is the difference between the
caller learning what happened and the caller getting a string that reads like an
answer. None of them had coverage.

Venue: :7999-eligible — no server, no network, no state mutation.
"""

import json

import pytest

import lupin_mcp.cosa_voice_mcp as cv


class _Resp:
    def __init__( self, exit_code, response_value=None, default_used=False, status="failed" ):
        self.exit_code      = exit_code
        self.response_value = response_value
        self.default_used   = default_used
        self.status         = status


@pytest.fixture( autouse=True )
def _stable_sender( monkeypatch ):
    monkeypatch.setattr( cv, "_wait_for_sender_id", lambda: "claude.code@lupin.deepily.ai#aaaaaaaa" )


# ── converse outcomes ─────────────────────────────────────────────────────────

class TestConverseOutcomes:

    def test_an_answer_is_returned_bare( self, monkeypatch ):
        monkeypatch.setattr( cv, "notify_user_sync", lambda request, debug: _Resp( 0, "yes please" ) )
        assert cv.converse.fn( "Ship it?" ) == "yes please"

    def test_a_default_used_answer_is_marked_so_the_caller_knows_nobody_typed_it( self, monkeypatch ):
        # Without the marker an auto-filled default is indistinguishable from a
        # human's answer, which is the whole reason the marker exists.
        monkeypatch.setattr( cv, "notify_user_sync",
                             lambda request, debug: _Resp( 0, "yes", default_used=True ) )
        got = cv.converse.fn( "Ship it?" )
        assert got.startswith( cv.DEFAULT_USED_MARKER )
        assert got.endswith( "yes" )

    def test_an_empty_answer_does_not_become_the_string_none( self, monkeypatch ):
        monkeypatch.setattr( cv, "notify_user_sync", lambda request, debug: _Resp( 0, None ) )
        assert cv.converse.fn( "Ship it?" ) == ""

    def test_a_timeout_with_a_default_returns_the_default_and_says_so( self, monkeypatch ):
        monkeypatch.setattr( cv, "notify_user_sync", lambda request, debug: _Resp( 2 ) )
        got = cv.converse.fn( "Ship it?", response_default="no" )
        assert "timeout - using default" in got
        assert got.endswith( "no" )

    def test_a_timeout_with_no_default_says_nothing_came_back( self, monkeypatch ):
        monkeypatch.setattr( cv, "notify_user_sync", lambda request, debug: _Resp( 2 ) )
        assert cv.converse.fn( "Ship it?" ) == "[timeout - no response received]"

    def test_any_other_exit_code_reports_the_status( self, monkeypatch ):
        monkeypatch.setattr( cv, "notify_user_sync",
                             lambda request, debug: _Resp( 1, status="transport_error" ) )
        assert cv.converse.fn( "Ship it?" ) == "[error: transport_error]"

    def test_a_bad_priority_is_caught_before_the_transport( self, monkeypatch ):
        def must_not_run( **k ):
            raise AssertionError( "an invalid request must never reach the transport" )
        monkeypatch.setattr( cv, "notify_user_sync", must_not_run )
        assert "validation error" in cv.converse.fn( "Ship it?", priority="nope" )


# ── the multiple-choice response parser ───────────────────────────────────────

class TestParseMultipleChoiceResponse:

    def test_a_well_formed_payload_passes_through( self ):
        got = cv._parse_multiple_choice_response( json.dumps( { "answers": { "DB": "PostgreSQL" } } ) )
        assert got == { "answers": { "DB": "PostgreSQL" } }

    def test_no_response_value_is_an_empty_answer_set( self ):
        assert cv._parse_multiple_choice_response( None ) == { "answers": {} }
        assert cv._parse_multiple_choice_response( "" )   == { "answers": {} }

    def test_a_bare_json_list_is_wrapped_under_answers( self ):
        assert cv._parse_multiple_choice_response( '["a"]' ) == { "answers": [ "a" ] }

    def test_unparseable_text_is_handed_back_rather_than_dropped( self, caplog ):
        with caplog.at_level( "WARNING", logger=cv.logger.name ):
            got = cv._parse_multiple_choice_response( "PostgreSQL" )
        assert got == { "answers": { "response": "PostgreSQL" } }
        assert "Could not parse multiple choice response" in caplog.text


# ── _notify_impl fallbacks ────────────────────────────────────────────────────

class TestNotifyImplFallbacks:

    def test_an_unreadable_bridge_falls_back_to_the_module_session_id( self, monkeypatch ):
        """
        Session-id resolution here is best-effort: it only decides which seat's
        speakerphone state to read. Raising would cost the notification itself,
        which is a far worse trade than reading a slightly stale id.
        """
        class _Sent:
            success = True
            status  = "delivered"
            message = ""

        def boom():
            raise RuntimeError( "bridge unreadable" )
        monkeypatch.setattr( cv, "_get_cc_metadata", boom )
        monkeypatch.setattr( cv, "_outbox_has_backlog", lambda: False )
        monkeypatch.setattr( cv, "notify_user_async", lambda request, debug: _Sent() )

        got = cv._notify_impl( "hello" )                    # must not raise
        assert got == "Notification sent (delivered)"

    def test_a_send_failure_is_spooled_for_durable_retry_rather_than_lost( self, monkeypatch ):
        # A notification that cannot be delivered right now is still owed. The
        # spool is what stops "the server blinked" from becoming "nobody was told".
        class _Failed:
            success = False
            status  = "error"
            message = "server down"

        monkeypatch.setattr( cv, "_outbox_has_backlog", lambda: False )
        monkeypatch.setattr( cv, "notify_user_async", lambda request, debug: _Failed() )
        monkeypatch.setattr( cv, "_spool_failed_notify", lambda request: True )

        assert cv._notify_impl( "hello" ) == "Queued for durable retry (server down)"

    def test_a_send_failure_that_cannot_be_spooled_reports_the_failure( self, monkeypatch ):
        class _Failed:
            success = False
            status  = "error"
            message = "server down"

        monkeypatch.setattr( cv, "_outbox_has_backlog", lambda: False )
        monkeypatch.setattr( cv, "notify_user_async", lambda request, debug: _Failed() )
        monkeypatch.setattr( cv, "_spool_failed_notify", lambda request: False )

        assert cv._notify_impl( "hello" ) == "Failed: server down"

    def test_an_existing_backlog_queues_behind_it_to_preserve_order( self, monkeypatch ):
        # Sending live while a backlog drains would deliver this message BEFORE
        # older ones, which is the FIFO inversion the spool exists to prevent.
        def must_not_send( **k ):
            raise AssertionError( "must not send live while a backlog exists" )
        monkeypatch.setattr( cv, "_outbox_has_backlog", lambda: True )
        monkeypatch.setattr( cv, "_spool_failed_notify", lambda request: True )
        monkeypatch.setattr( cv, "notify_user_async", must_not_send )

        assert cv._notify_impl( "hello" ) == "Queued (ordered behind backlog)"

    def test_a_bad_notification_type_is_a_validation_error_not_a_crash( self, monkeypatch ):
        def must_not_run( **k ):
            raise AssertionError( "an invalid request must never reach the transport" )
        monkeypatch.setattr( cv, "notify_user_async", must_not_run )

        assert "validation error" in cv._notify_impl( "hello", notification_type="not-a-type" )

    def test_a_bad_priority_is_a_validation_error_not_a_crash( self, monkeypatch ):
        def must_not_run( **k ):
            raise AssertionError( "an invalid request must never reach the transport" )
        monkeypatch.setattr( cv, "notify_user_async", must_not_run )

        assert "validation error" in cv._notify_impl( "hello", priority="not-a-priority" )


class TestNotifyToolDelegates:
    def test_notify_enforces_brevity_then_delegates_to_the_impl( self, monkeypatch ):
        # `notify` is a thin wrapper; the only thing it adds before delegating is
        # the spoken-brevity guard, so that is what this pins.
        seen = {}
        monkeypatch.setattr( cv, "_enforce_spoken_brevity",
                             lambda msg, override, field: seen.update( msg=msg, field=field ) )
        monkeypatch.setattr( cv, "_notify_impl", lambda **k: seen.update( impl=k ) or "sent" )

        assert cv.notify.fn( "a message", priority="low" ) == "sent"
        assert seen[ "field" ] == "message"
        assert seen[ "msg" ]   == "a message"
        assert seen[ "impl" ][ "priority" ] == "low"
