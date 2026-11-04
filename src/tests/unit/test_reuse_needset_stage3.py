"""
Stage 3: the control as a stage function, run on fakes with no model call.
"""
import asyncio

import pytest

from cosa.repo.symindex.candidates import candidate_stage as cs
from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import stage3
from tests.unit.test_reuse_needset_positive_control import need_of, pairs, pool


def pair_with_lang( i ):
    """Return pair i with an original language: even are Python, odd are TypeScript."""
    p = pairs()[ i ]
    return { **p, "original": { **p[ "original" ], "lang": "py" if i % 2 == 0 else "ts" }, "rewrite": { **p[ "rewrite" ], "lang": "py" if i % 2 == 0 else "ts" } }


def twenty():
    """Return the twenty pairs with languages."""
    return [ pair_with_lang( i ) for i in range( 20 ) ]


def lexical_ask( order=None ):
    """Return an async ask that uses the word stage and records the order it was asked in."""
    async def ask( planted, p ):
        if order is not None: order.append( p[ "rewrite" ][ "id" ] )
        return cs.shortlist( need_of( p ), cs.build_stage( planted ), 10 )[ "shortlist" ]
    return ask


def test_the_need_record_leaves_the_original_out_and_names_its_language():
    p = twenty()[ 1 ]
    assert stage3.need_for( p, "sentence" ) == { "kind": "work_alike", "write_lang": "ts", "seed": "d-orig01", "need": "sentence" }


def test_the_stage_finds_all_twenty_in_file_order_and_reports_each_language():
    order = []
    rep   = asyncio.run( stage3.control_stage( pool(), twenty(), lexical_ask( order ), cs.build_stage )() )
    assert order == [ p[ "rewrite" ][ "id" ] for p in twenty() ] and rep[ "found" ] == 20 and rep[ "stop" ] is False and rep[ "restored" ] is True
    assert rep[ "by_lang" ] == { "py": { "found": 10, "total": 10 }, "ts": { "found": 10, "total": 10 } }


def test_a_missed_pair_is_named_by_language_and_does_not_stop_the_run():
    async def blind_for_two( planted, p ):
        return [] if p[ "rewrite" ][ "id" ] in ( "d-rew01", "d-rew04" ) else await lexical_ask()( planted, p )

    rep = asyncio.run( stage3.control_stage( pool(), twenty(), blind_for_two, cs.build_stage )() )
    assert rep[ "stop" ] is False and rep[ "missed" ] == [ "d-rew01", "d-rew04" ] and rep[ "found" ] == 18      # the caller scores the misses and sets stop by its own rule
    assert rep[ "by_lang" ] == { "py": { "found": 9, "total": 10 }, "ts": { "found": 9, "total": 10 } }


def test_a_cap_refusal_inside_ask_reaches_the_runner_as_the_same_error():
    async def refused( planted, p ): raise er.NeedsetError( "CALL_CAP_REACHED", "cap" )   # the cap's own code, a literal because the cap module is not in this tree

    with pytest.raises( er.NeedsetError ) as e: asyncio.run( stage3.control_stage( pool(), twenty(), refused, cs.build_stage )() )
    assert e.value.code == "CALL_CAP_REACHED"


def test_a_trace_left_in_the_pool_raises_instead_of_reporting():
    records = pool()

    async def dirty( planted, p ):
        records[ 0 ][ "doc" ] = "trace"
        return []

    with pytest.raises( er.NeedsetError ) as e: asyncio.run( stage3.control_stage( records, twenty(), dirty, cs.build_stage )() )
    assert e.value.code == er.CONTROL_NOT_RESTORED
