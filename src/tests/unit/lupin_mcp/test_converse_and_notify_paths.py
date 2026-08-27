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

        # Speakerphone state is read LIVE from the session bridge, so an unpinned
        # test measures whichever box it runs on. Pinned OFF here: this is the arm
        # where an unrecognised value must reach validation untouched.
        import lupin_cli.claude_code.hooks.lib.session_bridge as sb
        monkeypatch.setattr( sb, "get_speakerphone", lambda sid: False )

        assert "validation error" in cv._notify_impl( "hello", notification_type="not-a-type" )

    def test_a_bad_priority_is_a_validation_error_not_a_crash( self, monkeypatch ):
        def must_not_run( **k ):
            raise AssertionError( "an invalid request must never reach the transport" )
        monkeypatch.setattr( cv, "notify_user_async", must_not_run )

        # Speakerphone state is read LIVE from the session bridge, so an unpinned
        # test measures whichever box it runs on. Pinned OFF here: this is the arm
        # where an unrecognised value must reach validation untouched.
        import lupin_cli.claude_code.hooks.lib.session_bridge as sb
        monkeypatch.setattr( sb, "get_speakerphone", lambda sid: False )

        assert "validation error" in cv._notify_impl( "hello", priority="not-a-priority" )

    def test_speakerphone_on_does_not_launder_an_unrecognised_priority( self, monkeypatch ):
        """
        The speakerphone arm of the same check — and the only one that exercises
        the lifting path at all.

        WHY IT EXISTS (row e2099400): speakerphone ON used to rewrite ANY priority
        outside ( "high", "urgent" ) to "high". An unrecognised value was rewritten
        along with the valid ones, so by the time NotificationPriority( priority )
        ran the bad value no longer existed — the call shipped HIGH and reported
        "Notification sent (delivered)". A priority nobody chose, delivered silently.

        The OFF-arm tests above cannot catch that: with speakerphone OFF the bad
        value is never rewritten, so they stay green against the defect. This one
        goes red against the old predicate and is the actual regression guard.

        Requires:
            - speakerphone reads True, so the lift branch is entered

        Ensures:
            - nothing reaches the transport
            - the caller is told, rather than getting a success string
        """
        import lupin_cli.claude_code.hooks.lib.session_bridge as sb
        shipped = []
        monkeypatch.setattr( cv, "_get_cc_metadata", lambda: { "session_id": "aaaaaaaa" } )
        monkeypatch.setattr( sb, "get_speakerphone", lambda sid: True )
        monkeypatch.setattr( cv, "_outbox_has_backlog", lambda: False )

        class _Sent:
            success = True
            status  = "delivered"
            message = ""
        # Capture rather than raise: asserting on WHAT SHIPPED names the corruption
        # ("shipped as high") instead of only reporting that something was sent.
        monkeypatch.setattr( cv, "notify_user_async",
                             lambda request, debug: shipped.append( request ) or _Sent() )

        result = cv._notify_impl( "hello", priority="not-a-priority" )

        assert not shipped, (
            "an unrecognised priority was laundered into a valid one and shipped as "
            f"{shipped[ 0 ].priority.value!r} — the lift must not rewrite a value "
            "that validation would have rejected"
        )
        assert "validation error" in result


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


class TestSoloChorusCrossTalkCue:
    """
    The last uncovered branch in `_notify_impl`, and the one whose two arms do
    OPPOSITE things to the same input.

    Setup: speakerphone OFF, a claude.code sender, and the caller asking for
    silent TTS. In SOLO only one session can hold speakerphone, so a silent-TTS
    notification from a phone-mode session is a leak symptom and the ding is
    forced back ON to make it audible. In CHORUS that same call is the normal
    pattern (this session is in phone mode while a sibling holds speakerphone),
    so suppress_ding is preserved. Inverting it there would ding the user on
    every routine notification.
    """

    @staticmethod
    def _arrange( monkeypatch, tts_mode ):
        import lupin_cli.claude_code.hooks.lib.session_bridge as sb
        import cosa.utils.util as _cu
        sent = {}
        monkeypatch.setattr( cv, "_get_cc_metadata", lambda: { "session_id": "aaaaaaaa" } )
        monkeypatch.setattr( sb, "get_speakerphone", lambda sid: False )     # speakerphone OFF
        if isinstance( tts_mode, Exception ):
            def boom():
                raise tts_mode
            monkeypatch.setattr( _cu, "get_tts_interaction_mode", boom )
        else:
            monkeypatch.setattr( _cu, "get_tts_interaction_mode", lambda: tts_mode )
        monkeypatch.setattr( cv, "_outbox_has_backlog", lambda: False )

        class _Sent:
            success = True
            status  = "delivered"
            message = ""
        monkeypatch.setattr( cv, "notify_user_async",
                             lambda request, debug: sent.update( req=request ) or _Sent() )
        return sent

    def test_solo_forces_the_ding_back_on_as_a_leak_cue( self, monkeypatch, caplog ):
        sent = self._arrange( monkeypatch, "solo" )
        with caplog.at_level( "INFO", logger=cv.logger.name ):
            cv._notify_impl( "hello", suppress_ding=True )
        assert sent[ "req" ].suppress_ding is False
        assert "solo cross-talk cue" in caplog.text

    def test_chorus_preserves_the_callers_silent_request( self, monkeypatch, caplog ):
        sent = self._arrange( monkeypatch, "chorus" )
        with caplog.at_level( "DEBUG", logger=cv.logger.name ):
            cv._notify_impl( "hello", suppress_ding=True )
        assert sent[ "req" ].suppress_ding is True
        assert "chorus passthrough" in caplog.text

    def test_an_unreadable_mode_defaults_to_chorus_and_stays_silent( self, monkeypatch ):
        # Defaulting to solo would ding the user on every routine notification
        # whenever the config was briefly unreadable.
        sent = self._arrange( monkeypatch, RuntimeError( "config unavailable" ) )
        cv._notify_impl( "hello", suppress_ding=True )
        assert sent[ "req" ].suppress_ding is True

    def test_speakerphone_on_forces_high_priority_and_strips_code_fences( self, monkeypatch ):
        # The other arm of the same branch: fenced code is TTS-hostile, and a
        # low-priority speakerphone message would never reach the listener.
        import lupin_cli.claude_code.hooks.lib.session_bridge as sb
        sent = {}
        monkeypatch.setattr( cv, "_get_cc_metadata", lambda: { "session_id": "aaaaaaaa" } )
        monkeypatch.setattr( sb, "get_speakerphone", lambda sid: True )
        monkeypatch.setattr( cv, "_outbox_has_backlog", lambda: False )

        class _Sent:
            success = True
            status  = "delivered"
            message = ""
        monkeypatch.setattr( cv, "notify_user_async",
                             lambda request, debug: sent.update( req=request ) or _Sent() )

        cv._notify_impl( "before\n```py\ncode()\n```\nafter",
                         priority="low", suppress_ding=False )

        req = sent[ "req" ]
        assert req.priority.value == "high"
        assert req.suppress_ding is True
        assert "code()" not in req.message


class TestSpokenBrevityUnitExtraction:
    """
    ⚠️ The enforce kill-switch is currently FALSE in this repo's config, so the
    guard is a no-op as configured and a test that relied on the ambient value
    would pass without exercising anything. These pin it ON explicitly, which
    both tests the real behavior and keeps the assertions independent of an INI
    that Rick can flip either way.
    """

    @pytest.fixture( autouse=True )
    def _enforced( self, monkeypatch ):
        monkeypatch.setattr( cv, "_get_spoken_enforce", lambda: True )
        monkeypatch.setattr( cv, "_get_spoken_char_cap", lambda: 500 )

    def test_a_question_list_is_measured_per_question( self ):
        # The list arm labels each unit so an over-long question names ITSELF
        # rather than the whole batch — otherwise the caller has to guess which.
        with pytest.raises( ValueError ) as ei:
            cv._enforce_spoken_brevity(
                [ { "question": "ok?" }, { "question": "x" * 550 } ],
                False, field="questions" )
        assert "questions[1].question" in str( ei.value )
        assert "override_size_limitation=True" in str( ei.value )

    def test_a_short_question_list_passes( self ):
        cv._enforce_spoken_brevity( [ { "question": "ok?" } ], False, field="questions" )

    def test_non_dict_entries_in_the_list_are_skipped_not_measured( self ):
        # A malformed entry must not crash the guard that runs before every ask.
        cv._enforce_spoken_brevity( [ "bare string", 42, { "question": "ok?" } ],
                                    False, field="questions" )

    def test_the_override_lets_a_long_message_through_deliberately( self ):
        cv._enforce_spoken_brevity( "x" * 550, True, field="message" )

    @pytest.mark.parametrize( "spoken", [ 42, { "question": "ok?" }, None ] )
    def test_a_value_that_is_neither_text_nor_a_question_list_is_left_alone( self, spoken ):
        # Nothing to measure, so nothing to reject. The guard runs ahead of every
        # ask and notify, so an unexpected type must fall through rather than
        # raise and take the call down with it.
        cv._enforce_spoken_brevity( spoken, False, field="message" )
