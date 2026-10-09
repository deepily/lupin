"""
The end-to-end runner on a stand-in: order, ceiling, ledger, canary and stop rules.

The index is generated: 105 small functions, so a run of 100 members has a member to leave out each time.
Every transport is a stand-in and the ledger is a scratch file. Nothing reaches Jev.
"""
import json
import math

import pytest

from lupin_mcp import reuse_e2e as e2e
from lupin_mcp import reuse_e2e_run as run
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_stage1 as s1
from lupin_mcp import reuse_stage1_run as rr
from lupin_mcp import reuse_tools as rt

WIDE = 105
IDS  = [ f"cosa.wide.f{i:03d}" for i in range( WIDE ) ]


def make_wide_repo( base ):
    """Ensures: writes a lupin-shaped tree of 105 public functions; returns its path."""
    root = base / "lupin"
    ( root / "src" / "cosa" ).mkdir( parents=True )
    ( root / "src" / "lupin_mcp" ).mkdir( parents=True )
    ( root / "src" / "lupin_mcp" / "tool.py" ).write_text( 'def serve( x ):\n    """Serve a thing."""\n    return x\n', encoding="utf-8" )
    body = "\n\n".join( f'def f{i:03d}( x ):\n    """Does the distinct job number {i} for a caller."""\n    return x + {i}' for i in range( WIDE ) )
    ( root / "src" / "cosa" / "wide.py" ).write_text( body + "\n", encoding="utf-8" )
    return root


def ask_old( ctx, item ): return rt.sweep_need_impl( item[ "need" ], item[ "member" ], ctx )
def ask_new( ctx, item ): return rt.sweep_need_impl( item[ "need" ] + " (new question)", item[ "member" ], ctx )


class Env:
    """A scratch environment: repo, data, ledger, a counting stand-in transport."""

    def __init__( self, tmp_path, limit=10 ** 9, asks=None, pack_size=50, tag="a" ):
        self.root   = make_wide_repo( tmp_path / tag )
        self.data   = tmp_path / tag / "data"
        self.path   = tmp_path / tag / "ledger.jsonl"
        rl.AccountLedger.create( self.path, limit, "test", "scratch" )
        self.posts  = []
        self.texts  = []
        self.asks   = asks or { "old": ask_old, "new": ask_new }
        self.pack   = pack_size

    def factory( self, budget ):
        inner, posts, texts = rr.StandIn( budget ), self.posts, self.texts
        class Counting:
            def post_with_meta( self, body ):
                posts.append( len( body[ "questions" ] ) )
                texts.extend( q[ "instructions" ] for q in body[ "questions" ].values() )
                return inner.post_with_meta( body )
        return Counting()

    def env( self ):
        return run.E2EEnv( self.root, self.data, rl.AccountLedger( self.path ), self.asks, transport_factory=self.factory, pack_size=self.pack )


def items_of( n, start=0 ): return [ { "member": IDS[ start + i ], "need": f"A function number {start + i} that does a distinct job." } for i in range( n ) ]


def twins_of( n ): return { IDS[ i ]: { IDS[ ( i + 1 ) % WIDE ] } for i in range( n ) }


def test_a_run_asks_member_by_member_both_questions_and_every_search_is_complete( tmp_path ):
    scratch = Env( tmp_path )
    rec     = run.run_searches( scratch.env(), "e2e-run", items_of( 6 ), twins_of( 6 ), 10 ** 8 )
    order   = [ ( s[ "member" ], s[ "question" ] ) for s in rec[ "searches" ] ]
    assert order == [ ( IDS[ i ], q ) for i in range( 6 ) for q in ( "old", "new" ) ]
    assert len( rec[ "searches" ] ) == 12 and all( s[ "status" ] == "complete" and s[ "causes" ] == [] for s in rec[ "searches" ] )
    assert all( s[ "tokens" ] > 0 and s[ "requests" ] > 0 and s[ "receipt_id" ] for s in rec[ "searches" ] )
    assert rec[ "stopped" ] is None and rec[ "kind" ] == "run" and rec[ "pack_size" ] == 50
    assert ( scratch.data / "e2e-results" / "e2e-run.json" ).exists()


def test_a_search_leaves_out_its_member_and_sweeps_every_other_entry_in_packs_of_fifty( tmp_path ):
    scratch = Env( tmp_path )
    rec     = run.run_searches( scratch.env(), "e2e-run", items_of( 1 ), twins_of( 1 ), 10 ** 8 )
    entries = WIDE + 1 - 1                                                                      # the generated functions plus serve(), less the member
    assert scratch.posts and sum( scratch.posts ) == entries * 2                                # two searches, each asking every other entry once
    assert sorted( scratch.posts ) == sorted( [ 50, 50, entries - 100 ] * 2 )
    assert [ s[ "requests" ] for s in rec[ "searches" ] ] == [ math.ceil( entries / 50 ) ] * 2


def test_a_hundred_members_run_to_the_end_at_packs_of_fifty_on_the_stand_in( tmp_path ):
    scratch = Env( tmp_path, asks={ "old": ask_old } )
    rec     = run.run_searches( scratch.env(), "e2e-run", items_of( 100 ), twins_of( 100 ), 10 ** 9 )
    assert len( rec[ "searches" ] ) == 100 and all( s[ "status" ] == "complete" for s in rec[ "searches" ] )
    assert rec[ "pack_size" ] == 50 and rec[ "totals" ][ "complete" ] == 100 and rec[ "totals" ][ "not_run" ] == 0


def test_the_ledger_holds_what_the_run_spent_and_the_run_is_closed( tmp_path ):
    scratch = Env( tmp_path )
    rec     = run.run_searches( scratch.env(), "e2e-run", items_of( 3 ), twins_of( 3 ), 10 ** 8 )
    limit, total = rl.AccountLedger( scratch.path ).snapshot()
    assert total == rec[ "totals" ][ "spent_tokens" ] == sum( s[ "tokens" ] for s in rec[ "searches" ] ) and total > 0 and limit == 10 ** 9
    with pytest.raises( s1.DriverRefused ): run.run_searches( scratch.env(), "e2e-run", items_of( 3 ), twins_of( 3 ), 10 ** 8 )     # the name was used


def test_the_ceiling_stops_the_whole_run_and_what_it_did_not_start_is_not_run_rather_than_failed( tmp_path ):
    probe  = Env( tmp_path, tag="probe", asks={ "old": ask_old } )
    one    = run.run_searches( probe.env(), "e2e-run", items_of( 1 ), twins_of( 1 ), 10 ** 8 )[ "searches" ][ 0 ][ "tokens" ]
    scratch = Env( tmp_path, asks={ "old": ask_old } )
    rec     = run.run_searches( scratch.env(), "e2e-run", items_of( 8 ), twins_of( 8 ), int( one * 2.4 ) )
    states  = [ s[ "status" ] for s in rec[ "searches" ] ]
    cut     = states.index( "incomplete" )
    assert cut >= 1 and states[ :cut ] == [ "complete" ] * cut and states[ cut + 1: ] == [ "not_run" ] * ( 7 - cut )
    assert rec[ "searches" ][ cut ][ "causes" ] == [ "ceiling" ] and rec[ "searches" ][ cut + 1 ][ "causes" ] == [ "ceiling" ]
    assert rec[ "stopped" ] == { "reason": "ceiling", "after": cut + 1 } and rec[ "totals" ][ "not_run" ] == 7 - cut
    assert rec[ "totals" ][ "spent_tokens" ] <= int( one * 2.4 )


def test_a_run_whose_ceiling_with_the_ledger_total_passes_the_account_limit_is_refused_with_no_request( tmp_path ):
    scratch = Env( tmp_path, limit=1500 )
    with pytest.raises( rl.AccountLimitReached ): run.run_searches( scratch.env(), "e2e-run", items_of( 2 ), twins_of( 2 ), 5000 )
    assert scratch.posts == [] and not ( scratch.data / "e2e-results" ).exists()


def test_two_runs_whose_ceilings_each_fit_but_not_together_refuse_the_second_with_no_request( tmp_path ):
    scratch = Env( tmp_path, limit=400000, asks={ "old": ask_old } )
    first   = run.run_searches( scratch.env(), "e2e-one", items_of( 1 ), twins_of( 1 ), 250000 )
    spent   = first[ "totals" ][ "spent_tokens" ]
    before  = len( scratch.posts )
    ceiling = 400000 - spent + 1                                                               # alone it fits the limit; with what the first run spent it is one over
    assert 0 < spent and ceiling <= 400000
    with pytest.raises( rl.AccountLimitReached ): run.run_searches( scratch.env(), "e2e-two", items_of( 1, 1 ), twins_of( 2 ), ceiling )
    assert len( scratch.posts ) == before


def test_an_unreadable_ledger_refuses_the_run_before_any_request( tmp_path ):
    scratch = Env( tmp_path )
    scratch.path.write_text( "not a ledger\n", encoding="utf-8" )
    with pytest.raises( rl.LedgerUnreadable ): run.run_searches( scratch.env(), "e2e-run", items_of( 2 ), twins_of( 2 ), 10 ** 6 )
    assert scratch.posts == []


def failing( failed=0, malformed=None, stopped=None, left=0 ):
    def ask( ctx, item ):
        return { "status": "ok", "verdict": "UNCERTAIN_READ_SOURCE", "shortlist": [], "nearest": [], "receipt_id": "r" * 16, "malformed": malformed or [],
                 "stats": { "failed": failed, "not_checked": left, "stopped_by": stopped, "requests": 1, "attempt_counts": { "n429": 2, "n529": 1 } } }
    return ask


def test_each_incomplete_search_carries_its_causes_apart_and_a_miss_is_not_a_complete_search( tmp_path ):
    scratch = Env( tmp_path, asks={ "old": failing( failed=2, malformed=[ { "id": "x", "reason": "r" } ] ) } )
    rec     = run.run_searches( scratch.env(), "e2e-run", items_of( 2 ), twins_of( 2 ), 10 ** 6 )
    assert [ s[ "causes" ] for s in rec[ "searches" ] ] == [ [ "CALL_FAILED", "MALFORMED_ANSWER" ] ] * 2
    assert all( s[ "status" ] == "incomplete" for s in rec[ "searches" ] ) and rec[ "totals" ][ "complete" ] == 0
    assert rec[ "searches" ][ 0 ][ "n429" ] == 2 and rec[ "searches" ][ 0 ][ "n529" ] == 1


def test_more_than_five_incomplete_searches_among_the_first_twenty_stop_the_run( tmp_path ):
    scratch = Env( tmp_path, asks={ "old": failing( failed=1 ) } )
    rec     = run.run_searches( scratch.env(), "e2e-run", items_of( 30 ), twins_of( 30 ), 10 ** 6 )
    states  = [ s[ "status" ] for s in rec[ "searches" ] ]
    assert states[ :6 ] == [ "incomplete" ] * 6 and states[ 6: ] == [ "not_run" ] * 24
    assert rec[ "stopped" ] == { "reason": "reliability", "after": 6 } and rec[ "searches" ][ 10 ][ "causes" ] == [ "reliability" ]


def test_exactly_five_incomplete_searches_among_the_first_twenty_do_not_stop_the_run( tmp_path ):
    state = { "n": 0 }
    def flaky( ctx, item ):
        state[ "n" ] += 1
        return failing( failed=1 if state[ "n" ] <= 5 else 0 )( ctx, item )
    scratch = Env( tmp_path, asks={ "old": flaky } )
    rec     = run.run_searches( scratch.env(), "e2e-run", items_of( 25 ), twins_of( 25 ), 10 ** 6 )
    assert rec[ "stopped" ] is None and rec[ "totals" ][ "incomplete" ] == 5 and rec[ "totals" ][ "not_run" ] == 0


def test_the_window_counts_searches_not_members_so_two_questions_fill_it_in_ten_members( tmp_path ):
    scratch = Env( tmp_path, asks={ "old": failing(), "new": failing( failed=1 ) } )
    rec     = run.run_searches( scratch.env(), "e2e-run", items_of( 20 ), twins_of( 20 ), 10 ** 6 )
    assert rec[ "stopped" ] == { "reason": "reliability", "after": 12 }                              # old and new alternate: the sixth incomplete is search 12


def test_a_run_with_nothing_to_ask_or_a_repeated_member_is_refused_before_the_ledger_opens( tmp_path ):
    scratch = Env( tmp_path )
    with pytest.raises( s1.DriverRefused ): run.run_searches( scratch.env(), "e2e-run", [], {}, 10 ** 6 )
    with pytest.raises( s1.DriverRefused ): run.run_searches( scratch.env(), "e2e-run", items_of( 1 ) + items_of( 1 ), twins_of( 1 ), 10 ** 6 )
    assert rl.AccountLedger( scratch.path ).total() == 0 and scratch.posts == []


def test_the_canary_asks_five_members_with_both_questions_and_reports_what_was_read_before_the_first_send( tmp_path ):
    scratch = Env( tmp_path )
    report  = run.run_canary( scratch.env(), items_of( 100 ), twins_of( 100 ), 10 ** 8 )
    assert report[ "members" ] == 5 and report[ "searches" ] == 10 and report[ "ledger_total_before"] == 0 and report[ "ledger_limit" ] == 10 ** 9
    assert report[ "tokens" ] > 0 and report[ "projection_tokens" ] == report[ "tokens" ] * 20 and report[ "approved" ] is None
    assert report[ "unasked" ] == 0 and report[ "requests" ] == 30 and set( report ) >= { "n429", "n529", "wall_seconds", "allowance_tokens", "tripped" }
    assert report[ "tripped" ] == [] and ( scratch.data / "e2e-results" / "e2e-canary.canary.json" ).exists()


def test_the_projection_is_held_against_the_smaller_of_one_and_a_half_times_the_estimate_and_the_ledger_remainder( tmp_path ):
    scratch = Env( tmp_path, limit=200000 )
    report  = run.run_canary( scratch.env(), items_of( 100 ), twins_of( 100 ), 10 ** 5 )
    assert report[ "allowance_tokens" ] == min( int( 1.5 * run.ESTIMATE_TOKENS ), 200000 - report[ "tokens" ] )
    assert "projection_over_allowance" in report[ "tripped" ]


def test_a_canary_with_an_incomplete_search_is_tripped_and_cannot_be_approved( tmp_path ):
    scratch = Env( tmp_path, asks={ "old": failing( failed=1 ) } )
    report  = run.run_canary( scratch.env(), items_of( 100 ), twins_of( 100 ), 10 ** 6 )
    assert "incomplete" in report[ "tripped" ]
    with pytest.raises( s1.CanaryTripped ): run.approve_canary( scratch.env(), "cheech", "read it" )


def test_the_full_run_waits_for_an_approved_canary_and_then_runs_the_remaining_members( tmp_path ):
    scratch = Env( tmp_path, asks={ "old": ask_old } )
    with pytest.raises( s1.CanaryNotApproved ): run.run_full( scratch.env(), items_of( 100 ), twins_of( 100 ), 5 * 10 ** 8 )
    run.run_canary( scratch.env(), items_of( 100 ), twins_of( 100 ), 10 ** 8 )
    with pytest.raises( s1.CanaryNotApproved ): run.run_full( scratch.env(), items_of( 100 ), twins_of( 100 ), 5 * 10 ** 8 )
    run.approve_canary( scratch.env(), "cheech", "tokens read" )
    with pytest.raises( s1.DriverRefused ): run.approve_canary( scratch.env(), "cheech", "again" )
    rec = run.run_full( scratch.env(), items_of( 100 ), twins_of( 100 ), 5 * 10 ** 8 )
    assert [ s[ "member" ] for s in rec[ "searches" ] ] == IDS[ 5:100 ] and rec[ "kind" ] == "run" and rec[ "totals" ][ "complete" ] == 95   # the canary's five are not asked twice
    assert rec[ "canary_run" ] == "e2e-canary"


def test_approval_needs_a_name_and_a_reason_and_a_canary_that_ran( tmp_path ):
    scratch = Env( tmp_path )
    with pytest.raises( s1.CanaryNotApproved ): run.approve_canary( scratch.env(), "cheech", "why" )
    run.run_canary( scratch.env(), items_of( 100 ), twins_of( 100 ), 10 ** 8 )
    with pytest.raises( s1.DriverRefused ): run.approve_canary( scratch.env(), "", "why" )
    with pytest.raises( s1.DriverRefused ): run.approve_canary( scratch.env(), "cheech", "" )


def test_an_ask_that_raises_is_recorded_as_an_error_search_and_the_error_goes_on( tmp_path ):
    def boom( ctx, item ): raise RuntimeError( "scratch failure" )
    scratch = Env( tmp_path, asks={ "old": boom } )
    with pytest.raises( RuntimeError, match="scratch failure" ): run.run_searches( scratch.env(), "e2e-run", items_of( 2 ), twins_of( 2 ), 10 ** 6 )
    rec = json.loads( ( scratch.data / "e2e-results" / "e2e-run.json" ).read_text( encoding="utf-8" ) )
    assert rec[ "state" ] == "error" and rec[ "searches" ][ -1 ][ "status" ] == "error" and rec[ "searches" ][ -1 ][ "causes" ] == [ "ERROR:RuntimeError" ]


def test_the_figures_count_an_incomplete_search_as_a_miss_and_give_complete_only_beside_them( tmp_path ):
    scratch = Env( tmp_path, asks={ "old": ask_old } )
    rec     = run.run_searches( scratch.env(), "e2e-run", items_of( 10 ), twins_of( 10 ), 10 ** 8 )
    rec[ "searches" ][ 0 ].update( status="incomplete", causes=[ "CALL_FAILED" ], read={ "verdict": "UNCERTAIN_READ_SOURCE", "on_shortlist": False, "ranked_first": False, "top_ten": False } )
    fig = e2e.figures( rec[ "searches" ], [ "old" ] )[ "old" ]
    assert fig[ "n_run" ] == 10 and fig[ "complete" ] == 9 and fig[ "incomplete" ] == 1
    assert fig[ "on_shortlist" ][ "n" ] == 10 and fig[ "on_shortlist_complete" ][ "n" ] == 9 and fig[ "on_shortlist" ][ "interval" ][ 0 ] is not None
    assert fig[ "causes" ] == { "CALL_FAILED": 1 }


def test_the_paired_comparison_counts_members_where_only_one_question_found_the_twin():
    def s( member, question, hit ): return { "member": member, "question": question, "status": "complete", "causes": [], "tokens": 10, "requests": 1, "unasked": 0,
                                           "read": { "verdict": "NEW", "on_shortlist": hit, "ranked_first": hit, "top_ten": hit } }
    rows = [ s( "a", "old", True ), s( "a", "new", False ), s( "b", "old", False ), s( "b", "new", True ), s( "c", "old", True ), s( "c", "new", True ), s( "d", "old", False ), s( "d", "new", False ) ]
    pair = e2e.paired( rows, "old", "new" )
    assert pair[ "on_shortlist" ] == { "only_old": 1, "only_new": 1, "both": 1, "neither": 1, "p": 1.0 }


def test_the_reliability_window_counts_the_canary_searches_that_came_before_the_run( tmp_path ):
    prior   = [ { "status": "incomplete" } ] * 4 + [ { "status": "complete" } ] * 6
    scratch = Env( tmp_path, asks={ "old": failing( failed=1 ) } )
    rec     = run.run_searches( scratch.env(), "e2e-run", items_of( 10 ), twins_of( 10 ), 10 ** 6, prior=prior )
    assert rec[ "stopped" ] == { "reason": "reliability", "after": 2 }                               # 4 earlier + 2 here is the sixth incomplete


def test_a_run_with_no_question_a_bad_pack_size_or_a_bad_worker_count_is_refused_before_the_ledger_opens( tmp_path ):
    scratch = Env( tmp_path, asks={ "old": ask_old } )
    for change in ( { "asks": {} }, { "pack_size": 0 }, { "pack_size": rt.MAX_PACK_SIZE + 1 }, { "workers": 99 } ):
        env = scratch.env()
        for k, v in change.items(): setattr( env, k, v )
        with pytest.raises( s1.DriverRefused ): run.run_searches( env, "e2e-run", items_of( 1 ), twins_of( 1 ), 10 ** 6 )
    assert rl.AccountLedger( scratch.path ).total() == 0 and scratch.posts == []


def test_the_live_transport_with_no_key_is_refused_before_the_ledger_opens( tmp_path, monkeypatch ):
    monkeypatch.delenv( s1.jt.KEY_VARIABLE, raising=False )
    scratch = Env( tmp_path, asks={ "old": ask_old } )
    env     = run.E2EEnv( scratch.root, scratch.data, rl.AccountLedger( scratch.path ), scratch.asks )
    assert env.live
    with pytest.raises( s1.KeyMissing ): run.run_searches( env, "e2e-run", items_of( 1 ), twins_of( 1 ), 10 ** 6 )
    assert rl.AccountLedger( scratch.path ).total() == 0


def test_an_error_result_makes_an_incomplete_search_with_its_own_cause_and_no_reading( tmp_path ):
    def refused( ctx, item ): return { "status": "error", "error": "UNKNOWN_ENTRY", "entry": item[ "member" ] }
    scratch = Env( tmp_path, asks={ "old": refused } )
    rec     = run.run_searches( scratch.env(), "e2e-run", items_of( 1 ), twins_of( 1 ), 10 ** 6 )
    assert rec[ "searches" ][ 0 ][ "status" ] == "incomplete" and rec[ "searches" ][ 0 ][ "causes" ] == [ "ERROR:UNKNOWN_ENTRY" ] and rec[ "searches" ][ 0 ][ "read" ] is None


def test_a_search_incomplete_by_malformed_answers_only_names_that_cause_and_not_call_failed( tmp_path ):
    scratch = Env( tmp_path, asks={ "old": failing( malformed=[ { "id": "cosa.wide.f001", "reason": "sum" } ] ) } )
    rec     = run.run_searches( scratch.env(), "e2e-run", items_of( 1 ), twins_of( 1 ), 10 ** 6 )
    assert rec[ "searches" ][ 0 ][ "status" ] == "incomplete" and rec[ "searches" ][ 0 ][ "causes" ] == [ "MALFORMED_ANSWER" ]


def test_a_real_sweep_with_one_malformed_stand_in_answer_is_incomplete_by_malformed_only( tmp_path ):
    scratch = Env( tmp_path, asks={ "old": ask_old } )
    inner   = scratch.factory
    def corrupting( budget ):
        transport, real = inner( budget ), None
        class Corrupt:
            def post_with_meta( self, body ):
                response, meta = transport.post_with_meta( body )
                first = next( iter( response[ "answers" ] ) )
                response[ "answers" ][ first ] = { "probabilities": { "reuse": 3.0, "extend": 0.0, "unrelated": 0.0 } }
                return response, meta
        return Corrupt()
    scratch.factory = corrupting
    rec = run.run_searches( scratch.env(), "e2e-run", items_of( 1 ), twins_of( 1 ), 10 ** 8 )
    assert rec[ "searches" ][ 0 ][ "causes" ] == [ "MALFORMED_ANSWER" ] and rec[ "searches" ][ 0 ][ "status" ] == "incomplete"


def write_page_wiki( root ):
    """Ensures: writes a wiki with one capability page that covers the generated module."""
    wiki = root / "src" / "docs" / "wiki"
    ( wiki / "capabilities" ).mkdir( parents=True, exist_ok=True )
    ( wiki / "INDEX.md" ).write_text( "- [[wide-page]] — a page about the wide module. `cosa.wide`\n", encoding="utf-8" )
    ( wiki / "capabilities" / "wide-page.md" ).write_text( f"---\ncapability: wide-page\npins:\n  - {IDS[ 0 ]}@aaaaaaaaaa\n---\n# wide-page\n", encoding="utf-8" )


def test_the_old_question_goes_through_the_free_text_sweep_so_no_page_is_asked_and_the_member_is_never_shown( tmp_path ):
    assert run._asks( [ "old" ] )[ "old" ] is run.ask_old
    scratch = Env( tmp_path, asks={ "old": run.ask_old } )
    write_page_wiki( scratch.root )
    rec     = run.run_searches( scratch.env(), "e2e-run", items_of( 1 ), twins_of( 1 ), 10 ** 8 )
    member  = rt.entry_text( next( e for e in rt.prepare( rt.ReuseContext( scratch.root, scratch.data ) )[ 1 ] if e[ "id" ] == IDS[ 0 ] ) )
    assert scratch.texts and not any( "wide-page" in t or "a page about the wide module" in t for t in scratch.texts )          # the page route is off
    assert not any( member in t for t in scratch.texts )                                                                    # the member is not its own candidate
    assert rec[ "searches" ][ 0 ][ "status" ] == "complete"


def test_a_ledger_stop_in_the_middle_of_a_run_ends_it_and_the_later_searches_are_not_run( tmp_path ):
    state = { "n": 0 }
    scratch = Env( tmp_path, asks={ "old": ask_old } )
    def lowering( ctx, item ):
        state[ "n" ] += 1
        if state[ "n" ] == 3: rl.AccountLedger( scratch.path ).set_limit( 1, "test", "lower the limit under the run" )
        return ask_old( ctx, item )
    scratch.asks = { "old": lowering }
    rec    = run.run_searches( scratch.env(), "e2e-run", items_of( 5 ), twins_of( 5 ), 10 ** 8 )
    states = [ s[ "status" ] for s in rec[ "searches" ] ]
    assert states[ :2 ] == [ "complete", "complete" ] and states[ 2 ] == "incomplete" and states[ 3: ] == [ "not_run", "not_run" ]
    assert rec[ "searches" ][ 2 ][ "causes" ] == [ "ledger" ] and rec[ "stopped" ] == { "reason": "ledger", "after": 3 } and rec[ "state" ] == "stopped"


def scripted( bad ):
    """Ensures: an ask incomplete on the numbered calls, counted across questions."""
    state = { "n": 0 }
    def ask( ctx, item ):
        state[ "n" ] += 1
        return failing( failed=1 if state[ "n" ] in bad else 0 )( ctx, item )
    return ask


def test_the_sixth_incomplete_search_at_the_twentieth_stops_the_run_and_at_the_twenty_first_does_not( tmp_path ):
    at_twenty = Env( tmp_path, tag="a", asks={ "old": scripted( { 1, 2, 3, 4, 5, 20 } ) } )
    rec = run.run_searches( at_twenty.env(), "e2e-run", items_of( 30 ), twins_of( 30 ), 10 ** 6 )
    assert rec[ "stopped" ] == { "reason": "reliability", "after": 20 } and rec[ "totals" ][ "not_run" ] == 10
    at_twenty_one = Env( tmp_path, tag="b", asks={ "old": scripted( { 1, 2, 3, 4, 5, 21 } ) } )
    rec = run.run_searches( at_twenty_one.env(), "e2e-run", items_of( 30 ), twins_of( 30 ), 10 ** 6 )
    assert rec[ "stopped" ] is None and rec[ "totals" ][ "incomplete" ] == 6 and rec[ "totals" ][ "not_run" ] == 0


def test_the_full_run_counts_the_canary_searches_in_the_window_at_the_door_the_command_line_uses( tmp_path ):
    both    = scripted( { 11, 12, 13, 14, 15, 21 } )                                       # the canary is searches 1 to 10; the sixth incomplete is search 21 of the whole
    scratch = Env( tmp_path, asks={ "old": both, "new": both } )
    run.run_canary( scratch.env(), items_of( 30 ), twins_of( 30 ), 10 ** 8 )
    run.approve_canary( scratch.env(), "cheech", "read it" )
    rec = run.run_full( scratch.env(), items_of( 30 ), twins_of( 30 ), 5 * 10 ** 8 )
    assert rec[ "stopped" ] is None and rec[ "totals" ][ "incomplete" ] == 6 and rec[ "totals" ][ "not_run" ] == 0                # alone, search 11 of this part would have stopped it


def test_unasked_counts_the_entries_that_failed_and_the_entries_never_reached( tmp_path ):
    scratch = Env( tmp_path, asks={ "old": failing( failed=1, left=2 ) } )
    assert run.run_searches( scratch.env(), "e2e-run", items_of( 1 ), twins_of( 1 ), 10 ** 6 )[ "searches" ][ 0 ][ "unasked" ] == 3


def test_the_result_file_is_rewritten_after_each_member_not_only_at_the_end( tmp_path ):
    scratch = Env( tmp_path, asks={ "old": ask_old } )
    seen    = {}
    def peeking( ctx, item ):
        path = scratch.data / "e2e-results" / "e2e-run.json"
        if item[ "member" ] == IDS[ 2 ]: seen[ "members" ] = [ s[ "member" ] for s in json.loads( path.read_text( encoding="utf-8" ) )[ "searches" ] ]
        return ask_old( ctx, item )
    scratch.asks = { "old": peeking }
    run.run_searches( scratch.env(), "e2e-run", items_of( 4 ), twins_of( 4 ), 10 ** 8 )
    assert seen[ "members" ] == [ IDS[ 0 ], IDS[ 1 ] ]


def test_a_ceiling_refusal_after_a_failed_attempt_is_named_the_ceiling_as_well_as_the_failed_calls():
    result = { "status": "ok", "malformed": [], "stats": { "failed": 3, "not_checked": 0, "stopped_by": None } }
    assert e2e.incomplete_causes( result, True, False ) == [ "ceiling", "CALL_FAILED" ]
    assert e2e.incomplete_causes( result, False, True ) == [ "ledger", "CALL_FAILED" ]
    assert e2e.incomplete_causes( result, False, False ) == [ "CALL_FAILED" ]


def test_a_ceiling_refusal_after_a_failed_attempt_stops_the_run_at_that_search( tmp_path ):
    state = { "n": 0 }
    scratch = Env( tmp_path, asks={ "old": failing( failed=2 ) } )
    def refused( ctx, item ):
        state[ "n" ] += 1
        if state[ "n" ] == 2: ctx.transport.budget_for_test.ceiling_refusals += 1
        return failing( failed=2 if state[ "n" ] == 2 else 0 )( ctx, item )
    original = scratch.factory
    def with_budget( budget ):
        transport = original( budget )
        transport.budget_for_test = budget
        return transport
    scratch.factory, scratch.asks = with_budget, { "old": refused }
    rec = run.run_searches( scratch.env(), "e2e-run", items_of( 5 ), twins_of( 5 ), 10 ** 6 )
    assert rec[ "searches" ][ 1 ][ "causes" ] == [ "ceiling", "CALL_FAILED" ] and rec[ "stopped" ] == { "reason": "ceiling", "after": 2 }
    assert [ s[ "status" ] for s in rec[ "searches" ][ 2: ] ] == [ "not_run" ] * 3


def test_the_new_question_sweeps_every_other_entry_and_never_shows_the_member( tmp_path ):
    scratch = Env( tmp_path, asks={ "new": run.ask_new } )
    run.run_searches( scratch.env(), "e2e-run", items_of( 1 ), twins_of( 1 ), 10 ** 8 )
    member = rt.entry_text( next( e for e in rt.prepare( rt.ReuseContext( scratch.root, scratch.data ) )[ 1 ] if e[ "id" ] == IDS[ 0 ] ) )
    assert scratch.texts and len( scratch.texts ) >= 2 * ( WIDE - 1 )                                              # two questions for each of the other entries were sent
    assert not any( member in t for t in scratch.texts )
