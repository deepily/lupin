"""
Receipts that name a left-out entry: ids of other questions do not move.

The page route these tests once covered is gone. A receipt it wrote stays readable and replays to ROUTE_RETIRED,
which test_reuse_candidate_route.py checks.
Every answer comes from the request-keyed fake in test_reuse_page_first, so no test makes a live call.
"""
import json

import pytest

from lupin_mcp import reuse_e2e_run as run
from lupin_mcp import reuse_stage1 as s1
from lupin_mcp import reuse_tools as rt
from tests.unit.test_reuse_page_first import (  # noqa: F401  (env and no_jev_key are fixtures)
    CHOSEN, FEEDS_PAGE, HIT, MATH_PAGE, PageFake, env, no_jev_key, receipt_of, write_wiki )
from tests.unit.test_reuse_tools import FEEDS_TEXT, MATHX_TEXT, SERVE_TEXT


def ctx_of( env, fake, **kw ): return rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=fake, **kw )



def test_a_stored_page_route_receipt_with_no_exclusion_replays_as_before( env ):
    write_wiki( env[ 0 ] )
    need = "no exclusion [plain]"
    ctx  = ctx_of( env, PageFake( need ) )
    r    = rt.check_exists_impl( need, ctx )
    assert "exclude_id" not in receipt_of( env, r ) and rt.replay_impl( r[ "receipt_id" ], ctx )[ "differences" ][ "frozen" ] == []



def test_receipt_ids_of_other_questions_do_not_move():
    base = dict( tool="fetch_similar", query="q", index_sha="i", model="m", policy={}, template_hash="t" )
    a = rt.receipt_id( base[ "tool" ], base[ "query" ], base[ "index_sha" ], base[ "model" ], base[ "policy" ], base[ "template_hash" ] )
    b = rt.receipt_id( base[ "tool" ], base[ "query" ], base[ "index_sha" ], base[ "model" ], base[ "policy" ], base[ "template_hash" ], exclude_id="q" )
    assert a == b                                                                         # fetch_similar passes its own id as exclude_id; its id has never carried it
    c = rt.receipt_id( "check_exists", "q", "i", "m", {}, "t" )
    d = rt.receipt_id( "check_exists", "q", "i", "m", {}, "t", exclude_id="x" )
    e = rt.receipt_id( "check_exists", "q", "i", "m", {}, "t", sweep_only=True, exclude_id="x" )
    assert len( { c, d, e } ) == 3


