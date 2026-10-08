"""
A 422 is never retried, and five in a row with no answer between them stop the run.

A 422 refuses that one request (plan 9.2). It is never posted again, and the next entry still goes.
A door that refuses everything must cost five posts, not one per index entry. After five refusals in a row,
with no answered request between them, the sweep stops, counts the rest unasked, and the receipt says why.
Until the first answer, and while a refusal is unanswered, posts go one at a time so the stop is exact.

The sweep is driven over a live transport with a scripted door. No case reaches Jev.
"""
import json
import threading
import time

import pytest

from cosa.repo.doc_lint import jev_transport
from lupin_mcp import reuse_tools as rt
from tests.unit.symindex_helpers import make_lupin_repo
from tests.unit.test_reuse_tools import FEEDS_TEXT, MATHX_TEXT, SERVE_TEXT, UNREL, FakeJev, N
from tests.unit.test_reuse_transport_telemetry import ENV, with_usage

ANSWER = json.dumps( with_usage( UNREL ) )


@pytest.fixture( autouse=True )
def no_jev_key( monkeypatch ):
    """No test here may find a real key: a live call would be spend and a leak."""
    monkeypatch.delenv( jev_transport.KEY_VARIABLE, raising=False )


@pytest.fixture
def env( tmp_path ):
    root = make_lupin_repo( tmp_path )
    return root, tmp_path / "data", tmp_path / "out"


def entries( count ):
    return [ { "id": f"m.f{i}", "sig": "()", "doc": f"does thing {i}" } for i in range( count ) ]


class Door:
    """A scripted door that counts its posts and the most made at once."""

    def __init__( self, statuses, pause=0.0 ):
        self.statuses, self.pause, self.posts, self.now, self.most, self.lock = list( statuses ), pause, 0, 0, 0, threading.Lock()

    def __call__( self, url, headers, body, timeout ):
        with self.lock:
            self.posts += 1; self.now += 1; self.most = max( self.most, self.now )
            status = self.statuses.pop( 0 ) if len( self.statuses ) > 1 else self.statuses[ 0 ]
        time.sleep( self.pause )
        with self.lock: self.now -= 1
        return ( 200, ANSWER ) if status == 200 else ( status, "refused" )


def ctx_over( env_, door ):
    root, data, out = env_
    transport = rt.LiveJevTransport( post_fn=door, sleep_fn=lambda s: None, environ=ENV, random_fn=lambda: 0.5 )
    return rt.ReuseContext( root, data, out_dir=out, transport=transport )


def test_a_422_is_posted_once_for_its_entry_and_never_retried( env ):
    door = Door( [ 422 ] )
    sw   = rt.sweep( ctx_over( env, door ), N( "q" ), entries( 3 ) )
    assert door.posts == 3 and sw[ "failed" ] == [ "m.f0", "m.f1", "m.f2" ] and sw[ "not_reached" ] == []
    assert [ f[ "attempts" ] for f in sw[ "failed_attempts" ] ] == [ 1, 1, 1 ]
    assert sw[ "refused_422" ] == 3 and sw[ "stopped_by" ] is None


def test_five_refusals_in_a_row_stop_the_run_and_the_rest_are_counted_unasked( env ):
    door = Door( [ 422 ] )
    sw   = rt.sweep( ctx_over( env, door ), N( "q" ), entries( 8 ) )
    assert door.posts == 5 and sw[ "refused_422" ] == 5 and sw[ "stopped_by" ] == "consecutive_422"
    assert sw[ "failed" ] == [ f"m.f{i}" for i in range( 5 ) ] and sw[ "not_reached" ] == [ "m.f5", "m.f6", "m.f7" ]


def test_an_answer_between_refusals_resets_the_count( env, monkeypatch ):
    monkeypatch.setattr( rt, "WORKERS", 1 )
    door = Door( [ 422, 422, 422, 422, 200, 422, 422, 422, 422, 200 ] )
    sw   = rt.sweep( ctx_over( env, door ), N( "q" ), entries( 10 ) )
    assert door.posts == 10 and sw[ "refused_422" ] == 8 and sw[ "stopped_by" ] is None and sw[ "not_reached" ] == []
    assert len( sw[ "answers" ] ) == 2


def test_posts_go_one_at_a_time_until_the_first_answer( env ):
    door = Door( [ 422 ], pause=0.02 )
    rt.sweep( ctx_over( env, door ), N( "q" ), entries( 12 ) )
    assert door.most == 1


def test_after_the_first_answer_posts_run_in_parallel_again( env ):
    door = Door( [ 200 ], pause=0.05 )
    sw   = rt.sweep( ctx_over( env, door ), N( "q" ), entries( 12 ) )
    assert door.most > 1 and len( sw[ "answers" ] ) == 12 and sw[ "stopped_by" ] is None


def test_the_receipt_says_why_the_run_stopped( env, monkeypatch ):
    monkeypatch.setattr( rt, "BREAKER_422", 2, raising=False )
    need = N( "stop" )
    r    = rt.check_exists_impl( need, ctx_over( env, Door( [ 422 ] ) ) )
    assert r[ "stats" ][ "stopped_by" ] == "consecutive_422" and r[ "stats" ][ "refused_422" ] == 2
    assert r[ "stats" ][ "failed" ] == 2 and r[ "stats" ][ "not_checked" ] == 1


def test_a_receipt_with_no_refusal_reports_none_and_zero( env ):
    r = rt.check_exists_impl( N( "ok" ), ctx_over( env, Door( [ 200 ] ) ) )
    assert r[ "stats" ][ "stopped_by" ] is None and r[ "stats" ][ "refused_422" ] == 0
