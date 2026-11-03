"""
The account spend ledger: one file, read before a run starts and before each send.

Plan section 11.5. A run is admitted only when the ledger total plus the run's ceiling fits the account
limit. An open run counts at its ceiling, a closed one at what it spent. An unreadable ledger refuses.
"""
import datetime
import json
import os
import re
import threading

import pytest

from cosa.repo.doc_lint import jev_transport as jt
from lupin_mcp import reuse_ceiling as rc
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_tools as rt

ENV  = { jt.KEY_VARIABLE: "test-key" }
BODY = { "model": rt.JEV_MODEL, "state": { "need": "read a feed" }, "questions": { "q_a": { "type": "choice" } } }
ONE  = rc.reserve_tokens( BODY, 1 )


class Post:
    def __init__( self, tokens_in=100, tokens_out=40 ): self.calls, self.reply = 0, ( 200, json.dumps( { "answers": {}, "usage": { "input_tokens": tokens_in, "output_tokens": tokens_out } } ) )

    def __call__( self, url, headers, body, timeout ):
        self.calls += 1
        return self.reply


def send( budget, post ):
    budget.open_request( BODY, 1 )
    try: text, meta = jt.send_with_meta( json.dumps( BODY ).encode( "utf-8" ), post, lambda s: None, ENV, budget, lambda: 0.5 )
    except Exception:
        budget.fail_request()
        raise
    budget.close_request( rt.usage_of( json.loads( text ) ) )


@pytest.fixture
def ledger( tmp_path ):
    return rl.AccountLedger.create( tmp_path / "jev-spend-ledger.jsonl", limit_tokens=100_000, by="test", why="fixture" )


def rows( led ): return [ json.loads( line ) for line in led.path.read_text( encoding="utf-8" ).splitlines() ]


def test_the_account_limit_of_19_31_dollars_is_459761904_tokens_at_the_pinned_price():
    assert rl.PRICE_PER_MILLION_USD == 0.042
    assert rl.usd_to_tokens( 19.31 ) == 459_761_904


def test_a_new_ledger_records_its_limit_with_who_set_it_and_why( ledger ):
    first = rows( ledger )[ 0 ]
    assert first[ "kind" ] == "limit" and first[ "tokens" ] == 100_000 and first[ "by" ] == "test" and first[ "why" ] == "fixture"
    assert ledger.limit_tokens() == 100_000 and ledger.total() == 0


def test_creating_a_ledger_that_exists_is_refused_so_the_limit_cannot_be_reset_by_accident( ledger ):
    with pytest.raises( FileExistsError ):
        rl.AccountLedger.create( ledger.path, limit_tokens=1, by="x", why="y" )


def test_a_later_limit_replaces_the_earlier_one_and_both_stay_in_the_file( ledger ):
    ledger.set_limit( 250_000, by="cheech", why="top-up landed" )
    assert ledger.limit_tokens() == 250_000 and [ r[ "kind" ] for r in rows( ledger ) ] == [ "limit", "limit" ]


@pytest.mark.parametrize( "bad", [ 0, -5, 1.5, True, None, "9" ] )
def test_a_limit_that_is_not_a_positive_integer_is_refused( ledger, bad ):
    with pytest.raises( ValueError ):
        ledger.set_limit( bad, by="x", why="y" )


def test_an_open_run_counts_at_its_ceiling_and_a_closed_run_at_what_it_spent( ledger ):
    ledger.begin_run( "a", 60_000 )
    assert ledger.total() == 60_000
    ledger.spend( "a", 10_000 )
    ledger.end_run( "a" )
    assert ledger.total() == 10_000


def test_an_open_run_that_overspent_counts_at_what_it_spent( ledger ):
    ledger.begin_run( "a", 1_000 )
    ledger.spend( "a", 5_000 )
    assert ledger.total() == 5_000


def test_two_runs_whose_ceilings_each_fit_and_together_do_not_the_second_is_refused( ledger ):
    ledger.begin_run( "a", 60_000 )
    with pytest.raises( rl.AccountLimitReached ):
        ledger.begin_run( "b", 60_000 )
    assert [ r.get( "run" ) for r in rows( ledger ) if r[ "kind" ] == "begin" ] == [ "a" ]


def test_the_second_run_gets_zero_http_calls_because_its_budget_cannot_be_built( ledger ):
    rc.TokenBudget( 10, 60_000, ledger=ledger, run="a" )
    post = Post()
    with pytest.raises( rl.AccountLimitReached ):
        send( rc.TokenBudget( 10, 60_000, ledger=ledger, run="b" ), post )
    assert post.calls == 0


def test_a_run_started_after_another_ended_is_admitted_on_what_the_first_spent( ledger ):
    ledger.begin_run( "a", 60_000 )
    ledger.spend( "a", 10_000 )
    ledger.end_run( "a" )
    ledger.begin_run( "b", 90_000 )
    assert ledger.total() == 100_000


def test_a_run_name_cannot_begin_twice( ledger ):
    ledger.begin_run( "a", 10 )
    with pytest.raises( ValueError, match="already" ):
        ledger.begin_run( "a", 10 )


def test_a_missing_ledger_refuses_the_run_with_zero_http_calls( tmp_path ):
    led, post = rl.AccountLedger( tmp_path / "nope.jsonl" ), Post()
    with pytest.raises( rl.LedgerUnreadable ):
        send( rc.TokenBudget( 10, 1_000, ledger=led, run="a" ), post )
    assert post.calls == 0


def test_a_ledger_with_a_damaged_line_is_unreadable_not_skipped( ledger ):
    with ledger.path.open( "a", encoding="utf-8" ) as f: f.write( "{not json\n" )
    with pytest.raises( rl.LedgerUnreadable ):
        ledger.total()


def test_a_ledger_with_no_limit_row_is_unreadable( tmp_path ):
    path = tmp_path / "l.jsonl"
    path.write_text( json.dumps( { "kind": "begin", "run": "a", "tokens": 1 } ) + "\n", encoding="utf-8" )
    with pytest.raises( rl.LedgerUnreadable, match="limit" ):
        rl.AccountLedger( path ).total()


def test_each_settled_send_is_appended_to_the_ledger_as_it_happens( ledger ):
    budget = rc.TokenBudget( 10, 50_000, ledger=ledger, run="a" )
    send( budget, Post( 100, 40 ) )
    send( budget, Post( 200, 50 ) )
    assert [ r[ "tokens" ] for r in rows( ledger ) if r[ "kind" ] == "spend" ] == [ 140, 250 ]


def test_a_failed_attempt_is_appended_at_its_input_estimate( ledger ):
    budget = rc.TokenBudget( 10, 50_000, ledger=ledger, run="a" )
    with pytest.raises( jt.JevCallError ):
        send( budget, lambda url, headers, body, timeout: ( 500, "" ) )
    assert [ r[ "tokens" ] for r in rows( ledger ) if r[ "kind" ] == "spend" ] == [ rc.input_reserve( BODY ) ]


def test_the_ledger_is_read_again_before_each_send_and_a_lowered_limit_refuses_it( ledger ):
    budget, post = rc.TokenBudget( 10, 50_000, ledger=ledger, run="a" ), Post()
    send( budget, post )
    ledger.set_limit( 1_000, by="x", why="lowered under a running run" )
    with pytest.raises( jt.JevBudgetSpent, match="ledger" ):
        send( budget, post )
    assert post.calls == 1 and budget.stop_reason is not None


def test_a_ledger_that_becomes_unreadable_mid_run_refuses_the_next_send_with_zero_http( ledger ):
    budget, post = rc.TokenBudget( 10, 50_000, ledger=ledger, run="a" ), Post()
    send( budget, post )
    with ledger.path.open( "a", encoding="utf-8" ) as f: f.write( "{broken\n" )
    with pytest.raises( jt.JevBudgetSpent, match="ledger" ):
        send( budget, post )
    assert post.calls == 1 and "unreadable" in budget.stop_reason


def test_ending_a_budget_closes_its_run_so_it_counts_at_what_it_spent( ledger ):
    budget = rc.TokenBudget( 10, 50_000, ledger=ledger, run="a" )
    send( budget, Post( 100, 40 ) )
    assert ledger.total() == 50_000
    budget.end()
    assert ledger.total() == 140


def test_two_threads_beginning_runs_at_once_admit_exactly_one( ledger ):
    got, lock, gate = [], threading.Lock(), threading.Barrier( 2 )

    def go( name ):
        gate.wait( 5 )
        try: ledger.begin_run( name, 60_000 ); result = "ok"
        except rl.AccountLimitReached: result = "refused"
        with lock: got.append( result )

    threads = [ threading.Thread( target=go, args=( n, ) ) for n in ( "a", "b" ) ]
    for t in threads: t.start()
    for t in threads: t.join( 5 )
    assert sorted( got ) == [ "ok", "refused" ]


def test_an_attempt_the_attempt_cap_refuses_adds_no_row_to_the_ledger( ledger ):
    budget = rc.TokenBudget( 1, 50_000, ledger=ledger, run="a" )
    with pytest.raises( jt.JevBudgetSpent ):
        send( budget, lambda url, headers, body, timeout: ( 429, "" ) )
    assert [ r[ "tokens" ] for r in rows( ledger ) if r[ "kind" ] == "spend" ] == [ rc.input_reserve( BODY ) ]


def test_reading_an_absent_ledger_does_not_create_it( tmp_path ):
    led = rl.AccountLedger( tmp_path / "none.jsonl" )
    with pytest.raises( rl.LedgerUnreadable ):
        led.total()
    with pytest.raises( rl.LedgerUnreadable ):
        led.begin_run( "a", 10 )
    assert not led.path.exists()


def test_a_stale_open_run_counts_at_its_ceiling_until_it_is_closed_by_name( ledger ):
    ledger.begin_run( "crashed", 60_000 )
    ledger.spend( "crashed", 1_000 )
    assert ledger.total() == 60_000
    ledger.close_run( "crashed", by="cheech", why="the process died before end()" )
    assert ledger.total() == 1_000
    closing = [ r for r in rows( ledger ) if r[ "kind" ] == "end" ][ 0 ]
    assert closing[ "run" ] == "crashed" and closing[ "by" ] == "cheech" and closing[ "why" ] == "the process died before end()"


def test_closing_a_run_that_never_began_or_is_already_closed_is_refused( ledger ):
    with pytest.raises( ValueError, match="never began" ):
        ledger.close_run( "ghost", by="x", why="y" )
    ledger.begin_run( "a", 10 )
    ledger.close_run( "a", by="x", why="y" )
    with pytest.raises( ValueError, match="already closed" ):
        ledger.close_run( "a", by="x", why="y" )


def test_a_close_needs_who_and_why( ledger ):
    ledger.begin_run( "a", 10 )
    for who, why in ( ( "", "y" ), ( "x", "" ), ( None, "y" ) ):
        with pytest.raises( ValueError, match="by and why" ):
            ledger.close_run( "a", by=who, why=why )


def test_after_a_stale_run_is_closed_a_run_that_did_not_fit_before_is_admitted( ledger ):
    ledger.begin_run( "crashed", 90_000 )
    with pytest.raises( rl.AccountLimitReached ):
        ledger.begin_run( "next", 50_000 )
    ledger.close_run( "crashed", by="cheech", why="stale" )
    ledger.begin_run( "next", 50_000 )


def test_a_budget_with_a_ledger_but_no_run_name_is_refused( ledger ):
    with pytest.raises( ValueError, match="name of the run" ):
        rc.TokenBudget( 10, 1_000, ledger=ledger, run="" )


def test_once_the_ledger_has_stopped_a_run_every_later_send_is_refused_without_reading_again( ledger ):
    budget, post = rc.TokenBudget( 10, 50_000, ledger=ledger, run="a" ), Post()
    with ledger.path.open( "a", encoding="utf-8" ) as f: f.write( "{broken\n" )
    for _ in range( 2 ):
        with pytest.raises( jt.JevBudgetSpent, match="stopped" ):
            send( budget, post )
    assert post.calls == 0


def test_a_ledger_that_fails_after_a_paid_response_keeps_the_response_and_stops_the_run( ledger ):
    budget, post = rc.TokenBudget( 10, 50_000, ledger=ledger, run="a" ), Post()

    class Vanishing( Post ):
        def __call__( self, url, headers, body, timeout ):
            ledger.path.unlink()                                  # the file goes while the request is in the air
            return super().__call__( url, headers, body, timeout )

    send( budget, Vanishing() )                                   # the answer is returned: it was paid for
    assert budget.spent_tokens == 140 and "unreadable" in budget.stop_reason
    with pytest.raises( jt.JevBudgetSpent ):
        send( budget, post )
    assert post.calls == 0


def test_closing_a_request_that_took_no_attempt_charges_nothing():
    budget = rc.TokenBudget( 10, 1_000 )
    budget.open_request( BODY, 1 )
    budget.close_request( None )
    assert budget.spent_tokens == 0 and budget.reserved_tokens == 0


def test_a_file_the_process_may_not_open_is_unreadable_not_a_crash( ledger, monkeypatch ):
    def denied( self, *a, **k ): raise PermissionError( "denied" )
    monkeypatch.setattr( type( ledger.path ), "open", denied )
    with pytest.raises( rl.LedgerUnreadable, match="denied" ):
        ledger.total()


def test_blank_lines_in_the_ledger_are_skipped( ledger ):
    with ledger.path.open( "a", encoding="utf-8" ) as f: f.write( "\n   \n" )
    ledger.begin_run( "a", 10 )
    assert ledger.total() == 10


@pytest.mark.parametrize( "line, why", [ ( "[1, 2]", "not a ledger row" ), ( json.dumps( { "kind": "bogus" } ), "not a ledger row" ),
                                           ( json.dumps( { "kind": "spend", "run": "a" } ), "token count" ),
                                           ( json.dumps( { "kind": "spend", "run": "a", "tokens": -1 } ), "token count" ),
                                           ( json.dumps( { "kind": "begin", "tokens": 5 } ), "names no run" ) ] )
def test_a_row_of_the_wrong_shape_makes_the_ledger_unreadable( ledger, line, why ):
    with ledger.path.open( "a", encoding="utf-8" ) as f: f.write( line + "\n" )
    with pytest.raises( rl.LedgerUnreadable, match=why ):
        ledger.total()


def test_spending_or_ending_a_run_that_never_began_is_refused( ledger ):
    with pytest.raises( ValueError, match="never began" ):
        ledger.spend( "ghost", 5 )
    with pytest.raises( ValueError, match="never began" ):
        ledger.end_run( "ghost" )


def test_a_run_whose_ceiling_exactly_fills_the_limit_is_admitted_and_one_token_more_is_refused( ledger ):
    ledger.begin_run( "a", 60_000 )
    ledger.begin_run( "b", 40_000 )
    assert ledger.total() == ledger.limit_tokens() == 100_000
    with pytest.raises( rl.AccountLimitReached ):
        ledger.begin_run( "c", 1 )


def test_every_row_is_on_disk_before_the_lock_is_let_go( ledger, monkeypatch ):
    """Ensures: a second reader sees each row while the writer's handle is still open."""
    seen, real = [], rl.AccountLedger._append

    def spy( self, f, row ):
        real( self, f, row )
        seen.append( ( row[ "kind" ], ledger.path.read_bytes().splitlines()[ -1 ] ) )

    monkeypatch.setattr( rl.AccountLedger, "_append", spy )
    ledger.begin_run( "r", 100 )
    ledger.spend( "r", 7 )
    ledger.end_run( "r" )
    assert [ k for k, _ in seen ] == [ "begin", "spend", "end" ]
    assert [ json.loads( last )[ "kind" ] for _, last in seen ] == [ "begin", "spend", "end" ]


def test_a_run_is_open_from_its_begin_row_until_its_end_row_and_an_unknown_name_is_not_open( ledger ):
    assert ledger.is_open( "a" ) is False
    ledger.begin_run( "a", 10 )
    assert ledger.is_open( "a" ) is True
    ledger.end_run( "a" )
    assert ledger.is_open( "a" ) is False


def test_close_run_ends_an_open_run_once_and_leaves_every_other_context_alone( ledger ):
    import types
    budget = rc.TokenBudget( 5, 1_000, ledger=ledger, run="r" )
    ctx    = types.SimpleNamespace( transport=rt.LiveJevTransport( budget=budget ) )
    assert ledger.total() == 1_000, "an open run holds its whole ceiling"
    assert rt.close_run( ctx ) == "r" and ledger.is_open( "r" ) is False and ledger.total() == 0
    assert rt.close_run( ctx ) is None and [ r[ "kind" ] for r in rows( ledger ) ].count( "end" ) == 1, "a second call writes nothing"
    assert rt.close_run( types.SimpleNamespace( transport=None ) ) is None
    assert rt.close_run( types.SimpleNamespace( transport=rt.LiveJevTransport( budget=jt.CallBudget( 3 ) ) ) ) is None
    assert rt.close_run( types.SimpleNamespace( transport=rt.LiveJevTransport( budget=rc.TokenBudget( 5, 1_000 ) ) ) ) is None


def test_a_run_name_holds_the_prefix_the_date_the_process_id_a_count_and_a_random_part():
    name = rl.make_run_name( "shadow-audit", today="2026-11-02", pid=4242 )
    head, count, random = name.rsplit( "-", 2 )
    assert head == "shadow-audit-2026-11-02-4242" and count.isdigit() and re.fullmatch( "[0-9a-f]{8}", random )
    assert name.split( "-" )[ -3 ] == "4242", "a reader takes the process id back out as the third part from the right"


def test_the_count_of_a_run_name_rises_by_one_for_each_name_this_process_makes():
    first, second = ( int( rl.make_run_name( "x", today="d", pid=1 ).split( "-" )[ -2 ] ) for _ in range( 2 ) )
    assert second == first + 1


def test_a_run_name_defaults_to_today_and_this_process():
    parts = rl.make_run_name( "lookup" ).split( "-" )
    assert "-".join( parts[ 1:4 ] ) == datetime.date.today().isoformat() and parts[ 4 ] == str( os.getpid() )


def test_names_made_at_once_by_many_threads_are_all_different():
    names, lock = [], threading.Lock()

    def make():
        for _ in range( 50 ):
            name = rl.make_run_name( "t", today="d", pid=1 )
            with lock: names.append( name )

    threads = [ threading.Thread( target=make ) for _ in range( 8 ) ]
    for t in threads: t.start()
    for t in threads: t.join()
    assert len( names ) == 400 and len( set( names ) ) == 400
    assert len( { n.rsplit( "-", 1 )[ 0 ] for n in names } ) == 400, "the counts alone are all different, whatever the random part"


LIVE_LIMIT, LIVE_SPENT = 1_428_571_428, 1_227_831_544            # the live ledger as measured on 2 November 2026 at about 18:14: 111 closed runs, none open


@pytest.fixture
def live_like( tmp_path ):
    """Ensures: returns a ledger holding the measured limit and spend, one closed run."""
    led = rl.AccountLedger.create( tmp_path / "live.jsonl", limit_tokens=LIVE_LIMIT, by="test", why="the measured live limit" )
    led.begin_run( "closed", 1 )
    led.spend( "closed", LIVE_SPENT )
    led.end_run( "closed" )
    return led


def test_the_ceiling_constants_are_the_plan_values_and_the_shadow_cap_is_four_a_week():
    assert ( rl.SEATS_AT_ONCE, rl.SHADOW_AUDIT_WEEKLY_CAP, rl.SHADOW_AUDIT_CEILING_TOKENS, rl.CEILING_MARGIN ) == ( 5, 4, 5_000_000, 1.5 )


def test_the_measured_headroom_admits_three_runs_at_the_old_ceiling_and_does_not_fit_five_seats_with_audits( live_like ):
    got = rl.account_capacity( live_like, lookup_ceiling=60_000_000 )
    assert got[ "headroom" ] == 200_739_884 and got[ "lookups_at_once" ] == 3 and got[ "fits" ] is False
    assert got[ "open_tokens" ] == 5 * 60_000_000 + 5_000_000 and got[ "spare_tokens" ] == 200_739_884 - 305_000_000 - 20_000_000


def test_the_ceiling_constants_fit_the_measured_headroom_with_the_audits_included( live_like ):
    got = rl.account_capacity( live_like )
    assert got[ "fits" ] is True and got[ "lookups_at_once" ] >= rl.SEATS_AT_ONCE
    assert got[ "audit_week_tokens" ] == rl.SHADOW_AUDIT_WEEKLY_CAP * rl.SHADOW_AUDIT_CEILING_TOKENS
    assert got[ "spare_tokens" ] == 200_739_884 - ( rl.SEATS_AT_ONCE * rl.LOOKUP_CEILING_TOKENS + rl.SHADOW_AUDIT_CEILING_TOKENS ) - got[ "audit_week_tokens" ]


def test_the_ledger_admits_the_seats_and_one_audit_at_the_constants_and_refuses_the_next_lookup( live_like ):
    for seat in range( rl.SEATS_AT_ONCE ): live_like.begin_run( f"lookup-{seat}", rl.LOOKUP_CEILING_TOKENS )
    live_like.begin_run( "audit", rl.SHADOW_AUDIT_CEILING_TOKENS )
    with pytest.raises( rl.AccountLimitReached ):
        live_like.begin_run( "one-more", rl.LOOKUP_CEILING_TOKENS )


def test_capacity_fits_at_exactly_zero_spare_and_not_one_token_under():
    open_and_week = 5 * 10 + 7 + 3 * 7
    assert rl.capacity( open_and_week, 10, 5, 7, 3 )[ "fits" ] is True and rl.capacity( open_and_week, 10, 5, 7, 3 )[ "spare_tokens" ] == 0
    assert rl.capacity( open_and_week - 1, 10, 5, 7, 3 )[ "fits" ] is False


def test_the_final_ceiling_is_the_worst_lookup_times_the_margin_rounded_up():
    assert rl.ceiling_for( 1_000_000 ) == 1_500_000 and rl.ceiling_for( 3, margin=1.5 ) == 5 and rl.ceiling_for( 10, margin=1 ) == 10



def test_lookups_at_once_counts_whole_ceilings_and_a_run_that_exactly_fills_the_headroom():
    assert rl.capacity( 20, 10 )[ "lookups_at_once" ] == 2 and rl.capacity( 19, 10 )[ "lookups_at_once" ] == 1 and rl.capacity( 9, 10 )[ "lookups_at_once" ] == 0
