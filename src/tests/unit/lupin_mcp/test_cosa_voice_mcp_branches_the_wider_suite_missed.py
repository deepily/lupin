"""
Tests for the cosa_voice_mcp.py lines and branches the wider unit tier did not reach.

The gap was eleven lines and eight branches. Measured on 07852d4c5 over the 71 unit files that name the module: 98.66%, with these gaps. Each test below
drives one gap through the function that holds it, and says which assertion goes red when the line is deleted.

Venue: :7999-eligible. Module globals are monkeypatched and restored; no server, no network, no writes.
"""
import importlib
import sys
import threading

import pytest

import lupin_mcp.cosa_voice_mcp as cv
from lupin_cli.claude_code.hooks.lib import session_bridge as sb


@pytest.fixture( autouse=True )
def _isolate_session_globals( monkeypatch ):
    monkeypatch.setattr( cv, "SESSION_ID", "aaaaaaaa", raising=False )
    monkeypatch.setattr( cv, "SENDER_ID", "claude.code@lupin.deepily.ai#aaaaaaaa", raising=False )
    monkeypatch.setattr( cv, "_session_failed", True, raising=False )
    monkeypatch.setattr( cv, "_session_ready", threading.Event(), raising=False )


def test_a_session_id_guessed_from_the_working_directory_is_logged_as_a_guess( monkeypatch, caplog ):
    # red when: the warning is dropped, so a borrowed identity is adopted in silence
    monkeypatch.setattr( cv, "wait_for_session_id_with_source", lambda **k: ( "bbbbbbbb-1111", sb.SOURCE_CWD_FALLBACK ) )
    monkeypatch.setattr( cv, "_get_cc_metadata", lambda: { "source": "session_file" } )
    with caplog.at_level( "WARNING", logger=cv.logger.name ):
        cv._session_watcher_thread()
    assert "GUESSED from the working directory" in caplog.text and cv.SESSION_ID == "bbbbbbbb"


def test_a_reattempt_that_resolves_nothing_says_so_and_leaves_the_failure_flag( monkeypatch, caplog ):
    monkeypatch.setattr( cv, "wait_for_session_id_with_source", lambda **k: ( "", "ppid" ) )
    with caplog.at_level( "WARNING", logger=cv.logger.name ):
        assert cv._reattempt_session_resolution( 0.01 ) is False
    assert "returned nothing" in caplog.text and cv._session_failed is True and not cv._session_ready.is_set()


def test_a_reattempt_that_finds_the_same_seat_clears_the_failure_and_keeps_the_sender( monkeypatch ):
    # red when: the same suffix is treated as a change and the sender id is rebuilt
    monkeypatch.setattr( cv, "wait_for_session_id_with_source", lambda **k: ( "aaaaaaaa-1111", "ppid" ) )
    monkeypatch.setattr( cv, "_get_sender_id", lambda *a: pytest.fail( "the sender id was rebuilt for an unchanged seat" ) )
    assert cv._reattempt_session_resolution( 0.01 ) is True
    assert cv._session_failed is False and cv._session_ready.is_set() and cv.SESSION_ID == "aaaaaaaa"
    assert cv.SENDER_ID == "claude.code@lupin.deepily.ai#aaaaaaaa"


def test_a_reattempt_that_finds_another_seat_rebuilds_the_sender_id( monkeypatch ):
    monkeypatch.setattr( cv, "wait_for_session_id_with_source", lambda **k: ( "cccccccc-1111", "ppid" ) )
    assert cv._reattempt_session_resolution( 0.01 ) is True and cv.SESSION_ID == "cccccccc" and cv.SENDER_ID.endswith( "#cccccccc" )


# --- the spawn path ------------------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def spawn_seams( monkeypatch ):
    """Stub every seam of spawn_sessions below the refusal.

    Ensures:
        - returns the list that records each arming of the wake watch
    """
    from lupin_mcp import session_spawner
    armed = []
    monkeypatch.setattr( cv, "SESSION_ID_SOURCE", sb.SOURCE_PPID )
    monkeypatch.setattr( cv, "_wait_for_sender_id", lambda *a, **k: None )
    monkeypatch.setattr( cv, "_get_cc_metadata", lambda: {} )
    monkeypatch.setattr( cv, "_spawn_config_mgr", lambda: object() )
    monkeypatch.setattr( cv, "_spawn_script_path", lambda: "/spawn.sh" )
    monkeypatch.setattr( session_spawner, "resolve_manager_identity", lambda meta, fallback_session_id: ( "sid", "mr radio" ) )
    monkeypatch.setattr( session_spawner, "resolve_spawn_config", lambda mgr: { "spawn_models": {}, "spawn_cap": 8 } )
    monkeypatch.setattr( session_spawner, "spawn_sessions", lambda *a, **k: { "status": "ok", "spawned": [ { "session_name": "cc-seat-1" } ] } )
    monkeypatch.setattr( cv, "_arm_respin_wake_watch", lambda result, persona, fired_at: armed.append( ( result, persona, fired_at ) ) )
    return armed


def test_a_spawn_that_brings_a_seat_back_arms_the_wake_watch_once_with_the_fire_time_taken_before_the_launch( spawn_seams ):
    # red when: the arming line is deleted, or reads the clock after the launch
    result = cv.spawn_sessions.fn( count=1, task_prompt="x", seed_memento="/mementos/pocholo.md" )
    assert result[ "status" ] == "ok" and len( spawn_seams ) == 1
    armed_result, persona, fired_at = spawn_seams[ 0 ]
    assert armed_result is result and persona == "mr radio" and fired_at.tzinfo is not None


@pytest.mark.parametrize( "kwargs", [ { }, { "seed_memento": "/mementos/pocholo.md", "dry_run": True }, { "dry_run": True } ], ids=[ "fresh", "dry-run-with-seed", "dry-run" ] )
def test_a_fresh_spawn_and_a_dry_run_never_arm_the_wake_watch( spawn_seams, kwargs ):
    result = cv.spawn_sessions.fn( count=1, task_prompt="x", **kwargs )
    assert result[ "status" ] == "ok" and spawn_seams == []


# --- where a spawned seat's data lives -------------------------------------------------------------------------------------------------------

def test_a_spawn_record_with_no_project_has_no_data_root():
    assert cv._data_root_of_spawn_record( { "session_name": "cc-seat-1" } ) is None
    assert cv._data_root_of_spawn_record( None ) is None
    assert cv._data_root_of_spawn_record( { "project": "" } ) is None


def test_a_project_whose_repo_cannot_be_found_has_no_data_root( monkeypatch ):
    from lupin_mcp import session_spawner
    monkeypatch.setattr( session_spawner, "_resolve_project_root", lambda project: None )
    assert cv._data_root_of_spawn_record( { "project": "no-such-project" } ) is None


def test_a_data_root_that_cannot_be_resolved_is_none_and_never_raises( monkeypatch ):
    from lupin_cli.claude_code.hooks.lib import heartbeat_hold
    from lupin_mcp import session_spawner
    monkeypatch.setattr( session_spawner, "_resolve_project_root", lambda project: "/some/repo" )
    monkeypatch.setattr( heartbeat_hold, "fleet_data_root", lambda root: ( _ for _ in () ).throw( OSError( "gone" ) ) )
    assert cv._data_root_of_spawn_record( { "project": "lupin" } ) is None


# --- the promotion status verb ----------------------------------------------------------------------------------------------------------------

def test_task_promotion_status_hands_the_ticket_to_its_impl_with_the_server_and_key( monkeypatch ):
    # red when: the wrapper stops forwarding one of the three arguments
    seen = {}
    monkeypatch.setattr( cv, "_get_server_url", lambda: "http://server" )
    monkeypatch.setattr( cv, "_mcp_outbound_api_key", lambda: "key" )
    monkeypatch.setattr( cv, "task_promotion_status_impl", lambda **kw: seen.update( kw ) or { "status": "pending" } )
    assert cv.task_promotion_status.fn( ticket_id="t-1" ) == { "status": "pending" }
    assert seen == { "api_base_url": "http://server", "api_key": "key", "ticket_id": "t-1" }


# --- the call-log middleware that cannot be mounted ------------------------------------------------------------------------------------------

def test_a_call_log_middleware_that_cannot_be_imported_is_reported_on_stderr_and_the_server_still_loads( monkeypatch, capsys ):
    # red when: the except clause is removed, so a missing middleware takes the whole server down at import
    monkeypatch.setitem( sys.modules, "lupin_mcp.reuse_call_log_middleware", None )
    try:
        importlib.reload( cv )
        err = capsys.readouterr().err
        assert "reuse call-log middleware not mounted: ModuleNotFoundError" in err
    finally:
        monkeypatch.undo()
        importlib.reload( cv )


# --- the key a notification carries ----------------------------------------------------------------------------------------------------------

def test_a_notification_is_sent_and_spooled_under_one_idempotency_key( monkeypatch ):
    # red when: the key is not stamped before the send, so a durable retry looks like a new message to the server
    sent, spooled = [], []

    class _Failed:
        success, status, message = False, "failed", "server down"

    monkeypatch.setattr( cv, "_get_cc_metadata", lambda: {} )
    monkeypatch.setattr( cv, "_outbox_has_backlog", lambda: False )
    monkeypatch.setattr( cv, "notify_user_async", lambda request, debug: sent.append( request ) or _Failed() )
    monkeypatch.setattr( cv, "_spool_failed_notify", lambda request: spooled.append( request ) or True )
    assert cv._notify_impl( "hello" ).startswith( "Queued for durable retry" )
    assert len( sent ) == 1 and len( spooled ) == 1
    assert sent[ 0 ].idempotency_key and sent[ 0 ].idempotency_key == spooled[ 0 ].idempotency_key
