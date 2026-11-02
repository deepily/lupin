"""
The control's scored report: labels, ranks, figures, the pass mark and the stop.
"""
import hashlib
import json
import pathlib

import pytest

import cosa.utils.util as cu
from lupin_mcp.reuse_needset import control_report as cr
from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import positive_control as pc
from tests.unit.test_reuse_needset_first_thousand import real_pair

REAL_RUN = pathlib.Path( cu.get_project_root() + "/io/semdup-labelling/2026.10.25-run5" )


def lab( item, choice, reviewer ):
    """Return one label row."""
    return { "item_id": item, "choice": choice, "note": "", "reviewer": reviewer, "symbols": [], "ts": "2026-10-30T00:00:00+00:00" }


def label_world( tmp_path ):
    """
    Write a key and three label files for four pairs; return ( pairs, labels dir, key path ).

    Pair 0 both reviewers call the same job, pair 1 both call it different. Pair 2 is disputed and the third rater says different; pair 3 is disputed and the third rater says same.
    """
    pairs = [ real_pair( i ) for i in range( 4 ) ]
    key   = { "items": { f"pair-{i}": { "a": p[ "rewrite" ][ "id" ], "b": p[ "original" ][ "id" ], "kind": "planted" } for i, p in enumerate( pairs ) } }
    ( tmp_path / "key.json" ).write_text( json.dumps( key ), encoding="utf-8" )
    first, second, third = ( [ "AS_PROPOSED", "NONE", "AS_PROPOSED", "NONE" ], [ "AS_PROPOSED", "NONE", "NONE", "AS_PROPOSED" ], { 2: "NONE", 3: "AS_PROPOSED" } )
    write = lambda name, rows: ( tmp_path / name ).write_text( "".join( json.dumps( r ) + "\n" for r in rows ), encoding="utf-8" )
    write( "labels-rick.jsonl", [ lab( f"pair-{i}", c, "rick" ) for i, c in enumerate( first ) ] )
    write( "labels-reviewer-2.jsonl", [ lab( f"pair-{i}", c, "reviewer-2" ) for i, c in enumerate( second ) ] )
    write( "labels-jason.jsonl", [ lab( f"pair-{i}", c, "jason" ) for i, c in third.items() ] )
    return pairs, tmp_path, tmp_path / "key.json"


def test_agreeing_reviewers_decide_and_the_third_rater_settles_each_dispute_and_the_label_files_are_named_by_hash( tmp_path ):
    pairs, folder, key = label_world( tmp_path )
    got = cr.same_job_labels( pairs, folder, key, expected_not_same=frozenset( ( "d-rew01", "d-rew02" ) ) )
    assert got[ "same_job" ] == { "d-rew00": True, "d-rew01": False, "d-rew02": False, "d-rew03": True }
    assert sorted( got[ "label_shas" ] ) == sorted( cr.LABEL_FILES ) and got[ "label_shas" ][ "labels-jason.jsonl" ] == hashlib.sha256( ( folder / "labels-jason.jsonl" ).read_bytes() ).hexdigest()
    assert got[ "answer_key_sha" ] == cr.file_sha( key ) and len( got[ "answer_key_sha" ] ) == 64


def test_a_not_the_same_job_set_that_is_not_the_pinned_one_is_refused_by_name_with_both_sets( tmp_path ):
    pairs, folder, key = label_world( tmp_path )
    with pytest.raises( er.NeedsetError ) as caught: cr.same_job_labels( pairs, folder, key, expected_not_same=frozenset( ( "d-rew01", ) ) )
    assert caught.value.code == er.CONTROL_LABELS_CHANGED and "d-rew02" in caught.value.detail and "expected ['d-rew01']" in caught.value.detail


@pytest.mark.skipif( not ( REAL_RUN / "packets" / "labels-jason.jsonl" ).is_file(), reason="the proof's label files are not on this host" )
def test_the_real_labels_give_exactly_the_five_pinned_pairs_as_a_different_job_and_fifteen_as_the_same():
    pairs = pc.load_pairs( str( REAL_RUN / "key" / "planted.json" ) )
    got   = cr.same_job_labels( pairs, str( REAL_RUN / "packets" ), str( REAL_RUN / "key" / "answer-key.json" ) )
    assert sorted( i for i, same in got[ "same_job" ].items() if not same ) == sorted( cr.NOT_SAME_JOB ) and sum( got[ "same_job" ].values() ) == 15 and len( cr.NOT_SAME_JOB ) == 5


def test_word_overlap_is_shared_words_over_all_words_and_zero_when_there_are_none():
    assert cr.content_words( "A Function that Tears-down the widget, 2 times" ) == { "function", "that", "tears", "down", "the", "widget", "times" }
    assert cr.word_overlap( "tears down the widget", "tears down a slider" ) == round( 2 / 5, 3 ) and cr.word_overlap( "", "" ) == 0.0 and cr.word_overlap( "alpha beta", "gamma delta" ) == 0.0


def test_a_place_is_one_based_and_none_for_an_absent_or_unnamed_entry():
    assert cr.position( [ "a", "b", "c" ], "c" ) == 3 and cr.position( [ "a" ], "z" ) is None and cr.position( [ "a" ], None ) is None


def answer_of( vector, code=( ), prose=( ), extra=( ) ):
    """Return a search answer whose three lists are whole."""
    return { "lists": { "code": list( code ), "prose": list( prose ), "vector_concat": list( vector ) } }


def test_ranks_come_from_the_whole_lists_and_the_merged_list_is_read_to_its_end():
    filler = [ f"f{i}" for i in range( 200 ) ]
    answer = answer_of( [ *filler, "plant" ], code=[ "plant", "x" ], prose=[ ] )
    got    = cr.ranks_of( answer, "plant" )
    assert got[ "code" ] == 1 and got[ "prose" ] is None and got[ "vector_concat" ] == 201 and got[ "fused" ] == 1, "the merged list puts the id two lists agree on first, however deep one of them has it"
    assert cr.ranks_of( answer, "f0" )[ "fused" ] == 2 and cr.ranks_of( answer, None ) == { "code": None, "prose": None, "vector_concat": None, "fused": None }
    deep = answer_of( [ *filler, *[ f"g{i}" for i in range( 400 ) ], "late" ] )
    assert cr.ranks_of( deep, "late" )[ "vector_concat" ] == 601 and cr.ranks_of( deep, "late" )[ "fused" ] is None, "an id past the fusion depth in every list is not in the merged list at all"


def receipt( asked, rated ):
    """Return a receipt that asked the first ids and rated the second ones relevant."""
    return { "id": "r", "candidate_stage": { "ids": sorted( asked ), "widened_ids": [] }, "shortlist": [ { "id": i } for i in rated ] }


def row_of( i, same, plant_asked, plant_rated, orig_asked=True, orig_rated=True, line="Does the work." ):
    """Return a pair row for pair i with the plant and the original judged as given."""
    pair, asked, rated = real_pair( i ), [ ], [ ]
    rid, oid = pair[ "rewrite" ][ "id" ], f"orig-{i}"
    if plant_asked: asked.append( rid )
    if plant_rated: rated.append( rid )
    if orig_asked: asked.append( oid )
    if orig_rated: rated.append( oid )
    return cr.pair_row( pair, same, "tears down the widget", receipt( asked, rated ), answer_of( [ rid, oid ] ), line, oid, "A line that tears down." )


def test_a_pair_row_says_where_each_side_was_lost_and_names_the_leak_for_the_plants_line_and_the_originals():
    row = row_of( 0, True, True, False )
    assert row[ "rewrite" ] == "d-rew00" and row[ "lang" ] == "py" and row[ "same_job" ] is True and row[ "drafted" ] is True and row[ "purpose_line" ] == "Does the work."
    assert row[ "plant" ][ "retrieved" ] is True and row[ "plant" ][ "accepted" ] is False and row[ "original" ][ "retrieved" ] is True and row[ "original" ][ "accepted" ] is True
    assert row[ "plant" ][ "ranks" ][ "vector_concat" ] == 1 and row[ "original" ][ "id" ] == "orig-0" and row[ "original" ][ "ranks" ][ "vector_concat" ] == 2
    assert row[ "leak" ] == { "plant": cr.word_overlap( "tears down the widget", "Does the work." ), "original": cr.word_overlap( "tears down the widget", "A line that tears down." ) }
    lost = row_of( 1, True, False, True, orig_asked=False, line=None )
    assert lost[ "plant" ][ "accepted" ] is False, "rated relevant without being asked is not accepted"
    assert lost[ "leak" ] == { "plant": None, "original": cr.word_overlap( "tears down the widget", "A line that tears down." ) }
    bare = cr.pair_row( real_pair( 2 ), True, "need", receipt( [ ], [ ] ), answer_of( [ ] ), None, None, None )
    assert bare[ "original" ][ "id" ] is None and bare[ "leak" ] == { "plant": None, "original": None } and bare[ "original" ][ "ranks" ][ "fused" ] is None


def test_the_figures_count_each_stage_and_the_wilson_interval_and_the_pass_mark_compares_plants_with_their_own_originals():
    rows = [ row_of( 0, True, True, True ), row_of( 1, True, True, False ), row_of( 2, True, False, False ), row_of( 3, True, False, False, orig_asked=False, orig_rated=False ) ]
    got  = cr.figures( rows, 2 )
    assert got[ "drafted" ] == 4 and got[ "undrafted" ] == 2 and got[ "retrieval" ][ "k" ] == 2 and got[ "retrieval" ][ "n" ] == 4
    assert got[ "judge" ][ "k" ] == 1 and got[ "judge" ][ "n" ] == 2 and got[ "end_to_end" ][ "k" ] == 1 and got[ "end_to_end" ][ "n" ] == 4
    assert got[ "itt_retrieved" ][ "k" ] == 2 and got[ "itt_retrieved" ][ "n" ] == 6 and got[ "itt_end_to_end" ][ "n" ] == 6
    assert got[ "originals_retrieved" ][ "k" ] == 3 and got[ "originals_accepted" ][ "k" ] == 3
    assert got[ "retrieval" ][ "interval" ] == cr.wilson( 2, 4 ) and 0.0 < got[ "retrieval" ][ "interval" ][ 0 ] < 0.5 < got[ "retrieval" ][ "interval" ][ 1 ] < 1.0
    assert got[ "pass_mark" ] == { "a": 1, "b": 0, "slack": 2, "passed": True } and got[ "pass_mark_end_to_end" ] == { "a": 2, "b": 0, "slack": 2, "passed": True }
    empty = cr.figures( [ ], 3 )
    assert empty[ "retrieval" ] == { "k": 0, "n": 0, "interval": ( None, None ) } and empty[ "pass_mark" ][ "passed" ] is True and empty[ "itt_retrieved" ][ "n" ] == 3


def test_the_pass_mark_fails_when_the_originals_beat_the_plants_by_more_than_two_and_passes_at_exactly_two():
    rows = lambda n: [ row_of( i, True, False, False ) for i in range( n ) ]
    assert cr.figures( rows( 2 ), 0 )[ "pass_mark" ] == { "a": 2, "b": 0, "slack": 2, "passed": True } and cr.figures( rows( 3 ), 0 )[ "pass_mark" ][ "passed" ] is False
    mixed = [ *rows( 3 ), row_of( 3, True, True, True, orig_asked=False, orig_rated=False ) ]
    assert cr.figures( mixed, 0 )[ "pass_mark" ] == { "a": 3, "b": 1, "slack": 2, "passed": True }, "a plant found where its original was not offsets one loss"


def test_the_scored_report_splits_the_populations_counts_every_undrafted_pair_and_stops_only_on_the_originals():
    same_job = { "d-rew00": True, "d-rew01": True, "d-rew02": False, "d-rew03": False, "d-rew04": True }
    rows     = [ row_of( 0, True, True, True ), row_of( 1, True, False, False ), row_of( 2, False, True, True ), row_of( 3, False, False, False ) ]
    gone     = [ { "pair": "d-rew04", "seed": "d-orig04", "reason": "NEED_LEAKS_KEY", "tries": 4, "history": [ { "try": 0, "words": [ "toolbar" ] } ] } ]
    out      = cr.scored( rows, gone, same_job )
    assert out[ "primary" ][ "drafted" ] == 2 and out[ "primary" ][ "undrafted" ] == 1 and out[ "secondary" ][ "drafted" ] == 2 and out[ "secondary" ][ "undrafted" ] == 0
    assert out[ "primary" ][ "itt_retrieved" ] == cr.count( 1, 3 ) and out[ "false_positives" ] == 1
    assert out[ "rows" ][ -1 ] == { "rewrite": "d-rew04", "same_job": True, "drafted": False, "reason": "NEED_LEAKS_KEY", "history": [ { "try": 0, "words": [ "toolbar" ] } ] } and len( out[ "rows" ] ) == 5
    assert out[ "stop" ] is False and out[ "originals_floor" ] == { "floor": 0.57, "rate": 1.0, "n": 4 }
    broken = cr.scored( [ row_of( i, True, True, True, orig_asked=False, orig_rated=False ) for i in range( 3 ) ], [ ], { f"d-rew0{i}": True for i in range( 3 ) } )
    assert broken[ "stop" ] is True and broken[ "originals_floor" ][ "rate" ] == 0.0, "the originals falling under the floor means the needs broke"
    edge = cr.scored( [ *[ row_of( i, True, False, False ) for i in range( 4 ) ], *[ row_of( i, True, False, False, orig_asked=False, orig_rated=False ) for i in range( 4, 7 ) ] ], [ ], { f"d-rew0{i}": True for i in range( 7 ) } )
    assert edge[ "originals_floor" ][ "rate" ] == 4 / 7 and edge[ "stop" ] is False, "4 of 7 is above 0.57 and a plant miss alone never stops"
    none = cr.scored( [ ], [ ], { } )
    assert none[ "stop" ] is True and none[ "originals_floor" ][ "n" ] == 0
