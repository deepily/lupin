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
                                   sleep_fn=( sleeps.append if sleeps is not None else ( lambda s: None ) ), environ=environ,
                                   random_fn=lambda: 0.5 )                  # jitter factor exactly 1, so waits are the plain doubling


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


def test_backoff_keeps_doubling_through_the_third_wait():
    sleeps = []
    ask( scripted_post( [ 429, 429, 429, 200 ] ), sleeps )
    assert sleeps == [ 1.0, 2.0, 4.0 ]


def test_retries_are_bounded_and_the_last_failure_does_not_sleep():
    sleeps, calls = [], []
    with pytest.raises( jev_transport.JevCallError, match="still answered status 429 after 4 calls" ):
        ask( scripted_post( [ 429 ] * 10, calls ), sleeps )
    assert len( calls ) == jev_transport.MAX_ATTEMPTS == 4
    assert len( sleeps ) == jev_transport.MAX_ATTEMPTS - 1


@pytest.mark.parametrize( "status", [ 401, 403, 422 ] )
def test_a_refused_key_or_request_is_a_configuration_error_and_not_retried( status ):
    calls = []
    with pytest.raises( jev_transport.JevConfigError, match=str( status ) ):
        ask( scripted_post( [ status ], calls ) )
    assert len( calls ) == 1


def test_any_other_status_is_a_call_error_without_retry():
    calls = []
    with pytest.raises( jev_transport.JevCallError, match="status 404" ):
        ask( scripted_post( [ 404 ], calls ) )
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
    ( '{"model": "jev-1.13.0", "answers": {"claim_stated": {"type": "noul", "noul": NaN}}}', "0 to 1" ),
    ( '{"model": "jev-1.13.0", "answers": {"claim_stated": {"type": "noul", "noul": Infinity}}}', "0 to 1" ),
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
        if status == 429: self.send_header( "Retry-After", "7" )
        self.end_headers()
        self.wfile.write( payload )
    def log_message( self, *args ): pass


def test_the_real_http_door_returns_status_and_text_for_ok_and_for_an_error_status():
    server = ThreadingHTTPServer( ( "127.0.0.1", 0 ), _Handler )
    thread = threading.Thread( target=server.serve_forever, daemon=True )
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[ 1 ]}"
        ok, busy = jev_transport._post( base + "/ok", {}, b"{}", 5 ), jev_transport._post( base + "/busy", {}, b"{}", 5 )
        assert ok[ :2 ] == ( 200, reply( 0.5 ) ) and busy[ :2 ] == ( 429, "slow down" )
        assert "Retry-After" not in ok[ 2 ] and busy[ 2 ][ "Retry-After" ] == "7"                  # the third item is the response headers
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
    assert seen == [ jev_transport.URL ] and len( waits ) == 1
    assert jev_transport.BACKOFF_SECONDS * ( 1 - jev_transport.JITTER ) <= waits[ 0 ] <= jev_transport.BACKOFF_SECONDS * ( 1 + jev_transport.JITTER )


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


def run( claims, new, design=None, post=None, answers=None, calls=None, lo=0.3, hi=0.8, allow=True ):
    return asyncio.run( jev_judge.judge_claims_jev( claims, new, design, MODEL, lo, hi, "opus-x",
                                                    query_fn=claude_query( answers or {}, calls ),
                                                    post_fn=post or fake_post(), sleep_fn=lambda s: None, environ=ENV,
                                                    allow_design_text=allow ) )


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
    sent     = []
    post     = lambda url, headers, body, timeout: ( sent.append( 1 ), ( 200, reply( 0.95 ) ) if len( sent ) == 1 else ( 500, "boom" ) )[ 1 ]    # one answer, then an outage that outlasts the retries
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

def make_backend( post=None, lo=0.3, hi=0.8, allow=False ):
    return jev_judge.JevBackend( MODEL, lo, hi, "opus-x", post_fn=post or fake_post(), sleep_fn=lambda s: None, environ=ENV,
                                 allow_design_text=allow )


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


DEFAULT_ESCALATION = { "returns none when parked": "present", "raises valueerror when blank": "absent" }


def extractor_and_escalation_query( answers=None ):
    async def query( prompt, options ):
        if options.model == "ext":
            claims = [ { "claim": "returns none when parked", "quote": "returns none when parked" },
                       { "claim": "raises valueerror when blank", "quote": "raises valueerror when blank" } ]
            text = json.dumps( { "claims": claims } )
        else:
            listed = re.search( r"<claims_(\w+)>\n(.*?)\n</claims_\1>", prompt, re.DOTALL ).group( 2 )
            texts  = [ line.split( ". ", 1 )[ 1 ] for line in listed.splitlines() ]
            text   = json.dumps( { "verdicts": [ { "id": n, "verdict": ( answers or DEFAULT_ESCALATION )[ t ] } for n, t in enumerate( texts, start=1 ) ] } )
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


# ---- design text, unanswered claims and the ledger ----------------------------------------

def test_a_design_document_is_refused_before_any_call_unless_allowed():
    calls = []
    with pytest.raises( jev_transport.JevConfigError, match="design document may not be sent" ):
        run( [ STATED ], "text", design="a design document", post=fake_post( calls ), allow=False )
    assert calls == []


def test_a_design_document_is_sent_as_design_doc_when_allowed_and_never_when_absent():
    calls = []
    run( [ STATED ], "text", design="the design text", post=fake_post( calls ), allow=True )
    assert json.loads( calls[ 0 ][ 2 ] )[ "state" ] == { "new_text": "text", "design_doc": "the design text" }
    calls.clear()
    run( [ STATED ], "text", design=None, post=fake_post( calls ), allow=False )
    assert json.loads( calls[ 0 ][ 2 ] )[ "state" ] == { "new_text": "text" }


def test_the_backend_refuses_a_design_document_by_default_and_sends_it_when_allowed():
    with pytest.raises( jev_transport.JevConfigError ):
        asyncio.run( make_backend().judge( [ STATED ], "t", "design", claude_query( {} ) ) )
    calls = []
    asyncio.run( make_backend( post=fake_post( calls ), allow=True ).judge( [ STATED ], "t", "design", claude_query( {} ) ) )
    assert "design_doc" in json.loads( calls[ 0 ][ 2 ] )[ "state" ]


def test_complete_is_false_when_any_claim_has_no_jev_answer():
    backend = make_backend()
    J = claim_judge.Judgement
    assert backend.complete( [ J( STATED, "present", False, None, 0.9 ), J( DROPPED, "absent", False, None, 0.1 ) ] ) is True
    assert backend.complete( [ J( STATED, "present", False, None, 0.9 ), J( DROPPED, "absent", True, "jev gave no answer", None ) ] ) is False
    assert backend.complete( [] ) is True


def outage_then_ok_post( calls ):
    def post( url, headers, body, timeout ):
        calls.append( 1 )
        return ( 400, "boom" ) if len( calls ) <= 2 else ( 200, reply( haystack_noul( body ) ) )
    return post


def test_a_run_where_jev_did_not_answer_every_claim_is_not_ledgered_and_is_asked_again( tmp_path ):
    ledger = harness_runner.Ledger( str( tmp_path / "ledger.jsonl" ) )
    calls  = []
    query  = extractor_and_escalation_query( { "returns none when parked": "present", "raises valueerror when blank": "absent" } )
    first  = asyncio.run( harness_runner.run_pair( PAIR, CONFIG, ledger, query_fn=query, judge_backend=make_backend( post=outage_then_ok_post( calls ) ) ) )
    assert [ r[ "noul" ] for r in first[ "lists" ][ 0 ][ "runs" ][ 0 ] ] == [ None, None ]
    assert [ k for k in ledger.entries if k.startswith( "judge|" ) ] == []
    again  = asyncio.run( harness_runner.run_pair( PAIR, CONFIG, ledger, query_fn=query, judge_backend=make_backend( post=outage_then_ok_post( calls ) ) ) )
    assert all( r[ "noul" ] is not None for r in again[ "lists" ][ 0 ][ "runs" ][ 0 ] )
    assert len( [ k for k in ledger.entries if k.startswith( "judge|" ) ] ) == 1


def rows_report( noul_values, jev_run ):
    rows = [ { "verdict": "present", "escalated": False, "reason": None, "noul": n } for n in noul_values ]
    result = { "id": "p", "seed_span": None, "lists": [ { "claims": [ { "start": 0, "end": 1, "text": "q", "quote": "q" } for _ in rows ],
                                                           "discarded": 0, "discards": [], "flags": [], "flag_words": [], "reextract_calls": 0, "parse_failed": False, "retry_calls": 0, "uncovered": 0.0, "longest_quote": 0.0, "runs": [ rows ] } ] }
    return harness_report.build_report( [ result ], CONFIG, jev_run=jev_run )


def test_the_report_counts_claims_that_carry_no_jev_probability():
    assert rows_report( [ 0.9, None, None ], True )[ "judge_unanswered" ] == 2
    assert rows_report( [ 0.9, 0.8 ], True )[ "judge_unanswered" ] == 0


def test_a_jev_run_with_an_unanswered_claim_can_not_pass_the_gate():
    clean   = rows_report( [ 0.9 ], True )
    dirty   = rows_report( [ 0.9, None ], True )
    assert clean[ "judge_unanswered" ] == 0 and dirty[ "default_gate_pass" ] is False


def test_a_run_that_did_not_use_jev_reports_no_unanswered_count():
    assert rows_report( [ None, None ], False )[ "judge_unanswered" ] is None


def test_the_cli_refuses_a_design_document_without_the_flag_and_sends_it_with_the_flag( tmp_path, monkeypatch, capsys ):
    monkeypatch.setenv( jev_transport.KEY_VARIABLE, KEY )
    sent = []
    monkeypatch.setattr( jev_transport, "_post", lambda url, headers, body, timeout: ( sent.append( body ) or ( 200, reply( haystack_noul( body ) ) ) ) )
    with_design = dict( PAIR, design="linked design text" )
    pairs_file  = tmp_path / "pairs.json"
    pairs_file.write_text( json.dumps( [ with_design ] ) )
    base = [ "--pairs", str( pairs_file ), "--ledger", str( tmp_path / "l.jsonl" ), "--out", str( tmp_path / "r.json" ),
             "--extractor-model", "ext", "--judge-model", MODEL, "--escalation-model", "opus-x", "--writer-model", "writer",
             "--extractor-lists", "1", "--judge-runs", "1", "--judge-backend", "jev", "--t-lo", "0.3", "--t-hi", "0.8" ]
    assert harness_cli.main( base, query_fn=extractor_and_escalation_query() ) == 2
    assert "design document may not be sent" in capsys.readouterr().err and sent == []
    assert harness_cli.main( base + [ "--allow-design-text" ], query_fn=extractor_and_escalation_query() ) == 0
    assert b"linked design text" in sent[ 0 ]


def passing_jev_results( blank_one=False ):
    """A run that clears every other gate criterion: 60 seeded pairs all caught, 20 calm unseeded pairs."""
    from tests.unit.test_doc_lint_harness import synthetic
    results = synthetic( 60, 0, unseeded=20 )
    results = json.loads( json.dumps( results ) )
    for r in results:
        for lst in r[ "lists" ]:
            for run in lst[ "runs" ]:
                for row in run: row[ "noul" ] = 0.9
    if blank_one: results[ 0 ][ "lists" ][ 0 ][ "runs" ][ 0 ][ 0 ][ "noul" ] = None
    return results


def test_one_unanswered_claim_is_the_only_thing_that_fails_an_otherwise_passing_jev_gate():
    clean = harness_report.build_report( passing_jev_results(), CONFIG, jev_run=True )
    dirty = harness_report.build_report( passing_jev_results( blank_one=True ), CONFIG, jev_run=True )
    assert clean[ "default_gate_pass" ] is True and clean[ "judge_unanswered" ] == 0
    assert dirty[ "judge_unanswered" ] == 1
    assert ( dirty[ "miss_criterion_met" ], dirty[ "false_alarm_ok" ] ) == ( True, True )
    assert dirty[ "default_gate_pass" ] is False


def test_design_text_is_refused_by_default_on_both_entry_points():
    with pytest.raises( jev_transport.JevConfigError ):
        asyncio.run( jev_judge.judge_claims_jev( [ STATED ], "t", "design", MODEL, 0.3, 0.8, "opus-x",
                                                 query_fn=claude_query( {} ), post_fn=fake_post(), environ=ENV ) )
    backend = jev_judge.JevBackend( MODEL, 0.3, 0.8, "opus-x", post_fn=fake_post(), environ=ENV )
    assert backend.allow_design_text is False


def test_the_cli_report_of_a_jev_run_carries_the_unanswered_count( tmp_path, monkeypatch ):
    monkeypatch.setenv( jev_transport.KEY_VARIABLE, KEY )
    monkeypatch.setattr( jev_transport, "_post", lambda url, headers, body, timeout: ( 200, reply( haystack_noul( body ) ) ) )
    assert harness_cli.main( cli_args( tmp_path, "--judge-backend", "jev", "--t-lo", "0.3", "--t-hi", "0.8" ), query_fn=extractor_and_escalation_query() ) == 0
    assert json.loads( ( tmp_path / "r.json" ).read_text() )[ "judge_unanswered" ] == 0


def grid_results( blank_last=True ):
    """Two lists of two runs each, every row answered but the very last one: the only unanswered claim."""
    from tests.unit.test_doc_lint_harness import synthetic
    results = json.loads( json.dumps( synthetic( 60, 0, unseeded=20 ) ) )
    for r in results:
        for lst in r[ "lists" ]:
            lst[ "runs" ] = [ [ { "verdict": lst[ "runs" ][ 0 ][ 0 ][ "verdict" ], "escalated": False, "reason": None, "noul": 0.9 } ] for _ in range( 2 ) ]
    if blank_last: results[ -1 ][ "lists" ][ -1 ][ "runs" ][ -1 ][ -1 ][ "noul" ] = None
    return results


def test_an_unanswered_claim_in_the_last_list_and_last_run_is_counted_and_fails_the_gate():
    report = harness_report.build_report( grid_results(), CONFIG, jev_run=True )
    assert report[ "judge_unanswered" ] == 1
    assert ( report[ "miss_criterion_met" ], report[ "false_alarm_ok" ] ) == ( True, True )
    assert report[ "default_gate_pass" ] is False
    assert harness_report.build_report( grid_results( blank_last=False ), CONFIG, jev_run=True )[ "judge_unanswered" ] == 0


def test_the_cli_reads_a_labelled_set_when_keys_are_given( tmp_path, monkeypatch ):
    monkeypatch.setenv( jev_transport.KEY_VARIABLE, KEY )
    sent = []
    monkeypatch.setattr( jev_transport, "_post", lambda url, headers, body, timeout: ( sent.append( body ) or ( 200, reply( haystack_noul( body ) ) ) ) )
    ( tmp_path / "dev" ).mkdir()
    pair = { "id": "p0", "old": PAIR[ "old" ], "new": PAIR[ "new" ], "linked_doc": "linked design text" }
    key  = { "id": "p0", "seeded_positive": True, "x_span_in_old": "raises valueerror when blank." }
    ( tmp_path / "dev" / "pairs.jsonl" ).write_text( json.dumps( pair ) + "\n" )
    ( tmp_path / "dev" / "keys.jsonl" ).write_text( json.dumps( key ) + "\n" )
    args = [ "--pairs", str( tmp_path / "dev" / "pairs.jsonl" ), "--keys", str( tmp_path / "dev" / "keys.jsonl" ),
             "--ledger", str( tmp_path / "l.jsonl" ), "--out", str( tmp_path / "r.json" ),
             "--extractor-model", "ext", "--judge-model", MODEL, "--escalation-model", "opus-x", "--writer-model", "writer",
             "--extractor-lists", "1", "--judge-runs", "1", "--judge-backend", "jev", "--t-lo", "0.3", "--t-hi", "0.8" ]
    assert harness_cli.main( args, query_fn=extractor_and_escalation_query() ) == 2 and sent == []
    assert harness_cli.main( args + [ "--allow-design-text" ], query_fn=extractor_and_escalation_query() ) == 0
    assert b"linked design text" in sent[ 0 ]
    assert json.loads( ( tmp_path / "r.json" ).read_text() )[ "pairs" ] == 1


def test_the_cli_refuses_a_gate_path_and_a_file_that_is_not_json( tmp_path, capsys ):
    ( tmp_path / "gate" ).mkdir()
    gate_pairs = tmp_path / "gate" / "pairs.jsonl"
    gate_pairs.write_text( "{}\n" )
    base = [ "--ledger", str( tmp_path / "l.jsonl" ), "--out", str( tmp_path / "r.json" ), "--extractor-model", "ext",
             "--judge-model", "claude-j", "--escalation-model", "opus-x", "--writer-model", "writer" ]
    assert harness_cli.main( [ "--pairs", str( gate_pairs ), "--keys", str( tmp_path / "gate-keys.jsonl" ), *base ] ) == 2
    assert "gate split" in capsys.readouterr().err
    not_json = tmp_path / "pairs.json"
    not_json.write_text( "this is not json" )
    assert harness_cli.main( [ "--pairs", str( not_json ), *base ] ) == 2
    assert "REFUSED" in capsys.readouterr().err


# ---- the gate door, gate paths and the Jev defaults on the command line --------------------

import hashlib


def gate_set( tmp_path ):
    ( tmp_path / "gate" ).mkdir()
    pair = { "id": "g0", "old": PAIR[ "old" ], "new": PAIR[ "new" ], "linked_doc": "" }
    key  = { "id": "g0", "seeded_positive": False, "x_span_in_old": "" }
    ( tmp_path / "gate" / "pairs.jsonl" ).write_text( json.dumps( pair ) + "\n" )
    ( tmp_path / "gate" / "keys.jsonl" ).write_text( json.dumps( key ) + "\n" )
    return tmp_path / "gate" / "pairs.jsonl", tmp_path / "gate" / "keys.jsonl"


def gate_args( tmp_path, pairs, keys, *extra ):
    return [ "--pairs", str( pairs ), "--keys", str( keys ), "--ledger", str( tmp_path / "l.jsonl" ), "--out", str( tmp_path / "r.json" ),
             "--extractor-model", "ext", "--judge-model", MODEL, "--escalation-model", "opus-x", "--writer-model", "writer",
             "--extractor-lists", "1", "--judge-backend", "jev", "--t-lo", "0.3", "--t-hi", "0.8", *extra ]


def test_a_gate_path_without_the_gate_flag_is_refused_before_it_is_opened( tmp_path, capsys ):
    missing = tmp_path / "gate" / "nope.jsonl"
    assert harness_cli.main( gate_args( tmp_path, missing, tmp_path / "keys" / "dev-keys.jsonl" ) ) == 2
    assert "gate split" in capsys.readouterr().err
    pairs, keys = gate_set( tmp_path )
    link = tmp_path / "p.jsonl"
    link.symlink_to( pairs )
    assert harness_cli.main( gate_args( tmp_path, link, keys ) ) == 2
    assert harness_cli.main( [ "--pairs", str( pairs ), *gate_args( tmp_path, pairs, keys )[ 2: ] ] ) == 2
    dev_pairs = tmp_path / "dev" / "pairs.jsonl"
    assert harness_cli.main( gate_args( tmp_path, dev_pairs, keys ) ) == 2
    assert "gate split" in capsys.readouterr().err


def test_the_gate_door_opens_only_with_frozen_versions_thresholds_and_pairs_sha( tmp_path, monkeypatch, capsys ):
    monkeypatch.setenv( jev_transport.KEY_VARIABLE, KEY )
    monkeypatch.setattr( jev_transport, "_post", lambda url, headers, body, timeout: ( 200, reply( haystack_noul( body ) ) ) )
    pairs, keys = gate_set( tmp_path )
    versions    = f"{harness_cli.claim_extractor.PROMPT_VERSION},{jev_judge.PROMPT_VERSION}"
    sha         = hashlib.sha256( pairs.read_bytes() ).hexdigest()
    base        = gate_args( tmp_path, pairs, keys, "--gate" )
    query       = extractor_and_escalation_query()
    assert harness_cli.main( base + [ "--frozen-versions", versions, "--frozen-pairs-sha", sha ], query_fn=query ) == 3
    assert "frozen-thresholds" in capsys.readouterr().err
    assert harness_cli.main( base + [ "--frozen-versions", versions, "--frozen-pairs-sha", sha, "--frozen-thresholds", "0.3,0.9" ], query_fn=query ) == 3
    assert harness_cli.main( base + [ "--frozen-thresholds", "0.3,0.8", "--frozen-pairs-sha", sha ], query_fn=query ) == 3
    assert harness_cli.main( base + [ "--frozen-thresholds", "0.3,0.8", "--frozen-versions", versions, "--frozen-pairs-sha", "0" * 64 ], query_fn=query ) == 3
    assert harness_cli.main( base + [ "--frozen-thresholds", "0.3,0.8", "--frozen-versions", versions, "--frozen-pairs-sha", sha ], query_fn=query ) == 0
    assert json.loads( ( tmp_path / "r.json" ).read_text() )[ "pairs" ] == 1


def runs_args( tmp_path, *extra ):
    """Command line with no --judge-runs, so the default applies."""
    args = cli_args( tmp_path, *extra )
    i = args.index( "--judge-runs" )
    return args[ :i ] + args[ i + 2: ]


def cli_claude_query():
    async def query( prompt, options ):
        if options.model == "ext":
            text = json.dumps( { "claims": [ { "claim": "returns none when parked", "quote": "returns none when parked" } ] } )
        else:
            text = json.dumps( { "verdicts": [ { "id": 1, "verdict": "present" } ] } )
        yield AssistantMessage( content=[ TextBlock( text ) ], model=options.model )
    return query


def test_jev_defaults_to_one_judge_run( tmp_path, monkeypatch ):
    monkeypatch.setenv( jev_transport.KEY_VARIABLE, KEY )
    monkeypatch.setattr( jev_transport, "_post", lambda url, headers, body, timeout: ( 200, reply( haystack_noul( body ) ) ) )
    code = harness_cli.main( runs_args( tmp_path, "--judge-backend", "jev", "--t-lo", "0.3", "--t-hi", "0.8" ), query_fn=extractor_and_escalation_query() )
    assert code == 0 and ( tmp_path / "l.jsonl" ).read_text().count( "judge|" ) == 1


def test_the_claude_judge_defaults_to_three_runs_and_an_explicit_count_wins( tmp_path ):
    assert harness_cli.main( runs_args( tmp_path ), query_fn=cli_claude_query() ) == 0
    assert ( tmp_path / "l.jsonl" ).read_text().count( "judge|" ) == 3
    other = tmp_path / "two"
    other.mkdir()
    assert harness_cli.main( cli_args( other )[ : -1 ] + [ "2" ], query_fn=cli_claude_query() ) == 0
    assert ( other / "l.jsonl" ).read_text().count( "judge|" ) == 2


def test_thresholds_with_the_claude_backend_are_refused_not_ignored( tmp_path, capsys ):
    assert harness_cli.main( cli_args( tmp_path, "--t-lo", "0.3" ) ) == 2
    assert "only apply to --judge-backend jev" in capsys.readouterr().err
    assert harness_cli.main( cli_args( tmp_path, "--t-hi", "0.8" ) ) == 2


def test_a_claude_backend_report_has_no_unanswered_count( tmp_path ):
    async def query( prompt, options ):
        if options.model == "ext":
            text = json.dumps( { "claims": [ { "claim": "returns none when parked", "quote": "returns none when parked" } ] } )
        else:
            text = json.dumps( { "verdicts": [ { "id": 1, "verdict": "present" } ] } )
        yield AssistantMessage( content=[ TextBlock( text ) ], model=options.model )
    args = [ a for a in cli_args( tmp_path ) ]
    args[ args.index( "--judge-model" ) + 1 ] = "claude-j"
    assert harness_cli.main( args, query_fn=query ) == 0
    assert json.loads( ( tmp_path / "r.json" ).read_text() )[ "judge_unanswered" ] is None


# ---- the Claude Code binary is run config ------------------------------------------------

import os
import stat

from cosa.repo.doc_lint import model_transport


@pytest.fixture( autouse=True )
def reset_cli_path():
    model_transport.configure( None )
    yield
    model_transport.configure( None )


def fake_binary( tmp_path, mode=0o755 ):
    path = tmp_path / "claude"
    path.write_text( "#!/bin/sh\n" )
    path.chmod( mode )
    return str( path )


def seen_cli_path():
    seen = []
    async def query( prompt, options ):
        seen.append( options.cli_path )
        yield AssistantMessage( content=[ TextBlock( "ok" ) ], model="m" )
    asyncio.run( model_transport.complete( "claude-x", "sys", "user", query_fn=query ) )
    return seen[ 0 ]


def test_by_default_the_sdk_chooses_its_own_binary():
    assert seen_cli_path() is None


def test_a_configured_binary_reaches_the_sdk_and_none_restores_the_default( tmp_path ):
    path = fake_binary( tmp_path )
    model_transport.configure( path )
    assert seen_cli_path() == path
    model_transport.configure( None )
    assert seen_cli_path() is None


@pytest.mark.parametrize( "make", [ lambda p: str( p / "missing" ), lambda p: str( p ), lambda p: fake_binary( p, mode=0o644 ) ] )
def test_a_path_that_is_not_an_executable_file_is_refused( tmp_path, make ):
    with pytest.raises( ValueError, match="not an executable file" ):
        model_transport.configure( make( tmp_path ) )
    assert seen_cli_path() is None


def test_the_cli_flag_sets_the_binary_and_the_report_records_it( tmp_path, monkeypatch ):
    monkeypatch.setenv( jev_transport.KEY_VARIABLE, KEY )
    monkeypatch.setattr( jev_transport, "_post", lambda url, headers, body, timeout: ( 200, reply( haystack_noul( body ) ) ) )
    path = fake_binary( tmp_path )
    seen = []
    inner = extractor_and_escalation_query()
    async def query( prompt, options ):
        seen.append( options.cli_path )
        async for message in inner( prompt, options ): yield message
    args = cli_args( tmp_path, "--judge-backend", "jev", "--t-lo", "0.3", "--t-hi", "0.8", "--claude-cli-path", path )
    assert harness_cli.main( args, query_fn=query ) == 0
    assert set( seen ) == { path }
    assert json.loads( ( tmp_path / "r.json" ).read_text() )[ "claude_cli" ] == path


def test_the_cli_refuses_a_missing_binary_and_records_none_by_default( tmp_path, capsys ):
    assert harness_cli.main( cli_args( tmp_path, "--claude-cli-path", str( tmp_path / "nope" ) ) ) == 2
    assert "not an executable file" in capsys.readouterr().err
    assert harness_cli.main( cli_args( tmp_path ), query_fn=cli_claude_query() ) == 0
    assert json.loads( ( tmp_path / "r.json" ).read_text() )[ "claude_cli" ] is None


def test_has_key_reports_presence_only_from_the_given_or_real_environment( monkeypatch ):
    assert jev_transport.has_key( { jev_transport.KEY_VARIABLE: KEY } ) is True
    assert jev_transport.has_key( {} ) is False and jev_transport.has_key( { jev_transport.KEY_VARIABLE: "" } ) is False
    monkeypatch.setenv( jev_transport.KEY_VARIABLE, KEY )
    assert jev_transport.has_key() is True
    monkeypatch.delenv( jev_transport.KEY_VARIABLE )
    assert jev_transport.has_key() is False


def test_send_returns_the_response_text_and_refuses_without_a_key():
    body = b'{"any": "shape"}'
    assert jev_transport.send( body, post_fn=scripted_post( [ 200 ] ), environ=ENV ) == reply( 0.9 )
    with pytest.raises( jev_transport.JevConfigError ): jev_transport.send( body, post_fn=fake_post(), environ={} )


SENTINEL = "sentinel-key-9f3a7c1e5b"


def chain_text( exc ):
    """Ensures: returns the str, repr and formatted traceback of an exception and of everything in its cause/context chain."""
    import traceback
    out, seen = [], set()
    while exc is not None and id( exc ) not in seen:
        seen.add( id( exc ) )
        out += [ str( exc ), repr( exc ), "".join( traceback.format_exception( exc ) ) ]
        exc = exc.__cause__ or exc.__context__
    return "\n".join( out )


def refusing_post( status, text="no" ):
    def post( url, headers, body, timeout ): return status, text
    return post


def failing_post( url, headers, body, timeout ):
    raise ConnectionError( "connection reset" )


@pytest.mark.parametrize( "post, error", [
    ( refusing_post( 401 ),          jev_transport.JevConfigError ),
    ( refusing_post( 422 ),          jev_transport.JevConfigError ),
    ( refusing_post( 500 ),          jev_transport.JevCallError ),
    ( refusing_post( 429 ),          jev_transport.JevCallError ),
    ( failing_post,                  jev_transport.JevCallError ),
    ( refusing_post( 200, "<html>" ), jev_transport.JevCallError ),
] )
def test_no_error_message_or_chain_ever_contains_the_key_value( post, error ):
    with pytest.raises( error ) as caught:
        jev_transport.ask_noul( MODEL, {}, "q", jev_judge.CRITERIA, post_fn=post, sleep_fn=lambda s: None, environ={ jev_transport.KEY_VARIABLE: SENTINEL } )
    text = chain_text( caught.value )
    assert SENTINEL not in text and "Bearer" not in text and len( text ) > 0


def test_the_live_transport_and_a_refused_sweep_never_leak_the_key_into_errors_logs_or_the_verdict( capsys, caplog ):
    from lupin_mcp import reuse_tools as rt
    t = rt.LiveJevTransport( post_fn=refusing_post( 403 ), sleep_fn=lambda s: None, environ={ jev_transport.KEY_VARIABLE: SENTINEL } )
    for _ in range( 2 ):                                                                            # the first refusal, then the remembered one
        with pytest.raises( jev_transport.JevConfigError ) as caught: t.post( {} )
        assert SENTINEL not in chain_text( caught.value )
    out, err = capsys.readouterr()
    assert SENTINEL not in out + err + caplog.text
