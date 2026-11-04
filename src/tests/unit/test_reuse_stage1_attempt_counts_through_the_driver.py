"""
The 429 and 529 counts of a report over an arm the real driver wrote.

The driver here is the real `run_arm` on a stand-in transport that retries one request and fails another outright.
Nothing reaches Jev and no real ledger is touched.
"""
import json

import pytest

from cosa.repo.doc_lint import jev_transport as jt
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_stage1 as st
from lupin_mcp import reuse_stage1_analysis as an
from tests.unit.test_reuse_stage1_driver import ENTRIES, LIMIT, NEED, Standin

RETRY_KEY = rp.question_key( ENTRIES[ 1 ][ "id" ] )                                 # the request that is retried and the one that fails are fixed by their question, not by arrival order
FAIL_KEY  = rp.question_key( ENTRIES[ 3 ][ "id" ] )
RETRIED   = [ { "status": 429 }, { "status": 529 }, { "status": 200 } ]
FAILED    = [ { "status": 429 }, { "status": 429 }, { "status": 429 }, { "status": 529 } ]


class Flaky( Standin ):
    """A stand-in that retries one request and fails another after four attempts."""

    def post_with_meta( self, body ):
        if FAIL_KEY in body[ "questions" ]:
            for _ in FAILED: self.budget.take()
            self.bodies.append( body )
            raise jt.JevCallError( "retries ran out", 529, FAILED )
        response, meta = super().post_with_meta( body )
        if RETRY_KEY in body[ "questions" ]:
            self.budget.take(); self.budget.take()
            meta.update( attempts=3, attempt_log=RETRIED )
        return response, meta


class Bare( Standin ):
    """A stand-in whose meta carries no attempt log."""

    def post_with_meta( self, body ):
        response, meta = super().post_with_meta( body )
        del meta[ "attempt_log" ]
        return response, meta


@pytest.fixture
def env( tmp_path ):
    """A driver environment on a scratch ledger."""
    ledger = rl.AccountLedger.create( tmp_path / "ledger.jsonl", LIMIT, "test", "scratch" )
    return st.Stage1Env( root=tmp_path, data=tmp_path / "data", ledger=ledger, transport_factory=lambda budget, **kw: Flaky( budget, **kw ), entries_in_index=len( ENTRIES ) )


def written( env ):
    """Ensures: returns the arm record the driver wrote."""
    return json.loads( ( env.results_dir / "s1-q1-single1.json" ).read_text() )


def test_the_report_counts_the_429s_and_529s_of_a_retried_request_and_of_one_that_failed_outright( env ):
    st.run_arm( env, 1, "single1", NEED, ENTRIES, 5_000_000 )
    rec = written( env )
    assert any( r[ "status" ] != "answered" and r[ "http" ] is None for r in rec[ "rows" ] )          # the failed request has no transport call
    stats = an.request_stats( an.read_stage( [ rec ] ) )[ 1 ][ "single1" ]
    assert ( stats[ "attempts_429" ], stats[ "attempts_529" ] ) == ( 4, 2 ) and ( stats[ "retried_calls" ], stats[ "extra_attempts" ] ) == ( 2, 5 )


def test_the_text_report_prints_those_counts_on_the_request_line( env ):
    st.run_arm( env, 1, "single1", NEED, ENTRIES, 5_000_000 )
    text = an.render( an.build_report( [ written( env ) ], canaries=[] ) )
    assert "retried calls 2, extra attempts 5; usage missing 1; 429s 4, 529s 2" in text


def test_a_meta_with_no_attempt_log_does_not_crash_the_report_and_counts_none( env ):
    env.transport_factory = lambda budget, **kw: Bare( budget, **kw )
    st.run_arm( env, 1, "single1", NEED, ENTRIES, 5_000_000 )
    stats = an.request_stats( an.read_stage( [ written( env ) ] ) )[ 1 ][ "single1" ]
    assert ( stats[ "attempts_429" ], stats[ "attempts_529" ], stats[ "extra_attempts" ] ) == ( 0, 0, 0 )
