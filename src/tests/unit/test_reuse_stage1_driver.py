"""
The measurement driver: arms as runs, the stage budget, the canary gate, results files.

Design: the measurement run sheet (sections 0 and 7) and the arm results format file.
Every transport here is a stand-in. Nothing reaches Jev and no real ledger is touched.
"""
import json
import threading

import pytest

from cosa.repo.doc_lint import jev_transport as jt
from lupin_mcp import reuse_ceiling as rc
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_stage1 as st
from lupin_mcp import reuse_tools as rt

NEED    = "read an RSS feed and return its articles"
PROBS   = { "reuse": 0.7, "extend": 0.2, "unrelated": 0.1 }
ENTRIES = [ { "id": f"pkg.mod.fn{i:03d}", "sig": "()", "doc": f"Does thing {i}.", "file": "src/pkg/mod.py" } for i in range( 25 ) ]
PAGES   = [ { "id": f"page.{i}", "sig": "", "doc": f"Page {i} describes a capability." } for i in range( 3 ) ]
LIMIT   = rl.ACCOUNT_LIMIT_TOKENS


class Standin:
    """
    A transport that answers any packed body and records it.

    `out_per_entry` is the output tokens it reports for each question; `usage_in` the input tokens.
    `refuse_over` raises a 422 for a body with more questions. `die_after` raises a JevCallError from that request on.
    """

    def __init__( self, budget, out_per_entry=40, usage_in=500, refuse_over=None, die_after=None, usage=True, hook=None, drop_last=False ):
        self.budget, self.out, self.usage_in, self.refuse_over, self.die_after, self.usage, self.hook = budget, out_per_entry, usage_in, refuse_over, die_after, usage, hook
        self.drop_last = drop_last
        self.bodies, self.lock = [], threading.Lock()

    def post_with_meta( self, body ):
        self.budget.take()
        with self.lock:
            self.bodies.append( body )
            n = len( self.bodies )
        if self.hook is not None: self.hook( n )
        if self.die_after is not None and n > self.die_after: raise jt.JevCallError( "down" )
        if self.refuse_over is not None and len( body[ "questions" ] ) > self.refuse_over: raise jt.JevConfigError( "Jev refused the request with status 422", 422 )
        response = { "answers": { key: { "probabilities": dict( PROBS ) } for key in body[ "questions" ] }, "model": body[ "model" ] }
        if self.drop_last: response[ "answers" ].popitem()                                      # one question the response leaves out
        if self.usage: response[ "usage" ] = { "input_tokens": self.usage_in, "output_tokens": self.out * len( body[ "questions" ] ) }
        return response, { "status": 200, "attempts": 1, "retry_after": None, "latency_ms": 3 }


@pytest.fixture
def env( tmp_path ):
    """A driver environment on a scratch ledger; `made` collects the stand-ins it builds."""
    ledger = rl.AccountLedger.create( tmp_path / "ledger.jsonl", LIMIT, "test", "scratch" )
    made   = []

    def factory( budget, **kw ):
        made.append( Standin( budget, **{ **env.standin, **kw } ) )
        return made[ -1 ]

    env = st.Stage1Env( root=tmp_path, data=tmp_path / "data", ledger=ledger, transport_factory=factory, entries_in_index=len( ENTRIES ) )
    env.standin, env.made, env.ledger = {}, made, ledger
    return env


def read( env, question, arm ):
    """The results file of one arm, as written."""
    return json.loads( ( env.results_dir / f"{st.run_name( question, arm )}.json" ).read_text() )


def bodies( env ): return [ b for t in env.made for b in t.bodies ]


def test_names_indexes_and_sizes_of_the_arms():
    assert st.run_name( 2, "pack50" ) == "s1-q2-pack50"
    assert st.ARMS == { "single1": ( 1, 1 ), "single2": ( 2, 1 ), "canary": ( 3, 10 ), "pack10": ( 3, 10 ), "pack50": ( 4, 50 ), "pack200": ( 5, 200 ),
                        "page-single1": ( 6, 1 ), "page-single2": ( 7, 1 ), "page-pack": ( 8, 200 ),
                        "probe-first-random": ( 9, 200 ), "probe-middle-random": ( 10, 200 ), "probe-last-random": ( 11, 200 ),
                        "probe-first-near": ( 12, 200 ), "probe-middle-near": ( 13, 200 ), "probe-last-near": ( 14, 200 ) }
    assert len( { index for index, size in st.ARMS.values() if size != 10 } | { 3 } ) == len( st.ARMS ) - 1        # only the canary and pack10 share an index
    assert st.STAGE_TOKENS == 71_000_000 == rl.STAGE1_CEILING_TOKENS


@pytest.mark.parametrize( "question,arm", [ ( 0, "single1" ), ( 5, "single1" ), ( "1", "single1" ), ( True, "single1" ), ( 1, "pack7" ) ] )
def test_a_question_or_arm_out_of_range_is_refused_before_anything_happens( env, question, arm ):
    with pytest.raises( ValueError ): st.run_arm( env, question, arm, NEED, ENTRIES, 1_000_000 )
    assert env.made == [] and not env.results_dir.exists()


def test_the_ledger_counts_a_prefix_closed_at_spend_and_open_at_the_larger_of_ceiling_and_spend( env ):
    led = env.ledger
    led.begin_run( "s1-a", 10 ); led.spend( "s1-a", 3 ); led.end_run( "s1-a" )
    led.begin_run( "s1-b", 10 ); led.spend( "s1-b", 4 )
    led.begin_run( "s1-c", 5 ); led.spend( "s1-c", 9 )
    led.begin_run( "other", 100 )
    assert led.held_by_prefix( "s1-" ) == 3 + 10 + 9
    assert led.held_by_prefix( "other" ) == 100 and led.held_by_prefix( "nothing" ) == 0


def test_the_stage_remaining_is_the_stage_total_less_what_its_runs_hold( env ):
    assert st.stage_remaining( env.ledger ) == 71_000_000
    env.ledger.begin_run( "s1-q1-dead", 30_000_000 )
    assert st.stage_remaining( env.ledger ) == 41_000_000


def test_an_arm_that_asks_for_more_than_the_stage_has_left_is_refused_before_any_send( env ):
    env.ledger.begin_run( "s1-q1-dead", 70_000_000 )                       # a run whose process died and was never closed
    rows_before = env.ledger.path.read_text()
    with pytest.raises( st.StageRefused, match="remaining" ):
        st.run_arm( env, 1, "single1", NEED, ENTRIES, 1_500_000 )
    assert env.made == [] and env.ledger.path.read_text() == rows_before and not env.results_dir.exists()


def test_the_remaining_ceiling_itself_is_granted_and_one_token_more_is_not( env ):
    env.ledger.begin_run( "s1-q1-dead", 70_000_000 )
    with pytest.raises( st.StageRefused ): st.run_arm( env, 1, "single1", NEED, ENTRIES[ :2 ], 1_000_001 )
    assert read_after( env, 1_000_000 )[ "state" ] == "complete"


def read_after( env, ceiling ):
    st.run_arm( env, 1, "single1", NEED, ENTRIES[ :2 ], ceiling )
    return read( env, 1, "single1" )


def test_an_arm_closes_its_run_so_the_stage_then_holds_only_what_it_spent( env ):
    st.run_arm( env, 1, "single1", NEED, ENTRIES[ :4 ], 5_000_000 )
    held = env.ledger.held_by_prefix( "s1-" )
    assert held == read( env, 1, "single1" )[ "totals" ][ "spent_tokens" ] == 4 * ( 500 + 40 ) < 5_000_000
    assert st.stage_remaining( env.ledger ) == 71_000_000 - held


def test_an_arm_asking_for_more_than_the_attempt_cap_is_refused_before_a_ledger_row( env ):
    before = env.ledger.path.read_text()
    with pytest.raises( rt.ReuseError ) as caught:
        st.run_arm( env, 1, "single1", NEED, ENTRIES, 1_000_000, attempt_limit=rt.CALL_BUDGET_CAP + 1 )
    assert caught.value.name == "BAD_BUDGET" and env.ledger.path.read_text() == before and env.made == []


def test_the_default_attempt_limit_is_the_cap_and_is_what_the_budget_gets( env ):
    st.run_arm( env, 1, "single1", NEED, ENTRIES[ :2 ], 1_000_000 )
    assert read( env, 1, "single1" )[ "attempt_limit" ] == rt.CALL_BUDGET_CAP == env.made[ 0 ].budget.limit


def test_a_single_entry_arm_that_runs_out_of_attempts_says_so_and_does_not_raise( env ):
    st.run_arm( env, 1, "single1", NEED, ENTRIES, 5_000_000, attempt_limit=10 )
    out = read( env, 1, "single1" )
    assert out[ "state" ] == "incomplete" and out[ "stop_reason" ] == "attempts"
    assert len( out[ "answers" ] ) == 10 and len( out[ "not_reached" ] ) == 15 and out[ "failed" ] == []
    assert out[ "totals" ][ "calls" ] == 10 and len( [ r for r in out[ "rows" ] if r[ "attempts" ] ] ) == 10          # 25 rows, ten of them sent
    assert env.ledger.snapshot()[ 1 ] == out[ "totals" ][ "spent_tokens" ]


def test_a_ceiling_reached_mid_arm_leaves_the_rest_not_reached_with_the_ceiling_as_the_reason( env ):
    st.run_arm( env, 1, "single1", NEED, ENTRIES, 6_000 )                  # about eleven requests at 500 in and 40 out
    out = read( env, 1, "single1" )
    assert out[ "state" ] == "incomplete" and out[ "stop_reason" ] == "ceiling"
    assert out[ "totals" ][ "ceiling_refusals" ] > 0 and out[ "not_reached" ] and out[ "totals" ][ "spent_tokens" ] <= 6_000


def test_arms_do_not_share_answers_so_each_asks_again( env ):
    entries = ENTRIES[ :6 ]
    st.run_arm( env, 1, "single1", NEED, entries, 5_000_000 )
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 ); st.approve_canary( env, 1, "maria", "ok" )
    before = len( bodies( env ) )
    st.run_arm( env, 1, "single2", NEED, entries, 5_000_000 )
    assert before == 6 + 1 and len( bodies( env ) ) - before == 6                  # six more requests, none served from the first arm
    assert read( env, 1, "single2" )[ "cache_hits" ] == 0 and len( read( env, 1, "single2" )[ "answers" ] ) == 6


def test_an_arm_run_again_under_the_same_name_is_refused_and_the_first_file_is_kept( env ):
    st.run_arm( env, 1, "single1", NEED, ENTRIES[ :2 ], 1_000_000 )
    first = ( env.results_dir / "s1-q1-single1.json" ).read_text()
    with pytest.raises( ValueError, match="already began" ): st.run_arm( env, 1, "single1", NEED, ENTRIES[ :2 ], 1_000_000 )
    assert ( env.results_dir / "s1-q1-single1.json" ).read_text() == first


def test_a_missing_ledger_stops_everything_before_a_send_or_a_file( env, tmp_path ):
    env.ledger.path.unlink()
    with pytest.raises( rl.LedgerUnreadable ): st.run_arm( env, 1, "single1", NEED, ENTRIES[ :2 ], 1_000_000 )
    assert env.made == [] and not env.results_dir.exists()


def test_a_run_that_raises_is_closed_in_the_ledger_and_its_file_says_error( env, monkeypatch ):
    def boom( *a, **k ): raise RuntimeError( "disk full" )
    monkeypatch.setattr( rp, "sweep_packed", boom )
    with pytest.raises( RuntimeError, match="disk full" ): st.run_arm( env, 1, "single1", NEED, ENTRIES[ :3 ], 2_000_000 )
    kinds = [ json.loads( line )[ "kind" ] for line in env.ledger.path.read_text().splitlines() ]
    assert kinds == [ "limit", "begin", "end" ]
    out = read( env, 1, "single1" )
    assert out[ "state" ] == "error" and out[ "stop_reason" ] == "error: RuntimeError" and out[ "answers" ] == []
    assert st.stage_remaining( env.ledger ) == 71_000_000                  # nothing spent, so nothing held


def test_the_results_file_holds_every_request_and_the_fields_the_analysis_reads( env ):
    st.run_arm( env, 2, "single1", NEED, ENTRIES[ :5 ], 2_000_000 )
    out = read( env, 2, "single1" )
    assert out[ "format" ] == "stage1-arm-1" and out[ "question" ] == 2 and out[ "arm" ] == "single1" and out[ "run_name" ] == "s1-q2-single1"
    assert out[ "need" ] == NEED and out[ "run_index" ] == 1 and out[ "size" ] == 1 and out[ "model" ] == rt.JEV_MODEL
    assert out[ "template_hash" ] == rt.prompt_template_hash( rt.PROMPT_TEMPLATE ) and out[ "ceiling_tokens" ] == 2_000_000
    assert out[ "entry_ids" ] == [ e[ "id" ] for e in ENTRIES[ :5 ] ] == [ a[ "id" ] for a in out[ "answers" ] ]
    assert out[ "answers" ][ 0 ][ "probabilities" ] == PROBS and out[ "entries_in_index" ] == len( ENTRIES )
    assert out[ "state" ] == "complete" and out[ "stop_reason" ] is None and out[ "started_at" ] and out[ "ended_at" ]
    assert len( out[ "rows" ] ) == out[ "totals" ][ "requests" ] == 5 == len( out[ "transport_calls" ] )
    assert out[ "totals" ][ "tokens_in" ] == 5 * 500 and out[ "totals" ][ "tokens_out" ] == 5 * 40
    assert not list( env.results_dir.glob( "*.tmp" ) )


def test_each_rows_reserve_is_recorded_from_its_own_body( env ):
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 ); st.approve_canary( env, 1, "maria", "ok" )
    st.run_arm( env, 1, "pack50", NEED, ENTRIES[ :10 ], 5_000_000 )          # not pack10: the canary already answered those ten under pack10's keys
    out  = read( env, 1, "pack50" )
    body = rp.pack_request( NEED, ENTRIES[ :10 ] )[ 0 ]
    assert [ r[ "reserve_tokens" ] for r in out[ "rows" ] ] == [ rc.reserve_tokens( body, 10 ) ]


def test_a_row_that_was_never_sent_has_no_reserve( env ):
    st.run_arm( env, 1, "single1", NEED, ENTRIES, 5_000_000, attempt_limit=3 )
    rows = read( env, 1, "single1" )[ "rows" ]
    sent, unsent = [ r for r in rows if r[ "attempts" ] ], [ r for r in rows if r[ "status" ] == "not_reached" ]
    assert len( sent ) == 3 and len( unsent ) == len( ENTRIES ) - 3 == len( rows ) - 3
    assert all( r[ "reserve_tokens" ] is not None for r in sent ) and all( r[ "reserve_tokens" ] is None for r in unsent )


def test_every_arm_after_the_first_is_refused_until_the_canary_is_approved( env ):
    for arm in ( "single2", "pack10", "pack50", "pack200", "page-single1", "page-single2", "page-pack", "probe-first-random", "probe-last-near" ):
        with pytest.raises( st.CanaryNotApproved, match="canary" ): st.run_arm( env, 1, arm, NEED, ENTRIES[ :4 ], 1_000_000 )
    assert env.made == [] and not env.results_dir.exists()
    st.run_arm( env, 1, "single1", NEED, ENTRIES[ :4 ], 1_000_000 )         # the first single run is allowed before the canary


def test_the_canary_asks_the_first_ten_in_one_request_and_only_it_spends( env ):
    report = st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 )
    assert len( bodies( env ) ) == 1 and len( bodies( env )[ 0 ][ "questions" ] ) == 10
    assert report[ "tripped" ] == [] and report[ "approved" ] is None and report[ "output_tokens_per_entry" ] == [ 40 ]
    spend_rows = [ json.loads( line ) for line in env.ledger.path.read_text().splitlines() if '"spend"' in line ]
    assert {r[ "run" ] for r in spend_rows } == { "s1-q1-canary" } and sum( r[ "tokens" ] for r in spend_rows ) == 500 + 400
    assert ( env.results_dir / "s1-q1-canary.canary.json" ).exists() and read( env, 1, "canary" )[ "size" ] == 10


def test_a_canary_that_stays_inside_every_number_is_approved_and_the_gate_opens( env ):
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 )
    st.approve_canary( env, 1, "maria", "read the first pack: 40 tokens an entry, no refusal" )
    approval = json.loads( ( env.results_dir / "s1-q1-canary.canary.json" ).read_text() )[ "approved" ]
    assert approval[ "by" ] == "maria" and "40 tokens" in approval[ "why" ] and approval[ "at" ]
    st.run_arm( env, 1, "pack10", NEED, ENTRIES, 2_000_000 )
    assert read( env, 1, "pack10" )[ "cache_hits" ] == 10                   # the canary's ten come back from the arm's own cache


def test_approval_is_per_question( env ):
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 )
    st.approve_canary( env, 1, "maria", "ok" )
    with pytest.raises( st.CanaryNotApproved ): st.run_arm( env, 2, "pack10", NEED, ENTRIES, 2_000_000 )


def test_the_canary_trips_when_output_tokens_per_entry_pass_the_reserve_of_sixty( env ):
    env.standin = { "out_per_entry": 61 }
    report = st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 )
    assert "output_per_entry_over_60" in report[ "tripped" ] and report[ "output_tokens_per_entry" ] == [ 61 ]


def test_exactly_sixty_output_tokens_an_entry_does_not_trip( env ):
    env.standin = { "out_per_entry": 60 }
    assert st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 )[ "tripped" ] == []


def test_the_canary_trips_when_usage_passes_the_requests_reserve( env ):
    body    = rp.pack_request( NEED, ENTRIES[ :10 ] )[ 0 ]
    reserve = rc.reserve_tokens( body, 10 )
    env.standin = { "usage_in": reserve, "out_per_entry": 1 }
    report = st.run_canary( env, 1, NEED, ENTRIES, 5_000_000 )
    assert "usage_over_reserve" in report[ "tripped" ] and report[ "usage_vs_reserve" ][ 0 ][ "over" ] is True
    assert report[ "usage_vs_reserve" ][ 0 ][ "reserve" ] == reserve and report[ "usage_vs_reserve" ][ 0 ][ "usage" ] == reserve + 10


def test_usage_equal_to_the_reserve_does_not_trip( env ):
    body    = rp.pack_request( NEED, ENTRIES[ :10 ] )[ 0 ]
    reserve = rc.reserve_tokens( body, 10 )
    env.standin = { "usage_in": reserve - 10, "out_per_entry": 1 }
    report = st.run_canary( env, 1, NEED, ENTRIES, 5_000_000 )
    assert report[ "tripped" ] == [] and report[ "usage_vs_reserve" ][ 0 ][ "over" ] is False


def test_the_canary_trips_on_any_refusal( env ):
    env.standin = { "refuse_over": 5 }
    report = st.run_canary( env, 1, NEED, ENTRIES, 5_000_000 )
    assert "refusal" in report[ "tripped" ] and report[ "refusals" ] >= 1


def test_the_canary_trips_when_a_response_carries_no_usage_because_it_cannot_be_read_against_the_reserve( env ):
    env.standin = { "usage": False }
    assert "usage_missing" in st.run_canary( env, 1, NEED, ENTRIES, 5_000_000 )[ "tripped" ]


def test_a_tripped_canary_is_never_approved( env ):
    env.standin = { "out_per_entry": 90 }
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 )
    with pytest.raises( st.CanaryTripped, match="output_per_entry_over_60" ): st.approve_canary( env, 1, "maria", "looks fine to me" )
    with pytest.raises( st.CanaryNotApproved ): st.run_arm( env, 1, "pack10", NEED, ENTRIES, 2_000_000 )


def test_approval_needs_a_canary_and_a_named_approver_and_a_reason( env ):
    with pytest.raises( st.CanaryNotApproved, match="no canary" ): st.approve_canary( env, 1, "maria", "ok" )
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 )
    for by, why in ( ( "", "ok" ), ( "maria", "" ), ( None, "ok" ) ):
        with pytest.raises( ValueError, match="by and why" ): st.approve_canary( env, 1, by, why )


def test_an_approved_canary_cannot_be_approved_again( env ):
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 )
    st.approve_canary( env, 1, "maria", "ok" )
    with pytest.raises( ValueError, match="already approved" ): st.approve_canary( env, 1, "someone", "again" )


def test_the_page_arms_ask_the_page_template_each_under_its_own_index( env ):
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 ); st.approve_canary( env, 1, "maria", "ok" )
    for arm, index, size in ( ( "page-single1", 6, 1 ), ( "page-single2", 7, 1 ), ( "page-pack", 8, 200 ) ):
        st.run_arm( env, 1, arm, NEED, PAGES, 2_000_000 )
        out = read( env, 1, arm )
        assert out[ "template_hash" ] == rt.prompt_template_hash( rt.PAGE_TEMPLATE ) and out[ "run_index" ] == index and out[ "size" ] == size
        assert out[ "entry_ids" ] == [ p[ "id" ] for p in PAGES ] and out[ "cache_hits" ] == 0
    first_words = rt.PAGE_TEMPLATE[ "instructions" ].split( "CANDIDATE" )[ 0 ]
    assert all( first_words in q[ "instructions" ] for q in bodies( env )[ -1 ][ "questions" ].values() )


def probe_of( entry, placement="middle", neighbours="random" ): return { "id": entry[ "id" ], "placement": placement, "neighbours": neighbours }


def test_a_probe_arm_records_its_probe_and_asks_one_pack_with_the_whole_pack_answered( env ):
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 ); st.approve_canary( env, 1, "maria", "ok" )
    probe = probe_of( ENTRIES[ 12 ], "middle", "near_duplicate" )
    st.run_arm( env, 1, "probe-middle-near", NEED, ENTRIES, 2_000_000, probe=probe )
    out = read( env, 1, "probe-middle-near" )
    assert out[ "probe" ] == probe and out[ "run_index" ] == 13 and out[ "size" ] == 200
    assert out[ "totals" ][ "requests" ] == 1 and len( out[ "answers" ] ) == len( ENTRIES )


def test_a_probe_arm_without_a_probe_and_another_arm_with_one_are_refused( env ):
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 ); st.approve_canary( env, 1, "maria", "ok" )
    with pytest.raises( ValueError, match="probe" ): st.run_arm( env, 1, "probe-first-random", NEED, ENTRIES, 2_000_000 )
    with pytest.raises( ValueError, match="probe" ): st.run_arm( env, 1, "pack50", NEED, ENTRIES, 2_000_000, probe=probe_of( ENTRIES[ 0 ] ) )
    assert len( bodies( env ) ) == 1                                         # only the canary was ever sent


@pytest.mark.parametrize( "probe", [ { "id": "x", "placement": "top", "neighbours": "random" }, { "id": "x", "placement": "first", "neighbours": "close" },
                                     { "placement": "first", "neighbours": "random" }, "x", { "id": "x", "placement": "first", "neighbours": "random", "extra": 1 } ] )
def test_a_malformed_probe_is_refused_before_any_send( env, probe ):
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 ); st.approve_canary( env, 1, "maria", "ok" )
    with pytest.raises( ValueError, match="probe" ): st.run_arm( env, 1, "probe-first-random", NEED, ENTRIES, 2_000_000, probe=probe )
    assert len( bodies( env ) ) == 1


def test_a_probe_must_name_an_entry_of_the_pack_and_its_arm_must_match_the_placement( env ):
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 ); st.approve_canary( env, 1, "maria", "ok" )
    with pytest.raises( ValueError, match="not in the pack" ): st.run_arm( env, 1, "probe-first-random", NEED, ENTRIES[ :5 ], 2_000_000, probe=probe_of( ENTRIES[ 9 ], "first" ) )
    with pytest.raises( ValueError, match="arm" ): st.run_arm( env, 1, "probe-last-random", NEED, ENTRIES, 2_000_000, probe=probe_of( ENTRIES[ 0 ], "first", "random" ) )
    with pytest.raises( ValueError, match="arm" ): st.run_arm( env, 1, "probe-first-near", NEED, ENTRIES, 2_000_000, probe=probe_of( ENTRIES[ 0 ], "first", "random" ) )


def test_repeated_refusals_stop_the_arm_and_the_reason_names_the_breaker( env ):
    env.standin = { "refuse_over": 0 }
    st.run_arm( env, 1, "single1", NEED, ENTRIES[ :1 ], 5_000_000, attempt_limit=50 )
    assert read( env, 1, "single1" )[ "failed" ] == [ ENTRIES[ 0 ][ "id" ] ] and read( env, 1, "single1" )[ "totals" ][ "refused_422" ] == 1


def test_a_dying_transport_marks_the_requests_failed_and_the_arm_incomplete( env ):
    env.standin = { "die_after": 2 }
    st.run_arm( env, 1, "single1", NEED, ENTRIES[ :5 ], 5_000_000 )
    out = read( env, 1, "single1" )
    assert out[ "state" ] == "incomplete" and len( out[ "failed" ] ) == 3 and len( out[ "answers" ] ) == 2
    assert out[ "stop_reason" ] is None                                      # failed requests are reported by `failed`, not as a stop


def test_the_entry_count_of_the_run_tree_is_written_into_the_file( env ):
    env.entries_in_index = 5712
    st.run_arm( env, 1, "single1", NEED, ENTRIES[ :2 ], 1_000_000 )
    assert read( env, 1, "single1" )[ "entries_in_index" ] == 5712


def test_a_ledger_whose_total_passes_the_limit_mid_arm_stops_the_arm_with_the_ledger_as_the_reason( env ):
    env.standin = { "hook": lambda n: env.ledger.set_limit( 10, "peer", "another run spent the account" ) if n == 3 else None }
    st.run_arm( env, 1, "single1", NEED, ENTRIES, 5_000_000, attempt_limit=50 )
    out = read( env, 1, "single1" )
    assert out[ "state" ] == "incomplete" and out[ "stop_reason" ] == "ledger" and out[ "not_reached" ]


def test_five_refused_requests_in_a_row_stop_the_arm_and_the_reason_is_the_breaker( env ):
    env.standin = { "refuse_over": 0 }
    st.run_arm( env, 1, "single1", NEED, ENTRIES[ :12 ], 5_000_000, attempt_limit=50 )
    out = read( env, 1, "single1" )
    assert out[ "stop_reason" ] == "consecutive_422" == out[ "totals" ][ "stopped_by" ] and out[ "totals" ][ "refused_422" ] >= rt.BREAKER_422 and out[ "not_reached" ]


@pytest.mark.parametrize( "arm,place,near,where", [ ( "probe-first-random", "first", "random", 3 ), ( "probe-last-near", "last", "near_duplicate", 3 ),
                                                    ( "probe-middle-random", "middle", "random", 0 ), ( "probe-middle-near", "middle", "near_duplicate", 24 ) ] )
def test_a_probe_must_sit_where_its_placement_says( env, arm, place, near, where ):
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 ); st.approve_canary( env, 1, "maria", "ok" )
    with pytest.raises( ValueError, match="position" ): st.run_arm( env, 1, arm, NEED, ENTRIES, 2_000_000, probe=probe_of( ENTRIES[ where ], place, near ) )
    assert len( bodies( env ) ) == 1


def test_a_probe_in_each_right_place_is_accepted( env ):
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 ); st.approve_canary( env, 1, "maria", "ok" )
    for place, where in ( ( "first", 0 ), ( "middle", 12 ), ( "last", 24 ) ):
        st.run_arm( env, 1, f"probe-{place}-random", NEED, ENTRIES, 2_000_000, probe=probe_of( ENTRIES[ where ], place, "random" ) )
        assert read( env, 1, f"probe-{place}-random" )[ "state" ] == "complete"


def test_a_canary_that_did_not_finish_trips( env ):
    env.standin = { "die_after": 0 }
    report = st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 )
    assert "incomplete" in report[ "tripped" ] and report[ "output_tokens_per_entry" ] == []


def test_the_default_transport_is_the_live_one_on_the_arms_own_budget( env ):
    default = st.Stage1Env( env.root, env.data, env.ledger )
    budget  = rc.TokenBudget( 5, 1_000_000 )
    transport = default.transport_factory( budget )
    assert isinstance( transport, rt.LiveJevTransport ) and transport.budget is budget


def test_a_retried_request_is_counted_in_the_canary( env ):
    class Retried( Standin ):
        def post_with_meta( self, body ):
            response, meta = super().post_with_meta( body )
            return response, { **meta, "attempts": 2 }
    env.transport_factory = lambda budget: Retried( budget )
    assert st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 )[ "attempts_over_one" ] == 1


def tripped_canary( env, attempt=1, reason=None, out=90 ):
    """Run a canary that trips on output tokens; returns its report."""
    env.standin = { "out_per_entry": out }
    return st.run_canary( env, 1, NEED, ENTRIES, 2_000_000, attempt=attempt, reason=reason )


def test_a_canary_retry_is_a_new_run_with_its_own_files_and_the_first_is_kept( env ):
    tripped_canary( env )
    first = [ ( env.results_dir / name ).read_bytes() for name in ( "s1-q1-canary.json", "s1-q1-canary.canary.json" ) ]
    env.standin = {}
    report = st.run_canary( env, 1, NEED, ENTRIES, 2_000_000, attempt=2, reason="the transport timed out on the first attempt" )
    assert report[ "run_name" ] == "s1-q1-canary-a2" and report[ "attempt" ] == 2 and report[ "tripped" ] == []
    assert report[ "retry_reason" ] == "the transport timed out on the first attempt"
    assert [ ( env.results_dir / name ).read_bytes() for name in ( "s1-q1-canary.json", "s1-q1-canary.canary.json" ) ] == first
    assert ( env.results_dir / "s1-q1-canary-a2.json" ).exists() and ( env.results_dir / "s1-q1-canary-a2.canary.json" ).exists()


def test_the_results_file_names_its_attempt_and_the_reason( env ):
    tripped_canary( env )
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000, attempt=2, reason="retry after a fix" )
    assert read( env, 1, "canary" )[ "attempt" ] == 1 and read( env, 1, "canary" )[ "retry_reason" ] is None
    out = json.loads( ( env.results_dir / "s1-q1-canary-a2.json" ).read_text() )
    assert out[ "attempt" ] == 2 and out[ "retry_reason" ] == "retry after a fix" and out[ "run_name" ] == "s1-q1-canary-a2"


def test_every_attempts_spend_counts_on_the_ledger_and_the_stage( env ):
    tripped_canary( env )
    tripped_canary( env, attempt=2, reason="second look" )
    one, two = ( json.loads( ( env.results_dir / n ).read_text() )[ "totals" ][ "spent_tokens" ] for n in ( "s1-q1-canary.json", "s1-q1-canary-a2.json" ) )
    assert one == two == 500 + 900
    assert env.ledger.held_by_prefix( "s1-" ) == one + two and st.stage_remaining( env.ledger ) == 71_000_000 - one - two


def test_a_retry_that_would_pass_the_stage_cap_is_refused_before_any_send( env ):
    tripped_canary( env )
    env.ledger.begin_run( "s1-q9-dead", 70_000_000 )
    sent = len( bodies( env ) )
    with pytest.raises( st.StageRefused ): st.run_canary( env, 1, NEED, ENTRIES, 2_000_000, attempt=2, reason="again" )
    assert len( bodies( env ) ) == sent


def test_a_fourth_attempt_is_refused_and_so_is_any_attempt_out_of_range( env ):
    tripped_canary( env )
    tripped_canary( env, attempt=2, reason="r2" )
    tripped_canary( env, attempt=3, reason="r3" )
    sent = len( bodies( env ) )
    for bad in ( 4, 0, -1, "2", True, None, 2.0 ):
        with pytest.raises( ValueError, match="attempt" ): st.run_canary( env, 1, NEED, ENTRIES, 2_000_000, attempt=bad, reason="r4" )
    assert len( bodies( env ) ) == sent and env.ledger.held_by_prefix( "s1-" ) == 3 * 1400


def test_a_retry_needs_a_named_reason_and_a_first_attempt_has_none( env ):
    tripped_canary( env )
    for reason in ( None, "", "   ", 5 ):
        with pytest.raises( ValueError, match="reason" ): st.run_canary( env, 1, NEED, ENTRIES, 2_000_000, attempt=2, reason=reason )
    with pytest.raises( ValueError, match="reason" ): st.run_canary( env, 1, NEED, ENTRIES, 2_000_000, attempt=1, reason="not a retry" )
    assert len( bodies( env ) ) == 1


def test_a_retry_needs_the_attempt_before_it( env ):
    with pytest.raises( ValueError, match="no earlier attempt" ): st.run_canary( env, 1, NEED, ENTRIES, 2_000_000, attempt=2, reason="r" )
    tripped_canary( env )
    with pytest.raises( ValueError, match="no earlier attempt" ): st.run_canary( env, 1, NEED, ENTRIES, 2_000_000, attempt=3, reason="r" )
    assert len( bodies( env ) ) == 1


def test_a_canary_already_approved_is_not_retried( env ):
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 ); st.approve_canary( env, 1, "maria", "ok" )
    with pytest.raises( ValueError, match="already approved" ): st.run_canary( env, 1, NEED, ENTRIES, 2_000_000, attempt=2, reason="just in case" )


def test_a_retry_after_an_attempt_that_raised_is_allowed( env, monkeypatch ):
    real = rp.sweep_packed
    monkeypatch.setattr( rp, "sweep_packed", lambda *a, **k: ( _ for _ in () ).throw( RuntimeError( "disk full" ) ) )
    with pytest.raises( RuntimeError ): st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 )
    monkeypatch.setattr( rp, "sweep_packed", real )
    report = st.run_canary( env, 1, NEED, ENTRIES, 2_000_000, attempt=2, reason="the first attempt died on a full disk" )
    assert report[ "tripped" ] == [] and read( env, 1, "canary" )[ "state" ] == "error"


def test_only_the_canary_may_be_retried( env ):
    st.run_arm( env, 1, "single1", NEED, ENTRIES[ :2 ], 1_000_000 )
    with pytest.raises( ValueError, match="canary" ): st.run_arm( env, 1, "single1", NEED, ENTRIES[ :2 ], 1_000_000, attempt=2, reason="again" )
    assert len( bodies( env ) ) == 2


def test_approval_goes_to_the_latest_attempt_and_opens_the_gate( env ):
    tripped_canary( env )
    env.standin = {}
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000, attempt=2, reason="fixed" )
    st.approve_canary( env, 1, "maria", "second attempt read" )
    assert json.loads( ( env.results_dir / "s1-q1-canary-a2.canary.json" ).read_text() )[ "approved" ][ "by" ] == "maria"
    assert json.loads( ( env.results_dir / "s1-q1-canary.canary.json" ).read_text() )[ "approved" ] is None
    st.run_arm( env, 1, "pack50", NEED, ENTRIES[ :10 ], 2_000_000 )


def test_an_earlier_tripped_attempt_cannot_be_approved_by_naming_it( env ):
    tripped_canary( env )
    env.standin = {}
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000, attempt=2, reason="fixed" )
    with pytest.raises( st.CanaryTripped ): st.approve_canary( env, 1, "maria", "ok", attempt=1 )
    with pytest.raises( st.CanaryNotApproved, match="attempt 3" ): st.approve_canary( env, 1, "maria", "ok", attempt=3 )
    with pytest.raises( st.CanaryNotApproved ): st.run_arm( env, 1, "pack50", NEED, ENTRIES[ :10 ], 2_000_000 )


def test_a_tripped_latest_attempt_blocks_approval_though_an_earlier_one_was_clean( env ):
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 )                       # clean and never read
    tripped_canary( env, attempt=2, reason="the clean one was never read" )
    with pytest.raises( st.CanaryTripped ): st.approve_canary( env, 1, "maria", "ok" )


def test_a_retry_asks_again_under_its_own_run_index_so_it_cannot_read_the_first_attempts_answers( env ):
    tripped_canary( env )
    sent = len( bodies( env ) )
    env.standin = {}
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000, attempt=2, reason="fixed" )
    out = json.loads( ( env.results_dir / "s1-q1-canary-a2.json" ).read_text() )
    assert len( bodies( env ) ) == sent + 1 and out[ "cache_hits" ] == 0 and out[ "run_index" ] == st.RETRY_INDEX[ 2 ] == 15
    assert st.RETRY_INDEX == { 2: 15, 3: 16 } and not set( st.RETRY_INDEX.values() ) & { index for index, _ in st.ARMS.values() }


def test_a_canary_that_sent_nothing_measured_nothing_and_trips( env ):
    budget  = rc.TokenBudget( 10, 1_000_000 )
    seeding = rt.ReuseContext( env.root, env.data, transport=Standin( budget ) )
    seeded  = rp.sweep_packed( seeding, NEED, ENTRIES[ :10 ], 10, key_mode="stage1", run_index=3, budget=budget )     # the canary's answers already sit in the cache
    assert seeded[ "calls" ] == 10
    report = st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 )
    assert "nothing_measured" in report[ "tripped" ] and len( bodies( env ) ) == 0
    with pytest.raises( st.CanaryTripped, match="nothing_measured" ): st.approve_canary( env, 1, "maria", "ok" )


def test_a_canary_whose_only_request_was_never_sent_measured_nothing( env ):
    report = st.run_canary( env, 1, NEED, ENTRIES, 100 )                       # a ceiling too small for the first request
    assert bodies( env ) == [] and "nothing_measured" in report[ "tripped" ] and "incomplete" in report[ "tripped" ]


def test_the_third_attempt_can_be_approved_and_opens_the_gate( env ):
    tripped_canary( env )
    tripped_canary( env, attempt=2, reason="second" )
    env.standin = {}
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000, attempt=3, reason="third" )
    st.approve_canary( env, 1, "maria", "third attempt read" )
    assert json.loads( ( env.results_dir / "s1-q1-canary-a3.canary.json" ).read_text() )[ "approved" ][ "by" ] == "maria"
    st.run_arm( env, 1, "pack50", NEED, ENTRIES[ :10 ], 2_000_000 )


def ledger_kinds( env ): return [ json.loads( line )[ "kind" ] for line in env.ledger.path.read_text().splitlines() ]


def test_an_entry_with_no_id_raises_before_the_ledger_is_touched( env ):
    before = env.ledger.path.read_text()
    with pytest.raises( KeyError ): st.run_arm( env, 1, "single1", NEED, [ ENTRIES[ 0 ], { "sig": "()", "doc": "no id" } ], 1_000_000 )
    assert env.ledger.path.read_text() == before and env.made == [] and not env.results_dir.exists()


def test_a_clock_that_fails_at_the_start_raises_before_the_ledger_is_touched( env ):
    def dead(): raise RuntimeError( "clock gone" )
    env.clock = dead
    before = env.ledger.path.read_text()
    with pytest.raises( RuntimeError, match="clock gone" ): st.run_arm( env, 1, "single1", NEED, ENTRIES[ :2 ], 1_000_000 )
    assert env.ledger.path.read_text() == before and st.stage_remaining( env.ledger ) == 71_000_000


def test_a_clock_that_fails_at_the_end_still_closes_the_run( env ):
    calls = []
    def clock():
        calls.append( 1 )
        if len( calls ) > 1: raise RuntimeError( "clock gone" )
        return "2026-10-08T00:00:00-0400"
    env.clock = clock
    with pytest.raises( RuntimeError, match="clock gone" ): st.run_arm( env, 1, "single1", NEED, ENTRIES[ :2 ], 1_000_000 )
    assert ledger_kinds( env )[ -1 ] == "end" and st.stage_remaining( env.ledger ) == 71_000_000 - 2 * ( 500 + 40 )


def test_an_interrupt_inside_the_arm_is_recorded_closed_and_passed_on( env, monkeypatch ):
    monkeypatch.setattr( rp, "sweep_packed", lambda *a, **k: ( _ for _ in () ).throw( KeyboardInterrupt() ) )
    with pytest.raises( KeyboardInterrupt ): st.run_arm( env, 1, "single1", NEED, ENTRIES[ :2 ], 1_000_000 )
    out = read( env, 1, "single1" )
    assert out[ "state" ] == "error" and out[ "stop_reason" ] == "error: KeyboardInterrupt" and out[ "totals" ][ "requests" ] == 0 and ledger_kinds( env )[ -1 ] == "end"


def test_the_canarys_output_per_entry_divides_by_the_entries_it_asked_not_by_ten( env ):
    env.standin = { "out_per_entry": 70 }
    report = st.run_canary( env, 1, NEED, ENTRIES[ :8 ], 2_000_000 )
    assert report[ "output_tokens_per_entry" ] == [ 70 ] and "output_per_entry_over_60" in report[ "tripped" ]


class Budgeted:
    """Just enough of a budget for _stop_reason."""

    def __init__( self, stop_reason=None, ceiling_refusals=0 ): self.stop_reason, self.ceiling_refusals = stop_reason, ceiling_refusals


def test_when_several_things_stopped_an_arm_the_ledger_comes_first_then_the_breaker_then_the_ceiling_then_the_attempts():
    sweep = { "stopped_by": "consecutive_422", "not_reached": [ "x" ] }
    assert st._stop_reason( sweep, Budgeted( "ledger unreadable", 3 ) ) == "ledger"
    assert st._stop_reason( sweep, Budgeted( None, 3 ) ) == "consecutive_422"
    assert st._stop_reason( { **sweep, "stopped_by": None }, Budgeted( None, 3 ) ) == "ceiling"
    assert st._stop_reason( { **sweep, "stopped_by": None }, Budgeted( None, 0 ) ) == "attempts"
    assert st._stop_reason( { "stopped_by": None, "not_reached": [] }, Budgeted() ) is None


def test_two_arms_started_at_once_cannot_both_be_admitted_against_a_stage_that_holds_one( env, monkeypatch ):
    real, finished, lock, release = st.stage_remaining, [], threading.Lock(), threading.Event()
    def slow_check( ledger ):
        left = real( ledger )
        threading.Event().wait( 0.05 )                                         # a window between the check and the admission
        return left
    monkeypatch.setattr( st, "stage_remaining", slow_check )
    env.standin = { "hook": lambda n: release.wait( 5 ) }                      # an admitted arm waits in its first request
    def go( slot ):
        try: st.run_arm( env, slot, "single1", NEED, ENTRIES[ :2 ], 50_000_000 ); result = "ran"
        except st.StageRefused: result = "refused"
        with lock: finished.append( result )
    threads = [ threading.Thread( target=go, args=( slot, ) ) for slot in ( 1, 2 ) ]
    for t in threads: t.start()
    for _ in range( 60 ):                                                      # the refused one finishes while the admitted one waits
        if finished: break
        threading.Event().wait( 0.05 )
    release.set()
    for t in threads: t.join( 10 )
    assert sorted( finished ) == [ "ran", "refused" ]


def test_a_canary_file_that_is_approved_but_tripped_unlocks_nothing( env ):
    env.standin = { "out_per_entry": 90 }
    st.run_canary( env, 1, NEED, ENTRIES, 2_000_000 )
    path   = env.results_dir / "s1-q1-canary.canary.json"
    report = json.loads( path.read_text() )
    report[ "approved" ] = { "by": "someone", "why": "edited by hand", "at": "now" }
    path.write_text( json.dumps( report ) )
    with pytest.raises( st.CanaryNotApproved ): st.run_arm( env, 1, "pack50", NEED, ENTRIES[ :10 ], 2_000_000 )


@pytest.mark.parametrize( "ceiling", [ "5000", 0, -5, True, 1.5, None ] )
def test_a_ceiling_that_is_not_a_positive_whole_number_is_refused_before_the_ledger_is_touched( env, ceiling ):
    before = env.ledger.path.read_text()
    with pytest.raises( ValueError, match="ceiling" ): st.run_arm( env, 1, "single1", NEED, ENTRIES[ :2 ], ceiling )
    assert env.ledger.path.read_text() == before and env.made == []


def test_two_separate_drivers_on_one_ledger_file_cannot_both_be_admitted_against_a_stage_that_holds_one( env, monkeypatch ):
    second = st.Stage1Env( env.root, env.data, rl.AccountLedger( env.ledger.path ), transport_factory=env.transport_factory )
    assert second is not env and second.ledger is not env.ledger
    real, finished, lock, release = st.stage_remaining, [], threading.Lock(), threading.Event()
    def slow_check( ledger ):
        left = real( ledger )
        threading.Event().wait( 0.05 )
        return left
    monkeypatch.setattr( st, "stage_remaining", slow_check )
    env.standin = { "hook": lambda n: release.wait( 5 ) }
    def go( driver, slot ):
        try: st.run_arm( driver, slot, "single1", NEED, ENTRIES[ :2 ], 50_000_000 ); result = "ran"
        except st.StageRefused: result = "refused"
        with lock: finished.append( result )
    threads = [ threading.Thread( target=go, args=( driver, slot ) ) for driver, slot in ( ( env, 1 ), ( second, 2 ) ) ]
    for t in threads: t.start()
    for _ in range( 60 ):
        if finished: break
        threading.Event().wait( 0.05 )
    release.set()
    for t in threads: t.join( 10 )
    assert sorted( finished ) == [ "ran", "refused" ]


SOME = "some"          # at least one; the stand-in's timing decides how many


def stop_ledger( env ): return lambda n: env.ledger.set_limit( 10, "peer", "another run spent the account" ) if n == 3 else None


@pytest.mark.parametrize( "ending,arm,count,ceiling,limit,standin,want", [
    ( "every entry answered",       "single1", 5,  5_000_000, None, {},                    ( "complete",   None,              5,    0,    0,    0 ) ),
    ( "failed but all attempted",   "single1", 5,  5_000_000, None, { "die_after": 2 },    ( "incomplete", None,              2,    3,    0,    0 ) ),
    ( "attempt cap hit",            "single1", 25, 5_000_000, 10,   {},                    ( "incomplete", "attempts",        10,   0,    15,   0 ) ),
    ( "ceiling reached",            "single1", 25, 6_000,     None, {},                    ( "incomplete", "ceiling",         SOME, 0,    SOME, 0 ) ),
    ( "consecutive 422",            "single1", 12, 5_000_000, 50,   { "refuse_over": 0 },  ( "incomplete", "consecutive_422", 0,    SOME, SOME, 0 ) ),
    ( "response left one unasked",  "canary",  10, 2_000_000, None, { "drop_last": True }, ( "incomplete", None,              9,    1,    0,    1 ) ) ] )
def test_each_ending_of_an_arm_writes_its_state_stop_reason_and_where_the_lost_ids_are_listed( env, ending, arm, count, ceiling, limit, standin, want ):
    env.standin = standin
    st.run_arm( env, 1, arm, NEED, ENTRIES[ :count ], ceiling, attempt_limit=limit )
    out  = read( env, 1, arm )
    got  = ( out[ "state" ], out[ "stop_reason" ], len( out[ "answers" ] ), len( out[ "failed" ] ), len( out[ "not_reached" ] ), len( out[ "unasked" ] ) )
    for have, expected in zip( got, want ): assert have == expected or ( expected == SOME and have > 0 ), ( ending, got, want )
    lost = [ a[ "id" ] for a in out[ "answers" ] ] + out[ "failed" ] + out[ "not_reached" ]
    assert sorted( lost ) == sorted( out[ "entry_ids" ] ), ending                  # every entry is answered, failed or not reached, and only one of them
    assert set( out[ "unasked" ] ) <= set( out[ "failed" ] ), ending               # an unasked id is also listed under failed
    assert ( out[ "state" ] == "complete" ) == ( not out[ "failed" ] and not out[ "not_reached" ] ), ending


def test_the_ending_that_raised_writes_state_error_and_lists_nothing( env, monkeypatch ):
    monkeypatch.setattr( rp, "sweep_packed", lambda *a, **k: ( _ for _ in () ).throw( RuntimeError( "boom" ) ) )
    with pytest.raises( RuntimeError, match="boom" ): st.run_arm( env, 1, "single1", NEED, ENTRIES[ :5 ], 5_000_000 )
    out = read( env, 1, "single1" )
    assert ( out[ "state" ], out[ "stop_reason" ] ) == ( "error", "error: RuntimeError" )
    assert out[ "answers" ] == out[ "failed" ] == out[ "not_reached" ] == out[ "unasked" ] == [] and len( out[ "entry_ids" ] ) == 5       # nothing listed, though five were asked


def test_a_ledger_that_ran_out_mid_arm_writes_ledger_and_lists_the_rest_not_reached( env ):
    env.standin = { "hook": stop_ledger( env ) }
    st.run_arm( env, 1, "single1", NEED, ENTRIES, 5_000_000, attempt_limit=50 )
    out = read( env, 1, "single1" )
    lost = [ a[ "id" ] for a in out[ "answers" ] ] + out[ "failed" ] + out[ "not_reached" ]
    assert ( out[ "state" ], out[ "stop_reason" ] ) == ( "incomplete", "ledger" ) and out[ "not_reached" ] and out[ "unasked" ] == []
    assert sorted( lost ) == sorted( out[ "entry_ids" ] )


KEY = "JEV_API_TOASTER"


def live_env( tmp_path, ledger ):
    """A driver environment on the default (live) transport; nothing here may post."""
    return st.Stage1Env( tmp_path, tmp_path / "data", ledger, entries_in_index=len( ENTRIES ) )


def standin_env( env, tmp_path ):
    """A second environment on the same ledger, on the stand-in transport."""
    return st.Stage1Env( tmp_path, tmp_path / "data", env.ledger, transport_factory=lambda budget: Standin( budget ), entries_in_index=len( ENTRIES ) )


@pytest.mark.parametrize( "arm", [ "single1", "canary" ] )
def test_no_key_on_the_live_transport_is_refused_before_a_ledger_run_opens_and_no_name_is_spent( env, tmp_path, monkeypatch, arm ):
    monkeypatch.delenv( KEY, raising=False )
    live, before = live_env( tmp_path, env.ledger ), env.ledger.path.read_text()
    with pytest.raises( st.KeyMissing, match=KEY ): st.run_arm( live, 1, arm, NEED, ENTRIES[ :5 ], 1_000_000 )
    assert env.ledger.path.read_text() == before and not live.results_dir.exists()          # no begin row, no results file
    st.run_arm( standin_env( env, tmp_path ), 1, arm, NEED, ENTRIES[ :5 ], 1_000_000 )         # the same name still runs
    assert read( env, 1, arm )[ "state" ] == "complete"


def test_the_canary_without_a_key_is_refused_the_same_way_and_leaves_no_file( env, tmp_path, monkeypatch ):
    monkeypatch.delenv( KEY, raising=False )
    live, before = live_env( tmp_path, env.ledger ), env.ledger.path.read_text()
    with pytest.raises( st.KeyMissing, match=KEY ): st.run_canary( live, 1, NEED, ENTRIES, 1_000_000 )
    assert env.ledger.path.read_text() == before and not live.results_dir.exists()


def test_an_empty_key_counts_as_no_key( env, tmp_path, monkeypatch ):
    monkeypatch.setenv( KEY, "" )
    with pytest.raises( st.KeyMissing ): st.run_arm( live_env( tmp_path, env.ledger ), 1, "single1", NEED, ENTRIES[ :2 ], 1_000_000 )


def test_a_key_on_the_live_transport_lets_the_arm_run( env, tmp_path, monkeypatch ):
    monkeypatch.setenv( KEY, "not-a-real-key" )
    monkeypatch.setattr( rt, "LiveJevTransport", Standin )                                           # the live class is never built here
    st.run_arm( live_env( tmp_path, env.ledger ), 1, "single1", NEED, ENTRIES[ :3 ], 1_000_000 )
    assert read( env, 1, "single1" )[ "state" ] == "complete"


def test_a_transport_the_caller_supplies_needs_no_key( env, monkeypatch ):
    monkeypatch.delenv( KEY, raising=False )
    st.run_arm( env, 1, "single1", NEED, ENTRIES[ :3 ], 1_000_000 )
    assert read( env, 1, "single1" )[ "state" ] == "complete"


@pytest.mark.parametrize( "workers", [ 3, 9, 32, 0, True, "6", 6.0, None ] )
def test_workers_outside_four_to_eight_are_refused_before_a_ledger_run_opens( env, workers ):
    env.workers, before = workers, env.ledger.path.read_text()
    with pytest.raises( ValueError, match="workers" ): st.run_arm( env, 1, "single1", NEED, ENTRIES[ :3 ], 1_000_000 )
    assert env.ledger.path.read_text() == before and env.made == [] and not env.results_dir.exists()


@pytest.mark.parametrize( "workers", [ 4, 8 ] )
def test_the_edges_four_and_eight_workers_run( env, workers ):
    env.workers = workers
    st.run_arm( env, 1, "single1", NEED, ENTRIES[ :3 ], 1_000_000 )
    assert read( env, 1, "single1" )[ "state" ] == "complete"


def test_a_repeated_entry_id_is_refused_before_a_ledger_run_opens( env ):
    before = env.ledger.path.read_text()
    with pytest.raises( ValueError, match="repeated" ) as raised: st.run_arm( env, 1, "single1", NEED, [ ENTRIES[ 0 ], ENTRIES[ 1 ], ENTRIES[ 0 ] ], 1_000_000 )
    assert ENTRIES[ 0 ][ "id" ] in str( raised.value )                                           # it names the id
    assert env.ledger.path.read_text() == before and env.made == [] and not env.results_dir.exists()
    st.run_arm( env, 1, "single1", NEED, ENTRIES[ :3 ], 1_000_000 )                                  # the name was not spent
