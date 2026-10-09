"""
The end-to-end run's frozen inputs and the reading of one search.

The sample test reads the shipped fixture file itself and pins its hash to a literal.
Nothing here sends a request.
"""
import hashlib
import json
import pathlib

import pytest

from lupin_mcp import reuse_e2e as e2e

FIXTURE = pathlib.Path( __file__ ).resolve().parent.parent / "fixtures" / "reuse_e2e" / "sample-by-component-58-42-seed-20261007.json"
LITERAL = "5b6d84fc2dd8dc458b36255e129001f55e3fbe4d252c14c6d65a4994779a91fd"


def sha_of( text ): return hashlib.sha256( text.encode( "utf-8" ) ).hexdigest()


def write( path, record ):
    text = json.dumps( record, sort_keys=True )
    path.write_text( text, encoding="utf-8" )
    return sha_of( text )


def sample_record( exact=58, near=42 ):
    return { "strata": { "has_exact_cluster": { "members": [ f"pkg.exact{i:03d}" for i in range( exact ) ] },
                         "near_only"        : { "members": [ f"pkg.near{i:03d}" for i in range( near ) ] } } }


def test_the_shipped_sample_file_has_the_recorded_hash_and_loads_in_the_frozen_order():
    assert e2e.SAMPLE_SHA256 == LITERAL
    assert hashlib.sha256( FIXTURE.read_bytes() ).hexdigest() == LITERAL
    members = e2e.load_sample( FIXTURE )
    assert len( members ) == 100 and len( set( members ) ) == 100
    first = json.loads( FIXTURE.read_text( encoding="utf-8" ) )[ "strata" ][ "has_exact_cluster" ][ "members" ]
    assert members[ :58 ] == first and len( first ) == 58                                           # exact-cluster members first, then the near-only 42


def test_a_sample_whose_hash_is_not_the_recorded_one_is_refused( tmp_path ):
    other = tmp_path / "sample.json"
    write( other, sample_record() )
    with pytest.raises( e2e.FrozenInputRefused, match="sha256" ): e2e.load_sample( other )


def test_a_sample_with_the_wrong_stratum_sizes_or_a_repeated_member_is_refused( tmp_path ):
    path = tmp_path / "sample.json"
    sha  = write( path, sample_record( 57, 43 ) )
    with pytest.raises( e2e.FrozenInputRefused, match="58 and 42" ): e2e.load_sample( path, sha )
    rec = sample_record()
    rec[ "strata" ][ "near_only" ][ "members" ][ 0 ] = rec[ "strata" ][ "has_exact_cluster" ][ "members" ][ 0 ]
    sha = write( path, rec )
    with pytest.raises( e2e.FrozenInputRefused, match="repeated" ): e2e.load_sample( path, sha )


def needs_record( members, **over ):
    return { "format": "reuse-e2e-needs-1", "sample_sha256": LITERAL, "needs": [ { "member": m, "need": f"A function number {i} that returns a value.", "writer_job_id": f"job-{i}" } for i, m in enumerate( members ) ], **over }


def test_the_needs_file_must_match_the_sample_members_in_the_same_order( tmp_path ):
    members = e2e.load_sample( FIXTURE )
    path    = tmp_path / "needs.json"
    sha     = write( path, needs_record( members ) )
    got     = e2e.load_needs( path, sha, members, LITERAL )
    assert [ g[ "member" ] for g in got ] == members and all( g[ "need" ] for g in got ) and len( got ) == 100
    swapped = list( members ); swapped[ 0 ], swapped[ 1 ] = swapped[ 1 ], swapped[ 0 ]
    sha = write( path, needs_record( swapped ) )
    with pytest.raises( e2e.FrozenInputRefused, match="order" ): e2e.load_needs( path, sha, members, LITERAL )
    sha = write( path, needs_record( members[ :99 ] ) )
    with pytest.raises( e2e.FrozenInputRefused, match="100" ): e2e.load_needs( path, sha, members, LITERAL )


def test_the_needs_file_is_refused_for_a_wrong_hash_a_wrong_format_or_an_empty_need( tmp_path ):
    members = e2e.load_sample( FIXTURE )
    path    = tmp_path / "needs.json"
    sha     = write( path, needs_record( members ) )
    with pytest.raises( e2e.FrozenInputRefused, match="sha256" ): e2e.load_needs( path, "0" * 64, members, LITERAL )
    sha = write( path, needs_record( members, format="other" ) )
    with pytest.raises( e2e.FrozenInputRefused, match="format" ): e2e.load_needs( path, sha, members, LITERAL )
    rec = needs_record( members )
    rec[ "needs" ][ 5 ][ "need" ] = "   "
    sha = write( path, rec )
    with pytest.raises( e2e.FrozenInputRefused, match="empty need" ): e2e.load_needs( path, sha, members, LITERAL )


def test_twins_are_read_from_the_manifest_after_its_hash_is_checked( tmp_path ):
    path = tmp_path / "manifest.json"
    sha  = write( path, { "exact": [ { "members": [ { "id": "a" }, { "id": "b" }, { "id": "c" } ] } ], "near": [ { "members": [ { "id": "c" }, { "id": "d" } ] } ] } )
    assert e2e.load_twins( path, sha ) == { "a": { "b", "c" }, "b": { "a", "c" }, "c": { "a", "b", "d" }, "d": { "c" } }
    with pytest.raises( e2e.FrozenInputRefused, match="sha256" ): e2e.load_twins( path, "1" * 64 )


def hit( *ids ): return [ { "id": i, "p_overlap": 0.9 } for i in ids ]


def test_a_search_is_read_as_on_the_shortlist_ranked_first_and_in_the_top_ten():
    twins  = { "t1", "t2" }
    result = { "verdict": "REUSE", "shortlist": hit( "x", "t1" ), "nearest": hit( "x", "t1", "y" ) }
    assert e2e.read_search( result, twins ) == { "verdict": "REUSE", "on_shortlist": True, "ranked_first": False, "top_ten": True }
    result = { "verdict": "NEW", "shortlist": [], "nearest": hit( "t2", "x" ) }
    assert e2e.read_search( result, twins ) == { "verdict": "NEW", "on_shortlist": False, "ranked_first": True, "top_ten": True }
    result = { "verdict": "NEW", "shortlist": [], "nearest": [] }
    assert e2e.read_search( result, twins ) == { "verdict": "NEW", "on_shortlist": False, "ranked_first": False, "top_ten": False }


def stats( **over ): return { "failed": 0, "not_checked": 0, "stopped_by": None, **over }


def result_of( **over ): return { "status": "ok", "malformed": [], "stats": stats(), **over }


def test_a_search_is_complete_only_when_nothing_failed_nothing_was_left_unasked_and_nothing_was_malformed():
    assert e2e.incomplete_causes( result_of(), False, False ) == []
    assert e2e.incomplete_causes( result_of( stats=stats( failed=2 ) ), False, False ) == [ "CALL_FAILED" ]
    assert e2e.incomplete_causes( result_of( malformed=[ { "id": "x", "reason": "r" } ] ), False, False ) == [ "MALFORMED_ANSWER" ]


def test_the_ceiling_the_ledger_and_the_calls_are_four_reasons_that_never_fold_together():
    left = result_of( stats=stats( not_checked=7 ) )
    assert e2e.incomplete_causes( left, True, False ) == [ "ceiling" ]
    assert e2e.incomplete_causes( left, False, True ) == [ "ledger" ]
    assert e2e.incomplete_causes( left, True, True ) == [ "ceiling", "ledger" ]
    both = result_of( stats=stats( not_checked=7, failed=1 ), malformed=[ { "id": "x", "reason": "r" } ] )
    assert e2e.incomplete_causes( both, True, False ) == [ "ceiling", "CALL_FAILED", "MALFORMED_ANSWER" ]


def test_entries_left_unasked_for_no_named_reason_are_named_attempts_and_a_breaker_stop_names_itself():
    assert e2e.incomplete_causes( result_of( stats=stats( not_checked=3 ) ), False, False ) == [ "attempts" ]
    assert e2e.incomplete_causes( result_of( stats=stats( not_checked=3, stopped_by="consecutive_422" ) ), False, False ) == [ "consecutive_422" ]


def test_an_error_result_is_incomplete_with_its_own_name():
    assert e2e.incomplete_causes( { "status": "error", "error": "UNKNOWN_ENTRY" }, False, False ) == [ "ERROR:UNKNOWN_ENTRY" ]


def test_the_wilson_interval_and_the_exact_mcnemar_p_match_hand_computed_values():
    lo, hi = e2e.wilson( 50, 100 )
    assert round( lo, 4 ) == 0.4038 and round( hi, 4 ) == 0.5962
    assert e2e.wilson( 0, 0 ) == ( None, None )
    assert e2e.wilson( 100, 100 )[ 1 ] == 1.0
    assert e2e.mcnemar_exact( 0, 0 ) == 1.0
    assert e2e.mcnemar_exact( 5, 0 ) == 0.0625
    assert e2e.mcnemar_exact( 3, 3 ) == 1.0
    assert round( e2e.mcnemar_exact( 9, 2 ), 6 ) == 0.065430


def test_a_file_with_the_right_hash_that_is_not_json_is_refused( tmp_path ):
    path = tmp_path / "sample.json"
    path.write_text( "not json", encoding="utf-8" )
    with pytest.raises( e2e.FrozenInputRefused, match="not JSON" ): e2e.load_sample( path, sha_of( "not json" ) )


def search( member, question, status="complete", hit=False, tokens=0 ):
    return { "member": member, "question": question, "status": status, "causes": [] if status == "complete" else [ "CALL_FAILED" ], "tokens": tokens, "requests": 1, "unasked": 0,
             "n429": 0, "n529": 0, "read": { "verdict": "NEW", "on_shortlist": hit, "ranked_first": hit, "top_ten": hit } }


def test_an_incomplete_search_with_the_twin_on_its_answered_shortlist_still_counts_as_a_miss():
    rows = [ search( "a", "old", "incomplete", hit=True ), search( "b", "old", hit=True ) ]
    fig  = e2e.figures( rows, [ "old" ] )[ "old" ]
    assert fig[ "on_shortlist" ][ "k" ] == 1 and fig[ "on_shortlist" ][ "n" ] == 2 and fig[ "on_shortlist_complete" ][ "k" ] == 1 and fig[ "on_shortlist_complete" ][ "n" ] == 1
    assert e2e.paired( rows + [ search( "a", "new" ), search( "b", "new" ) ], "old", "new" )[ "on_shortlist" ][ "only_old" ] == 1       # a is a miss for old, so b alone is old-only


def test_the_cost_of_a_search_is_the_tokens_over_the_searches_run_at_the_pinned_price():
    rows = [ search( "a", "old", tokens=1_000_000 ), search( "b", "old", tokens=1_000_000 ) ]
    assert e2e.figures( rows, [ "old" ] )[ "old" ][ "usd_per_search" ] == pytest.approx( 0.042 )
    assert e2e.figures( [], [ "old" ] )[ "old" ][ "usd_per_search" ] is None


def test_the_paired_comparison_leaves_out_a_member_whose_search_was_not_run():
    rows = [ search( "a", "old", hit=True ), search( "a", "new", "not_run" ), search( "b", "old", hit=True ), search( "b", "new", hit=False ) ]
    pair = e2e.paired( rows, "old", "new" )[ "on_shortlist" ]
    assert pair == { "only_old": 1, "only_new": 0, "both": 0, "neither": 0, "p": 1.0 }                                  # only b is counted


def need_check_document( sample_sha, needs ):
    """The writer's document, copied from needs_document in test_reuse_need_check.py (4384a96c9)."""
    return { "format": e2e.NEEDS_FORMAT, "sample_sha256": sample_sha,
             "needs": [ { "member": i, "need": n, "kind": "function", "writer_job_id": "j-" + str( k ), "attempts": 1, "rewrites": 0 } for k, ( i, n ) in enumerate( needs.items() ) ] }


def test_a_document_in_the_writers_shape_loads_with_its_sample_hash_checked( tmp_path ):
    members = e2e.load_sample( FIXTURE )
    path    = tmp_path / "needs.json"
    sha     = write( path, need_check_document( LITERAL, { m: f"A function number {i} that does a thing." for i, m in enumerate( members ) } ) )
    got     = e2e.load_needs( path, sha, members, LITERAL )
    assert len( got ) == 100 and got[ 0 ] == { "member": members[ 0 ], "need": "A function number 0 that does a thing." }


def test_a_needs_document_written_for_another_sample_or_naming_none_is_refused( tmp_path ):
    members = e2e.load_sample( FIXTURE )
    path    = tmp_path / "needs.json"
    needs   = { m: f"A function number {i} that does a thing." for i, m in enumerate( members ) }
    sha     = write( path, need_check_document( "1" * 64, needs ) )
    with pytest.raises( e2e.FrozenInputRefused, match="sample_sha256" ): e2e.load_needs( path, sha, members, LITERAL )
    record = need_check_document( LITERAL, needs )
    del record[ "sample_sha256" ]
    sha = write( path, record )
    with pytest.raises( e2e.FrozenInputRefused, match="sample_sha256" ): e2e.load_needs( path, sha, members, LITERAL )
