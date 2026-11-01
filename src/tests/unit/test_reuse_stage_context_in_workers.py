"""
Jev calls made on a sweep's worker threads are charged to the stage that asked for them.
"""
import concurrent.futures
import json

import pytest

from cosa.repo.doc_lint import jev_transport as jt
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_tools as rt
from lupin_mcp.reuse_needset import call_cap, errors as er
from tests.unit.test_reuse_pack_breaker import MANY
from tests.unit.test_reuse_pack_send import NEED, PROBS, Fake


class Charging( Fake ):
    """A transport that charges the call cap, as the live Jev transport does, for each request."""

    def post_with_meta( self, body ):
        jt._charged( json.dumps( { "model": body[ "model" ] } ) )
        answers = { key: { "probabilities": dict( PROBS ) } for key in body[ "questions" ] }
        return { "answers": answers, "model": body[ "model" ] }, { "status": 200, "attempts": 1, "retry_after": None, "latency_ms": 1 }


def test_the_packed_sweeps_worker_threads_charge_their_calls_to_the_running_stage( tmp_path ):
    cap = call_cap.CallCap( str( tmp_path / "calls.jsonl" ), 100, { "attribution": 50 } )
    ctx = rt.ReuseContext( tmp_path, tmp_path / "data", out_dir=tmp_path / "out", transport=Charging() )
    with cap.installed(), call_cap.stage( "attribution" ):
        out = rp.sweep_packed( ctx, NEED, MANY, 6, workers=4 )
    assert len( out[ "answers" ] ) == len( MANY ) and cap.used() == 4
    assert cap.by_stage() == { "attribution": 4 } and "unstaged" not in cap.by_stage()


def test_a_call_past_the_stages_budget_on_a_worker_thread_is_refused_by_name( tmp_path ):
    cap = call_cap.CallCap( str( tmp_path / "calls.jsonl" ), 100, { "attribution": 1 } )
    with cap.installed(), call_cap.stage( "attribution" ), concurrent.futures.ThreadPoolExecutor( max_workers=2 ) as pool:
        results = rt.map_in_context( pool, lambda n: jt._charged( json.dumps( { "model": "m" } ) ), [ 1 ] )
        assert list( results ) == [ None ]
        with pytest.raises( er.NeedsetError ) as e: list( rt.map_in_context( pool, lambda n: jt._charged( json.dumps( { "model": "m" } ) ), [ 2 ] ) )
    assert e.value.code == er.STAGE_BUDGET_REACHED and "attribution" in e.value.detail and cap.by_stage() == { "attribution": 1 }


def test_without_the_context_copy_the_same_worker_calls_would_be_filed_unstaged( tmp_path ):
    cap = call_cap.CallCap( str( tmp_path / "calls.jsonl" ), 100 )
    with cap.installed(), call_cap.stage( "attribution" ), concurrent.futures.ThreadPoolExecutor( max_workers=2 ) as pool:
        list( pool.map( lambda n: jt._charged( json.dumps( { "model": "m" } ) ), [ 1, 2 ] ) )
    assert cap.by_stage() == { "unstaged": 2 }
