"""
Unit tests for two cosa_voice_mcp tools whose bodies had no coverage:
`ask_open_ended_batch` and `set_session_topic`, plus the batch response parser.

Both are @mcp.tool FunctionTool objects, so the underlying callable is reached
via `.fn()` — the same convention as test_cosa_voice_task_store_wrappers.py.

WHY THESE MATTER
`set_session_topic` is the focus-bar's only input. A session that never pushes a
topic is INVISIBLE to the operator, so the failure modes here (no bridge, an
unwritable bridge, a UI push that quietly fails) decide whether a seat shows up
on the roster at all. `ask_open_ended_batch` is a BLOCKING ask — every one of its
non-zero exit paths is a case where a human is waiting and must be told what
happened rather than left holding an empty dict.

Venue: :7999-eligible — no server, no network, no state mutation. Every notify
call is injected and the bridge is a tmp file.
"""

import json

import pytest

import lupin_mcp.cosa_voice_mcp as cv


class _Resp:
    def __init__( self, exit_code, response_value=None ):
        self.exit_code      = exit_code
        self.response_value = response_value


QUESTIONS = [ { "question": "What topic?",  "header": "Topic"  },
              { "question": "What budget?", "header": "Budget" } ]


# ── the batch response parser ─────────────────────────────────────────────────

class TestParseOpenEndedBatchResponse:

    def test_a_well_formed_payload_passes_through( self ):
        got = cv._parse_open_ended_batch_response(
            json.dumps( { "answers": { "Topic": "quantum", "Budget": "10" } } ) )
        assert got == { "answers": { "Topic": "quantum", "Budget": "10" } }

    def test_no_response_value_is_an_empty_answer_set_not_an_error( self ):
        # The human answered nothing; that is a legitimate outcome, distinct from
        # a parse failure, and the caller should see an empty map.
        assert cv._parse_open_ended_batch_response( None ) == { "answers": {} }
        assert cv._parse_open_ended_batch_response( "" )   == { "answers": {} }

    def test_a_bare_json_list_is_wrapped_under_answers( self ):
        assert cv._parse_open_ended_batch_response( '["a", "b"]' ) == { "answers": [ "a", "b" ] }

    def test_unparseable_text_is_preserved_rather_than_discarded( self, caplog ):
        # A human typed something and it did not survive as JSON. Dropping it
        # would lose the only copy of the answer, so it is handed back verbatim.
        with caplog.at_level( "WARNING", logger=cv.logger.name ):
            got = cv._parse_open_ended_batch_response( "just plain text" )
        assert got == { "answers": { "response": "just plain text" } }
        assert "Could not parse open-ended batch response" in caplog.text


# ── ask_open_ended_batch ──────────────────────────────────────────────────────

class TestAskOpenEndedBatch:

    @pytest.mark.parametrize( "bad", [ [], None, "not a list", {} ] )
    def test_a_non_list_or_empty_question_set_is_rejected_before_any_ask( self, bad, monkeypatch ):
        def must_not_run( **k ):
            raise AssertionError( "no notification should be sent for invalid input" )
        monkeypatch.setattr( cv, "notify_user_sync", must_not_run )

        assert cv.ask_open_ended_batch.fn( bad ) == { "error": "questions must be a non-empty list" }

    def test_a_zero_exit_returns_the_parsed_answers( self, monkeypatch ):
        monkeypatch.setattr( cv, "_wait_for_sender_id", lambda: "claude.code@lupin.deepily.ai" )
        monkeypatch.setattr( cv, "notify_user_sync",
                             lambda request, debug: _Resp( 0, json.dumps( { "answers": { "Topic": "quantum" } } ) ) )

        assert cv.ask_open_ended_batch.fn( QUESTIONS ) == { "answers": { "Topic": "quantum" } }

    def test_a_timeout_is_reported_as_a_timeout_not_an_empty_answer( self, monkeypatch ):
        # exit_code 2 means the human never answered. Returning {"answers": {}}
        # here would be indistinguishable from them answering nothing.
        monkeypatch.setattr( cv, "_wait_for_sender_id", lambda: "claude.code@lupin.deepily.ai" )
        monkeypatch.setattr( cv, "notify_user_sync", lambda request, debug: _Resp( 2 ) )

        got = cv.ask_open_ended_batch.fn( QUESTIONS )
        assert got[ "timeout" ] is True
        assert "timeout" in got[ "error" ]

    def test_any_other_exit_code_returns_the_error_dict( self, monkeypatch ):
        monkeypatch.setattr( cv, "_wait_for_sender_id", lambda: "claude.code@lupin.deepily.ai" )
        monkeypatch.setattr( cv, "notify_user_sync", lambda request, debug: _Resp( 1 ) )
        monkeypatch.setattr( cv, "_error_dict", lambda r: { "error": f"exit {r.exit_code}" } )

        assert cv.ask_open_ended_batch.fn( QUESTIONS ) == { "error": "exit 1" }

    def test_a_bad_priority_is_a_validation_error_not_a_crash( self, monkeypatch ):
        monkeypatch.setattr( cv, "_wait_for_sender_id", lambda: "claude.code@lupin.deepily.ai" )
        def must_not_run( **k ):
            raise AssertionError( "must not reach the transport with an invalid request" )
        monkeypatch.setattr( cv, "notify_user_sync", must_not_run )

        got = cv.ask_open_ended_batch.fn( QUESTIONS, priority="not-a-priority" )
        assert "validation error" in got[ "error" ]

    def test_the_request_carries_an_idempotency_key_so_a_re_post_cannot_duplicate_the_card( self, monkeypatch ):
        # Bug f433fbae — without the stamp, a retried ask mints a second card and
        # the human sees the same question twice.
        seen = {}
        monkeypatch.setattr( cv, "_wait_for_sender_id", lambda: "claude.code@lupin.deepily.ai" )
        monkeypatch.setattr( cv, "notify_user_sync",
                             lambda request, debug: seen.update( req=request ) or _Resp( 0, None ) )

        cv.ask_open_ended_batch.fn( QUESTIONS )

        assert seen[ "req" ].idempotency_key                # stamped, non-empty


# ── set_session_topic ─────────────────────────────────────────────────────────

class TestSetSessionTopic:

    def _bridge( self, tmp_path, payload=None ):
        p = tmp_path / "cc-bridge.json"
        p.write_text( json.dumps( payload if payload is not None else { "session_id": "abcd1234" } ) )
        return p

    def test_no_bridge_file_is_an_explicit_error( self, monkeypatch ):
        # A session with no bridge cannot be put on the roster, and saying so
        # beats returning ok and staying invisible.
        monkeypatch.setattr( cv, "_get_cc_metadata", lambda: {} )
        assert cv.set_session_topic.fn( "anything" ) == {
            "status": "error", "reason": "No bridge file found" }

    def test_the_topic_is_written_to_the_bridge_and_pushed_to_the_ui( self, tmp_path, monkeypatch ):
        bridge = self._bridge( tmp_path )
        pushed = {}
        monkeypatch.setattr( cv, "_get_cc_metadata", lambda: { "_bridge_path": str( bridge ) } )
        monkeypatch.setattr( cv, "_notify_impl", lambda **k: pushed.update( k ) or "sent" )

        got = cv.set_session_topic.fn( "Bug Fix: WS queue crash" )

        assert got == { "status": "ok", "topic": "Bug Fix: WS queue crash", "ui_push": "ok" }
        assert json.loads( bridge.read_text() )[ "session_topic" ] == "Bug Fix: WS queue crash"
        assert pushed[ "notification_type" ] == "session_topic"
        assert pushed[ "suppress_ding" ] is True
        assert pushed[ "_internal_call" ] is True          # bypasses the conv-mode gate

    def test_existing_bridge_keys_survive_the_write( self, tmp_path, monkeypatch ):
        # The bridge is shared state; clobbering it would strip the session id
        # every other reader keys on.
        bridge = self._bridge( tmp_path, { "session_id": "abcd1234", "voice_persona": { "name": "sam" } } )
        monkeypatch.setattr( cv, "_get_cc_metadata", lambda: { "_bridge_path": str( bridge ) } )
        monkeypatch.setattr( cv, "_notify_impl", lambda **k: "sent" )

        cv.set_session_topic.fn( "New topic" )

        data = json.loads( bridge.read_text() )
        assert data[ "session_id" ] == "abcd1234"
        assert data[ "voice_persona" ] == { "name": "sam" }

    def test_a_long_topic_is_truncated_for_the_ui_but_stored_in_full( self, tmp_path, monkeypatch ):
        # The notification header has minimal room; the bridge does not. Losing
        # the full topic on disk would shorten it for every later reader too.
        bridge = self._bridge( tmp_path )
        pushed = {}
        monkeypatch.setattr( cv, "_get_cc_metadata", lambda: { "_bridge_path": str( bridge ) } )
        monkeypatch.setattr( cv, "_notify_impl", lambda **k: pushed.update( k ) or "sent" )

        long_topic = "T" * 100
        got = cv.set_session_topic.fn( long_topic )

        assert got[ "topic" ] == long_topic                            # full in the return
        assert json.loads( bridge.read_text() )[ "session_topic" ] == long_topic
        assert len( pushed[ "session_name" ] ) == 64                   # truncated for display
        assert pushed[ "session_name" ].endswith( "..." )

    def test_a_topic_at_the_limit_is_not_truncated( self, tmp_path, monkeypatch ):
        bridge = self._bridge( tmp_path )
        pushed = {}
        monkeypatch.setattr( cv, "_get_cc_metadata", lambda: { "_bridge_path": str( bridge ) } )
        monkeypatch.setattr( cv, "_notify_impl", lambda **k: pushed.update( k ) or "sent" )

        exact = "T" * 64
        cv.set_session_topic.fn( exact )

        assert pushed[ "session_name" ] == exact
        assert "..." not in pushed[ "session_name" ]

    @pytest.mark.parametrize( "failure", [ "[validation error] bad field", "Failed: server down" ] )
    def test_a_failed_ui_push_is_surfaced_rather_than_reported_as_ok( self, tmp_path, monkeypatch, caplog, failure ):
        """
        The bridge write succeeded but the operator's focus bar did not update.
        Reporting "ok" would leave the seat looking present on disk and missing
        on the roster, which is the confusion this field exists to prevent.
        """
        bridge = self._bridge( tmp_path )
        monkeypatch.setattr( cv, "_get_cc_metadata", lambda: { "_bridge_path": str( bridge ) } )
        monkeypatch.setattr( cv, "_notify_impl", lambda **k: failure )

        with caplog.at_level( "WARNING", logger=cv.logger.name ):
            got = cv.set_session_topic.fn( "a topic" )

        assert got[ "status" ]  == "ok"                    # the bridge DID get written
        assert got[ "ui_push" ] == failure                 # ...and the push did not
        assert "UI push failed" in caplog.text

    def test_an_unwritable_bridge_returns_the_reason_instead_of_raising( self, tmp_path, monkeypatch ):
        # This is called from the MCP tool surface; an exception here would
        # surface to the caller as a tool crash rather than a status.
        missing = tmp_path / "no" / "such" / "bridge.json"
        monkeypatch.setattr( cv, "_get_cc_metadata", lambda: { "_bridge_path": str( missing ) } )

        got = cv.set_session_topic.fn( "a topic" )

        assert got[ "status" ] == "error"
        assert got[ "reason" ]                              # carries the OS message


class TestAskMultipleChoiceRejectsNullBeforeLogging:
    """
    The same defect lived in `ask_multiple_choice`, which is why it is pinned
    here alongside its sibling rather than left for whoever trips it next: both
    tools logged `len( questions )` on the line ABOVE their own guard, so a null
    raised TypeError out of the MCP tool and the guard below never ran.
    """

    @pytest.mark.parametrize( "bad", [ None, [], 0, "" ] )
    def test_a_null_or_empty_question_set_returns_the_error_dict( self, bad, monkeypatch ):
        def must_not_run( **k ):
            raise AssertionError( "no notification should be sent for invalid input" )
        monkeypatch.setattr( cv, "notify_user_sync", must_not_run )

        assert cv.ask_multiple_choice.fn( bad ) == { "error": "questions must be a non-empty list" }

    def test_an_unsized_argument_does_not_raise_out_of_the_tool( self, monkeypatch ):
        # An int has no len(). Before the fix this was a TypeError escaping an
        # MCP tool call rather than a structured error the caller can read.
        def must_not_run( **k ):
            raise AssertionError( "must not reach the transport" )
        monkeypatch.setattr( cv, "notify_user_sync", must_not_run )

        assert cv.ask_multiple_choice.fn( 42 )[ "error" ]
        assert cv.ask_open_ended_batch.fn( 42 )[ "error" ]
