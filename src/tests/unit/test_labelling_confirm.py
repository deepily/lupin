"""
Unit tests for confirm mode: the sample, the packet, the manifest and the report.
"""
import json

import pytest

from cosa.repo.labelling import confirm as cf
from cosa.repo.labelling import errors as er
from cosa.repo.labelling import packets as pk
from tests.unit.test_labelling_items_and_packets import code_of, need_item, none_item, pair_item


def label( item_id, reviewer, choice=pk.AS_PROPOSED, symbols=() ):
    """Return one label in the format read_labels returns."""
    return { "item_id": item_id, "reviewer": reviewer, "choice": choice, "symbols": list( symbols ), "note": "", "ts": "2026-10-25T12:00:00-04:00" }


def items_of( n ):
    """Return n distinct items of the three shapes."""
    return [ ( need_item, none_item, pair_item )[ k % 3 ]( k ) for k in range( n ) ]


def rick_of( items, **choices ):
    """Return Rick's label for every item, AS_PROPOSED unless the item id is named in choices."""
    return [ label( i[ "item_id" ], "rick", *choices.get( i[ "item_id" ], ( pk.AS_PROPOSED, () ) ) ) for i in items ]


def written( paths ):
    """Return the packet lines and the manifest a round wrote."""
    return [ json.loads( l ) for l in paths[ "path" ].read_text().splitlines() ], json.loads( paths[ "manifest_path" ].read_text() )


def test_the_sample_is_twenty_percent_half_rounded_up_seeded_and_independent_of_input_order():
    ids = [ f"n-{k:03d}" for k in range( 30 ) ]
    assert len( cf.blind_sample_ids( ids, 7 ) ) == 6 and len( cf.blind_sample_ids( ids[ :25 ], 7 ) ) == 5
    assert len( cf.blind_sample_ids( ids[ :22 ], 7 ) ) == 4 and len( cf.blind_sample_ids( ids[ :23 ], 7 ) ) == 5      # 4.4 down, 4.6 up
    assert len( cf.blind_sample_ids( ids[ :10 ], 7, 0.25 ) ) == 3 and len( cf.blind_sample_ids( ids[ :10 ], 7, 0.15 ) ) == 2        # 2.5 and 1.5 round up; round() would give 2 and 2
    assert cf.blind_sample_ids( ids, 7 ) == cf.blind_sample_ids( list( reversed( ids ) ), 7 ) != cf.blind_sample_ids( ids, 8 )
    assert cf.blind_sample_ids( [], 7 ) == [] and set( cf.blind_sample_ids( ids, 7 ) ) <= set( ids )


def test_a_confirm_packet_hides_rick_on_the_blind_sample_and_shows_him_on_the_rest( tmp_path ):
    items = items_of( 10 )
    rick  = rick_of( items, **{ "n-000": ( pk.OTHER, [ "pkg.f" ] ), "z-001": ( pk.NONE, () ) } )
    paths = cf.export_confirm_packet( items, rick, "sam", 7, tmp_path )
    lines, manifest = written( paths )
    blind = set( paths[ "blind_ids" ] )
    assert len( blind ) == 2 and set( paths[ "confirm_ids" ] ) == { i[ "item_id" ] for i in items } - blind
    assert paths[ "path" ] == pk.packet_path( tmp_path, "sam" ) and paths[ "manifest_path" ] == cf.manifest_path( tmp_path, "sam" )
    by_id = { l[ "item_id" ]: l for l in lines }
    assert len( lines ) == 10 and set( by_id ) == { i[ "item_id" ] for i in items }
    for item_id, line in by_id.items():
        if item_id in blind: assert set( line ) == { "item_id", "type", "payload", "mode" } and line[ "mode" ] == cf.MODE_BLIND
        else: assert set( line ) == { "item_id", "type", "payload", "mode", "rick_label" } and line[ "mode" ] == cf.MODE_CONFIRM and set( line[ "rick_label" ] ) == { "choice", "symbols" }
    shown = { l[ "item_id" ]: l[ "rick_label" ] for l in lines if l[ "mode" ] == cf.MODE_CONFIRM }
    assert shown == { r[ "item_id" ]: { "choice": r[ "choice" ], "symbols": r[ "symbols" ] } for r in rick if r[ "item_id" ] not in blind }
    assert "n-000" in blind or shown[ "n-000" ] == { "choice": pk.OTHER, "symbols": [ "pkg.f" ] }
    assert manifest == { "format": cf.MANIFEST_FORMAT, "seed": 7, "share": 0.2, "reviewer": "sam", "rick": "rick", "n_items": 10, "n_blind": 2, "blind_ids": sorted( blind ) }
    assert cf.read_manifest( paths[ "manifest_path" ] ) == manifest


def test_the_same_seed_gives_the_same_packet_and_another_seed_a_different_sample( tmp_path ):
    items = items_of( 20 )
    rick  = rick_of( items )
    a, b  = cf.export_confirm_packet( items, rick, "sam", 7, tmp_path / "a" ), cf.export_confirm_packet( items, rick, "sam", 7, tmp_path / "b" )
    c     = cf.export_confirm_packet( items, rick, "sam", 8, tmp_path / "c" )
    assert a[ "path" ].read_text() == b[ "path" ].read_text() and a[ "blind_ids" ] == b[ "blind_ids" ] != c[ "blind_ids" ]


@pytest.mark.parametrize( "mutate, code", [
    ( lambda items, rick: ( items + [ items[ 0 ] ], rick, "sam", 0.2 ), er.BAD_ITEM ),                       # duplicate ids
    ( lambda items, rick: ( items, rick, "s m", 0.2 ), er.BAD_ITEM ),                                         # a bad name
    ( lambda items, rick: ( items, rick, "rick", 0.2 ), er.BAD_ITEM ),                                        # the second reviewer is Rick
    ( lambda items, rick: ( items, rick, "sam", 0 ), er.BAD_ITEM ),
    ( lambda items, rick: ( items, rick, "sam", 1 ), er.BAD_ITEM ),
    ( lambda items, rick: ( items[ :1 ], rick[ :1 ], "sam", 0.2 ), er.BAD_ITEM ),                             # 0.2 of 1 draws nothing
    ( lambda items, rick: ( items, rick[ 1: ], "sam", 0.2 ), er.BAD_LABEL ),                                  # an item Rick did not label
    ( lambda items, rick: ( items, rick + [ label( "stray", "rick" ) ], "sam", 0.2 ), er.BAD_LABEL ),         # a label for no item
    ( lambda items, rick: ( items, rick + [ rick[ 0 ] ], "sam", 0.2 ), er.BAD_LABEL ),                        # a label twice
] )
def test_a_bad_round_is_refused_by_name_and_writes_nothing( tmp_path, mutate, code ):
    items = items_of( 10 )
    args  = mutate( items, rick_of( items ) )
    assert code_of( lambda: cf.export_confirm_packet( args[ 0 ], args[ 1 ], args[ 2 ], 7, tmp_path, args[ 3 ] ) ) == code
    assert list( tmp_path.iterdir() ) == []


def test_an_item_with_a_hidden_field_is_refused_before_anything_is_written( tmp_path ):
    items = items_of( 10 )
    items[ 3 ] = dict( items[ 3 ], verdict="same" )
    assert code_of( lambda: cf.export_confirm_packet( items, rick_of( items ), "sam", 7, tmp_path ) ) == er.PACKET_LEAK and list( tmp_path.iterdir() ) == []


def test_a_packet_that_reads_back_differently_is_removed_and_a_changed_line_is_a_leak( tmp_path, monkeypatch ):
    items = items_of( 10 )
    def tampered( path, expected ):
        path.write_text( path.read_text() + json.dumps( { "item_id": "n-000", "extra": 1 } ) + "\n" )
        return real( path, expected )
    real = cf._check_written
    monkeypatch.setattr( cf, "_check_written", tampered )
    assert code_of( lambda: cf.export_confirm_packet( items, rick_of( items ), "sam", 7, tmp_path ) ) == er.PACKET_LEAK
    assert list( tmp_path.iterdir() ) == []
    path = tmp_path / "p.jsonl"
    path.write_text( json.dumps( { "item_id": "ghost" } ) + "\n" )
    assert code_of( real, path, { "n-000": {} } ) == er.PACKET_LEAK


@pytest.mark.parametrize( "text", [ "not json", "[]", json.dumps( { "format": "other" } ),
                                    json.dumps( { "format": cf.MANIFEST_FORMAT, "seed": 1, "share": 0.2, "reviewer": "s", "rick": "r", "n_items": 5, "n_blind": 2, "blind_ids": [ "a" ] } ) ] )
def test_a_file_that_is_not_a_manifest_is_a_bad_label( tmp_path, text ):
    path = tmp_path / "m.json"
    path.write_text( text )
    assert code_of( cf.read_manifest, path ) == er.BAD_LABEL


def run_round( tmp_path, n=20, rick_choices=None, second=None ):
    """
    Export a round of n items and return its items, labels, manifest and paths.

    Returns ( items, Rick's labels, the second reviewer's labels, manifest, paths ). The second reviewer repeats Rick's choice unless second names the item.
    """
    items = items_of( n )
    rick  = rick_of( items, **( rick_choices or {} ) )
    paths = cf.export_confirm_packet( items, rick, "sam", 7, tmp_path )
    mine  = [ label( l[ "item_id" ], "sam", *( second or {} ).get( l[ "item_id" ], ( l[ "choice" ], l[ "symbols" ] ) ) ) for l in rick ]
    return items, rick, mine, cf.read_manifest( paths[ "manifest_path" ] ), paths


def test_kappa_is_computed_on_the_blind_sample_only_and_the_report_says_so_with_its_size( tmp_path ):
    n = 20
    items = items_of( n )
    probe = cf.blind_sample_ids( [ i[ "item_id" ] for i in items ], 7 )
    a, b  = probe[ 0 ], probe[ 1 ]                                       # two blind items: Rick says AS_PROPOSED on both
    rick  = { a: ( pk.AS_PROPOSED, () ), b: ( pk.NONE, () ) }
    second = { a: ( pk.AS_PROPOSED, () ), b: ( pk.AS_PROPOSED, () ), probe[ 2 ]: ( pk.NONE, () ), probe[ 3 ]: ( pk.NONE, () ) }
    items, rick_l, mine, manifest, _ = run_round( tmp_path, n, rick, second )
    confirm_item = next( i[ "item_id" ] for i in items if i[ "item_id" ] not in probe )
    mine = [ label( l[ "item_id" ], "sam", pk.OTHER, [ "x.y" ] ) if l[ "item_id" ] == confirm_item else l for l in mine ]      # a dispute outside the sample
    rep = cf.confirm_report( rick_l, mine, manifest )
    assert rep[ "kappa_basis" ] == "blind sample only" and rep[ "kappa_n" ] == 4 == rep[ "blind" ][ "n" ] and rep[ "confirm_n" ] == 16 and rep[ "seed" ] == 7
    assert rep[ "confirmed" ] == 15 and rep[ "disputed_confirm" ] == [ confirm_item ]
    assert rep[ "disputed_blind" ] == sorted( [ b, probe[ 2 ], probe[ 3 ] ] ) and rep[ "disputes_for_rick" ] == sorted( rep[ "disputed_blind" ] + [ confirm_item ] )
    assert "kappa was computed on the blind sample only: 4 of 20 items, drawn with seed 7" in rep[ "statement" ] and "16 items were confirmed against rick's labels" in rep[ "statement" ]
    from cosa.repo.labelling.agreement import agreement_report
    sample = [ ( x, y ) for x, y in zip( rick_l, mine ) if x[ "item_id" ] in probe ]
    assert rep[ "kappa" ] == agreement_report( [ x for x, _ in sample ], [ y for _, y in sample ], pk.CHOICES )[ "kappa" ]


def test_the_confirm_part_does_not_move_kappa( tmp_path ):
    items, rick, mine, manifest, _ = run_round( tmp_path, 20, { "n-000": ( pk.NONE, () ) } )
    base = cf.confirm_report( rick, mine, manifest )
    flipped = [ label( l[ "item_id" ], "sam", pk.NONE ) if l[ "item_id" ] not in manifest[ "blind_ids" ] else l for l in mine ]
    again = cf.confirm_report( rick, flipped, manifest )
    assert again[ "kappa" ] == base[ "kappa" ] and again[ "kappa_n" ] == base[ "kappa_n" ] and again[ "confirmed" ] < base[ "confirmed" ]


def test_a_blind_sample_in_one_category_leaves_kappa_none_but_still_reports_the_confirm_part( tmp_path ):
    items, rick, mine, manifest, _ = run_round( tmp_path, 10 )
    rep = cf.confirm_report( rick, mine, manifest )
    assert rep[ "kappa" ] is None and rep[ "blind" ] is None and rep[ "kappa_n" ] == 2 and rep[ "confirmed" ] == 8 and rep[ "disputes_for_rick" ] == []


def test_a_report_over_other_items_or_an_unknown_blind_id_is_refused( tmp_path ):
    items, rick, mine, manifest, _ = run_round( tmp_path, 10 )
    assert code_of( cf.confirm_report, rick, mine[ 1: ], manifest ) == er.BAD_LABEL
    assert code_of( cf.confirm_report, rick, mine, dict( manifest, blind_ids=[ "ghost" ] ) ) == er.BAD_LABEL


def test_a_choice_outside_the_categories_is_not_swallowed_as_undefined_kappa( tmp_path ):
    items, rick, mine, manifest, _ = run_round( tmp_path, 10 )
    assert code_of( cf.confirm_report, rick, mine, manifest, [ pk.NONE ] ) == er.BAD_LABEL
