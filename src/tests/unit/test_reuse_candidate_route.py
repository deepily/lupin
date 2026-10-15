"""
check_exists through the candidate stage: the shortlist is asked, a failure is named.

The stage is a stand-in with the client's own interface, so no vector set, embedding call or server is needed.
Jev answers come from the packed fake of test_reuse_pack_route, which refuses any candidate it was not given.
"""
import copy
import json

import pytest

from cosa.repo.symindex.candidates.errors import CandidateError
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_tools as rt
from tests.unit.test_reuse_pack_route import PackedFake, env, no_jev_key, receipt_of   # noqa: F401  (env and no_jev_key are fixtures)
from tests.unit.test_reuse_page_first import HIT
from tests.unit.test_reuse_tools import FEEDS_TEXT

FEEDS_ID, MATH_ID, SERVE_ID = "cosa.feeds.parse_feed", "cosa.mathx.add", "lupin_mcp.tool.serve"
MANIFEST = "a" * 64


class FakeStage:
    """The candidate stage's interface: shortlist() and manifest(), with every call recorded."""

    arm, K = "B2w", 128

    def __init__( self, ids=( MATH_ID, FEEDS_ID ), manifest_hash=MANIFEST, error=None ):
        self.ids, self.manifest_hash, self.error, self.calls = list( ids ), manifest_hash, error, []

    def manifest( self ): return { "manifest_hash": self.manifest_hash }

    def shortlist( self, ranking_text, entries, index_sha, pages, exclude_id=None, cache_only=False, wiki_ids=None ):
        self.calls.append( { "ranking_text": ranking_text, "entries": len( entries ), "exclude_id": exclude_id, "cache_only": cache_only, "wiki_ids": wiki_ids } )
        if self.error is not None: raise CandidateError( self.error, "stand-in failure" )
        ids = sorted( i for i in self.ids if i != exclude_id )
        return { "ids": ids, "ranking": ids, "lists": { "code": { "size": len( ids ), "head": ids } }, "manifest_hash": self.manifest_hash,
                 "embed_models": { "code": "c-model", "prose": "p-model" }, "arm": self.arm, "K": self.K, "widened": False, "stage_key": "k" * 32,
                 "wiki": 0, "wiki_ids": [] if wiki_ids is None else list( wiki_ids ), "ranking_hash": "r" * 64 }


def ctx_with( env, fake, stage, size=10 ):
    root, data, out = env
    return rt.ReuseContext( root, data, out_dir=out, transport=fake, sweeper=rp.packed_sweeper( size, shape=rp.SHAPE_WHOLE ), request_shape=rp.SHAPE_WHOLE,
                            pack_size=size, candidate_stage=stage )


def asked_ids( rec ): return sorted( i for q in rec[ "requests" ] for i in q[ "ids" ] )


def test_only_the_shortlist_is_asked_and_the_receipt_counts_what_was_not( env ):
    need  = "read an RSS feed [cand-1]"
    stage = FakeStage()
    fake  = PackedFake( need, { FEEDS_TEXT: HIT } )
    r     = rt.check_exists_impl( need, ctx_with( env, fake, stage ) )
    rec   = receipt_of( env, r )
    assert ( r[ "status" ], r[ "verdict" ] ) == ( "ok", "REUSE" ) and fake.unexpected == []
    assert rec[ "route" ] == "candidates" and asked_ids( rec ) == sorted( [ FEEDS_ID, MATH_ID ] ) and rec[ "request_shape" ] == rp.SHAPE_WHOLE
    cs = rec[ "candidate_stage" ]
    assert cs[ "entries_total" ] == 3 and cs[ "entries_asked" ] == 2 and cs[ "entries_not_asked" ] == 1
    assert cs[ "entries_asked" ] + cs[ "entries_not_asked" ] == cs[ "entries_total" ] and cs[ "ids" ] == sorted( [ FEEDS_ID, MATH_ID ] )
    assert cs[ "manifest_hash" ] == MANIFEST and cs[ "K" ] == 128 and cs[ "arm" ] == "B2w" and cs[ "ranking_text" ] == need and "error" not in cs
    assert rec[ "stats" ][ "stages" ][ 0 ][ "stage" ] == "candidates" and rec[ "stats" ][ "entries" ] == 2


def test_a_failed_stage_answers_uncertain_with_call_failed_and_sweeps_nothing( env ):
    need  = "read an RSS feed [cand-fail]"
    fake  = PackedFake( need )
    r     = rt.check_exists_impl( need, ctx_with( env, fake, FakeStage( error="QUERY_VECTOR_MISSING" ) ) )
    rec   = receipt_of( env, r )
    assert r[ "verdict" ] == "UNCERTAIN_READ_SOURCE" and r[ "cause" ] == "CALL_FAILED" and fake.bodies == []
    assert rec[ "route" ] == "none" and rec[ "candidate_stage" ][ "error" ] == { "code": "QUERY_VECTOR_MISSING", "detail": "stand-in failure" }
    assert rec[ "candidate_stage" ][ "entries_asked" ] == 0 and rec[ "candidate_stage" ][ "entries_not_asked" ] == 3 and rec[ "candidate_stage" ][ "manifest_hash" ] is None


def test_a_failed_stage_receipt_replays_to_its_stored_verdict_and_sends_nothing( env ):
    need  = "read an RSS feed [cand-fail-replay]"
    ctx   = ctx_with( env, PackedFake( need ), FakeStage( error="CANDIDATE_SEARCH_FAILED" ) )
    r     = rt.check_exists_impl( need, ctx )
    out   = rt.replay_impl( r[ "receipt_id" ], ctx )
    assert out[ "status" ] == "ok" and out[ "frozen" ][ "verdict" ] == "UNCERTAIN_READ_SOURCE" and out[ "differences" ][ "frozen" ] == []


@pytest.mark.parametrize( "call", [ lambda ctx, need: rt.sweep_need_impl( need, None, ctx ), lambda ctx, need: rt.fetch_similar_impl( FEEDS_ID, ctx ) ] )
def test_a_sweep_only_question_and_a_fetch_similar_never_use_the_stage_and_ask_every_entry( env, call ):
    need  = "read an RSS feed [cand-off]"
    stage = FakeStage()
    fake  = PackedFake( need )
    r     = call( ctx_with( env, fake, stage ), need )
    rec   = receipt_of( env, r )
    assert r[ "status" ] == "ok" and stage.calls == [] and rec[ "route" ] == "full" and "candidate_stage" not in rec


def test_a_left_out_entry_goes_to_the_stage_so_it_is_dropped_from_the_shortlist_and_the_asked_set( env ):
    need  = "read an RSS feed [cand-exclude]"
    stage = FakeStage()
    fake  = PackedFake( need )
    r     = rt.run_question( ctx_with( env, fake, stage ), "check_exists", need, need, exclude_id=MATH_ID )
    assert stage.calls[ 0 ][ "exclude_id" ] == MATH_ID and stage.calls[ 0 ][ "entries" ] == 3        # the stage holds the whole index
    assert asked_ids( r ) == [ FEEDS_ID ] and r[ "candidate_stage" ][ "entries_total" ] == 2 and r[ "candidate_stage" ][ "entries_asked" ] == 1


def test_the_receipt_id_holds_the_manifest_hash_and_k_so_another_stage_is_another_receipt( env ):
    need = "read an RSS feed [cand-id]"
    a    = rt.check_exists_impl( need, ctx_with( env, PackedFake( need ), FakeStage() ) )
    b    = rt.check_exists_impl( need, ctx_with( env, PackedFake( need ), FakeStage( manifest_hash="b" * 64 ) ) )
    wide = FakeStage()
    wide.K = 512
    c    = rt.check_exists_impl( need, ctx_with( env, PackedFake( need ), wide ) )
    assert len( { a[ "receipt_id" ], b[ "receipt_id" ], c[ "receipt_id" ] } ) == 3


def test_a_stored_receipt_whose_manifest_hash_was_edited_no_longer_matches_its_id( env ):
    need = "read an RSS feed [cand-edit]"
    ctx  = ctx_with( env, PackedFake( need ), FakeStage() )
    r    = rt.check_exists_impl( need, ctx )
    path = next( ( env[ 1 ] / "receipts" ).glob( f"{r[ 'receipt_id' ]}*.json" ) )
    rec  = json.loads( path.read_text( encoding="utf-8" ) )
    rec[ "candidate_stage" ][ "manifest_hash" ] = "c" * 64
    path.write_text( json.dumps( rec, sort_keys=True ), encoding="utf-8" )
    with pytest.raises( rt.ReuseError, match="RECEIPT_ID_MISMATCH" ): rt.load_receipt( ctx, r[ "receipt_id" ] )


def test_a_frozen_replay_rebuilds_the_shortlist_from_the_cache_and_reads_only_cached_answers( env ):
    need  = "read an RSS feed [cand-replay]"
    stage = FakeStage()
    ctx   = ctx_with( env, PackedFake( need, { FEEDS_TEXT: HIT } ), stage )
    r     = rt.check_exists_impl( need, ctx )
    out   = rt.replay_impl( r[ "receipt_id" ], ctx )
    assert out[ "status" ] == "ok" and out[ "differences" ] == { "frozen": [], "head": [] } and out[ "frozen" ][ "verdict" ] == "REUSE"
    replayed = [ c for c in stage.calls if c[ "cache_only" ] ]
    assert len( replayed ) == 1 and replayed[ 0 ][ "ranking_text" ] == need and replayed[ 0 ][ "wiki_ids" ] == []


def test_a_replay_names_a_replaced_vector_set_before_anything_is_read( env ):
    need  = "read an RSS feed [cand-replaced]"
    stage = FakeStage()
    ctx   = ctx_with( env, PackedFake( need ), stage )
    r     = rt.check_exists_impl( need, ctx )
    stage.manifest_hash = "d" * 64
    out   = rt.replay_impl( r[ "receipt_id" ], ctx )
    assert out[ "status" ] == "error" and out[ "error" ] == "VECTOR_SET_REPLACED"


def test_a_replay_names_changed_candidates_and_a_lost_query_vector( env ):
    need  = "read an RSS feed [cand-changed]"
    stage = FakeStage()
    ctx   = ctx_with( env, PackedFake( need ), stage )
    r     = rt.check_exists_impl( need, ctx )
    stage.ids = [ MATH_ID, SERVE_ID ]
    assert rt.replay_impl( r[ "receipt_id" ], ctx )[ "error" ] == "CANDIDATES_CHANGED"
    stage.ids, stage.error = [ MATH_ID, FEEDS_ID ], "QUERY_VECTOR_MISSING"
    out = rt.replay_impl( r[ "receipt_id" ], ctx )
    assert out[ "error" ] == "CANDIDATE_STAGE_FAILED" and "QUERY_VECTOR_MISSING" in out[ "detail" ]


def test_a_replay_on_a_context_with_no_stage_is_a_named_error( env ):
    need = "read an RSS feed [cand-nostage]"
    ctx  = ctx_with( env, PackedFake( need ), FakeStage() )
    r    = rt.check_exists_impl( need, ctx )
    bare = copy.copy( ctx )
    bare.candidate_stage = None
    assert rt.replay_impl( r[ "receipt_id" ], bare )[ "error" ] == "CANDIDATE_STAGE_UNAVAILABLE"


def test_a_recorded_pack_that_is_not_a_cut_of_the_recorded_ids_is_refused( env ):
    need = "read an RSS feed [cand-packs]"
    ctx  = ctx_with( env, PackedFake( need ), FakeStage(), size=1 )
    r    = rt.check_exists_impl( need, ctx )
    path = next( ( env[ 1 ] / "receipts" ).glob( f"{r[ 'receipt_id' ]}*.json" ) )
    rec  = json.loads( path.read_text( encoding="utf-8" ) )
    assert [ q[ "ids" ] for q in rec[ "requests" ] ] == [ [ FEEDS_ID ], [ MATH_ID ] ]
    rec[ "requests" ][ 0 ][ "ids" ] = [ FEEDS_ID, MATH_ID ]
    path.write_text( json.dumps( rec, sort_keys=True ), encoding="utf-8" )
    assert rt.replay_impl( r[ "receipt_id" ], ctx )[ "error" ] == "PACKS_CHANGED"


@pytest.mark.parametrize( "route", [ "pages", "pages_then_full" ] )
def test_a_receipt_of_the_retired_page_route_stays_readable_and_replays_to_route_retired( env, route ):
    need = "read an RSS feed [cand-retired]"
    ctx  = ctx_with( env, PackedFake( need ), FakeStage() )
    r    = rt.check_exists_impl( need, ctx )
    path = next( ( env[ 1 ] / "receipts" ).glob( f"{r[ 'receipt_id' ]}*.json" ) )
    rec  = json.loads( path.read_text( encoding="utf-8" ) )
    rec[ "route" ] = route                                                                    # the route is not in the id, so the receipt still loads
    path.write_text( json.dumps( rec, sort_keys=True ), encoding="utf-8" )
    assert rt.load_receipt( ctx, r[ "receipt_id" ] )[ "route" ] == route
    out = rt.replay_impl( r[ "receipt_id" ], ctx )
    assert out[ "status" ] == "error" and out[ "error" ] == "ROUTE_RETIRED" and route in out[ "detail" ]


def test_the_environment_builds_the_candidate_stage_and_a_missing_storage_key_is_named( monkeypatch, env ):
    monkeypatch.setenv( "LUPIN_REUSE_DATA_DIR", str( env[ 1 ] ) ); monkeypatch.setenv( "LUPIN_REUSE_OUT_DIR", str( env[ 2 ] ) )
    monkeypatch.setenv( "LUPIN_REUSE_JEV_PACK_SIZE", "50" ); monkeypatch.setenv( "LUPIN_REUSE_JEV_TOKEN_CEILING", "1000" ); monkeypatch.setenv( "LUPIN_REUSE_JEV_RUN_NAME", "cand-env" )
    monkeypatch.setenv( "LUPIN_REUSE_CANDIDATE_VECTORS_DIR", "/vec" ); monkeypatch.setenv( "LUPIN_REUSE_CANDIDATE_QUERY_CACHE_DIR", "/qc" )
    monkeypatch.setenv( "LUPIN_REUSE_CANDIDATE_PURPOSE_DIR", "/pp" )
    stage = rt.context_from_environment( env[ 0 ] ).candidate_stage
    assert stage.vectors_dir == "/vec" and stage.query_cache_dir == "/qc" and str( stage.purposes_path ) == "/pp/purpose.jsonl" and stage.arm == "B2w" and stage.K == 128
    monkeypatch.setenv( "LUPIN_REUSE_CANDIDATE_VECTORS_DIR", "relative" )
    with pytest.raises( rt.ReuseError, match="CANDIDATE_STAGE_UNCONFIGURED" ): rt.context_from_environment( env[ 0 ] )


def test_the_caller_sees_how_many_entries_were_not_asked_and_a_full_sweep_says_none( env ):
    need = "read an RSS feed [cand-public]"
    r    = rt.check_exists_impl( need, ctx_with( env, PackedFake( need ), FakeStage() ) )
    assert r[ "verdict" ] == "NEW" and ( r[ "entries_total" ], r[ "entries_asked" ], r[ "entries_not_asked" ] ) == ( 3, 2, 1 )
    full = rt.sweep_need_impl( need, None, ctx_with( env, PackedFake( need ), FakeStage() ) )
    assert ( full[ "entries_total" ], full[ "entries_asked" ], full[ "entries_not_asked" ] ) == ( None, None, None )


def test_a_replay_reads_the_cached_answer_a_resent_pack_left_out( env ):
    """Pocholo's probe at the replay door: the frozen run reads the answer the live run kept."""
    need = "read an RSS feed [cand-cached-gap]"
    small = FakeStage( ids=[ MATH_ID, FEEDS_ID ] )
    small.K = 64                                                                              # another K, so the second lookup gets a receipt of its own
    rt.check_exists_impl( need, ctx_with( env, PackedFake( need, { FEEDS_TEXT: HIT } ), small ) )          # warm: the feeds and math answers are cached
    resent = ctx_with( env, PackedFake( need, { FEEDS_TEXT: HIT }, omit=[ FEEDS_TEXT ] ), FakeStage( ids=[ MATH_ID, FEEDS_ID, SERVE_ID ] ) )
    r      = rt.check_exists_impl( need, resent )                                             # the serve entry is new, so the whole pack goes again, without feeds
    assert r[ "verdict" ] == "REUSE" and receipt_of( env, r )[ "stats" ][ "failed_attempts" ] == []
    out = rt.replay_impl( r[ "receipt_id" ], resent )
    assert out[ "status" ] == "ok" and out[ "frozen" ][ "verdict" ] == "REUSE" and out[ "differences" ][ "frozen" ] == []


def test_two_lookups_that_differ_only_in_their_shortlist_get_different_receipt_ids( env ):
    need = "read an RSS feed [cand-ids]"
    a    = rt.check_exists_impl( need, ctx_with( env, PackedFake( need ), FakeStage( ids=[ MATH_ID, FEEDS_ID ] ) ) )
    b    = rt.check_exists_impl( need, ctx_with( env, PackedFake( need ), FakeStage( ids=[ MATH_ID, FEEDS_ID, SERVE_ID ] ) ) )
    assert a[ "receipt_id" ] != b[ "receipt_id" ] and receipt_of( env, a )[ "candidate_stage" ][ "ids" ] != receipt_of( env, b )[ "candidate_stage" ][ "ids" ]
    again = rt.check_exists_impl( need, ctx_with( env, PackedFake( need ), FakeStage( ids=[ FEEDS_ID, MATH_ID ] ) ) )
    assert again[ "receipt_id" ] == a[ "receipt_id" ]                                          # the same shortlist in another order is the same receipt


def test_two_lookups_with_shortlists_of_one_size_and_different_ids_get_different_receipt_ids( env ):
    need = "read an RSS feed [cand-ids-same-size]"
    a    = rt.check_exists_impl( need, ctx_with( env, PackedFake( need ), FakeStage( ids=[ MATH_ID, FEEDS_ID ] ) ) )
    b    = rt.check_exists_impl( need, ctx_with( env, PackedFake( need ), FakeStage( ids=[ MATH_ID, SERVE_ID ] ) ) )
    assert len( receipt_of( env, a )[ "candidate_stage" ][ "ids" ] ) == len( receipt_of( env, b )[ "candidate_stage" ][ "ids" ] ) == 2
    assert a[ "receipt_id" ] != b[ "receipt_id" ]                                              # a count-only hash would give the same id here


def _stored( env, r, edit ):
    """Ensures: returns the stored receipt dict, edited by `edit`, and the path it was read from."""
    path = next( ( env[ 1 ] / "receipts" ).glob( f"{r[ 'receipt_id' ]}*.json" ) )
    rec  = json.loads( path.read_text( encoding="utf-8" ) )
    edit( rec )
    return rec, path


def test_a_candidate_receipt_made_before_the_ids_hash_is_refused_by_name_and_not_loaded( env ):
    need = "read an RSS feed [cand-old-id]"
    ctx  = ctx_with( env, PackedFake( need ), FakeStage() )
    r    = rt.check_exists_impl( need, ctx )
    rec, path = _stored( env, r, lambda rec: None )
    old = rt.receipt_id( rec[ "tool" ], rec[ "query" ], rec[ "index_sha" ], rec[ "model" ], rec[ "policy" ], rec[ "prompt_template_hash" ], rec[ "causes" ],
                         rec[ "tool_version" ], rec[ "request_shape" ], False, None, None,
                         { "manifest_hash": rec[ "candidate_stage" ][ "manifest_hash" ], "K": rec[ "candidate_stage" ][ "K" ] } )     # the id before the ids hash
    rec[ "id" ] = old
    ( path.parent / f"{old}.json" ).write_text( json.dumps( rec, sort_keys=True ), encoding="utf-8" )
    with pytest.raises( rt.ReuseError, match="RECEIPT_ID_MISMATCH" ): rt.load_receipt( ctx, old )
    assert rt.replay_impl( old, ctx )[ "error" ] == "RECEIPT_ID_MISMATCH"


def test_a_candidate_stage_block_with_no_ids_is_a_named_corrupt_receipt_not_a_crash( env ):
    need = "read an RSS feed [cand-no-ids]"
    ctx  = ctx_with( env, PackedFake( need ), FakeStage() )
    r    = rt.check_exists_impl( need, ctx )
    rec, path = _stored( env, r, lambda rec: rec[ "candidate_stage" ].pop( "ids" ) )
    path.write_text( json.dumps( rec, sort_keys=True ), encoding="utf-8" )
    with pytest.raises( rt.ReuseError, match="RECEIPT_CORRUPT" ): rt.load_receipt( ctx, r[ "receipt_id" ] )
    assert rt.replay_impl( r[ "receipt_id" ], ctx )[ "error" ] == "RECEIPT_CORRUPT"
