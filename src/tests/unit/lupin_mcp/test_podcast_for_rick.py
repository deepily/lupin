"""
Tests for the seat-side podcast tool.

Path translation runs against real git repositories. The ask, poll, start flow runs against a scripted
server at the request seam. Nothing here reaches a network or buys audio.
"""
import os
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from lupin_mcp import podcast_for_rick as pfr

START = datetime( 2026, 10, 8, 20, 0, 0, tzinfo=timezone.utc )


def _git( cwd, *args ):
    subprocess.run( [ "git", "-C", str( cwd ), *args ], check=True, capture_output=True,
                    env={ **os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e" } )


@pytest.fixture
def repos( tmp_path ):
    """A main checkout named lupin, plus a linked worktree with its own io/tmp file."""
    main = tmp_path / "lupin"
    ( main / "io" / "tmp" ).mkdir( parents=True )
    ( main / "io" / "tmp" / "x.md" ).write_text( "summary" )
    _git( main, "init", "-q" )
    _git( main, "commit", "-q", "--allow-empty", "-m", "first" )
    tree = main / ".claude" / "worktrees" / "seat-a"
    _git( main, "worktree", "add", "-q", "--detach", str( tree ) )
    ( tree / "io" / "tmp" ).mkdir( parents=True )
    ( tree / "io" / "tmp" / "y.md" ).write_text( "in a worktree" )
    return { "main": main, "tree": tree }


# ── path translation ────────────────────────────────────────────────────────

def test_a_file_in_a_main_checkout_becomes_scope_slash_relative( repos ):
    out = pfr.translate_host_path( str( repos[ "main" ] / "io" / "tmp" / "x.md" ) )
    assert out == { "status": "ok", "path": "lupin/io/tmp/x.md" }


def test_a_symlink_to_a_main_checkout_file_is_resolved_first( repos, tmp_path ):
    link = tmp_path / "link.md"
    link.symlink_to( repos[ "main" ] / "io" / "tmp" / "x.md" )
    assert pfr.translate_host_path( str( link ) )[ "path" ] == "lupin/io/tmp/x.md"


def test_a_relative_path_is_refused( repos ):
    assert pfr.translate_host_path( "io/tmp/x.md" )[ "reason" ] == "path_not_absolute"


def test_a_non_string_path_is_refused():
    assert pfr.translate_host_path( None )[ "reason" ] == "path_not_absolute"


def test_a_missing_file_is_refused_and_named( repos ):
    missing = str( repos[ "main" ] / "io" / "tmp" / "nope.md" )
    out = pfr.translate_host_path( missing )
    assert out[ "reason" ] == "file_not_found" and missing in out[ "detail" ]


def test_a_file_under_no_git_repository_is_refused( tmp_path ):
    loose = tmp_path / "loose.md"
    loose.write_text( "x" )
    assert pfr.translate_host_path( str( loose ), run_fn=lambda argv, cwd: None )[ "reason" ] == "outside_any_repo"


def test_a_file_inside_a_linked_worktree_is_refused_with_the_advice( repos ):
    out = pfr.translate_host_path( str( repos[ "tree" ] / "io" / "tmp" / "y.md" ) )
    assert out[ "reason" ] == "inside_a_worktree"
    assert "write it to the main checkout's io/tmp" in out[ "detail" ]


# ── the flow, against a scripted server ─────────────────────────────────────

class Server:
    """Scripted answers by (method, path); the clock moves only when the tool sleeps."""

    def __init__( self, ask, polls, start=None, facts=None ):
        self.ask, self.polls, self.start, self.facts = ask, list( polls ), start, facts
        self.calls, self.now = [], START

    def request( self, method, path, base, key, json_body=None, **_ ):
        self.calls.append( ( method, path, json_body ) )
        if path == pfr.PODCAST_ASK_PATH:   return self.ask
        if path == pfr.PODCAST_START_PATH: return self.start
        if path == pfr.CARD_FACTS_PATH.format( card_id="c1" ): return self.facts
        assert path == pfr.CARD_RESPONSE_PATH.format( card_id="c1" ), path
        return self.polls.pop( 0 ) if len( self.polls ) > 1 else self.polls[ 0 ]

    def sleep( self, seconds ): self.now += timedelta( seconds=seconds )
    def clock( self ):          return self.now

    def starts( self ): return [ c for c in self.calls if c[ 1 ] == pfr.PODCAST_START_PATH ]
    def asks( self ):   return [ c for c in self.calls if c[ 1 ] == pfr.PODCAST_ASK_PATH ]
    def polled( self ): return [ c for c in self.calls if c[ 1 ].startswith( "/api/notifications/response/" ) ]


def ASK( minutes=10, **over ):
    return { "card_id": "c1", "expires_at": ( START + timedelta( minutes=minutes ) ).isoformat(), "pushed": True, **over }


def ANSWER( value, source="keypress" ):
    return { "state": "responded", "response_value": { "value": value, "source": source }, "responded_at": "x" }


PENDING = { "state": "pending", "response_value": None, "responded_at": None }
ERROR   = { "status": "error", "reason": "server_unreachable", "detail": "down" }


def run( server, repos, path=True, card_id="" ):
    host = str( repos[ "main" ] / "io" / "tmp" / "x.md" ) if path else ""
    return pfr.podcast_for_rick_impl( "http://s", "key", "tiffany 641d31ee", host, card_id,
                                      request_fn=server.request, sleep_fn=server.sleep, now_fn=server.clock )


def FACTS( **over ):
    return { "card_id": "c1", "scope_path": "lupin/io/tmp/x.md", "state": "yes", "spent": False, "job_id": None,
             "expires_at": ( START + timedelta( minutes=10 ) ).isoformat(), **over }


def refusal( http_status, code, message="m" ):
    return { "status": "error", "http_status": http_status, "detail": { "code": code, "message": message } }


def test_a_yes_starts_the_job_exactly_once_with_the_card_id( repos ):
    server = Server( ASK(), [ PENDING, PENDING, ANSWER( "yes" ) ], start={ "job_id": "j9" } )
    out = run( server, repos )
    assert out == { "status": "started", "job_id": "j9", "card_id": "c1" }
    assert server.calls[ 0 ] == ( "POST", pfr.PODCAST_ASK_PATH, { "path": "lupin/io/tmp/x.md", "actor": "tiffany 641d31ee" } )
    assert server.starts() == [ ( "POST", pfr.PODCAST_START_PATH, { "card_id": "c1", "actor": "tiffany 641d31ee" } ) ]


def test_a_no_never_calls_start( repos ):
    server = Server( ASK(), [ ANSWER( "no" ) ] )
    assert run( server, repos ) == { "status": "declined", "card_id": "c1" }
    assert server.starts() == []


def test_a_neither_is_a_decline_not_a_yes( repos ):
    server = Server( ASK(), [ ANSWER( "neither" ) ] )
    assert run( server, repos )[ "status" ] == "declined" and server.starts() == []


def test_a_timed_out_default_never_calls_start_even_when_it_says_yes( repos ):
    server = Server( ASK(), [ ANSWER( "yes", source="timeout_default" ) ] )
    assert run( server, repos ) == { "status": "default_used", "card_id": "c1" }
    assert server.starts() == []


def test_an_answer_with_no_value_dict_is_a_decline( repos ):
    server = Server( ASK(), [ { "state": "responded", "response_value": None } ] )
    assert run( server, repos )[ "status" ] == "declined" and server.starts() == []


def test_an_unanswered_card_expires_at_the_servers_expiry( repos ):
    server = Server( ASK( minutes=1 ), [ PENDING ] )
    assert run( server, repos ) == { "status": "expired", "card_id": "c1" }
    assert server.now >= START + timedelta( minutes=1 ) and server.starts() == []


def test_a_zone_less_expiry_is_read_as_utc( repos ):
    zoneless = ( START + timedelta( minutes=1 ) ).replace( tzinfo=None ).isoformat()
    server = Server( ASK( expires_at=zoneless ), [ PENDING ] )
    assert run( server, repos )[ "status" ] == "expired"


def test_five_unreadable_polls_in_a_row_give_up_and_name_the_card( repos ):
    server = Server( ASK(), [ ERROR ] )
    out = run( server, repos )
    assert out[ "reason" ] == "card_unreadable" and out[ "card_id" ] == "c1" and server.starts() == []
    assert len( [ c for c in server.calls if c[ 0 ] == "GET" ] ) == pfr.POLL_FAILURE_LIMIT


def test_an_unreadable_poll_between_good_ones_does_not_accumulate( repos ):
    server = Server( ASK(), [ ERROR, ERROR, ERROR, ERROR, PENDING, ERROR, ERROR, ERROR, ERROR, ANSWER( "yes" ) ], start={ "job_id": "j" } )
    assert run( server, repos )[ "status" ] == "started"


@pytest.mark.parametrize( "ask", [ {}, { "card_id": "c1" }, { "card_id": "c1", "expires_at": 5 }, { "card_id": "c1", "expires_at": "not a time" }, { "expires_at": "2099-01-01T00:00:00+00:00" } ] )
def test_a_malformed_ask_answer_is_an_error_and_nothing_is_polled( repos, ask ):
    server = Server( ask, [ ANSWER( "yes" ) ] )
    out = run( server, repos )
    assert out[ "reason" ] == "ask_answer_malformed" and out[ "stage" ] == "ask"
    assert len( server.calls ) == 1


def test_a_refused_ask_passes_through_with_its_stage( repos ):
    refused = { "status": "error", "http_status": 400, "detail": "no such file lupin/io/tmp/x.md" }
    out = run( Server( refused, [] ), repos )
    assert out == { **refused, "stage": "ask" }


def test_a_waiting_card_for_the_same_file_is_named_not_asked_twice( repos ):
    out = run( Server( { "status": "error", "http_status": 409, "detail": "card abc waits" }, [] ), repos )
    assert out[ "reason" ] == "card_already_waiting" and out[ "detail" ] == "card abc waits"


def test_a_waiting_card_named_in_its_own_field_is_offered_for_resume( repos ):
    waiting = { "status": "error", "http_status": 409, "detail": { "code": "card_waiting", "message": "m", "card_id": "c7" } }
    out = run( Server( waiting, [] ), repos )
    assert out[ "reason" ] == "card_already_waiting" and out[ "card_id" ] == "c7" and "card_id=c7" in out[ "retry" ]


def test_a_refused_path_never_reaches_the_server( repos ):
    server = Server( ASK(), [] )
    out = pfr.podcast_for_rick_impl( "http://s", "key", "a", "relative.md", request_fn=server.request, sleep_fn=server.sleep, now_fn=server.clock )
    assert out[ "reason" ] == "path_not_absolute" and server.calls == []


def test_a_spent_card_is_named_and_start_is_not_retried( repos ):
    server = Server( ASK(), [ ANSWER( "yes" ) ], start=refusal( 409, "spent" ) )
    out = run( server, repos )
    assert out[ "reason" ] == "card_already_spent" and out[ "card_id" ] == "c1" and out[ "stage" ] == "start"
    assert len( server.starts() ) == 1


def test_any_other_refusal_of_start_passes_through_with_the_card( repos ):
    server = Server( ASK(), [ ANSWER( "yes" ) ], start=refusal( 409, "hash_mismatch" ) )
    out = run( server, repos )
    assert out == { **refusal( 409, "hash_mismatch" ), "reason": "hash_mismatch", "card_id": "c1", "stage": "start" }


def test_a_refusal_with_no_code_is_passed_through_without_a_reason( repos ):
    plain = { "status": "error", "http_status": 500, "detail": "boom" }
    out = run( Server( ASK(), [ ANSWER( "yes" ) ], start=plain ), repos )
    assert out == { **plain, "card_id": "c1", "stage": "start" } and "reason" not in out


def test_a_queue_failure_names_the_code_and_says_the_card_is_still_valid( repos ):
    out = run( Server( ASK(), [ ANSWER( "yes" ) ], start=refusal( 502, "queue_failed" ) ), repos )
    assert out[ "reason" ] == "queue_failed" and "card_id=c1" in out[ "retry" ]


def test_a_refused_ask_with_a_code_reports_the_code_as_the_reason( repos ):
    out = run( Server( refusal( 400, "file_refused" ), [] ), repos )
    assert out[ "reason" ] == "file_refused" and out[ "stage" ] == "ask"


# ── resume with a card_id ───────────────────────────────────────────────────

def test_resume_after_a_queue_failure_starts_once_without_asking_again( repos ):
    server = Server( None, [ ANSWER( "yes" ) ], start={ "card_id": "c1", "job_id": "j9", "status": "waiting" }, facts=FACTS() )
    out = run( server, repos, path=False, card_id="c1" )
    assert out[ "status" ] == "started" and out[ "job_id" ] == "j9"
    assert server.asks() == [] and len( server.starts() ) == 1


def test_resume_on_a_spent_card_names_the_job_and_starts_nothing( repos ):
    server = Server( None, [ ANSWER( "yes" ) ], start=refusal( 409, "spent" ), facts=FACTS( spent=True, job_id="j1" ) )
    out = run( server, repos, path=False, card_id="c1" )
    assert out[ "reason" ] == "card_already_spent" and out[ "job_id" ] == "j1" and "j1" in out[ "detail" ]
    assert server.asks() == [] and server.polled() == [] and server.starts() == []


def test_a_card_for_a_different_file_than_the_path_is_refused_before_any_poll( repos ):
    server = Server( None, [ ANSWER( "yes" ) ], start={ "job_id": "j" }, facts=FACTS( scope_path="lupin/io/tmp/other.md" ) )
    out = run( server, repos, card_id="c1" )
    assert out[ "reason" ] == "card_for_a_different_file" and "other.md" in out[ "detail" ]
    assert server.asks() == [] and server.polled() == [] and server.starts() == []


def test_a_card_for_the_same_file_as_the_path_resumes( repos ):
    server = Server( None, [ ANSWER( "yes" ) ], start={ "job_id": "j" }, facts=FACTS() )
    assert run( server, repos, card_id="c1" )[ "status" ] == "started"


def test_neither_a_path_nor_a_card_is_refused( repos ):
    server = Server( ASK(), [] )
    assert run( server, repos, path=False )[ "reason" ] == "path_or_card_required" and server.calls == []


def test_an_unreadable_card_stops_the_resume_with_its_code_and_stage( repos ):
    out = run( Server( None, [], facts=refusal( 404, "no_card" ) ), repos, path=False, card_id="c1" )
    assert out[ "reason" ] == "no_card" and out[ "stage" ] == "card" and out[ "card_id" ] == "c1"


def test_an_unreachable_server_on_resume_keeps_its_own_reason( repos ):
    out = run( Server( None, [], facts=ERROR ), repos, path=False, card_id="c1" )
    assert out[ "reason" ] == "server_unreachable" and out[ "stage" ] == "card"


def test_card_facts_with_no_expiry_are_malformed( repos ):
    out = run( Server( None, [], facts=FACTS( expires_at=None ) ), repos, path=False, card_id="c1" )
    assert out[ "reason" ] == "ask_answer_malformed"


# ── the registered tool ─────────────────────────────────────────────────────

import inspect

import lupin_mcp.cosa_voice_mcp as cv
from lupin_cli.claude_code.hooks.lib import session_bridge as sb


@pytest.fixture
def stamped( monkeypatch ):
    monkeypatch.setattr( cv, "_commons_persona_fields", lambda: { "persona_name": "tiffany", "persona_icon": "x", "persona_color": "#0F0" } )
    monkeypatch.setattr( cv, "SESSION_ID", "641d31ee" )
    monkeypatch.setattr( cv, "_get_server_url", lambda: "http://stub:7999" )
    monkeypatch.setattr( cv, "_mcp_outbound_api_key", lambda: "ck_live_stub" )
    monkeypatch.setattr( cv, "SESSION_ID_SOURCE", sb.SOURCE_PPID )


def test_the_tool_stamps_the_actor_and_passes_the_path_through( stamped, monkeypatch ):
    captured, sentinel = { }, { "status": "started" }
    monkeypatch.setattr( cv, "podcast_for_rick_impl", lambda **kwargs: captured.update( kwargs ) or sentinel )
    assert cv.podcast_for_rick.fn.sync( path="/abs/x.md", card_id="c1" ) is sentinel
    assert captured == { "api_base_url": "http://stub:7999", "api_key": "ck_live_stub", "actor": "tiffany 641d31ee", "host_path": "/abs/x.md", "card_id": "c1" }


def test_actor_is_not_a_tool_parameter():
    assert list( inspect.signature( cv.podcast_for_rick.fn ).parameters ) == [ "path", "card_id" ]


def test_a_borrowed_identity_is_refused_before_the_impl( stamped, monkeypatch ):
    monkeypatch.setattr( cv, "SESSION_ID_SOURCE", sb.SOURCE_CWD_FALLBACK )
    def _sentinel( **kwargs ): raise AssertionError( "reached the impl while wearing a borrowed identity" )
    monkeypatch.setattr( cv, "podcast_for_rick_impl", _sentinel )
    result = cv.podcast_for_rick.fn.sync( path="/abs/x.md" )
    assert result[ "reason" ] == "borrowed_identity" and "podcast_for_rick" in result[ "detail" ]


def test_the_tool_blocks_off_the_event_loop():
    assert hasattr( cv.podcast_for_rick.fn, "sync" ), "a human-waiting tool must be offloaded or it starves the session"
