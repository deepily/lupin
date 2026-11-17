"""
The proof's label loader, end to end on a synthetic full label set.

Packets and the key come from label_prep.prepare, the labels from the page's own writer, and the result goes into proof_run.
"""
import hashlib
import json
import pathlib

import pytest

from cosa.utils import file_hash
from cosa.utils.file_hash import file_sha256
from cosa.repo.labelling import packets as pk
from cosa.repo.labelling import pair_labels as pl
from cosa.repo.duplicate_check.proof import label_load as ll
from cosa.repo.duplicate_check.proof import label_prep as lp
from cosa.repo.duplicate_check.proof import proof_run as pr
from tests.unit.test_duplicate_check_proof_run import Toy

CLOCK = lambda: "2026-10-26T21:00:00+00:00"


@pytest.fixture
def run( tmp_path ):
    """Prepare packets and a key for the toy's known pairs; return ( toy, packets, key path )."""
    toy  = Toy( tmp_path )
    mono = { "defs": toy.spec[ "monolith_defs" ], "pairs": toy.spec[ "monolith_pairs" ], "blob": "blob" }
    made = lp.prepare( toy.spec[ "planted" ], mono, [ "rick", "second" ], 3, tmp_path / "run", "sha", { "source_commit": "a" * 40, "index_generation": "gen-0123456789" } )
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
    assert ll.fingerprints( [ a ], None, None, other, "/t" )[ "answer_key" ] != same[ "answer_key" ] and same[ "answer_key" ] == file_sha256( key )


def test_fingerprints_hash_files_with_the_one_shared_file_sha256_helper( run, monkeypatch, tmp_path ):
    toy, packets, key = run
    a    = pl.labels_path( packets[ "rick" ] )
    a.write_text( "", encoding="utf-8" )
    assert ll.file_sha256 is file_hash.file_sha256, "the loader must not keep a copy of its own"
    monkeypatch.setattr( ll, "file_sha256", lambda path: f"sha-of-{pathlib.Path( path ).name}" )
    got  = ll.fingerprints( [ a ], key, key, key, "/t" )
    assert got == { "labels": { str( a ): f"sha-of-{a.name}" }, "rulings": f"sha-of-{pathlib.Path( key ).name}", "third_labels": f"sha-of-{pathlib.Path( key ).name}",
                    "answer_key": f"sha-of-{pathlib.Path( key ).name}", "tree_root": "/t" }


# ---- the supplement: labels for pairs outside the key, kept in files of their own --------------------------------

def make_supplement( toy, tmp_path, rick, second, key_name="supplement-key.json" ):
    """
    Build a two-pair supplement outside the toy's key, with both reviewers' labels.

    rick and second are { position: bool } by pair order ( d1|d2 first, d1|d3 second ).
    Returns ( { key, labels: [ rick's path, second's path ] }, { pair key: item id } ).
    """
    pairs = [ ( toy.d[ "d1" ], toy.d[ "d2" ] ), ( toy.d[ "d1" ], toy.d[ "d3" ] ) ]
    made  = [ lp.pair_item( a, b, 3 ) for a, b in pairs ]
    rows  = { m[ "item" ][ "item_id" ]: { **m[ "row" ], "kind": "flag", "stratum": "flag" } for m in made }
    key   = tmp_path / key_name
    key.write_text( json.dumps( { "items": rows } ), encoding="utf-8" )
    packs = pk.export_packets( [ m[ "item" ] for m in made ], [ "rick-supp", "second-supp" ], 3, tmp_path / "supp-packets", { "source_commit": "a" * 40, "index_generation": "gen-0123456789" } )
    for reviewer, answers in ( ( "rick-supp", rick ), ( "second-supp", second ) ):
        for n, m in enumerate( made ): pl.save_label( packs[ reviewer ], m[ "item" ][ "item_id" ], answers[ n ], clock=CLOCK )
    by_pair = { pr.label_key( p[ 0 ][ "id" ], p[ 1 ][ "id" ] ): m[ "item" ][ "item_id" ] for p, m in zip( pairs, made ) }
    return { "key": key, "labels": [ pl.labels_path( packs[ r ] ) for r in ( "rick-supp", "second-supp" ) ] }, by_pair


def labelled_run( run ):
    """Label both packets by the toy's truth; return ( truth, first path, second path, key )."""
    toy, packets, key = run
    truth = truth_of( toy )
    for r in packets: answer( packets, key, r, truth )
    return truth, pl.labels_path( packets[ "rick" ] ), pl.labels_path( packets[ "second" ] ), key


def test_a_supplement_adds_its_pairs_to_the_settled_labels_and_leaves_the_key_labels_as_they_were( run, tmp_path ):
    truth, first, second, key = labelled_run( run )
    supp, by_pair             = make_supplement( run[ 0 ], tmp_path, [ True, False ], [ True, False ] )
    keys                      = list( by_pair )
    got                       = ll.resolved_labels( first, second, key, supplement=supp )
    assert got == { **truth, keys[ 0 ]: True, keys[ 1 ]: False } and len( got ) == len( truth ) + 2
    assert ll.resolved_labels( first, second, key ) == truth


def test_a_supplement_pair_the_two_reviewers_split_on_is_refused_until_ruled_and_a_third_file_is_not_asked_for_it( run, tmp_path ):
    truth, first, second, key = labelled_run( run )
    supp, by_pair             = make_supplement( run[ 0 ], tmp_path, [ True, False ], [ False, False ] )
    split                     = list( by_pair )[ 0 ]
    with pytest.raises( ValueError, match="1 disagreements have no ruling: " + split.replace( "|", r"\|" ) ): ll.resolved_labels( first, second, key, supplement=supp )
    assert ll.resolved_labels( first, second, key, rulings={ split: True }, supplement=supp )[ split ] is True
    empty = tmp_path / "labels-third.jsonl"
    empty.write_text( "" )
    assert ll.resolved_labels( first, second, key, rulings={ split: False }, third_path=empty, supplement=supp )[ split ] is False


def test_a_supplement_pair_one_reviewer_has_not_labelled_is_named( run, tmp_path ):
    truth, first, second, key = labelled_run( run )
    supp, by_pair             = make_supplement( run[ 0 ], tmp_path, [ True, False ], [ True, False ] )
    supp[ "labels" ][ 1 ].write_text( "", encoding="utf-8" )
    with pytest.raises( ValueError, match="2 pairs are not labelled by both reviewers" ): ll.resolved_labels( first, second, key, supplement=supp )


def test_a_supplement_that_repeats_a_pair_of_the_key_is_refused( run, tmp_path ):
    truth, first, second, key = labelled_run( run )
    supp, by_pair             = make_supplement( run[ 0 ], tmp_path, [ True, False ], [ True, False ] )
    rows                      = ll.key_rows( key )
    one                       = next( iter( rows.values() ) )
    mine                      = json.loads( supp[ "key" ].read_text() )
    mine[ "items" ][ "pair-twin" ] = { **one, "kind": "flag", "stratum": "flag" }
    supp[ "key" ].write_text( json.dumps( mine ), encoding="utf-8" )
    with pytest.raises( ValueError, match="supplement pairs already in the key: " + pr.label_key( one[ "a" ], one[ "b" ] ).replace( "|", r"\|" ) ):
        ll.resolved_labels( first, second, key, supplement=supp )


def test_a_supplement_that_reuses_an_item_id_of_the_key_is_refused( run, tmp_path ):
    truth, first, second, key = labelled_run( run )
    supp, by_pair             = make_supplement( run[ 0 ], tmp_path, [ True, False ], [ True, False ] )
    shared                    = next( iter( ll.key_rows( key ) ) )
    mine                      = json.loads( supp[ "key" ].read_text() )
    mine[ "items" ][ shared ] = mine[ "items" ].pop( next( iter( mine[ "items" ] ) ) )
    supp[ "key" ].write_text( json.dumps( mine ), encoding="utf-8" )
    with pytest.raises( ValueError, match="supplement item ids already in the key: " + shared ): ll.supplement_rows( supp, key )


def test_a_supplement_names_exactly_two_labels_files( run, tmp_path ):
    truth, first, second, key = labelled_run( run )
    supp, _                   = make_supplement( run[ 0 ], tmp_path, [ True, False ], [ True, False ] )
    with pytest.raises( ValueError, match="a supplement takes two labels files, 1 given" ): ll.supplement_rows( { **supp, "labels": supp[ "labels" ][ :1 ] }, key )


def test_fingerprints_name_the_supplement_key_and_both_its_files_and_say_nothing_without_one( run, tmp_path ):
    truth, first, second, key = labelled_run( run )
    supp, _                   = make_supplement( run[ 0 ], tmp_path, [ True, False ], [ True, False ] )
    got                       = ll.fingerprints( [ first, second ], None, None, key, "/t", supplement=supp )
    assert got[ "supplement" ] == { "key": file_sha256( supp[ "key" ] ), "labels": { str( p ): file_sha256( p ) for p in supp[ "labels" ] } }
    assert "supplement" not in ll.fingerprints( [ first, second ], None, None, key, "/t" )


def test_unsure_pairs_include_those_either_reviewer_marked_unsure_in_the_supplement( run, tmp_path ):
    truth, first, second, key = labelled_run( run )
    supp, by_pair             = make_supplement( run[ 0 ], tmp_path, [ True, False ], [ True, False ] )
    item                      = next( iter( by_pair.values() ) )
    pl.save_label( pk.packet_path( supp[ "labels" ][ 0 ].parent, "rick-supp" ), item, True, True, "hmm", clock=CLOCK )
    assert ll.unsure_pair_keys( [ first, second ], key, supplement=supp ) == [ next( iter( by_pair ) ) ]
    assert ll.unsure_pair_keys( [ first, second ], key ) == []


def supp_third( supp, by_pair, which, same, unsure=False ):
    """Label a third rater's packet of the supplement's disputed pairs; return its labels path."""
    path = pk.export_subset_packet( supp[ "labels" ][ 0 ].parent, ll.disputed_items( *supp[ "labels" ] ), "third-supp", 3 )
    pl.save_label( path, by_pair[ which ], same, unsure=unsure, note="leaning" if unsure else "", clock=CLOCK )
    return pl.labels_path( path )


def test_a_supplement_third_file_settles_a_supplement_dispute_by_majority_even_against_a_ruling( run, tmp_path ):
    truth, first, second, key = labelled_run( run )
    supp, by_pair             = make_supplement( run[ 0 ], tmp_path, [ True, False ], [ False, False ] )
    split                     = list( by_pair )[ 0 ]
    supp[ "third" ]           = supp_third( supp, by_pair, split, True )
    got                       = ll.resolved_labels( first, second, key, rulings={ split: False }, supplement=supp )
    assert got[ split ] is True and len( got ) == len( truth ) + 2


def test_an_unsure_supplement_third_label_falls_to_the_ruling( run, tmp_path ):
    truth, first, second, key = labelled_run( run )
    supp, by_pair             = make_supplement( run[ 0 ], tmp_path, [ True, False ], [ False, False ] )
    split                     = list( by_pair )[ 0 ]
    supp[ "third" ]           = supp_third( supp, by_pair, split, True, unsure=True )
    with pytest.raises( ValueError, match="1 disagreements have no ruling" ): ll.resolved_labels( first, second, key, supplement=supp )
    assert ll.resolved_labels( first, second, key, rulings={ split: False }, supplement=supp )[ split ] is False


def test_a_supplement_third_file_that_misses_a_disputed_pair_is_refused( run, tmp_path ):
    truth, first, second, key = labelled_run( run )
    supp, by_pair             = make_supplement( run[ 0 ], tmp_path, [ True, False ], [ False, False ] )
    empty                     = tmp_path / "labels-third-supp.jsonl"
    empty.write_text( "" )
    supp[ "third" ]           = empty
    with pytest.raises( ValueError, match="supplement's third rater has not labelled 1 disputed pairs: " + list( by_pair )[ 0 ].replace( "|", r"\|" ) ):
        ll.resolved_labels( first, second, key, supplement=supp )


def test_a_supplement_third_file_that_labels_a_pair_not_in_dispute_is_refused( run, tmp_path ):
    truth, first, second, key = labelled_run( run )
    supp, by_pair             = make_supplement( run[ 0 ], tmp_path, [ True, False ], [ False, False ] )
    split, other              = list( by_pair )
    supp[ "third" ]           = supp_third( supp, by_pair, split, True )
    line                      = json.loads( supp[ "third" ].read_text().splitlines()[ 0 ] )
    with open( supp[ "third" ], "a" ) as f: f.write( json.dumps( { **line, "item_id": by_pair[ other ] } ) + "\n" )
    with pytest.raises( ValueError, match="supplement's third rater labelled 1 pairs that are not disputed: " + other.replace( "|", r"\|" ) ):
        ll.resolved_labels( first, second, key, supplement=supp )


def test_a_supplement_third_file_does_not_count_for_a_key_dispute_and_the_key_third_is_still_asked_for_it( run, tmp_path ):
    toy, packets, key = run
    truth, odd        = truth_of( toy ), toy.key( "m1", "m5" )
    answer( packets, key, "rick", truth )
    answer( packets, key, "second", truth, flip=( odd, ) )
    first, second     = ( pl.labels_path( packets[ r ] ) for r in ( "rick", "second" ) )
    supp, by_pair     = make_supplement( toy, tmp_path, [ True, False ], [ False, False ] )
    split             = list( by_pair )[ 0 ]
    supp[ "third" ]   = supp_third( supp, by_pair, split, True )
    with pytest.raises( ValueError, match="disagreements have no ruling: " + odd.replace( "|", r"\|" ) ):
        ll.resolved_labels( first, second, key, supplement=supp )
    third = third_packet( packets, key, truth, odd, False )[ 2 ]
    got   = ll.resolved_labels( first, second, key, third_path=third, supplement=supp )
    assert got[ odd ] is False and got[ split ] is True


def test_fingerprints_add_the_supplement_third_file_only_when_one_is_named( run, tmp_path ):
    truth, first, second, key = labelled_run( run )
    supp, by_pair             = make_supplement( run[ 0 ], tmp_path, [ True, False ], [ False, False ] )
    assert "third_labels" not in ll.fingerprints( [ first, second ], None, None, key, "/t", supplement=supp )[ "supplement" ]
    supp[ "third" ]           = supp_third( supp, by_pair, list( by_pair )[ 0 ], True )
    assert ll.fingerprints( [ first, second ], None, None, key, "/t", supplement=supp )[ "supplement" ][ "third_labels" ] == file_sha256( supp[ "third" ] )


def test_a_supplement_third_file_naming_an_item_in_neither_key_is_refused( run, tmp_path ):
    truth, first, second, key = labelled_run( run )
    supp, by_pair             = make_supplement( run[ 0 ], tmp_path, [ True, False ], [ False, False ] )
    supp[ "third" ]           = supp_third( supp, by_pair, list( by_pair )[ 0 ], True )
    line                      = json.loads( supp[ "third" ].read_text().splitlines()[ 0 ] )
    with open( supp[ "third" ], "a" ) as f: f.write( json.dumps( { **line, "item_id": "pair-in-neither-key" } ) + "\n" )
    with pytest.raises( ValueError, match="labels for items the key does not know: pair-in-neither-key" ):
        ll.resolved_labels( first, second, key, supplement=supp )
