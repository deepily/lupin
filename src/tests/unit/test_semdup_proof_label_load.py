"""
The proof's label loader, end to end on a synthetic full label set.

Packets and the key come from label_prep.prepare, the labels from the page's own writer, and the result goes into proof_run.
"""
import json

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
