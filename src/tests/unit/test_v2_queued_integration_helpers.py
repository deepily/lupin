#!/usr/bin/env python3
"""
Unit tests for the queued-contract helpers the v2 integration tests use —
src/tests/integration/v2_queued.py.

WHY A TEST HELPER GETS ITS OWN TESTS. These two functions are what decides pass or
fail at the :8000 gate, and they only ever run there — a mistake in them shows up as a
gate result nobody can reproduce locally. Everything they do is pure decision-making
over an HTTP response, so all of it is exercisable here with a fake transport: no
server, no queue, no sleeping. :7999-eligible.
"""

import pytest

from tests.integration import v2_queued


# ────────────────────────────────────────────────────────────── fakes

class _FakeResponse:
    def __init__( self, payload, status_code=200 ):
        self._payload    = payload
        self.status_code = status_code

    def json( self ):
        return self._payload


class _FakeRequests:
    """Serves a scripted sequence of queue reads, recording what was asked for."""

    def __init__( self, pages ):
        self._pages = list( pages )     # list of { queue_name: [ job, ... ] } or a status int
        self.gets   = []

    def get( self, url, headers=None, timeout=None ):
        queue_name = url.rsplit( "/", 1 )[ -1 ]
        self.gets.append( queue_name )
        page = self._pages[ 0 ] if len( self._pages ) == 1 else self._pages.pop( 0 )
        if isinstance( page, int ):
            return _FakeResponse( {}, status_code=page )
        return _FakeResponse( { f"{queue_name}_jobs_metadata": page.get( queue_name, [] ) } )


@pytest.fixture
def no_sleep( monkeypatch ):
    monkeypatch.setattr( v2_queued.time, "sleep", lambda seconds: None )


# ────────────────────────────────────────────────── the hand-off assertion

def test_a_waiting_response_yields_its_job_id():
    body = { "status": "waiting", "job_id": "abc::u1", "cache_hit": False, "path": "agent" }

    assert v2_queued.assert_handed_off( body, expect_cache_hit=False, expect_path="agent" ) == "abc::u1"


def test_a_done_response_is_refused_and_names_the_executor():
    """
    The whole point of row ce29cd20: `done` from one ask means the INLINE executor
    ran it. The message says so, because the tempting "fix" is to flip the INI back.
    """
    with pytest.raises( AssertionError, match="v2 executor" ):
        v2_queued.assert_handed_off( { "status": "done", "job_id": "abc::u1" } )


def test_a_hand_off_with_no_job_id_is_refused():
    """Nothing to observe is indistinguishable from work that was never queued."""
    with pytest.raises( AssertionError, match="nothing to observe" ):
        v2_queued.assert_handed_off( { "status": "waiting", "job_id": None } )


def test_the_optional_expectations_are_checked_when_given():
    body = { "status": "waiting", "job_id": "abc::u1", "cache_hit": False, "path": "agent" }

    with pytest.raises( AssertionError, match="cache_hit" ):
        v2_queued.assert_handed_off( body, expect_cache_hit=True )
    with pytest.raises( AssertionError, match="expected path" ):
        v2_queued.assert_handed_off( body, expect_path="replay" )


# ────────────────────────────────────────────────── observing completion

def test_the_job_is_matched_by_its_exact_id_not_by_position( monkeypatch, no_sleep ):
    """
    maya's rule: match the exact job_id the API returned. A count, or the first row,
    would pick up another test's traffic sharing the same queue.
    """
    fake = _FakeRequests( [ { "done": [ { "job_id": "other::u2", "response_text": "not mine" },
                                        { "job_id": "mine::u1",  "response_text": "4" } ] } ] )
    monkeypatch.setattr( v2_queued, "requests", fake )

    job = v2_queued.wait_for_done( "http://x", "mine::u1", {}, timeout=10 )

    assert job[ "response_text" ] == "4"


def test_a_job_appearing_later_is_still_found( monkeypatch, no_sleep ):
    fake = _FakeRequests( [ { "done": [], "dead": [] },
                            { "done": [], "dead": [] },
                            { "done": [ { "job_id": "mine::u1" } ] } ] )
    monkeypatch.setattr( v2_queued, "requests", fake )

    assert v2_queued.wait_for_done( "http://x", "mine::u1", {}, timeout=10 )[ "job_id" ] == "mine::u1"


def test_a_dead_job_is_reported_immediately_with_its_error( monkeypatch, no_sleep ):
    """
    Polled in the same loop on purpose — a job that died must not be reported as a
    timeout after the full wait, which sends the reader hunting a slow queue.
    """
    fake = _FakeRequests( [ { "done": [], "dead": [ { "job_id": "mine::u1", "error": "boom" } ] } ] )
    monkeypatch.setattr( v2_queued, "requests", fake )

    with pytest.raises( AssertionError, match="DEAD queue: boom" ):
        v2_queued.wait_for_done( "http://x", "mine::u1", {}, timeout=10 )


def test_a_timeout_says_where_the_job_actually_was( monkeypatch, no_sleep ):
    """
    "I stopped waiting" and "it failed" are different facts. A job still running is
    reported as still running, with its id and the queue holding it.
    """
    fake = _FakeRequests( [ { "done": [], "dead": [], "run": [ { "job_id": "mine::u1" } ] } ] )
    monkeypatch.setattr( v2_queued, "requests", fake )

    with pytest.raises( AssertionError, match="still in the 'run' queue" ):
        v2_queued.wait_for_done( "http://x", "mine::u1", {}, timeout=0 )


def test_a_job_that_finished_in_the_last_interval_is_a_pass( monkeypatch, no_sleep ):
    """The final sweep looks at done FIRST — a slow-but-finished job is not a failure."""
    fake = _FakeRequests( [ { "done": [ { "job_id": "mine::u1", "response_text": "4" } ] } ] )
    monkeypatch.setattr( v2_queued, "requests", fake )

    assert v2_queued.wait_for_done( "http://x", "mine::u1", {}, timeout=0 )[ "response_text" ] == "4"


def test_a_job_in_no_queue_is_reported_as_indeterminate( monkeypatch, no_sleep ):
    fake = _FakeRequests( [ { "done": [], "dead": [], "run": [], "todo": [] } ] )
    monkeypatch.setattr( v2_queued, "requests", fake )

    with pytest.raises( AssertionError, match="NO queue" ):
        v2_queued.wait_for_done( "http://x", "mine::u1", {}, timeout=0 )


def test_an_unreadable_queue_endpoint_is_a_miss_not_a_crash( monkeypatch, no_sleep ):
    """A 500 from one queue read must not end the wait — the next poll may succeed."""
    fake = _FakeRequests( [ 500, 500, 500, 500 ] )
    monkeypatch.setattr( v2_queued, "requests", fake )

    with pytest.raises( AssertionError, match="NO queue" ):
        v2_queued.wait_for_done( "http://x", "mine::u1", {}, timeout=0 )


def test_the_snapshot_is_looked_up_by_the_verbatim_question( monkeypatch ):
    """
    Teardown cannot read the id off the ask response any more — a waiting hand-off has
    written nothing, and the row appears later under an id the queue chose. So it asks
    the synonym table what the verbatim question resolves to.
    """
    import cosa.rest.db.database as database_mod
    import cosa.rest.db.repositories.canonical_synonym_repository as synonym_mod

    class _Scope:
        def __enter__( self ): return "session"
        def __exit__( self, *args ): return False

    class _Repo:
        def __init__( self, session ):
            self.session = session
        def find_exact_verbatim( self, question ):
            return "snap-99" if question == "what is 2+2" else None

    monkeypatch.setattr( database_mod, "get_db", lambda: _Scope() )
    monkeypatch.setattr( synonym_mod, "CanonicalSynonymRepository", _Repo )

    assert v2_queued.snapshot_id_for_question( "what is 2+2" ) == "snap-99"
    assert v2_queued.snapshot_id_for_question( "never asked" ) is None


def test_a_snapshot_lookup_failure_returns_none_rather_than_masking_the_test( monkeypatch ):
    """
    Teardown must never raise: an exception here would replace the assertion the test
    actually made with a database error from the cleanup.

    RED ON REVERT: drop the try/except in snapshot_id_for_question and this raises
    instead of returning None.
    """
    import cosa.rest.db.database as database_mod

    def _boom():
        raise RuntimeError( "no database here" )

    monkeypatch.setattr( database_mod, "get_db", _boom )

    assert v2_queued.snapshot_id_for_question( "what is 2+2" ) is None


def test_a_job_found_dead_on_the_final_sweep_reports_dead( monkeypatch, no_sleep ):
    """
    The sweep has to say what the loop says. A job that died during the last interval
    was found by the sweep and reported as "still in the 'dead' queue... it did not
    fail, the test stopped waiting" — which is the opposite of what happened, and sends
    the reader hunting a slow queue instead of the error the job already carries
    (Pocholo).

    RED ON REVERT: drop the sweep's dead branch and this reports a stop, not a death.
    """
    fake = _FakeRequests( [ { "done": [], "dead": [ { "job_id": "mine::u1", "error": "boom" } ] } ] )
    monkeypatch.setattr( v2_queued, "requests", fake )

    with pytest.raises( AssertionError, match="DEAD queue: boom" ):
        v2_queued.wait_for_done( "http://x", "mine::u1", {}, timeout=0 )
