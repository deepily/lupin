"""
The call budget on check_exists: a hard ceiling on HTTP attempts to Jev, retries included.

Why it exists: the sweep asks Jev once per sendable index entry, about 7,700 of them.
Each entry may be tried three times, and each try retried again on a 429 or 529.
The worst case was about 92,000 HTTP calls. Rick ruled a hard cap of 8,000 for the first live run.

Every HTTP door here is a counting stand-in for jev_transport._post. No real key is used and no
network is touched.
"""
import json
import threading

import pytest

from cosa.repo.doc_lint import jev_transport
from lupin_mcp import reuse_tools as rt
from tests.unit.symindex_helpers import make_lupin_repo


NEED = "read an RSS feed and return articles"
UNRELATED = { "answers": { "fit": { "choice": "unrelated", "probabilities": { "reuse": 0.05, "extend": 0.05, "unrelated": 0.9 } } } }


@pytest.fixture( autouse=True )
def fake_key( monkeypatch ):
    """A fake key so the live transport is built, and no real sleeping between retries."""
    monkeypatch.setenv( jev_transport.KEY_VARIABLE, "fake-key-for-budget-tests" )
    monkeypatch.setattr( jev_transport.time, "sleep", lambda s: None )


@pytest.fixture
def env( tmp_path ):
    root = make_lupin_repo( tmp_path )
    return root, tmp_path / "data", tmp_path / "out"


def make_ctx( env, **kw ):
    root, data, out = env
    return rt.ReuseContext( root, data, out_dir=out, **kw )


def counting_door( monkeypatch, status=200 ):
    """Replace the one HTTP function; returns the list that records every attempt."""
    seen = []
    lock = threading.Lock()
    def door( url, headers, body, timeout ):
        with lock: seen.append( body )
        return status, json.dumps( UNRELATED ) if status == 200 else "busy"
    monkeypatch.setattr( jev_transport, "_post", door )
    return seen


def test_the_budget_counts_up_to_its_limit_then_refuses_without_counting():
    budget = jev_transport.CallBudget( 3 )
    for _ in range( 3 ): budget.take()
    assert budget.used == 3 and budget.spent
    with pytest.raises( jev_transport.JevBudgetSpent ): budget.take()
    assert budget.used == 3


def test_many_threads_never_take_more_than_the_limit():
    budget, took, lock = jev_transport.CallBudget( 50 ), [], threading.Lock()
    def grab():
        try: budget.take(); ok = True
        except jev_transport.JevBudgetSpent: ok = False
        with lock: took.append( ok )
    threads = [ threading.Thread( target=grab ) for _ in range( 200 ) ]
    for t in threads: t.start()
    for t in threads: t.join()
    assert sum( took ) == 50 and budget.used == 50


@pytest.mark.parametrize( "bad", [ 0, -1, 2.5, "5", True, None ] )
def test_a_budget_that_is_not_a_positive_integer_is_refused( bad ):
    with pytest.raises( ValueError ): jev_transport.CallBudget( bad )


def test_every_retry_of_a_busy_server_takes_one_from_the_budget():
    """The retry loop inside send is counted, and an attempt over the limit makes no HTTP."""
    posted = []
    def busy( url, headers, body, timeout ): posted.append( 1 ); return 429, "busy"
    budget = jev_transport.CallBudget( 3 )
    with pytest.raises( jev_transport.JevBudgetSpent ):
        jev_transport.send( b"{}", post_fn=busy, sleep_fn=lambda s: None, environ={ jev_transport.KEY_VARIABLE: "k" }, budget=budget )
    assert len( posted ) == 3 and budget.used == 3


def test_a_send_without_a_budget_is_unchanged():
    posted = []
    def busy( url, headers, body, timeout ): posted.append( 1 ); return 429, "busy"
    with pytest.raises( jev_transport.JevCallError ):
        jev_transport.send( b"{}", post_fn=busy, sleep_fn=lambda s: None, environ={ jev_transport.KEY_VARIABLE: "k" } )
    assert len( posted ) == jev_transport.MAX_ATTEMPTS


def test_a_sweep_stops_at_the_budget_and_reports_the_rest_as_not_checked( env, monkeypatch ):
    seen = counting_door( monkeypatch )
    r = rt.check_exists_impl( NEED, make_ctx( env, call_budget=2 ) )
    assert len( seen ) == 2
    assert r[ "stats" ][ "attempts" ] == 2 and r[ "stats" ][ "call_budget" ] == 2
    assert r[ "stats" ][ "not_checked" ] == 1 and len( r[ "missing" ] ) == 1


def test_an_unreached_entry_is_never_reported_as_new( env, monkeypatch ):
    """An entry left unasked makes the verdict uncertain; the control run with room says new."""
    counting_door( monkeypatch )
    cut = rt.check_exists_impl( NEED, make_ctx( env, call_budget=2 ) )
    assert ( cut[ "verdict" ], cut[ "cause" ] ) == ( "UNCERTAIN_READ_SOURCE", "CALL_FAILED" )
    assert cut[ "shortlist" ] == []
    full = rt.check_exists_impl( NEED + " [control]", make_ctx( env, call_budget=100 ) )
    assert full[ "verdict" ] == "NEW" and full[ "stats" ][ "not_checked" ] == 0


def test_when_every_call_fails_and_retries_the_attempts_still_stop_at_the_budget( env, monkeypatch ):
    """Without a budget this is 36 HTTP calls for three entries; with one it stops at the limit."""
    seen = counting_door( monkeypatch, status=429 )
    r = rt.check_exists_impl( NEED, make_ctx( env, call_budget=5 ) )
    assert len( seen ) == 5
    assert r[ "stats" ][ "attempts" ] == 5
    assert r[ "verdict" ] == "UNCERTAIN_READ_SOURCE"


def test_cache_hits_cost_nothing_and_are_still_served_after_the_budget_is_spent( env, monkeypatch ):
    counting_door( monkeypatch )
    first = rt.check_exists_impl( NEED, make_ctx( env, call_budget=100 ) )
    assert first[ "stats" ][ "attempts" ] == 3
    seen = counting_door( monkeypatch )
    again = rt.run_question( make_ctx( env, call_budget=1 ), "check_exists", NEED, NEED, write=False )      # not stored: the same inputs would return the first receipt
    assert seen == [] and again[ "stats" ][ "attempts" ] == 0 and again[ "stats" ][ "cache_hits" ] == 3
    assert again[ "verdict" ] == "NEW"


def test_a_budget_above_the_hard_cap_is_refused_never_clamped( env ):
    assert rt.CALL_BUDGET_CAP == 8000 and rt.DEFAULT_CALL_BUDGET == 8000
    make_ctx( env, call_budget=8000 )
    for bad in ( 8001, 0, -5, "100", True, 2.5 ):
        with pytest.raises( rt.ReuseError ) as e: make_ctx( env, call_budget=bad )
        assert e.value.name == "BAD_BUDGET"


def test_the_environment_variable_sets_the_budget_and_a_bad_value_is_loud( env, monkeypatch ):
    monkeypatch.delenv( rt.BUDGET_VARIABLE, raising=False )
    assert rt.context_from_environment( env[ 0 ] ).call_budget == 8000
    monkeypatch.setenv( rt.BUDGET_VARIABLE, "" )
    assert rt.context_from_environment( env[ 0 ] ).call_budget == 8000
    monkeypatch.setenv( rt.BUDGET_VARIABLE, "250" )
    assert rt.context_from_environment( env[ 0 ] ).call_budget == 250
    for bad in ( "8001", "0", "-3", "many", "2.5" ):
        monkeypatch.setenv( rt.BUDGET_VARIABLE, bad )
        with pytest.raises( rt.ReuseError ) as e: rt.context_from_environment( env[ 0 ] )
        assert e.value.name == "BAD_BUDGET"


def test_a_live_transport_without_a_budget_reports_zero_attempts_and_is_not_limited( env, monkeypatch ):
    """A context builds a budget only for its own transport; an injected one is left alone."""
    seen = counting_door( monkeypatch )
    transport = rt.LiveJevTransport()
    r = rt.check_exists_impl( NEED, make_ctx( env, transport=transport, call_budget=1 ) )
    assert len( seen ) == 3 and r[ "stats" ][ "attempts" ] == 0 and r[ "stats" ][ "not_checked" ] == 0
