"""
The proof's label loader, end to end on a synthetic full label set.

Packets and the key come from label_prep.prepare, the labels from the page's own writer, and the result goes into proof_run.
"""
import hashlib
import json
import pathlib

import pytest

from cosa.repo.labelling import packets as pk
from cosa.repo.labelling import pair_labels as pl
from cosa.repo.semdup.proof import label_load as ll
from cosa.repo.semdup.proof import label_prep as lp
from cosa.repo.semdup.proof import proof_run as pr
from tests.unit.test_semdup_proof_run import Toy

CLOCK = lambda: "2026-10-26T21:00:00+00:00"


@pytest.fixture
def run( tmp_path ):
    """Prepare packets and a key for the toy's known pairs; return ( toy, packets, key path )."""
    toy  = Toy( tmp_path )
    mono = { "defs": toy.spec[ "monolith_defs" ], "pairs": toy.spec[ "monolith_pairs" ], "blob": "blob" }
    made = lp.prepare( toy.spec[ "planted" ], mono, [ "rick", "second" ], 3, tmp_path / "run", "sha" )
    return toy, { r: pk.packet_path( tmp_path / "run" / "packets", r ) for r in made[ "packets" ] }, made[ "key" ]


def answer( packets, key, reviewer, truth, flip=() ):
    """Label a reviewer's whole packet from { pair key: bool }, flipping the keys named."""
    rows = ll.key_rows( key )
    for item in pl.load_items( packets[ reviewer ] ):
        k    = pr.label_key( rows[ item[ "item_id" ] ][ "a" ], rows[ item[ "item_id" ] ][ "b" ] )
        pl.save_label( packets[ reviewer ], item[ "item_id" ], truth[ k ] != ( k in flip ), clock=CLOCK )


def truth_of( toy ):
    """The toy's hand labels for its six known pairs."""
    every = toy.all_labels()
    return { k: v for k, v in every.items() if k != toy.key( "r1", "d3" ) }


def test_one_reviewers_labels_come_out_as_pair_keys_the_proof_uses( run ):
    toy, packets, key = run
    truth = truth_of( toy )
    answer( packets, key, "rick", truth )
    assert ll.pair_key_labels( pl.labels_path( packets[ "rick" ] ), key ) == truth


def test_two_agreeing_reviewers_feed_proof_run_to_a_complete_record( run, tmp_path ):
    toy, packets, key = run
    truth = truth_of( toy )
    for r in packets: answer( packets, key, r, truth )
    labels = ll.resolved_labels( pl.labels_path( packets[ "rick" ] ), pl.labels_path( packets[ "second" ] ), key )
    assert labels == truth
    toy.spec[ "labels" ] = { **labels, toy.key( "r1", "d3" ): False }
    record = pr.proof_run( toy.spec, toy.wiring )
    assert record[ "status" ] == "complete" and record[ "counts" ][ "true_pairs" ] == 5 and "owed" not in record


def test_a_disagreement_is_refused_until_it_has_a_ruling_and_then_takes_it( run ):
    toy, packets, key = run
    truth, odd = truth_of( toy ), toy.key( "m1", "m5" )
    answer( packets, key, "rick", truth )
    answer( packets, key, "second", truth, flip=( odd, ) )
    paths = ( pl.labels_path( packets[ "rick" ] ), pl.labels_path( packets[ "second" ] ), key )
    with pytest.raises( ValueError, match="1 disagreements have no ruling: " + odd.replace( "|", r"\|" ) ): ll.resolved_labels( *paths )
    assert ll.resolved_labels( *paths, rulings={ odd: True } )[ odd ] is True


def test_a_pair_one_reviewer_has_not_labelled_is_named_and_nothing_is_guessed( run ):
    toy, packets, key = run
    truth = truth_of( toy )
    answer( packets, key, "rick", truth )
    second = packets[ "second" ]
    item   = pl.load_items( second )[ 0 ][ "item_id" ]
    pl.save_label( second, item, True, clock=CLOCK )
    with pytest.raises( ValueError, match="5 pairs are not labelled by both reviewers" ):
        ll.resolved_labels( pl.labels_path( packets[ "rick" ] ), pl.labels_path( second ), key )


def test_labels_for_an_item_the_key_does_not_know_are_refused( run, tmp_path ):
    toy, packets, key = run
    answer( packets, key, "rick", truth_of( toy ) )
    stripped = tmp_path / "key.json"
    rows = json.loads( open( key ).read() )
    rows[ "items" ].pop( next( iter( rows[ "items" ] ) ) )
    stripped.write_text( json.dumps( rows ) )
    with pytest.raises( ValueError, match="the key does not know" ): ll.pair_key_labels( pl.labels_path( packets[ "rick" ] ), stripped )


# ---- the third rater ---------------------------------------------------------------------------------------------

def item_of( key, pair ):
    """Return the item id the key gives a pair key."""
    return next( i for i, r in ll.key_rows( key ).items() if pr.label_key( r[ "a" ], r[ "b" ] ) == pair )


def third_packet( packets, key, truth, odd, same, unsure=False ):
    """Export and label the third rater's packet of the disputed pair; return the label paths."""
    first, second = ( pl.labels_path( packets[ r ] ) for r in ( "rick", "second" ) )
    path = pk.export_subset_packet( packets[ "rick" ].parent, ll.disputed_items( first, second ), "third", 3 )
    pl.save_label( path, item_of( key, odd ), same, unsure=unsure, note="leaning" if unsure else "", clock=CLOCK )
    return first, second, pl.labels_path( path )


@pytest.fixture
def disputed( run ):
    """Rick and the second reviewer disagree on one pair; return ( run, truth, the pair key )."""
    toy, packets, key = run
    truth, odd = truth_of( toy ), toy.key( "m1", "m5" )
    answer( packets, key, "rick", truth )
    answer( packets, key, "second", truth, flip=( odd, ) )
    return ( toy, packets, key ), truth, odd


def test_the_disputed_items_are_the_ones_both_reviewers_labelled_differently( disputed ):
    ( toy, packets, key ), truth, odd = disputed
    first, second = ( pl.labels_path( packets[ r ] ) for r in ( "rick", "second" ) )
    assert ll.disputed_items( first, second ) == [ item_of( key, odd ) ]


@pytest.mark.parametrize( "same", [ True, False ] )
def test_a_sure_third_label_settles_the_dispute_by_majority_even_against_a_ruling( disputed, same ):
    ( toy, packets, key ), truth, odd = disputed
    first, second, third = third_packet( packets, key, truth, odd, same )
    labels = ll.resolved_labels( first, second, key, rulings={ odd: not same }, third_path=third )
    assert labels[ odd ] is same and { k: v for k, v in labels.items() if k != odd } == { k: v for k, v in truth.items() if k != odd }


def test_an_unsure_third_label_is_no_majority_and_falls_to_ricks_ruling( disputed ):
    ( toy, packets, key ), truth, odd = disputed
    first, second, third = third_packet( packets, key, truth, odd, True, unsure=True )
    assert ll.third_votes( third, key ) == { odd: None }
    with pytest.raises( ValueError, match="1 disagreements have no ruling" ): ll.resolved_labels( first, second, key, third_path=third )
    assert ll.resolved_labels( first, second, key, rulings={ odd: False }, third_path=third )[ odd ] is False


def test_a_third_file_that_labels_a_pair_not_in_dispute_is_refused( disputed ):
    ( toy, packets, key ), truth, odd = disputed
    first, second, third = third_packet( packets, key, truth, odd, True )
    other = next( k for k in truth if k != odd )
    line  = json.loads( third.read_text().splitlines()[ 0 ] )
    with open( third, "a" ) as f: f.write( json.dumps( { **line, "item_id": item_of( key, other ) } ) + "\n" )
    with pytest.raises( ValueError, match="labelled 1 pairs that are not disputed: " + other.replace( "|", r"\|" ) ):
        ll.resolved_labels( first, second, key, third_path=third )


def test_a_third_file_that_misses_a_disputed_pair_is_refused( disputed, tmp_path ):
    ( toy, packets, key ), truth, odd = disputed
    first, second = ( pl.labels_path( packets[ r ] ) for r in ( "rick", "second" ) )
    empty = tmp_path / "labels-third.jsonl"
    empty.write_text( "" )
    with pytest.raises( ValueError, match="has not labelled 1 disputed pairs: " + odd.replace( "|", r"\|" ) ):
        ll.resolved_labels( first, second, key, third_path=empty )


def test_third_votes_refuses_an_item_the_key_does_not_know( disputed, tmp_path ):
    ( toy, packets, key ), truth, odd = disputed
    _, _, third = third_packet( packets, key, truth, odd, True )
    rows = json.loads( open( key ).read() )
    rows[ "items" ].pop( item_of( key, odd ) )
    stripped = tmp_path / "key.json"
    stripped.write_text( json.dumps( rows ) )
    with pytest.raises( ValueError, match="the key does not know" ): ll.third_votes( third, stripped )


# ---- R3 fingerprints, R2 latest answer, W10 unsure pairs --------------------------------------------------------

def test_fingerprints_are_the_sha256_of_each_file_the_rulings_the_third_file_and_the_tree_root( run, tmp_path ):
    toy, packets, key = run
    for r in packets: answer( packets, key, r, truth_of( toy ) )
    a, b   = ( pl.labels_path( packets[ r ] ) for r in ( "rick", "second" ) )
    rul    = tmp_path / "rulings.json"
    rul.write_text( "{}", encoding="utf-8" )
    got    = ll.fingerprints( [ a, b ], rul, a, key, "/the/tree" )
    sha    = lambda path: hashlib.sha256( path.read_bytes() ).hexdigest()
    assert got == { "labels": { str( a ): sha( a ), str( b ): sha( b ) }, "rulings": sha( rul ), "third_labels": sha( a ), "answer_key": sha( pathlib.Path( key ) ), "tree_root": "/the/tree" }
    assert got[ "rulings" ] == hashlib.sha256( b"{}" ).hexdigest()
    bare = ll.fingerprints( [ a ], None, None, key, tmp_path )
    assert bare[ "rulings" ] is None and bare[ "third_labels" ] is None and bare[ "tree_root" ] == str( tmp_path ) and list( bare[ "labels" ] ) == [ str( a ) ]


def test_an_appended_answer_changes_the_fingerprint_of_the_file_it_was_added_to_and_no_other( run ):
    toy, packets, key = run
    for r in packets: answer( packets, key, r, truth_of( toy ) )
    a, b   = ( pl.labels_path( packets[ r ] ) for r in ( "rick", "second" ) )
    before = ll.fingerprints( [ a, b ], None, None, key, "/t" )
    item   = pl.load_items( packets[ "rick" ] )[ 0 ][ "item_id" ]
    pl.save_label( packets[ "rick" ], item, not pl.same_job_labels( a )[ item ], clock=CLOCK )
    after  = ll.fingerprints( [ a, b ], None, None, key, "/t" )
    assert after[ "labels" ][ str( a ) ] != before[ "labels" ][ str( a ) ] and after[ "labels" ][ str( b ) ] == before[ "labels" ][ str( b ) ]


def test_a_changed_answer_is_the_one_the_loader_resolves_with( run ):
    toy, packets, key = run
    truth = truth_of( toy )
    for r in packets: answer( packets, key, r, truth )
    rows  = ll.key_rows( key )
    item  = pl.load_items( packets[ "rick" ] )[ 0 ][ "item_id" ]
    k     = pr.label_key( rows[ item ][ "a" ], rows[ item ][ "b" ] )
    pl.save_label( packets[ "rick" ], item, not truth[ k ], clock=CLOCK )
    got   = ll.pair_key_labels( pl.labels_path( packets[ "rick" ] ), key )
    assert got[ k ] is ( not truth[ k ] ) and ll.disputed_items( pl.labels_path( packets[ "rick" ] ), pl.labels_path( packets[ "second" ] ) ) == [ item ]


def test_unsure_pairs_are_those_either_reviewer_marked_unsure_at_their_latest_answer( run ):
    toy, packets, key = run
    truth = truth_of( toy )
    for r in packets: answer( packets, key, r, truth )
    rows  = ll.key_rows( key )
    ids   = [ i[ "item_id" ] for i in pl.load_items( packets[ "rick" ] ) ]
    pk_of = lambda i: pr.label_key( rows[ i ][ "a" ], rows[ i ][ "b" ] )
    both  = [ pl.labels_path( packets[ r ] ) for r in ( "rick", "second" ) ]
    assert ll.unsure_pair_keys( both, key ) == []
    pl.save_label( packets[ "rick" ], ids[ 0 ], truth[ pk_of( ids[ 0 ] ) ], True, "hmm", clock=CLOCK )
    pl.save_label( packets[ "second" ], ids[ 1 ], truth[ pk_of( ids[ 1 ] ) ], True, "hmm", clock=CLOCK )
    pl.save_label( packets[ "second" ], ids[ 2 ], truth[ pk_of( ids[ 2 ] ) ], True, "hmm", clock=CLOCK )
    pl.save_label( packets[ "second" ], ids[ 2 ], truth[ pk_of( ids[ 2 ] ) ], False, "sure now", clock=CLOCK )
    assert ll.unsure_pair_keys( both, key ) == sorted( [ pk_of( ids[ 0 ] ), pk_of( ids[ 1 ] ) ] )
    assert ll.unsure_pair_keys( both[ :1 ], key ) == [ pk_of( ids[ 0 ] ) ] and ll.unsure_pair_keys( [], key ) == []


def test_unsure_pairs_refuse_labels_for_items_the_key_does_not_know( run, tmp_path ):
    toy, packets, key = run
    stray = tmp_path / "stray.jsonl"
    stray.write_text( json.dumps( { "item_id": "pair-nope", "reviewer": "x", "choice": "NONE", "symbols": [], "note": "", "ts": "t" } ) + "\n", encoding="utf-8" )
    with pytest.raises( ValueError, match="pair-nope" ): ll.unsure_pair_keys( [ stray ], key )


def test_a_different_answer_key_gives_a_different_fingerprint_for_the_same_label_files( run, tmp_path ):
    toy, packets, key = run
    a      = pl.labels_path( packets[ "rick" ] )
    a.write_text( "", encoding="utf-8" )
    other  = tmp_path / "other-key.json"
    other.write_text( pathlib.Path( key ).read_text( encoding="utf-8" ) + " ", encoding="utf-8" )
    same   = ll.fingerprints( [ a ], None, None, key, "/t" )
    assert ll.fingerprints( [ a ], None, None, other, "/t" )[ "answer_key" ] != same[ "answer_key" ] and same[ "answer_key" ] == ll.file_sha256( key )
