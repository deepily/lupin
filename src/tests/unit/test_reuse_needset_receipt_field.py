"""
Which receipt field lists the entries the checker sent to the judge, on each path.

The answer is candidate_stage ids plus widened_ids. The request rows are not the field, because
an entry answered from the cache is in no row. Each test builds a receipt through the real question.
"""
import pytest

from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_tools as rt
from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import loss_trace
from tests.unit.test_reuse_candidate_route import FEEDS_ID, MATH_ID, SERVE_ID, FakeStage
from tests.unit.test_reuse_candidate_widening import BAND, NEAR, NO_BAND, RankedStage
from tests.unit.test_reuse_pack_route import PackedFake, env, no_jev_key   # noqa: F401  (env and no_jev_key are fixtures)
from tests.unit.test_reuse_tools import FEEDS_TEXT, FakeJev

NEED = "read an RSS feed"


def need_record( seed=None, kind="work_alike" ):
    """Return the parts of a need that check_need reads."""
    return { "need": NEED, "seed": seed, "kind": kind, "write_lang": "py" }


def packed( env, fake, stage, policy=None ):
    root, data, out = env
    return rt.ReuseContext( root, data, out_dir=out, transport=fake, sweeper=rp.packed_sweeper( 10, shape=rp.SHAPE_WHOLE ), request_shape=rp.SHAPE_WHOLE, pack_size=10,
                            candidate_stage=stage, policy=policy )


def rows_ids( receipt ): return sorted( { i for row in receipt[ "requests" ] for i in row[ "ids" ] } )


def test_the_packed_receipt_lists_the_asked_ids_in_its_candidate_stage_and_in_its_rows( env ):
    receipt = loss_trace.check_need( need_record(), packed( env, PackedFake( NEED ), FakeStage() ) )
    assert loss_trace.asked_ids( receipt ) == sorted( [ FEEDS_ID, MATH_ID ] ) == rows_ids( receipt )
    assert receipt[ "candidate_stage" ][ "entries_asked" ] == len( loss_trace.asked_ids( receipt ) ) == 2


def test_the_unpacked_receipt_has_no_rows_and_the_candidate_stage_still_lists_the_ids( env ):
    root, data, out = env
    ctx     = rt.ReuseContext( root, data, out_dir=out, transport=FakeJev( { FEEDS_TEXT: NEAR }, need=NEED ), candidate_stage=FakeStage() )
    receipt = loss_trace.check_need( need_record(), ctx )
    assert "requests" not in receipt and loss_trace.asked_ids( receipt ) == sorted( [ FEEDS_ID, MATH_ID ] )


def test_a_widened_receipt_lists_the_first_and_the_extra_ids( env ):
    receipt = loss_trace.check_need( need_record(), packed( env, PackedFake( NEED, { FEEDS_TEXT: NEAR } ), RankedStage(), policy=dict( BAND ) ) )
    assert receipt[ "candidate_stage" ][ "widened" ] is True and loss_trace.asked_ids( receipt ) == sorted( [ FEEDS_ID, MATH_ID, SERVE_ID ] )


def test_an_entry_answered_from_the_cache_is_in_the_candidate_stage_and_in_no_request_row( env ):
    """The reason the rows are not the field: a warm run sends less than it asks."""
    loss_trace.check_need( need_record(), packed( env, PackedFake( NEED, { FEEDS_TEXT: NEAR } ), RankedStage(), policy=dict( NO_BAND ) ) )     # warms the cache with the first entry only
    receipt = loss_trace.check_need( need_record(), packed( env, PackedFake( NEED, { FEEDS_TEXT: NEAR } ), RankedStage(), policy=dict( BAND ) ) )
    assert rows_ids( receipt ) == sorted( [ MATH_ID, SERVE_ID ] ) and FEEDS_ID not in rows_ids( receipt )
    assert loss_trace.asked_ids( receipt ) == sorted( [ FEEDS_ID, MATH_ID, SERVE_ID ] ) and receipt[ "candidate_stage" ][ "entries_asked" ] == 3


def test_the_seed_is_left_out_of_the_asked_ids( env ):
    receipt = loss_trace.check_need( need_record( seed=FEEDS_ID ), packed( env, PackedFake( NEED ), FakeStage() ) )
    assert loss_trace.asked_ids( receipt ) == [ MATH_ID ]


def test_a_cross_language_need_asks_every_language_and_the_others_ask_their_own( env, monkeypatch ):
    seen = []
    real = rt.run_question

    def spy( *args, **kwargs ):
        seen.append( kwargs[ "language" ] )
        return real( *args, **kwargs )

    monkeypatch.setattr( rt, "run_question", spy )
    for kind in ( "cross_language", "work_alike", "nothing" ): loss_trace.check_need( need_record( kind=kind ), packed( env, PackedFake( NEED ), FakeStage() ) )
    assert seen == [ "all", "py", "py" ]


def test_a_failed_stage_and_a_context_without_a_stage_raise_instead_of_reading_as_nothing_asked( env ):
    failed = loss_trace.check_need( need_record(), packed( env, PackedFake( NEED ), FakeStage( error="QUERY_VECTOR_MISSING" ) ) )
    with pytest.raises( er.NeedsetError ) as e: loss_trace.asked_ids( failed )
    assert e.value.code == er.RECEIPT_FIELD_ABSENT
    full = loss_trace.check_need( need_record(), packed( env, PackedFake( NEED ), None ) )
    with pytest.raises( er.NeedsetError ) as e: loss_trace.asked_ids( full )
    assert e.value.code == er.RECEIPT_FIELD_ABSENT and full[ "id" ] in e.value.detail
