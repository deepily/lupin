"""
`cosa.agents.test_suite.v2_client` -- how callers submit a test suite now that
/api/test-suite/submit is retired (row a3c59f2d). Pure functions; the through-the-door
behaviour is in test_v2_submit_test_suite_through_path.py.
"""

from cosa.agents.test_suite.v2_client import TEST_SUITE_COMMAND, read_reply, submit_body


def test_a_minimal_body_carries_the_command_the_types_and_dry_run():
    assert submit_body( "e2e_a" ) == {
        "command": TEST_SUITE_COMMAND, "speak": False, "args": { "test_types": "e2e_a", "dry_run": False } }


def test_every_optional_field_lands_in_the_right_place():
    body = submit_body( "e2e_a,e2e_b", pytest_args="-k x", dry_run=True, auto_fix_on_failure=False,
                        env_vars={ "TFE_X": "1" }, scheduled_at="2026-01-01T00:00:00",
                        websocket_id="ws", parent_id_hash="p" )
    assert body[ "args" ] == { "test_types": "e2e_a,e2e_b", "dry_run": True, "pytest_args": "-k x",
                               "auto_fix_on_failure": False, "env_vars": { "TFE_X": "1" } }
    assert ( body[ "scheduled_at" ], body[ "websocket_id" ], body[ "parent_id_hash" ] ) == ( "2026-01-01T00:00:00", "ws", "p" )
    assert "monopolize" not in body


def test_auto_fix_none_is_omitted_but_false_is_kept():
    assert "auto_fix_on_failure" not in submit_body( "unit" )[ "args" ]
    assert submit_body( "unit", auto_fix_on_failure=False )[ "args" ][ "auto_fix_on_failure" ] is False


def test_empty_optionals_are_omitted():
    body = submit_body( "unit", pytest_args="", env_vars={ }, scheduled_at="", websocket_id="" )
    assert set( body[ "args" ] ) == { "test_types", "dry_run" }
    assert set( body ) == { "command", "args", "speak" }


def test_a_waiting_reply_is_ok_and_carries_the_old_fields():
    ok, info = read_reply( 200, { "status": "waiting", "job_id": "ts-1", "queue_position": 3, "answer": "queued" } )
    assert ok is True and info == { "status": "waiting", "job_id": "ts-1", "queue_position": 3,
                                    "message": "queued", "error": None }


def test_a_200_refusal_is_not_ok_and_names_the_cause():
    ok, info = read_reply( 200, { "status": "failed", "job_id": None, "error": "unknown test suite(s) ['e2e_ui']" } )
    assert ok is False and "e2e_ui" in info[ "error" ]


def test_a_200_with_no_error_text_still_names_the_status():
    ok, info = read_reply( 200, { "status": "needs_input" } )
    assert ok is False and "needs_input" in info[ "error" ]


def test_a_non_2xx_is_not_ok_and_uses_detail_or_the_code():
    assert read_reply( 410, { "detail": "GONE" } ) == ( False, {
        "status": None, "job_id": None, "queue_position": None, "message": "", "error": "GONE" } )
    assert read_reply( 502, None )[ 1 ][ "error" ] == "HTTP 502"


def test_a_message_falls_back_to_the_message_field():
    assert read_reply( 200, { "status": "waiting", "message": "m" } )[ 1 ][ "message" ] == "m"


# ── the builder wrapper (row a3c59f2d) ─────────────────────────────────────────

def test_the_refusing_wrapper_turns_a_valueerror_into_submit_refused_and_passes_everything_else():
    import pytest
    from cosa.rest.agentic_job_factory import _refusing_bad_input
    from cosa.rest.v2.refusal import SubmitRefused

    def bad( *a, **k ):     raise ValueError( "nope" )
    def refused( *a, **k ): raise SubmitRefused( "own_reason", "own" )
    def boom( *a, **k ):    raise KeyError( "k" )
    def fine( *a, **k ):    return ( a, k )

    with pytest.raises( SubmitRefused ) as caught:
        _refusing_bad_input( bad )()
    assert caught.value.route_reason == "submit_refused" and str( caught.value ) == "nope"
    with pytest.raises( SubmitRefused ) as own:
        _refusing_bad_input( refused )()
    assert own.value.route_reason == "own_reason"
    with pytest.raises( KeyError ):
        _refusing_bad_input( boom )()
    assert _refusing_bad_input( fine )( 1, x=2 ) == ( ( 1, ), { "x": 2 } )
    assert _refusing_bad_input( fine ).__name__ == "fine"
