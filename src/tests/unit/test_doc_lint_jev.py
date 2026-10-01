"""
The Jev judge back end: the HTTP door, the probability-to-verdict mapping, escalation and fail-closed.

The fake post function reads the request it is handed and answers from it: the probability it
returns depends on how many of the claim's words occur in the state, so a verdict that ignored its
input would not survive. One fixture is a response captured from the real API (jev-1.13.0).
"""

import asyncio
import json
import pathlib
import re
import threading
from collections import namedtuple
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock

from cosa.repo.doc_lint import claim_judge, harness_cli, harness_report, harness_runner, jev_judge, jev_transport

FIXTURE = pathlib.Path( __file__ ).parent / "fixtures" / "jev" / "noul-response-jev-1.13.0.json"
KEY     = "test-key-never-printed"
ENV     = { jev_transport.KEY_VARIABLE: KEY }
MODEL   = "jev-1.13.0"

C = namedtuple( "C", [ "text", "quote", "start", "end" ], defaults=( 0, 0 ) )


def reply( noul, model=MODEL ):
    return json.dumps( { "model": model, "answers": { jev_transport.QUESTION_ID: { "type": "noul", "noul": noul } } } )


def haystack_noul( request ):
    """Probability from the request itself: the share of the claim's words found in the state."""
    body   = json.loads( request )
    claim  = body[ "questions" ][ jev_transport.QUESTION_ID ][ "instructions" ].split( ": ", 1 )[ -1 ]
    state  = json.dumps( body[ "state" ] ).lower()
    words  = re.findall( r"[a-z]+", claim.lower() )
    return sum( 1 for w in words if w in state ) / len( words )


def fake_post( calls=None ):
    def post( url, headers, body, timeout ):
        if calls is not None: calls.append( ( url, headers, body, timeout ) )
        return 200, reply( haystack_noul( body ) )
    return post


def scripted_post( statuses, calls=None ):
    queue = list( statuses )
    def post( url, headers, body, timeout ):
        if calls is not None: calls.append( url )
        status = queue.pop( 0 )
        return status, reply( 0.9 ) if status == 200 else "overloaded"
    return post


def ask( post, sleeps=None, environ=ENV, model=MODEL ):
    return jev_transport.ask_noul( model, { "new_text": "x" }, "q", jev_judge.CRITERIA, post_fn=post,
                                   sleep_fn=( sleeps.append if sleeps is not None else ( lambda s: None ) ), environ=environ )


# ---- transport ----------------------------------------------------------------------------

def test_the_captured_real_response_parses():
    noul, model = jev_transport.parse_answer( FIXTURE.read_text(), MODEL )
    assert ( noul, model ) == ( 0.97, "jev-1.13.0" )


def test_the_request_body_has_the_documented_shape():
    body = json.loads( jev_transport.build_body( MODEL, { "new_text": "t" }, "does it", { "true": "yes", "false": "no" } ) )
    assert body == { "state": { "new_text": "t" }, "model": MODEL,
                     "questions": { "claim_stated": { "type": "noul", "instructions": "does it",
                                                      "criteria": { "true": "yes", "false": "no" } } } }


def test_the_key_travels_only_in_the_authorization_header():
    calls = []
    ask( fake_post( calls ) )
    url, headers, body, timeout = calls[ 0 ]
    assert url == jev_transport.URL and timeout == jev_transport.TIMEOUT_SECONDS
    assert headers[ "Authorization" ] == "Bearer " + KEY
    assert KEY not in body.decode()


def test_a_missing_or_empty_key_refuses_before_any_call():
    calls = []
    for env in ( {}, { jev_transport.KEY_VARIABLE: "" } ):
        with pytest.raises( jev_transport.JevConfigError, match=jev_transport.KEY_VARIABLE ):
            ask( fake_post( calls ), environ=env )
    assert calls == []


def test_the_real_environment_is_read_when_none_is_given( monkeypatch ):
    monkeypatch.setenv( jev_transport.KEY_VARIABLE, KEY )
    assert jev_transport.ask_noul( MODEL, {}, "q", jev_judge.CRITERIA, post_fn=fake_post() ) is not None
    monkeypatch.delenv( jev_transport.KEY_VARIABLE )
    with pytest.raises( jev_transport.JevConfigError ):
        jev_transport.ask_noul( MODEL, {}, "q", jev_judge.CRITERIA, post_fn=fake_post() )


def test_an_empty_model_id_is_refused():
    with pytest.raises( ValueError, match="no default" ):
        ask( fake_post(), model="" )


def test_retry_on_429_then_success_waits_with_doubling_backoff():
    sleeps, calls = [], []
    noul, _ = ask( scripted_post( [ 429, 529, 200 ], calls ), sleeps )
    assert noul == 0.9 and len( calls ) == 3
    assert sleeps == [ jev_transport.BACKOFF_SECONDS, jev_transport.BACKOFF_SECONDS * 2 ]


def test_retries_are_bounded_and_the_last_failure_does_not_sleep():
    sleeps, calls = [], []
    with pytest.raises( jev_transport.JevCallError, match="still answered a retry status" ):
        ask( scripted_post( [ 429 ] * 10, calls ), sleeps )
    assert len( calls ) == jev_transport.MAX_ATTEMPTS
    assert len( sleeps ) == jev_transport.MAX_ATTEMPTS - 1


@pytest.mark.parametrize( "status", [ 401, 403, 422 ] )
def test_a_refused_key_or_request_is_a_configuration_error_and_not_retried( status ):
    calls = []
    with pytest.raises( jev_transport.JevConfigError, match=str( status ) ):
        ask( scripted_post( [ status ], calls ) )
    assert len( calls ) == 1


def test_any_other_status_is_a_call_error_without_retry():
    calls = []
    with pytest.raises( jev_transport.JevCallError, match="status 500" ):
        ask( scripted_post( [ 500 ], calls ) )
    assert len( calls ) == 1


def test_a_network_error_is_a_call_error_that_does_not_carry_the_key():
    def post( url, headers, body, timeout ): raise ConnectionError( "Bearer " + KEY )
    with pytest.raises( jev_transport.JevCallError ) as caught:
        ask( post )
    assert KEY not in str( caught.value )


@pytest.mark.parametrize( "text, match", [
    ( "not json",                                                "expected shape" ),
    ( json.dumps( { "model": MODEL, "answers": {} } ),           "expected shape" ),
    ( json.dumps( [ 1 ] ),                                       "expected shape" ),
    ( reply( 1.5 ),                                              "0 to 1" ),
    ( reply( -0.1 ),                                             "0 to 1" ),
    ( reply( "0.9" ),                                            "0 to 1" ),
    ( reply( True ),                                             "0 to 1" ),
    ( reply( 0.9, model="jev-2.0.0" ),                           "asked for model" ),
] )
def test_an_unusable_body_is_a_call_error( text, match ):
    with pytest.raises( jev_transport.JevCallError, match=match ):
        jev_transport.parse_answer( text, MODEL )


def test_the_boundary_values_zero_and_one_are_accepted():
    assert jev_transport.parse_answer( reply( 0 ), MODEL )[ 0 ] == 0.0
    assert jev_transport.parse_answer( reply( 1 ), MODEL )[ 0 ] == 1.0


class _Handler( BaseHTTPRequestHandler ):
    def do_POST( self ):
        self.rfile.read( int( self.headers[ "Content-Length" ] ) )
        status = 200 if self.path == "/ok" else 429
        payload = ( reply( 0.5 ) if status == 200 else "slow down" ).encode()
        self.send_response( status )
        self.end_headers()
        self.wfile.write( payload )
    def log_message( self, *args ): pass


def test_the_real_http_door_returns_status_and_text_for_ok_and_for_an_error_status():
    server = ThreadingHTTPServer( ( "127.0.0.1", 0 ), _Handler )
    thread = threading.Thread( target=server.serve_forever, daemon=True )
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[ 1 ]}"
        assert jev_transport._post( base + "/ok", {}, b"{}", 5 ) == ( 200, reply( 0.5 ) )
        assert jev_transport._post( base + "/busy", {}, b"{}", 5 ) == ( 429, "slow down" )
    finally:
        server.shutdown()
        server.server_close()


def test_the_default_post_and_sleep_are_used_when_none_are_given( monkeypatch ):
    seen = []
    monkeypatch.setattr( jev_transport, "_post", lambda url, headers, body, timeout: ( seen.append( url ) or ( 200, reply( 0.2 ) ) ) )
    assert jev_transport.ask_noul( MODEL, {}, "q", jev_judge.CRITERIA, environ=ENV )[ 0 ] == 0.2
    waits = []
    monkeypatch.setattr( jev_transport.time, "sleep", waits.append )
    monkeypatch.setattr( jev_transport, "_post", scripted_post( [ 429, 200 ] ) )
    jev_transport.ask_noul( MODEL, {}, "q", jev_judge.CRITERIA, environ=ENV )
    assert seen == [ jev_transport.URL ] and waits == [ jev_transport.BACKOFF_SECONDS ]


# ---- thresholds and the mapping -----------------------------------------------------------

@pytest.mark.parametrize( "noul, verdict", [
    ( 1.0, "present" ), ( 0.8, "present" ), ( 0.79, "uncertain" ), ( 0.5, "uncertain" ),
    ( 0.21, "uncertain" ), ( 0.2, "absent" ), ( 0.0, "absent" ),
] )
def test_each_band_edge_belongs_to_the_outer_band( noul, verdict ):
    assert jev_judge.verdict_for( noul, 0.2, 0.8 ) == verdict


@pytest.mark.parametrize( "lo, hi", [ ( 0.5, 0.5 ), ( 0.9, 0.1 ), ( -0.1, 0.5 ), ( 0.2, 1.1 ), ( None, 0.5 ), ( 0.2, "0.8" ) ] )
def test_bad_thresholds_are_refused( lo, hi ):
    with pytest.raises( ValueError, match="thresholds" ):
        jev_judge.check_thresholds( lo, hi )


def test_the_extreme_thresholds_zero_and_one_are_allowed():
    jev_judge.check_thresholds( 0, 1 )


def test_the_state_holds_the_design_document_only_when_there_is_one():
    assert jev_judge.build_state( "new", None ) == { "new_text": "new" }
    assert jev_judge.build_state( "new", "design" ) == { "new_text": "new", "design_doc": "design" }


# ---- the judge ----------------------------------------------------------------------------

def claude_query( answers, calls=None ):
    """Escalation stand-in: answers each claim from the table by its text, so the verdict follows the input."""
    async def query( prompt, options ):
        if calls is not None: calls.append( ( options.model, prompt ) )
        listed = re.search( r"<claims_(\w+)>\n(.*?)\n</claims_\1>", prompt, re.DOTALL ).group( 2 )
        texts  = [ line.split( ". ", 1 )[ 1 ] for line in listed.splitlines() ]
        yield AssistantMessage( content=[ TextBlock( json.dumps( { "verdicts": [
            { "id": n, "verdict": answers[ t ] } for n, t in enumerate( texts, start=1 ) ] } ) ) ], model=options.model )
    return query


def run( claims, new, design=None, post=None, answers=None, calls=None, lo=0.3, hi=0.8 ):
    return asyncio.run( jev_judge.judge_claims_jev( claims, new, design, MODEL, lo, hi, "opus-x",
                                                    query_fn=claude_query( answers or {}, calls ),
                                                    post_fn=post or fake_post(), sleep_fn=lambda s: None, environ=ENV ) )


STATED  = C( "returns none when parked", "q1" )
DROPPED = C( "raises valueerror when blank", "q2" )


def test_verdicts_follow_the_new_text_and_the_design_doc():
    both  = run( [ STATED, DROPPED ], "It returns none when parked and raises valueerror when blank." )
    one   = run( [ STATED, DROPPED ], "It returns none when parked." )
    moved = run( [ STATED, DROPPED ], "It returns none when parked.", design="raises valueerror when blank" )
    assert [ j.verdict for j in both.judgements ] == [ "present", "present" ]
    assert [ j.verdict for j in one.judgements ]  == [ "present", "absent" ]
    assert [ j.verdict for j in moved.judgements ] == [ "present", "present" ]


def test_scores_and_the_model_string_are_reported():
    result = run( [ STATED, DROPPED ], "It returns none when parked." )
    assert result.model == MODEL
    assert result.scores[ 0 ] == 1.0 and result.scores[ 1 ] == pytest.approx( 1 / 4 )
    assert [ j.noul for j in result.judgements ] == result.scores


def test_a_mid_band_claim_escalates_and_the_escalation_answer_stands():
    mid   = C( "returns none when maybe parked", "q3" )        # 4 of 5 words in the text: 0.8 is present, so use 3 of 5
    calls = []
    result = run( [ mid ], "returns none parked", answers={ mid.text: "present" }, calls=calls )
    assert result.scores == [ 0.6 ]
    assert [ ( j.verdict, j.escalated ) for j in result.judgements ] == [ ( "present", True ) ]
    assert [ m for m, _ in calls ] == [ "opus-x" ]


def test_a_claim_still_uncertain_after_escalation_fails_closed_to_absent():
    mid    = C( "returns none when maybe parked", "q3" )
    result = run( [ mid ], "returns none parked", answers={ mid.text: "uncertain" } )
    assert [ ( j.verdict, j.reason ) for j in result.judgements ] == [ ( "absent", "still uncertain after escalation" ) ]


def test_confident_claims_never_reach_the_escalation_model():
    calls = []
    run( [ STATED, DROPPED ], "It returns none when parked.", calls=calls )
    assert calls == []


def test_a_jev_outage_on_one_claim_escalates_that_claim_alone():
    outcomes = iter( [ ( 200, reply( 0.95 ) ), ( 500, "boom" ) ] )
    post     = lambda url, headers, body, timeout: next( outcomes )
    calls    = []
    result   = run( [ STATED, DROPPED ], "text", post=post, answers={ DROPPED.text: "present" }, calls=calls )
    assert [ j.verdict for j in result.judgements ] == [ "present", "present" ]
    assert [ j.escalated for j in result.judgements ] == [ False, True ]
    assert result.scores == [ 0.95, None ]
    assert len( calls ) == 1


def test_a_jev_outage_that_escalation_does_not_rescue_keeps_the_jev_failure_as_the_reason():
    post   = lambda url, headers, body, timeout: ( 500, "boom" )
    result = run( [ STATED ], "text", post=post, answers={ STATED.text: "uncertain" } )
    j = result.judgements[ 0 ]
    assert j.verdict == "absent" and j.reason.startswith( "jev gave no answer" ) and "status 500" in j.reason


def test_a_missing_key_is_not_a_verdict_it_raises():
    with pytest.raises( jev_transport.JevConfigError ):
        asyncio.run( jev_judge.judge_claims_jev( [ STATED ], "t", None, MODEL, 0.3, 0.8, "opus-x",
                                                 query_fn=claude_query( {} ), post_fn=fake_post(), environ={} ) )


def test_an_empty_claim_list_makes_no_call():
    calls = []
    result = run( [], "text", post=fake_post( calls ) )
    assert result == jev_judge.JevResult( [], None, [] ) and calls == []


def test_model_ids_and_thresholds_are_required():
    for jev, esc in ( ( "", "opus-x" ), ( MODEL, "" ) ):
        with pytest.raises( ValueError, match="no default" ):
            asyncio.run( jev_judge.judge_claims_jev( [ STATED ], "t", None, jev, 0.3, 0.8, esc ) )
    with pytest.raises( ValueError, match="thresholds" ):
        asyncio.run( jev_judge.judge_claims_jev( [ STATED ], "t", None, MODEL, 0.8, 0.3, "opus-x" ) )


def test_the_prompt_version_changes_with_the_code_it_names():
    assert jev_judge.PROMPT_VERSION.startswith( "jev-" ) and len( jev_judge.PROMPT_VERSION ) == len( "jev-" ) + 10


# ---- the back end and the runner ----------------------------------------------------------

def make_backend( post=None, lo=0.3, hi=0.8 ):
    return jev_judge.JevBackend( MODEL, lo, hi, "opus-x", post_fn=post or fake_post(), sleep_fn=lambda s: None, environ=ENV )


def test_the_backend_key_names_the_model_both_thresholds_and_the_escalation_model():
    backend = make_backend()
    assert backend.key_id == f"{MODEL}@0.3-0.8+opus-x"
    assert make_backend( lo=0.2 ).key_id != backend.key_id and make_backend( hi=0.9 ).key_id != backend.key_id
    assert backend.prompt_version == jev_judge.PROMPT_VERSION


def test_the_backend_refuses_missing_ids_and_bad_thresholds():
    with pytest.raises( ValueError, match="no default" ):
        jev_judge.JevBackend( "", 0.3, 0.8, "opus-x" )
    with pytest.raises( ValueError, match="thresholds" ):
        jev_judge.JevBackend( MODEL, 0.9, 0.3, "opus-x" )


def test_the_backend_judges_with_jev_and_returns_judgements_carrying_noul():
    judged = asyncio.run( make_backend().judge( [ STATED, DROPPED ], "It returns none when parked.", None, claude_query( {} ) ) )
    assert [ j.verdict for j in judged ] == [ "present", "absent" ] and judged[ 0 ].noul == 1.0


PAIR = { "id": "p1", "old": "returns none when parked. raises valueerror when blank.", "new": "returns none when parked.", "seed_span": None }
CONFIG = harness_runner.HarnessConfig( "ext", MODEL, "opus-x", "writer", 1, 1 )


def extractor_and_escalation_query():
    async def query( prompt, options ):
        if options.model == "ext":
            claims = [ { "claim": "returns none when parked", "quote": "returns none when parked" },
                       { "claim": "raises valueerror when blank", "quote": "raises valueerror when blank" } ]
            text = json.dumps( { "claims": claims } )
        else:
            text = "{}"
        yield AssistantMessage( content=[ TextBlock( text ) ], model=options.model )
    return query


def test_the_runner_uses_the_backend_and_a_ledger_row_is_never_shared_with_other_thresholds( tmp_path ):
    ledger = harness_runner.Ledger( str( tmp_path / "ledger.jsonl" ) )
    first  = asyncio.run( harness_runner.run_pair( PAIR, CONFIG, ledger, query_fn=extractor_and_escalation_query(), judge_backend=make_backend() ) )
    row    = first[ "lists" ][ 0 ][ "runs" ][ 0 ]
    assert [ r[ "verdict" ] for r in row ] == [ "present", "absent" ] and row[ 0 ][ "noul" ] == 1.0
    keys = [ k for k in ledger.entries if k.startswith( "judge|" ) ]
    assert len( keys ) == 1 and f"{MODEL}@0.3-0.8+opus-x" in keys[ 0 ] and jev_judge.PROMPT_VERSION in keys[ 0 ]
    calls = []
    asyncio.run( harness_runner.run_pair( PAIR, CONFIG, ledger, query_fn=extractor_and_escalation_query(), judge_backend=make_backend( post=fake_post( calls ), lo=0.2 ) ) )
    assert len( calls ) == 2 and len( [ k for k in ledger.entries if k.startswith( "judge|" ) ] ) == 2


def test_the_same_backend_resumes_from_the_ledger_without_calling_jev_again( tmp_path ):
    ledger = harness_runner.Ledger( str( tmp_path / "ledger.jsonl" ) )
    asyncio.run( harness_runner.run_pair( PAIR, CONFIG, ledger, query_fn=extractor_and_escalation_query(), judge_backend=make_backend() ) )
    calls = []
    asyncio.run( harness_runner.run_pair( PAIR, CONFIG, ledger, query_fn=extractor_and_escalation_query(), judge_backend=make_backend( post=fake_post( calls ) ) ) )
    assert calls == []


def test_run_all_passes_the_backend_through( tmp_path ):
    ledger  = harness_runner.Ledger( str( tmp_path / "ledger.jsonl" ) )
    results = asyncio.run( harness_runner.run_all( [ PAIR ], CONFIG, ledger, query_fn=extractor_and_escalation_query(), judge_backend=make_backend() ) )
    assert results[ 0 ][ "lists" ][ 0 ][ "runs" ][ 0 ][ 0 ][ "noul" ] == 1.0


def test_a_claude_run_rows_carry_no_noul( tmp_path ):
    async def query( prompt, options ):
        if options.model == "ext":
            text = json.dumps( { "claims": [ { "claim": "returns none when parked", "quote": "returns none when parked" } ] } )
        else:
            text = json.dumps( { "verdicts": [ { "id": 1, "verdict": "present" } ] } )
        yield AssistantMessage( content=[ TextBlock( text ) ], model=options.model )
    config = harness_runner.HarnessConfig( "ext", "claude-j", "opus-x", "writer", 1, 1 )
    ledger = harness_runner.Ledger( str( tmp_path / "ledger.jsonl" ) )
    out    = asyncio.run( harness_runner.run_pair( PAIR, config, ledger, query_fn=query ) )
    assert out[ "lists" ][ 0 ][ "runs" ][ 0 ] == [ { "verdict": "present", "escalated": False, "reason": None, "noul": None } ]


def test_the_report_records_the_jev_model_and_its_prompt_version():
    results = []
    report  = harness_report.build_report( results, CONFIG, judge_prompt_version=jev_judge.PROMPT_VERSION )
    assert report[ "models" ][ "judge" ] == MODEL and report[ "prompt_versions" ][ "judge" ] == jev_judge.PROMPT_VERSION
    assert harness_report.build_report( results, CONFIG )[ "prompt_versions" ][ "judge" ] == claim_judge.PROMPT_VERSION


# ---- the command line ---------------------------------------------------------------------

def write_pairs( tmp_path ):
    path = tmp_path / "pairs.json"
    path.write_text( json.dumps( [ PAIR ] ) )
    return path


def cli_args( tmp_path, *extra ):
    return [ "--pairs", str( write_pairs( tmp_path ) ), "--ledger", str( tmp_path / "l.jsonl" ), "--out", str( tmp_path / "r.json" ),
             "--extractor-model", "ext", "--judge-model", MODEL, "--escalation-model", "opus-x", "--writer-model", "writer",
             "--extractor-lists", "1", "--judge-runs", "1", *extra ]


def test_the_cli_refuses_a_jev_run_without_thresholds( tmp_path, capsys ):
    assert harness_cli.main( cli_args( tmp_path, "--judge-backend", "jev" ) ) == 2
    assert "thresholds" in capsys.readouterr().err


def test_the_cli_runs_the_jev_backend_and_records_its_prompt_version( tmp_path, monkeypatch ):
    monkeypatch.setenv( jev_transport.KEY_VARIABLE, KEY )
    monkeypatch.setattr( jev_transport, "_post", lambda url, headers, body, timeout: ( 200, reply( haystack_noul( body ) ) ) )
    code = harness_cli.main( cli_args( tmp_path, "--judge-backend", "jev", "--t-lo", "0.3", "--t-hi", "0.8" ), query_fn=extractor_and_escalation_query() )
    report = json.loads( ( tmp_path / "r.json" ).read_text() )
    assert code == 0 and report[ "prompt_versions" ][ "judge" ] == jev_judge.PROMPT_VERSION and report[ "models" ][ "judge" ] == MODEL


def test_a_gate_run_with_jev_needs_the_jev_prompt_version_among_the_frozen_versions( tmp_path, capsys ):
    wrong = f"{harness_cli.claim_extractor.PROMPT_VERSION},{claim_judge.PROMPT_VERSION}"
    args  = cli_args( tmp_path, "--judge-backend", "jev", "--t-lo", "0.3", "--t-hi", "0.8", "--gate", "--frozen-versions", wrong )
    assert harness_cli.main( args ) == 3
    assert jev_judge.PROMPT_VERSION in capsys.readouterr().err
