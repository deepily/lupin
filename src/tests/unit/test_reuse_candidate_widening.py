"""
Widening: a lookup whose first sweep sits near a cut-off also asks a wider shortlist.

The stage is a stand-in that ranks three ids and answers any K by cutting that ranking.
So the first set is the head of the wider one, as the fusion's prefix property makes it.
K is 1 and the wide size is 3 here, so a first set of one entry has two extra entries to ask.
The policy band is the test's own. The shipped policy has none, so nothing widens in production.
"""
import copy
import json

import pytest

from cosa.repo.symindex import verdict as vd
from cosa.repo.symindex.candidates.errors import CandidateError
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_tools as rt
from tests.unit.test_reuse_candidate_route import FEEDS_ID, MANIFEST, MATH_ID, SERVE_ID
from tests.unit.test_reuse_pack_route import PackedFake, env, no_jev_key, receipt_of   # noqa: F401  (env and no_jev_key are fixtures)
from tests.unit.test_reuse_tools import FEEDS_TEXT, FakeJev, resp

BAND   = dict( vd.POLICY, band=0.05 )
NEAR   = resp( 0.3, 0.2, 0.5 )                                                           # p_overlap 0.5, the threshold itself, and confidence 0.5
RANKED = [ FEEDS_ID, MATH_ID, SERVE_ID ]


class RankedStage:
    """The client's shortlist() and manifest(), cutting one fixed ranking at the K asked for."""

    arm = "B2w"

    def __init__( self, K=1, fail_wide=False, ranking=None ):
        self.K, self.fail_wide, self.ranking, self.calls = K, fail_wide, list( RANKED if ranking is None else ranking ), []

    def manifest( self ): return { "manifest_hash": MANIFEST }

    def shortlist( self, ranking_text, entries, index_sha, pages, exclude_id=None, cache_only=False, wiki_ids=None, K=None ):
        K = self.K if K is None else K
        self.calls.append( { "K": K, "cache_only": cache_only, "wiki_ids": wiki_ids, "exclude_id": exclude_id } )
        if self.fail_wide and K > self.K: raise CandidateError( "CANDIDATE_SEARCH_FAILED", "stand-in failure" )
        ids = [ i for i in self.ranking if i != exclude_id ][ :K ]
        return { "ids": sorted( ids ), "ranking": ids, "lists": { "code": { "size": len( ids ), "head": ids } }, "manifest_hash": MANIFEST,
                 "embed_models": { "code": "c", "prose": "p" }, "arm": self.arm, "K": K, "widened": False, "stage_key": "k" * 32, "wiki": 0,
                 "wiki_ids": [ "w1" ] if wiki_ids is None else list( wiki_ids ), "ranking_hash": "r" * 64 }


@pytest.fixture( autouse=True )
def wide_is_three( monkeypatch ): monkeypatch.setattr( rt, "WIDE_K", 3 )


def ctx_with( env, fake, stage, policy=BAND, size=10 ):
    root, data, out = env
    return rt.ReuseContext( root, data, out_dir=out, transport=fake, sweeper=rp.packed_sweeper( size, shape=rp.SHAPE_WHOLE ), request_shape=rp.SHAPE_WHOLE,
                            pack_size=size, candidate_stage=stage, policy=policy )


def ids_by_stage( rec ):
    out = {}
    for q in rec[ "requests" ]: out.setdefault( q[ "stage" ], [] ).extend( q[ "ids" ] )
    return out


def test_a_first_sweep_near_the_cutoff_asks_the_extra_entries_in_packs_of_their_own( env ):
    need  = "read an RSS feed [wide-1]"
    stage = RankedStage()
    fake  = PackedFake( need, { FEEDS_TEXT: NEAR } )
    r     = rt.check_exists_impl( need, ctx_with( env, fake, stage ) )
    rec   = receipt_of( env, r )
    assert [ c[ "K" ] for c in stage.calls ] == [ 1, 3 ] and stage.calls[ 1 ][ "wiki_ids" ] == [ "w1" ]       # the wide call holds the first call's wiki list
    assert ids_by_stage( rec ) == { "candidates": [ FEEDS_ID ], "widened": sorted( [ MATH_ID, SERVE_ID ] ) }
    cs = rec[ "candidate_stage" ]
    assert cs[ "widened" ] is True and cs[ "K" ] == 3 and cs[ "ids" ] == [ FEEDS_ID ] and cs[ "widened_ids" ] == sorted( [ MATH_ID, SERVE_ID ] )
    assert ( cs[ "entries_total" ], cs[ "entries_asked" ], cs[ "entries_not_asked" ] ) == ( 3, 3, 0 ) and r[ "widened" ] is True
    assert [ s[ "stage" ] for s in rec[ "stats" ][ "stages" ] ] == [ "candidates", "widened" ] and rec[ "stats" ][ "entries" ] == 3


def test_with_no_band_in_the_policy_nothing_widens( env ):
    need  = "read an RSS feed [wide-off]"
    stage = RankedStage()
    r     = rt.check_exists_impl( need, ctx_with( env, PackedFake( need, { FEEDS_TEXT: NEAR } ), stage, policy=None ) )
    rec   = receipt_of( env, r )
    assert [ c[ "K" ] for c in stage.calls ] == [ 1 ] and rec[ "candidate_stage" ][ "widened" ] is False and "widened_ids" in rec[ "candidate_stage" ]
    assert rec[ "candidate_stage" ][ "widened_ids" ] == [] and r[ "widened" ] is False and rec[ "policy" ] == vd.POLICY


def test_an_answer_far_from_every_cutoff_does_not_widen( env ):
    need  = "read an RSS feed [wide-far]"
    stage = RankedStage()
    rt.check_exists_impl( need, ctx_with( env, PackedFake( need, { FEEDS_TEXT: resp( 0.02, 0.03, 0.95 ) } ), stage ) )
    assert [ c[ "K" ] for c in stage.calls ] == [ 1 ]


def test_a_cause_beyond_low_confidence_and_near_cutoff_does_not_widen( env ):
    need  = "read an RSS feed [wide-other-cause]"
    stage = RankedStage()
    fake  = PackedFake( need, { FEEDS_TEXT: NEAR }, omit=[ FEEDS_TEXT ] )                   # the one asked entry is left out of the response: CALL_FAILED holds
    r     = rt.check_exists_impl( need, ctx_with( env, fake, stage ) )
    assert "CALL_FAILED" in r[ "causes" ] and [ c[ "K" ] for c in stage.calls ] == [ 1 ]


def test_no_extra_entries_leaves_the_lookup_as_it_was( env ):
    need  = "read an RSS feed [wide-none]"
    stage = RankedStage( ranking=[ FEEDS_ID ] )                                             # the index holds one id the stage ranks: K 3 adds nothing
    r     = rt.check_exists_impl( need, ctx_with( env, PackedFake( need, { FEEDS_TEXT: NEAR } ), stage ) )
    rec   = receipt_of( env, r )
    assert [ c[ "K" ] for c in stage.calls ] == [ 1, 3 ] and rec[ "candidate_stage" ][ "widened" ] is False and ids_by_stage( rec ) == { "candidates": [ FEEDS_ID ] }


def test_a_stage_that_fails_the_wide_call_adds_call_failed_and_keeps_the_first_sweep( env ):
    need  = "read an RSS feed [wide-fail]"
    stage = RankedStage( fail_wide=True )
    r     = rt.check_exists_impl( need, ctx_with( env, PackedFake( need, { FEEDS_TEXT: NEAR } ), stage ) )
    rec   = receipt_of( env, r )
    assert r[ "verdict" ] == "UNCERTAIN_READ_SOURCE" and "CALL_FAILED" in r[ "causes" ] and rec[ "route" ] == "candidates"
    assert rec[ "candidate_stage" ][ "widen_error" ] == { "code": "CANDIDATE_SEARCH_FAILED", "detail": "stand-in failure" } and rec[ "candidate_stage" ][ "widened" ] is False
    assert ids_by_stage( rec ) == { "candidates": [ FEEDS_ID ] }


def test_an_unpacked_context_never_widens( env ):
    need  = "read an RSS feed [wide-unpacked]"
    stage = RankedStage()
    root, data, out = env
    ctx   = rt.ReuseContext( root, data, out_dir=out, transport=FakeJev( { FEEDS_TEXT: NEAR }, need=need ), candidate_stage=stage, policy=BAND )
    r     = rt.check_exists_impl( need, ctx )
    assert r[ "status" ] == "ok" and [ c[ "K" ] for c in stage.calls ] == [ 1 ] and r[ "widened" ] is False


def test_a_judged_entry_is_not_sent_again_when_the_run_widens( env ):
    need  = "read an RSS feed [wide-warm]"
    stage = RankedStage()
    rt.check_exists_impl( need, ctx_with( env, PackedFake( need, { FEEDS_TEXT: NEAR } ), stage, policy=None ) )         # warm: only the first set is cached
    fake  = PackedFake( need, { FEEDS_TEXT: NEAR } )
    rt.check_exists_impl( need, ctx_with( env, fake, RankedStage() ) )
    sent  = [ q[ "instructions" ] for b in fake.bodies for q in b[ "questions" ].values() ]
    assert len( fake.bodies ) == 1 and not any( FEEDS_TEXT in text for text in sent ) and len( sent ) == 2


def test_the_warm_run_of_a_widened_lookup_sends_nothing_and_records_the_same_two_pack_sets( env ):
    need = "read an RSS feed [wide-cold-warm]"
    cold_fake, warm_fake = PackedFake( need, { FEEDS_TEXT: NEAR } ), PackedFake( need, { FEEDS_TEXT: NEAR } )
    cold = rt.run_question( ctx_with( env, cold_fake, RankedStage() ), "check_exists", need, need, write=False )
    warm = rt.run_question( ctx_with( env, warm_fake, RankedStage() ), "check_exists", need, need, write=False )
    assert len( cold_fake.bodies ) == 2 and warm_fake.bodies == []
    assert ids_by_stage( cold ) == { "candidates": [ FEEDS_ID ], "widened": sorted( [ MATH_ID, SERVE_ID ] ) } and ids_by_stage( warm ) == {}       # a fully cached pack has no request row
    for k in ( "ids", "widened_ids", "K", "widened" ): assert warm[ "candidate_stage" ][ k ] == cold[ "candidate_stage" ][ k ]               # the two sets are the receipt's own, cache or not


def test_a_replay_follows_the_recorded_k_and_both_pack_sets_and_never_decides_again( env ):
    need  = "read an RSS feed [wide-replay]"
    stage = RankedStage()
    ctx   = ctx_with( env, PackedFake( need, { FEEDS_TEXT: NEAR } ), stage )
    r     = rt.check_exists_impl( need, ctx )
    stage.calls.clear()
    out   = rt.replay_impl( r[ "receipt_id" ], ctx )
    frozen_calls = [ c for c in stage.calls if c[ "cache_only" ] ]
    assert out[ "status" ] == "ok" and out[ "differences" ][ "frozen" ] == [] and out[ "frozen" ][ "verdict" ] == r[ "verdict" ]
    assert [ c[ "K" ] for c in frozen_calls ] == [ 3 ] and stage.K == 1                     # the replay's own client copy carries the recorded K
    assert rt.load_receipt( ctx, r[ "receipt_id" ] )[ "candidate_stage" ][ "K" ] == 3


def test_a_replay_of_a_widened_receipt_names_changed_ids_and_changed_packs( env ):
    need  = "read an RSS feed [wide-replay-refuse]"
    stage = RankedStage()
    ctx   = ctx_with( env, PackedFake( need, { FEEDS_TEXT: NEAR } ), stage, size=1 )
    r     = rt.check_exists_impl( need, ctx )
    path  = next( ( env[ 1 ] / "receipts" ).glob( f"{r[ 'receipt_id' ]}*.json" ) )
    saved = path.read_text( encoding="utf-8" )
    rec   = json.loads( saved )
    widened_rows = [ q for q in rec[ "requests" ] if q[ "stage" ] == "widened" ]
    assert [ q[ "ids" ] for q in widened_rows ] == [ [ MATH_ID ], [ SERVE_ID ] ]
    widened_rows[ 0 ][ "ids" ] = [ MATH_ID, SERVE_ID ]
    path.write_text( json.dumps( rec, sort_keys=True ), encoding="utf-8" )
    assert rt.replay_impl( r[ "receipt_id" ], ctx )[ "error" ] == "PACKS_CHANGED"
    path.write_text( saved, encoding="utf-8" )
    stage.ranking = [ FEEDS_ID, MATH_ID ]                                                    # the wide ranking lost an id
    assert rt.replay_impl( r[ "receipt_id" ], ctx )[ "error" ] == "CANDIDATES_CHANGED"


def test_the_receipt_id_of_a_widened_run_differs_from_an_unwidened_one_of_the_same_need( env ):
    need = "read an RSS feed [wide-id]"
    a    = rt.check_exists_impl( need, ctx_with( env, PackedFake( need, { FEEDS_TEXT: NEAR } ), RankedStage(), policy=None ) )
    b    = rt.check_exists_impl( need, ctx_with( env, PackedFake( need, { FEEDS_TEXT: NEAR } ), RankedStage() ) )
    assert a[ "receipt_id" ] != b[ "receipt_id" ] and rt._candidate_of( receipt_of( env, b )[ "candidate_stage" ] )[ "widened_ids" ] != ""


def test_the_rule_widens_on_near_cutoff_with_low_confidence_only():
    assert rt._should_widen( { "causes": [ "NEAR_CUTOFF" ] } ) and rt._should_widen( { "causes": [ "NEAR_CUTOFF", "LOW_CONFIDENCE" ] } )
    assert not rt._should_widen( { "causes": [ "NEAR_CUTOFF", "CALL_FAILED" ] } ) and not rt._should_widen( { "causes": [ "LOW_CONFIDENCE" ] } )


def test_the_wide_call_leaves_out_the_same_entry_as_the_first_call( env ):
    need  = "read an RSS feed [wide-exclude]"
    stage = RankedStage()
    rec   = rt.run_question( ctx_with( env, PackedFake( need, { FEEDS_TEXT: NEAR } ), stage ), "check_exists", need, need, exclude_id=SERVE_ID, write=False )
    assert [ ( c[ "K" ], c[ "exclude_id" ] ) for c in stage.calls ] == [ ( 1, SERVE_ID ), ( 3, SERVE_ID ) ]
    assert rec[ "candidate_stage" ][ "widened_ids" ] == [ MATH_ID ]


def test_a_replay_decides_over_the_widened_entries_too( env ):
    need  = "read an RSS feed [wide-replay-verdict]"
    stage = RankedStage()
    ctx   = ctx_with( env, PackedFake( need, { FEEDS_TEXT: NEAR, rt_math_text(): resp( 0.9, 0.05, 0.05 ) } ), stage )
    r     = rt.check_exists_impl( need, ctx )
    out   = rt.replay_impl( r[ "receipt_id" ], ctx )
    assert r[ "widened" ] is True and MATH_ID in [ e[ "id" ] for e in r[ "shortlist" ] ]                 # the widened entry is on the shortlist
    assert [ e[ "id" ] for e in out[ "frozen" ][ "shortlist" ] ] == [ e[ "id" ] for e in r[ "shortlist" ] ] and out[ "differences" ][ "frozen" ] == []


def rt_math_text():
    from tests.unit.test_reuse_tools import MATHX_TEXT
    return MATHX_TEXT
