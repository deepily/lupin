"""
Unit tests for the CJ Flow v2 eval harness (src/scripts/v2_eval.py).

Covers the pure metric/report core, the injectable live-client seam, and — with a
dedicated prove-it-can-fail block — every property the run-integrity guard asserts.
No live server: the ask() transport and the auth/login call are injected/monkeypatched.
"""

import json
import os
import sys

import pytest


def _load_module():
    """Import v2_eval under its real name (src/scripts on path) so coverage can target it."""
    root        = os.environ[ "LUPIN_ROOT" ]
    scripts_dir = os.path.join( root, "src", "scripts" )
    if scripts_dir not in sys.path:
        sys.path.insert( 0, scripts_dir )
    import v2_eval
    return v2_eval


ve = _load_module()


def _rec( ok=True, status=200, expected="agent router go to math", utterance="u", **payload ):
    """Build one per-request record with the given §8 payload fields."""
    return {
        "utterance"        : utterance,
        "expected_command" : expected,
        "ok"               : ok,
        "status_code"      : status,
        "payload"          : dict( payload ),
    }


# ---------------------------------------------------------------------------
# is_utterance_line
# ---------------------------------------------------------------------------
def test_is_utterance_line_blank_comment_and_real():
    assert ve.is_utterance_line( "" )            is False
    assert ve.is_utterance_line( "   \n" )       is False
    assert ve.is_utterance_line( "# a comment" ) is False
    assert ve.is_utterance_line( "  # indented" ) is False
    assert ve.is_utterance_line( "what time is it" ) is True


# ---------------------------------------------------------------------------
# load_corpus + _apply_limit
# ---------------------------------------------------------------------------
def test_load_corpus_weather_pairs_and_limit():
    pairs = ve.load_corpus( "weather" )
    assert len( pairs ) == 2
    assert all( cmd == "agent router go to weather" for _, cmd in pairs )
    limited = ve.load_corpus( "weather", limit=1 )
    assert len( limited ) == 1


def test_load_corpus_unknown_name_raises():
    with pytest.raises( ValueError ):
        ve.load_corpus( "does-not-exist" )


def _make_simple_root( tmp_path, todo_lines, math_lines ):
    """Build a fake project root with the simple-corpus manifest + two data files."""
    ( tmp_path / "src" / "conf" / "training" ).mkdir( parents=True )
    ( tmp_path / "src" / "data" ).mkdir( parents=True )
    ( tmp_path / "src" / "data" / "todo.txt" ).write_text( todo_lines )
    ( tmp_path / "src" / "data" / "math.txt" ).write_text( math_lines )
    manifest = {
        "agent router go to todo" : "/src/data/todo.txt",
        "agent router go to math" : "/src/data/math.txt",
    }
    ( tmp_path / "src" / "conf" / "training" / "agent-router-simple-commands.json" ).write_text(
        json.dumps( manifest )
    )
    return str( tmp_path )


def test_load_corpus_simple_filters_and_pairs( tmp_path ):
    root  = _make_simple_root(
        tmp_path,
        todo_lines="# header\n\nadd milk to my list\nremind me to call\n",
        math_lines="what is two plus two\n",
    )
    pairs = ve.load_corpus( "simple", project_root=root )
    commands = { cmd for _, cmd in pairs }
    assert commands == { "agent router go to todo", "agent router go to math" }
    assert ( "add milk to my list", "agent router go to todo" ) in pairs
    assert len( pairs ) == 3   # comment + blank dropped


def test_load_corpus_simple_limit_per_command( tmp_path ):
    root  = _make_simple_root(
        tmp_path,
        todo_lines="a\nb\nc\n",
        math_lines="x\ny\n",
    )
    pairs = ve.load_corpus( "simple", project_root=root, limit=1 )
    assert len( pairs ) == 2   # one per command


def test_load_corpus_empty_raises( tmp_path ):
    root = _make_simple_root( tmp_path, todo_lines="# only a comment\n", math_lines="\n\n" )
    with pytest.raises( ValueError ):
        ve.load_corpus( "simple", project_root=root )


# ---------------------------------------------------------------------------
# stratified_sample
# ---------------------------------------------------------------------------
def _pairs( **by_command ):
    """Build a corpus: _pairs( math=["a","b"], todo=["x"] ) -> [(u, cmd), ...]."""
    out = []
    for command, utterances in by_command.items():
        for utterance in utterances:
            out.append( ( utterance, command ) )
    return out


def test_stratified_sample_empty_raises():
    with pytest.raises( ValueError ):
        ve.stratified_sample( [], 2, seed=1 )


def test_stratified_sample_bad_n_raises():
    with pytest.raises( ValueError ):
        ve.stratified_sample( _pairs( math=[ "a", "b" ] ), 0, seed=1 )


def test_stratified_sample_caps_per_command_and_is_reproducible():
    corpus = _pairs( math=[ "a", "b", "c", "d" ], todo=[ "x", "y", "z" ] )
    sampled_a, manifest_a = ve.stratified_sample( corpus, 2, seed=7 )
    sampled_b, manifest_b = ve.stratified_sample( corpus, 2, seed=7 )
    # exactly n per command, and the same seed reproduces the exact sample
    assert sampled_a == sampled_b
    assert manifest_a == manifest_b
    assert sum( 1 for _, c in sampled_a if c == "math" ) == 2
    assert sum( 1 for _, c in sampled_a if c == "todo" ) == 2
    assert manifest_a[ "seed" ] == 7
    assert manifest_a[ "n_per_command" ] == 2
    assert manifest_a[ "total_kept" ] == 4
    assert manifest_a[ "under_quota" ] == []
    assert manifest_a[ "per_command" ][ "math" ] == { "kept": 2, "available": 4 }


def test_stratified_sample_under_quota_keeps_all_and_names_short_commands():
    corpus = _pairs( math=[ "a", "b" ], todo=[ "x" ] )
    sampled, manifest = ve.stratified_sample( corpus, 5, seed=1 )
    assert len( sampled ) == 3                       # all kept, nothing invented
    assert manifest[ "under_quota" ] == [ "math", "todo" ]
    assert manifest[ "per_command" ][ "todo" ] == { "kept": 1, "available": 1 }


def test_stratified_sample_is_order_independent_within_a_command():
    forward  = _pairs( math=[ "a", "b", "c", "d" ] )
    reversed_ = _pairs( math=[ "d", "c", "b", "a" ] )
    sampled_f, _ = ve.stratified_sample( forward,  2, seed=3 )
    sampled_r, _ = ve.stratified_sample( reversed_, 2, seed=3 )
    assert set( sampled_f ) == set( sampled_r )      # same set chosen regardless of input order


def test_stratified_sample_preserves_first_appearance_command_order():
    corpus = _pairs( todo=[ "x", "y" ], math=[ "a", "b" ] )   # todo appears first
    sampled, _ = ve.stratified_sample( corpus, 1, seed=2 )
    commands = [ c for _, c in sampled ]
    assert commands == [ "todo", "math" ]


# ---------------------------------------------------------------------------
# field accessors
# ---------------------------------------------------------------------------
def test_accessors_on_failed_record_return_none():
    r = _rec( ok=False, status=500, path="replay", similarity=100.0,
              command="c", timings_ms={ "t_first_useful": 3.0 }, trace_id="t", route_reason="x" )
    assert ve.response_path( r )         is None
    assert ve.response_route_reason( r ) is None
    assert ve.response_similarity( r )   is None
    assert ve.matched_command( r )       is None
    assert ve.first_useful_ms( r )       is None
    assert ve.response_trace_id( r )     is None


def test_accessors_on_ok_record():
    r = _rec( path="agent", route_reason="agent_error", similarity="87.5",
              command="agent router go to math", timings_ms={ "t_first_useful": 12.0 }, trace_id="abc" )
    assert ve.response_path( r )         == "agent"
    assert ve.response_route_reason( r ) == "agent_error"
    assert ve.response_similarity( r )   == 87.5
    assert ve.matched_command( r )       == "agent router go to math"
    assert ve.first_useful_ms( r )       == 12.0
    assert ve.response_trace_id( r )     == "abc"


def test_similarity_and_first_useful_none_paths():
    r = _rec( similarity=None )                    # explicit None similarity
    assert ve.response_similarity( r ) is None
    r2 = _rec()                                    # no timings_ms key at all -> `or {}`
    assert ve.first_useful_ms( r2 ) is None
    r3 = _rec( timings_ms={ "other": 1.0 } )       # timings present, mark absent
    assert ve.first_useful_ms( r3 ) is None


# ---------------------------------------------------------------------------
# percentile / _rate / route_matches
# ---------------------------------------------------------------------------
def test_percentile_edges():
    assert ve.percentile( [], 50 )            is None
    assert ve.percentile( [ 7 ], 95 )         == 7.0
    assert ve.percentile( [ 10, 20 ], 0 )     == 10.0     # frac 0, low==high at rank 0
    assert ve.percentile( [ 10, 20 ], 100 )   == 20.0     # high clamps to last
    assert ve.percentile( [ 0, 10, 20, 30 ], 50 ) == 15.0 # interpolated


def test_rate_zero_denominator_and_normal():
    assert ve._rate( 3, 0 )  is None
    assert ve._rate( 1, 4 )  == 0.25


def test_route_matches():
    assert ve.route_matches( None, "x" )                     is False
    assert ve.route_matches( "  AGENT router go to Math ", "agent router go to math" ) is True
    assert ve.route_matches( "none", "agent router go to math" ) is False


# ---------------------------------------------------------------------------
# compute_metrics — every predicate branch, plus by_path 'unknown' + http error
# ---------------------------------------------------------------------------
def _mixed_records():
    return [
        _rec( path="replay", similarity=100.0, command="agent router go to math",
              timings_ms={ "t_first_useful": 5.0 } ),                                   # hit + right
        _rec( path="replay", similarity=99.0, command="wrong",
              timings_ms={ "t_first_useful": 10.0 } ),                                  # hit + would-be-wrong
        _rec( path="agent", route_reason="agent_error", command="agent router go to math",
              timings_ms={ "t_first_useful": 20.0 } ),                                  # agent_error, right
        _rec( expected="none", path="receptionist", route_reason="router_error",
              command="none", timings_ms={ "t_first_useful": 30.0 } ),                  # router_error, right
        _rec( path="needs_input", route_reason="extract_error", command=None ),         # extract_error, no latency
        _rec( path="agent", route_reason="replay_error", similarity=95.0,
              command="agent router go to math", timings_ms={ "t_first_useful": 40.0 } ), # replay_failure
        _rec( similarity=None, command="agent router go to math" ),                     # ok, path missing -> unknown
        _rec( ok=False, status=400 ),                                                   # http error
    ]


def test_compute_metrics_all_branches():
    m = ve.compute_metrics( _mixed_records() )
    assert m[ "n" ]            == 8
    assert m[ "n_ok" ]        == 7
    assert m[ "n_http_error" ] == 1
    assert m[ "cache_hits" ]  == 2
    assert m[ "cache_hit_rate" ]       == round( 2 / 7, 4 )
    assert m[ "cache_candidate_rate" ] == round( 3 / 7, 4 )   # sims: 100, 99, 95
    assert m[ "replay_failure_rate" ]  == round( 1 / 7, 4 )
    assert m[ "router_error_rate" ]    == round( 1 / 7, 4 )
    assert m[ "extract_error_rate" ]   == round( 1 / 7, 4 )
    assert m[ "agent_error_rate" ]     == round( 1 / 7, 4 )
    assert m[ "would_be_wrong" ]       == 1
    assert m[ "routing_accuracy" ]     == round( 5 / 7, 4 )   # r1,r3,r4,r6,r7 command matches expected
    assert m[ "p50_first_useful_ms" ]  == 20.0
    assert m[ "by_path" ][ "unknown" ] == 1
    assert m[ "by_path" ][ "replay" ]  == 2


def test_compute_metrics_empty_rates_are_none():
    m = ve.compute_metrics( [ _rec( ok=False, status=500 ) ] )
    assert m[ "n_ok" ]           == 0
    assert m[ "cache_hit_rate" ] is None
    assert m[ "p50_first_useful_ms" ] is None


# ---------------------------------------------------------------------------
# threshold_table
# ---------------------------------------------------------------------------
def test_threshold_table_counts_and_wrong():
    records = [
        _rec( similarity=100.0, command="agent router go to math" ),   # right at every floor
        _rec( similarity=97.0,  command="wrong" ),                     # wrong, >=95/90
        _rec( similarity=88.0,  command="agent router go to math" ),   # below all floors
        _rec( similarity=None,  command="agent router go to math" ),   # no candidate
    ]
    table = { row[ "floor" ]: row for row in ve.threshold_table( records ) }
    assert table[ 100.0 ][ "hits" ]           == 1
    assert table[ 95.0 ][ "hits" ]            == 2
    assert table[ 90.0 ][ "hits" ]            == 2
    assert table[ 95.0 ][ "would_be_wrong" ]  == 1
    assert table[ 100.0 ][ "hit_rate" ]       == round( 1 / 4, 4 )


def test_threshold_table_no_ok_gives_none_rate():
    rows = ve.threshold_table( [ _rec( ok=False, status=500 ) ] )
    assert all( row[ "hit_rate" ] is None for row in rows )


# ---------------------------------------------------------------------------
# latency_delta
# ---------------------------------------------------------------------------
def test_latency_delta_present_and_missing():
    cold = { "p50_first_useful_ms": 30.0, "p95_first_useful_ms": None }
    warm = { "p50_first_useful_ms": 12.0, "p95_first_useful_ms": 40.0 }
    d = ve.latency_delta( cold, warm )
    assert d[ "p50_delta_ms" ] == -18.0
    assert d[ "p95_delta_ms" ] is None


# ---------------------------------------------------------------------------
# read_jsonl_trace_ids
# ---------------------------------------------------------------------------
def test_read_jsonl_trace_ids_missing_and_present( tmp_path ):
    assert ve.read_jsonl_trace_ids( str( tmp_path / "nope.jsonl" ) ) == []
    p = tmp_path / "trace.jsonl"
    p.write_text( json.dumps( { "trace_id": "a" } ) + "\n\n" + json.dumps( { "trace_id": "b" } ) + "\n" )
    assert ve.read_jsonl_trace_ids( str( p ) ) == [ "a", "b" ]


# ---------------------------------------------------------------------------
# guard_run_integrity — PROVE EACH PROPERTY CAN FAIL
# ---------------------------------------------------------------------------
def test_guard_passes_when_all_properties_hold():
    records = [ _rec( trace_id="t1", path="replay", command="agent router go to math",
                      timings_ms={ "t_first_useful": 5.0 } ) ]
    assert ve.guard_run_integrity( records, [ "t1" ] ) is None


def test_guard_fails_on_http_error():
    records = [ _rec( ok=False, status=500 ) ]
    with pytest.raises( ve.EvalIntegrityError, match="http-all-ok" ):
        ve.guard_run_integrity( records, [] )


def test_guard_fails_on_trace_parity():
    records = [ _rec( trace_id="t1" ) ]
    with pytest.raises( ve.EvalIntegrityError, match="trace-parity" ):
        ve.guard_run_integrity( records, [ "other" ] )


def test_guard_fails_on_router_liveness():
    records = [ _rec( trace_id=f"t{i}", route_reason="router_error" ) for i in range( 5 ) ]
    with pytest.raises( ve.EvalIntegrityError, match="router-liveness" ):
        ve.guard_run_integrity( records, [ f"t{i}" for i in range( 5 ) ] )


def test_guard_reports_multiple_violations_together():
    records = [ _rec( ok=False, status=500 ), _rec( trace_id="t1" ) ]
    with pytest.raises( ve.EvalIntegrityError ) as excinfo:
        ve.guard_run_integrity( records, [] )
    assert "http-all-ok" in str( excinfo.value )
    assert "trace-parity" in str( excinfo.value )


# ---------------------------------------------------------------------------
# HttpAskClient + run_pass
# ---------------------------------------------------------------------------
class _FakeReply:
    def __init__( self, status_code, body ):
        self.status_code = status_code
        self._body       = body
    def json( self ):
        return self._body


def test_http_ask_client_ok_and_error():
    calls = []
    def post_fn( url, json, headers, timeout ):
        calls.append( ( url, json, headers, timeout ) )
        return _FakeReply( 200, { "path": "replay", "trace_id": "x" } )
    client = ve.HttpAskClient( "http://localhost:8000/", bearer="jwt", post_fn=post_fn )
    rec = client.ask( "what time is it" )
    assert rec[ "ok" ] is True
    assert rec[ "payload" ][ "path" ] == "replay"
    url, body, headers, _ = calls[ 0 ]
    assert url == "http://localhost:8000/api/v2/ask"
    assert body[ "speak" ] is False and body[ "interactive" ] is False
    assert headers[ "Authorization" ] == "Bearer jwt"

    err_client = ve.HttpAskClient( "http://localhost:8000", bearer="j",
                                   post_fn=lambda url, json, headers, timeout: _FakeReply( 400, {} ) )
    err = err_client.ask( "" )
    assert err[ "ok" ] is False
    assert err[ "payload" ] == {}


def test_http_ask_client_refreshes_bearer_on_401():
    # A long paired run outlives the JWT (~30min): a 401 must trigger a re-login + retry, so the
    # record is ok=True with the FRESH bearer and the span is measured on the successful retry.
    # Without the refresh (pre-fix code) the 401 stays ok=False — 4 such late 401s tripped
    # http-all-ok and the integrity guard refused a median-Δ (ts-d0f50349, row d8d019f6). RED control.
    replies      = [ _FakeReply( 401, {} ), _FakeReply( 200, { "path": "replay", "trace_id": "y" } ) ]
    seen_headers = []
    def post_fn( url, json, headers, timeout ):
        seen_headers.append( headers[ "Authorization" ] )
        return replies.pop( 0 )
    relogins = []
    def relogin_fn():
        relogins.append( 1 )
        return "fresh-jwt"
    client = ve.HttpAskClient( "http://localhost:8000", bearer="stale-jwt",
                               post_fn=post_fn, relogin_fn=relogin_fn )
    rec = client.ask( "what time is it" )
    assert rec[ "ok" ] is True                                       # the retry succeeded
    assert rec[ "status_code" ] == 200
    assert len( relogins ) == 1                                      # re-login fired exactly once
    assert seen_headers == [ "Bearer stale-jwt", "Bearer fresh-jwt" ]  # 1st stale, retry with fresh
    assert client.bearer == "fresh-jwt"                             # bearer updated for later asks


def test_http_ask_client_no_relogin_leaves_401_failed():
    # Negative control: with NO relogin_fn a 401 is a plain failure (ok=False) — proves the refresh
    # is what rescues the request, not something free-standing.
    client = ve.HttpAskClient( "http://localhost:8000", bearer="stale",
                               post_fn=lambda url, json, headers, timeout: _FakeReply( 401, {} ) )
    rec = client.ask( "x" )
    assert rec[ "ok" ] is False
    assert rec[ "status_code" ] == 401


def test_http_ask_client_read_timeout_survives_a_slow_inference():
    # RED control for the 6th blocker. The n=60 closer ran 3h02m and then died on a
    # ReadTimeoutError: one POST /api/v2/ask exceeded the old 120s read wall, BEFORE either
    # arm's artifact was dumped, so the whole run was unrecoverable. The timeout the client
    # hands the transport must be the one that survives the SLOWEST call actually observed
    # (v2 inference degraded to ~60s+/call, one over 120s), not the old 120.
    seen = []
    client = ve.HttpAskClient(
        "http://localhost:8000", bearer="j",
        post_fn=lambda url, json, headers, timeout: seen.append( timeout ) or _FakeReply( 200, { "path": "replay" } ),
    )
    client.ask( "what time is it" )
    assert seen == [ ve.ASK_READ_TIMEOUT_SECONDS ]        # the constant reaches the transport, not a literal
    assert ve.ASK_READ_TIMEOUT_SECONDS >= 300.0           # RED at the old 120.0
    assert seen[ 0 ] > 120.0                              # RED if the default is reverted


def test_default_client_factory_read_timeout_default_and_env_override( monkeypatch ):
    # The live run builds its client through the factory, so the factory — not just the
    # class default — is where the read budget has to land. Env override exists so a run can
    # move the wall without a code edit; RED if the factory drops the timeout argument.
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "a@b.c" )
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", "pw" )
    class _LoginReply:
        def raise_for_status( self ):
            return None
        def json( self ):
            return { "tokens": { "access_token": "jwt-123" } }
    class _FakeRequests:
        @staticmethod
        def post( url, json, timeout ):
            return _LoginReply()
    monkeypatch.setitem( sys.modules, "requests", _FakeRequests )

    monkeypatch.delenv( "LUPIN_V2_ASK_TIMEOUT_SECONDS", raising=False )
    assert ve._default_client_factory( "http://localhost:8000" ).timeout == ve.ASK_READ_TIMEOUT_SECONDS

    monkeypatch.setenv( "LUPIN_V2_ASK_TIMEOUT_SECONDS", "900" )
    assert ve._default_client_factory( "http://localhost:8000" ).timeout == 900.0


def test_a_hanging_ask_leaves_a_dangling_start_that_names_the_utterance():
    """THE SURVIVORSHIP CONTROL (María, row d8d019f6).

    The v2 flow trace writes a row only at COMPLETION, so the one call worth seeing — the one
    that hung — was the only one guaranteed to leave no evidence. 983 calls survived the last
    run and the single request that blew the read wall left nothing, which is why the timeout
    is sized at 4x worst-OBSERVED instead of to a known worst case.

    Here the transport raises the way a real read timeout does. The rows must show a start with
    NO matching end, so the hang identifies itself, and the utterance must be named. RED if the
    start row is moved to after the POST, or dropped.
    """
    rows = []
    def hanging_post( url, json, headers, timeout ):
        raise TimeoutError( "read timed out" )
    client = ve.HttpAskClient( "http://localhost:8000", bearer="j", post_fn=hanging_post,
                               attempt_log_fn=rows.append, wall_clock=lambda: 1000.0 )
    with pytest.raises( TimeoutError ):
        client.ask( "how many items are left in my grocery list" )

    phases = [ r[ "phase" ] for r in rows ]
    assert "start" in phases and "end" not in phases          # a dangling start — the whole point
    start = rows[ 0 ]
    assert start[ "utterance" ] == "how many items are left in my grocery list"
    assert start[ "timeout_s" ] == ve.ASK_READ_TIMEOUT_SECONDS and start[ "wall_ts" ] == 1000.0
    # …and the error row names what was waited on, so the outlier has an identity next time.
    assert rows[ -1 ][ "phase" ] == "error" and rows[ -1 ][ "error" ] == "TimeoutError"


def test_a_completed_ask_logs_a_matching_start_and_end():
    # The other half of the property: every completed call closes its own start row, so a
    # dangling start is unambiguous evidence of a hang rather than a routine gap.
    rows   = []
    client = ve.HttpAskClient( "http://localhost:8000", bearer="j",
                               post_fn=lambda url, json, headers, timeout: _FakeReply( 200, { "path": "replay" } ),
                               attempt_log_fn=rows.append )
    client.ask( "what time is it" )
    client.ask( "and now" )
    assert [ r[ "phase" ] for r in rows ] == [ "start", "end", "start", "end" ]
    assert [ r[ "seq" ] for r in rows ] == [ 1, 1, 2, 2 ]      # rows pair up by sequence number
    assert rows[ 1 ][ "ok" ] is True and rows[ 1 ][ "client_span_ms" ] is not None


def test_attempt_logging_is_off_and_harmless_without_a_sink():
    # No sink wired -> no rows, no crash. Keeps the instrument optional for callers that
    # inject their own transport (every other test in this file).
    client = ve.HttpAskClient( "http://localhost:8000", bearer="j",
                               post_fn=lambda url, json, headers, timeout: _FakeReply( 200, {} ) )
    assert client.ask( "x" )[ "ok" ] is True


def test_make_attempt_logger_closes_each_row_to_disk_before_the_next( tmp_path ):
    # Durability is the point: a row still buffered when the process dies is a row that does
    # not exist — the exact failure this instrument was built to end. Reading the first row
    # BEFORE the second write is what proves it landed rather than sat in a buffer.
    path   = str( tmp_path / "nested" / "ask-attempts.jsonl" )
    logger = ve.make_attempt_logger( path )
    logger( { "phase": "start", "utterance": "u1" } )
    with open( path ) as handle:                              # read BEFORE the second write
        assert json.loads( handle.read().strip() )[ "utterance" ] == "u1"
    logger( { "phase": "end", "utterance": "u1" } )
    lines = [ json.loads( l ) for l in open( path ).read().strip().split( "\n" ) ]
    assert [ r[ "phase" ] for r in lines ] == [ "start", "end" ]


def test_make_attempt_logger_path_precedence( tmp_path, monkeypatch ):
    # Explicit path wins; otherwise the env var; the default lands under io/v2-flow.
    monkeypatch.setenv( "LUPIN_V2_ASK_ATTEMPT_LOG", str( tmp_path / "from-env.jsonl" ) )
    ve.make_attempt_logger()( { "phase": "start" } )
    assert ( tmp_path / "from-env.jsonl" ).exists()
    explicit = str( tmp_path / "explicit.jsonl" )
    ve.make_attempt_logger( explicit )( { "phase": "start" } )
    assert os.path.exists( explicit )


def test_http_ask_client_default_transport_imports_requests( monkeypatch ):
    sent = {}
    class _FakeRequests:
        @staticmethod
        def post( url, json, headers, timeout ):
            sent[ "url" ] = url
            return _FakeReply( 200, { "ok": 1 } )
    monkeypatch.setitem( sys.modules, "requests", _FakeRequests )
    client = ve.HttpAskClient( "http://localhost:8000", bearer="j" )   # post_fn None -> import branch
    rec = client.ask( "hello" )
    assert rec[ "ok" ] is True
    assert sent[ "url" ].endswith( "/api/v2/ask" )


def test_run_pass_attaches_expected_and_kind():
    corpus = [ ( "u1", "cmd-a" ), ( "u2", "cmd-b" ) ]
    def ask( q ):
        return { "utterance": q, "ok": True, "status_code": 200, "payload": {} }
    records = ve.run_pass( corpus, ask, "cold" )
    assert [ r[ "expected_command" ] for r in records ] == [ "cmd-a", "cmd-b" ]
    assert all( r[ "pass_kind" ] == "cold" for r in records )


def test_run_pass_fail_fast_aborts_on_first_bad():
    # A broken endpoint costs ONE request, not the corpus (Cheech, thread 4fb7f475).
    calls = []
    def ask( q ):
        calls.append( q )
        return { "utterance": q, "ok": False, "status_code": 503, "payload": {} }
    with pytest.raises( ve.EvalIntegrityError, match="fail-fast" ):
        ve.run_pass( [ ( "u1", "cmd-a" ), ( "u2", "cmd-b" ) ], ask, "cold", fail_fast=True )
    assert calls == [ "u1" ]                    # stopped after the first request


def test_run_pass_fail_fast_only_guards_the_first_request():
    # First OK ⇒ no abort; a LATER failure does not trip fail-fast (it guards index 0 only).
    def ask( q ):
        ok = ( q == "u1" )
        return { "utterance": q, "ok": ok, "status_code": 200 if ok else 503, "payload": {} }
    records = ve.run_pass( [ ( "u1", "cmd-a" ), ( "u2", "cmd-b" ) ], ask, "cold", fail_fast=True )
    assert len( records ) == 2 and records[ 1 ][ "ok" ] is False


# ---------------------------------------------------------------------------
# rendering + output
# ---------------------------------------------------------------------------
def test_fmt_none_and_value():
    assert ve._fmt( None ) == "n/a"
    assert ve._fmt( 3.5 )  == "3.5"


def test_render_report_carries_sections_and_caveat():
    m = ve.compute_metrics( _mixed_records() )
    table = ve.threshold_table( _mixed_records() )
    delta = { "p50_delta_ms": -1.0, "p95_delta_ms": None }
    report = ve.render_report( m, m, table, delta, "simple", "2026-08-14-02-30-00", seed=1024, n_per_command=60 )
    assert "# CJ Flow v2 eval" in report
    assert "EXECUTOR: AI" in report
    assert "Cache-hit rate vs threshold" in report
    assert ve.WOULD_BE_WRONG_CAVEAT in report
    assert "`replay`" in report          # by_path section rendered
    assert ve.NOT_GONOGO_BANNER in report                    # v2-only label pinned (Cheech, thread 4fb7f475)
    assert "NOT the go/no-go decision table" in report       # the label is legible, not just the constant


def test_write_outputs( tmp_path ):
    out = str( tmp_path / "eval-x" )
    paths = ve.write_outputs( out, "# report", [ _rec( trace_id="c" ) ], [ _rec( trace_id="w" ) ] )
    assert os.path.exists( paths[ "report" ] )
    with open( paths[ "records" ] ) as h:
        lines = [ l for l in h if l.strip() ]
    assert len( lines ) == 2


# ---------------------------------------------------------------------------
# main + arg parser + _default_client_factory
# ---------------------------------------------------------------------------
class _StubClient:
    def ask( self, question ):
        return { "utterance": question, "ok": True, "status_code": 200,
                 "payload": { "path": "agent", "trace_id": "tid-" + question,
                              "command": "agent router go to weather",
                              "timings_ms": { "t_first_useful": 7.0 } } }


def test_main_rejects_non_two_passes():
    with pytest.raises( ValueError ):
        ve.main( argv=[ "--passes", "1" ], client_factory=lambda url: _StubClient() )


def _seed_trace( tmp_path, questions ):
    """Write the day's authoritative JSONL with the stub's trace ids so parity holds."""
    ( tmp_path / "io" / "v2-flow" ).mkdir( parents=True, exist_ok=True )
    path = tmp_path / "io" / "v2-flow" / "trace-2026-08-14.jsonl"
    with open( path, "w" ) as h:
        for q in questions:
            h.write( json.dumps( { "trace_id": "tid-" + q } ) + "\n" )


_WEATHER_QUESTIONS = [ "what's the weather in Tokyo", "what's the weather" ]


def test_main_happy_path_explicit_args( tmp_path ):
    root  = str( tmp_path )
    _seed_trace( tmp_path, _WEATHER_QUESTIONS )
    result = ve.main(
        argv=[ "--corpus", "weather", "--passes", "2", "--max-router-error-rate", "1.0" ],
        client_factory=lambda url: _StubClient(),
        project_root=root,
        timestamp="2026-08-14-02-30-00",
    )
    assert os.path.exists( result[ "paths" ][ "report" ] )
    assert result[ "warm" ][ "n" ] == 2


def test_main_stamps_provenance_and_writes_paired_artifact( tmp_path ):
    # B3 + wiring: main stratified-samples (seed/n stamped), stamps a v2 provenance record,
    # and writes the {metrics, provenance} artifact paired_eval consumes.
    import json as _json
    _seed_trace( tmp_path, _WEATHER_QUESTIONS )
    result = ve.main(
        argv=[ "--corpus", "weather", "--max-router-error-rate", "1.0", "--seed", "7", "--n-per-command", "5" ],
        client_factory=lambda url: _StubClient(),
        project_root=str( tmp_path ),
        timestamp="2026-08-14-02-30-00",
    )
    prov = result[ "provenance" ]
    assert prov[ "arm" ] == "v2" and prov[ "corpus" ] == "weather"
    assert prov[ "seed" ] == 7 and prov[ "n_per_command" ] == 5 and prov[ "sampled_n" ] == 2

    artifact_path = result[ "paths" ][ "artifact" ]
    assert os.path.exists( artifact_path )
    with open( artifact_path ) as h:
        artifact = _json.load( h )
    assert artifact[ "provenance" ] == prov
    assert "spans_by_utterance" in artifact[ "metrics" ]
    # The report stamps the seed so the sample reproduces.
    assert "seed `7`" in open( result[ "paths" ][ "report" ] ).read()


def test_main_defaults_use_injected_helpers( tmp_path, monkeypatch ):
    root = str( tmp_path )
    _seed_trace( tmp_path, _WEATHER_QUESTIONS )
    class _FixedDT:
        def strftime( self, fmt ):
            return "2026-08-14-02-30-00"
    monkeypatch.setattr( ve.du, "get_project_root", lambda: root )
    monkeypatch.setattr( ve.du, "get_current_datetime_raw", lambda: _FixedDT() )
    monkeypatch.setattr( ve, "_default_client_factory", lambda url: _StubClient() )
    result = ve.main( argv=[ "--corpus", "weather", "--max-router-error-rate", "1.0" ] )
    assert result[ "cold" ][ "n" ] == 2
    assert os.path.isdir( result[ "out_dir" ] )


def test_default_client_factory_missing_env_raises( monkeypatch ):
    monkeypatch.delenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", raising=False )
    monkeypatch.delenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", raising=False )
    with pytest.raises( ValueError ):
        ve._default_client_factory( "http://localhost:8000" )


def test_default_client_factory_logs_in( monkeypatch ):
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "a@b.c" )
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", "pw" )
    class _LoginReply:
        def raise_for_status( self ):
            return None
        def json( self ):
            # REAL /auth/login shape (B1): the token is NESTED under "tokens". This fixture
            # exercises the real seam — it goes RED against the old flat read at v2_eval.py:1052.
            return { "tokens": { "access_token": "jwt-123" } }
    class _FakeRequests:
        @staticmethod
        def post( url, json, timeout ):
            assert url.endswith( "/auth/login" )
            return _LoginReply()
    monkeypatch.setitem( sys.modules, "requests", _FakeRequests )
    client = ve._default_client_factory( "http://localhost:8000/" )
    assert isinstance( client, ve.HttpAskClient )
    assert client.bearer == "jwt-123"


# ---------------------------------------------------------------------------
# F1 — the client-send instrument (ask stamps it; compute_metrics reports it)
# ---------------------------------------------------------------------------
def _clock_from( values ):
    """A fake monotonic clock that returns the given values in order."""
    seq = iter( values )
    return lambda: next( seq )


def test_ask_stamps_client_span_ms_from_injected_clock():
    # send at 10.0, reply in hand at 10.5 -> a 500 ms client-send span (deterministic).
    client = ve.HttpAskClient(
        "http://localhost:8000", bearer="j",
        post_fn=lambda url, json, headers, timeout: _FakeReply( 200, { "path": "replay" } ),
        clock=_clock_from( [ 10.0, 10.5 ] ),
    )
    rec = client.ask( "what time is it" )
    assert rec[ "client_span_ms" ] == 500.0


def test_ask_stamps_client_span_ms_even_on_http_error():
    # The span is send->reply regardless of status; a failed call is still timed.
    client = ve.HttpAskClient(
        "http://localhost:8000", bearer="j",
        post_fn=lambda url, json, headers, timeout: _FakeReply( 500, {} ),
        clock=_clock_from( [ 1.0, 1.2 ] ),
    )
    rec = client.ask( "x" )
    assert rec[ "ok" ] is False
    assert round( rec[ "client_span_ms" ], 6 ) == 200.0


def _rec_cs( client_span_ms, **kw ):
    """An ok record carrying a client_span_ms (the F1 instrument)."""
    r = _rec( **kw )
    r[ "client_span_ms" ] = client_span_ms
    return r


def test_compute_metrics_reports_client_instrument_when_present():
    records = [
        _rec_cs( 100.0, utterance="a", path="agent", command="agent router go to math", timings_ms={ "t_first_useful": 1.0 } ),
        _rec_cs( 200.0, utterance="b", path="agent", command="agent router go to math", timings_ms={ "t_first_useful": 2.0 } ),
        _rec_cs( 300.0, utterance="c", path="agent", command="agent router go to math", timings_ms={ "t_first_useful": 3.0 } ),
    ]
    m = ve.compute_metrics( records )
    # The paired gate's input: per-utterance client spans (keyed by utterance, not a flat list).
    assert m[ "spans_by_utterance" ] == { "a": 100.0, "b": 200.0, "c": 300.0 }
    assert m[ "client_p50_ms" ] == 200.0
    assert m[ "client_p95_ms" ] == 290.0
    # additive: the server-stamped mark is still reported, untouched.
    assert m[ "p50_first_useful_ms" ] == 2.0


def test_compute_metrics_client_instrument_empty_when_absent():
    # Records without client_span_ms -> the instrument reports no usable per-utterance spans.
    m = ve.compute_metrics( [ _rec( path="agent", command="agent router go to math" ) ] )
    assert m[ "spans_by_utterance" ] == {}
    assert m[ "client_p50_ms" ] is None
    assert m[ "client_p95_ms" ] is None


def test_render_report_carries_client_rows_and_instrument_caveat():
    m = ve.compute_metrics( [ _rec_cs( 120.0, path="replay", similarity=99.0,
                                       command="agent router go to math",
                                       timings_ms={ "t_first_useful": 4.0 } ) ] )
    report = ve.render_report( m, m, ve.threshold_table( [ _rec( path="replay", similarity=99.0 ) ] ),
                               { "p50_delta_ms": 0.0, "p95_delta_ms": 0.0 }, "simple", "2026-08-15-02-30-00",
                               seed=1024, n_per_command=60 )
    assert "client-send (ms)" in report
    assert "client-send** is the F1 cross-arm span" in report
    assert "proxy" in report
    # B3: the seed is stamped so the report is reproducible.
    assert "seed `1024`" in report and "n_per_command `60`" in report


# ---------------------------------------------------------------------------
# The paired median-Δ gate MOVED to paired_eval.py (row d8d019f6) — its tests live in
# test_paired_eval.py. v2 now only EMITS spans_by_utterance (covered above); the cross-arm
# gate, the provenance check, and the ≥20% median-of-Δ verdict are tested there.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# F3 — the cold-start guard (prove it can fail)
# ---------------------------------------------------------------------------
def test_guard_cold_start_passes_when_cold():
    assert ve.guard_cold_start( { "cache_hit_rate": 0.0 } ) is None
    assert ve.guard_cold_start( { "cache_hit_rate": None } ) is None   # no 200s -> nothing to contaminate


def test_guard_cold_start_raises_on_prewarmed_store():
    with pytest.raises( ve.EvalIntegrityError, match="cold-start integrity failed" ):
        ve.guard_cold_start( { "cache_hit_rate": 0.5 } )


class _ReplayClient:
    """Every ask returns a cache hit — so the COLD pass reads warmth (a contaminated baseline)."""
    def ask( self, question ):
        return { "utterance": question, "ok": True, "status_code": 200,
                 "payload": { "path": "replay", "similarity": 99.0,
                              "command": "agent router go to weather",
                              "trace_id": "tid-" + question,
                              "timings_ms": { "t_first_useful": 3.0 } } }


def test_main_cold_guard_raises_on_warm_cold( tmp_path ):
    _seed_trace( tmp_path, _WEATHER_QUESTIONS )
    with pytest.raises( ve.EvalIntegrityError, match="cold-start integrity failed" ):
        ve.main(
            argv=[ "--corpus", "weather", "--max-router-error-rate", "1.0" ],
            client_factory=lambda url: _ReplayClient(),
            project_root=str( tmp_path ),
            timestamp="2026-08-14-02-30-00",
        )


def test_main_allow_warm_cold_skips_the_guard( tmp_path ):
    _seed_trace( tmp_path, _WEATHER_QUESTIONS )
    result = ve.main(
        argv=[ "--corpus", "weather", "--max-router-error-rate", "1.0", "--allow-warm-cold" ],
        client_factory=lambda url: _ReplayClient(),
        project_root=str( tmp_path ),
        timestamp="2026-08-14-02-30-00",
    )
    assert result[ "warm" ][ "cache_hit_rate" ] == 1.0


# ---------------------------------------------------------------------------
# Per-arm clean-step — clean_v2_snapshot_store (design §4, decision B)
#
# MUST-FAIL CONTROLS: a config-drift and a wrong-db each RAISE before any TRUNCATE runs.
# The fake connection RECORDS every .execute, so "connection.execute was never called" is
# asserted, not assumed — the ordering (guards first, execute last) is the safety property.
# ---------------------------------------------------------------------------
class _FakeEngine:
    def __init__( self, url ):
        self.url = url


class _FakeConnection:
    """A DB connection stand-in: exposes .engine.url and records .execute( sql ) + .commit() calls.

    Records the SQL as a STRING because 291fb3fa wraps the statement in SQLAlchemy `text()`,
    and a TextClause compared with `==` builds an expression instead of answering True/False.
    Records commits because 9b90ae5d made the TRUNCATE's commit the thing under test.
    """
    def __init__( self, url ):
        self.engine    = _FakeEngine( url )
        self.executed  = []
        self.committed = 0
    def execute( self, sql ):
        self.executed.append( str( sql ) )
        return None
    def commit( self ):
        self.committed += 1


class _FakeCfgV2:
    """Minimal ConfigurationManager stand-in: .get( key, default, return_type )."""
    def __init__( self, values ):
        self.values = values
    def get( self, key, default=None, return_type=None ):
        return self.values.get( key, default )


def _clean_cfg( declared ):
    return _FakeCfgV2( { "v2 snapshot table": declared } )


def test_clean_v2_snapshot_store_truncates_after_both_guards( monkeypatch ):
    # Pin the ORM write target so the test does not depend on the live model attribute.
    import eval_isolation_guard as guard
    monkeypatch.setattr( guard, "resolve_write_target", lambda: "solution_snapshots" )
    conn = _FakeConnection( "postgresql://u:p@h/lupin_db_test" )
    cfg  = _clean_cfg( "solution_snapshots" )
    result = ve.clean_v2_snapshot_store( conn, cfg )
    assert result == "solution_snapshots"
    # The TRUNCATE identifier is the RESOLVED target, never the raw config string.
    assert conn.executed == [ "TRUNCATE TABLE solution_snapshots" ]
    # And it is COMMITTED: SQLAlchemy 2.x is commit-as-you-go, so an uncommitted TRUNCATE rolls
    # back on close and the store stays dirty (9b90ae5d). RED if connection.commit() is removed.
    assert conn.committed == 1


def test_clean_v2_snapshot_store_refuses_config_drift_without_truncating( monkeypatch ):
    # CONTROL A: declared table != ORM write target -> raises, connection.execute NEVER called.
    import eval_isolation_guard as guard
    monkeypatch.setattr( guard, "resolve_write_target", lambda: "solution_snapshots" )
    conn = _FakeConnection( "postgresql://u:p@h/lupin_db_test" )
    cfg  = _clean_cfg( "v2_paired_snapshots" )
    with pytest.raises( guard.ConfigTableMismatch ):
        ve.clean_v2_snapshot_store( conn, cfg )
    assert conn.executed == [] and conn.committed == 0    # no TRUNCATE, and nothing committed


def test_clean_v2_snapshot_store_refuses_wrong_db_without_truncating( monkeypatch ):
    # CONTROL B: config matches but the connection points at the live dev db -> raises,
    # connection.execute NEVER called.
    import eval_isolation_guard as guard
    monkeypatch.setattr( guard, "resolve_write_target", lambda: "solution_snapshots" )
    conn = _FakeConnection( "postgresql://u:p@h/lupin_db_dev" )
    cfg  = _clean_cfg( "solution_snapshots" )
    with pytest.raises( guard.NotAMeasurementDatabase ):
        ve.clean_v2_snapshot_store( conn, cfg )
    assert conn.executed == [] and conn.committed == 0    # no TRUNCATE, and nothing committed


def test_clean_v2_snapshot_store_config_check_fires_before_db_check( monkeypatch ):
    # Ordering: BOTH wrong (drifted config AND wrong db) -> the config mismatch is raised
    # first, so a misconfigured operator is told the actionable cause and no db is touched.
    import eval_isolation_guard as guard
    monkeypatch.setattr( guard, "resolve_write_target", lambda: "solution_snapshots" )
    conn = _FakeConnection( "postgresql://u:p@h/lupin_db_dev" )
    cfg  = _clean_cfg( "v2_paired_snapshots" )
    with pytest.raises( guard.ConfigTableMismatch ):
        ve.clean_v2_snapshot_store( conn, cfg )
    assert conn.executed == [] and conn.committed == 0
