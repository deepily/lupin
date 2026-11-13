"""Unit tests for the two-ledger agreement script."""
import json
import math

import pytest

from cosa.repo.duplicate_check.proof import ledger_agreement as la


def _line( a, b, model, slot, rulings ):
    """Return one ledger line."""
    return json.dumps( { "key": f"semdup|{a}|{b}|pv|{model}|{slot}", "value": { "rulings": [ { "candidate": c, "verdict": v, "reason": "r" } for c, v in rulings ] } } )


def _write( tmp_path, name, lines ):
    """Write a ledger with a binding line first."""
    p = tmp_path / name
    p.write_text( "\n".join( [ json.dumps( { "binding": "x" } ), *lines ] ) + "\n", encoding="utf-8" )
    return p


def test_read_ledger_filters_and_skips( tmp_path ):
    p = _write( tmp_path, "l.jsonl", [ _line( "a", "b", "m1", 0, [ ( "c1", "duplicate" ) ] ), _line( "a", "b", "m2", 0, [ ( "c1", "related" ) ] ),
                                         _line( "a", "b", "m1", 1, [ ( "c1", "distinct" ) ] ), json.dumps( { "key": "semdup|z|y|pv|m1|0", "value": { "unreadable": {} } } ) ] )
    assert la.read_ledger( p, "m1", 0 ) == { ( "semdup|a|b|pv", "c1" ): "duplicate" }
    assert la.read_ledger( p, "m2" ) == { ( "semdup|a|b|pv", "c1" ): "related" }
    with pytest.raises( ValueError, match="ruled twice" ): la.read_ledger( p )


def test_read_ledger_bad_key( tmp_path ):
    p = tmp_path / "bad.jsonl"
    p.write_text( json.dumps( { "key": "semdup|a", "value": { "rulings": [] } } ) + "\n", encoding="utf-8" )
    with pytest.raises( ValueError, match="parts" ): la.read_ledger( p )


def test_paired_counts_one_sided():
    both, one = la.paired( { 1: "x", 2: "x" }, { 2: "x", 3: "x" } )
    assert both == [ 2 ] and one == 2


def test_table_and_hand_computed_figures():
    # 2x2: both 40, only first 10, only second 10, neither 40
    t = ( 40, 10, 10, 40 )
    assert la.kappa( t ) == pytest.approx( 0.6 )
    assert la.ac1( t ) == pytest.approx( 0.6 )
    assert la.positive_negative( t ) == pytest.approx( ( 80 / 100, 80 / 100 ) )
    # skewed: both 5, 2, 3, 90 -> po .95, pe = .07*.08 + .93*.92
    t2 = ( 5, 2, 3, 90 )
    pe = 0.07 * 0.08 + 0.93 * 0.92
    assert la.kappa( t2 ) == pytest.approx( ( 0.95 - pe ) / ( 1 - pe ) )
    pi = 0.075
    assert la.ac1( t2 ) == pytest.approx( ( 0.95 - 2 * pi * ( 1 - pi ) ) / ( 1 - 2 * pi * ( 1 - pi ) ) )


def test_undefined_cases():
    assert la.kappa( ( 0, 0, 0, 10 ) ) is None
    assert la.ac1( ( 0, 0, 0, 10 ) ) == pytest.approx( 1.0 )
    assert la.positive_negative( ( 0, 0, 0, 5 ) ) == ( None, 1.0 )
    assert la.positive_negative( ( 5, 0, 0, 0 ) ) == ( 1.0, None )


def test_weighted_kappa_and_exact():
    first  = { 1: "distinct", 2: "related", 3: "near_duplicate", 4: "duplicate" }
    second = { 1: "distinct", 2: "related", 3: "near_duplicate", 4: "duplicate" }
    assert la.weighted_kappa( first, second, [ 1, 2, 3, 4 ] ) == pytest.approx( 1.0 )
    assert la.exact( first, second, [ 1, 2, 3, 4 ] ) == 4
    off = { 1: "related", 2: "distinct", 3: "duplicate", 4: "near_duplicate" }
    # observed disagreement: 1/3 each over four pairs = 4/3; expected 5/3, so kappa 0.2
    assert la.weighted_kappa( first, off, [ 1, 2, 3, 4 ] ) == pytest.approx( 1 - ( 4 / 3 ) / la_expected( first, off ) )
    assert la.exact( first, off, [ 1, 2, 3, 4 ] ) == 0


def la_expected( first, second ):
    """Return the expected disagreement by direct enumeration, as an independent check."""
    keys = list( first )
    k    = 3
    idx  = { v: i for i, v in enumerate( la.LEVELS ) }
    return sum( abs( idx[ first[ i ] ] - idx[ second[ j ] ] ) / k for i in keys for j in keys ) / len( keys )


def test_weighted_kappa_constant_is_none():
    same = { 1: "distinct", 2: "distinct" }
    assert la.weighted_kappa( same, same, [ 1, 2 ] ) is None


def test_percentile():
    assert la.percentile( [ 0.0, 10.0 ], 0.5 ) == 5.0
    assert la.percentile( [ 1.0, 2.0, 3.0 ], 0.0 ) == 1.0
    assert la.percentile( [ 1.0, 2.0, 3.0 ], 1.0 ) == 3.0


def test_mcnemar_exact():
    assert la.mcnemar_exact( 0, 0 ) == 1.0
    assert la.mcnemar_exact( 5, 5 ) == 1.0
    assert la.mcnemar_exact( 0, 6 ) == pytest.approx( 2 / 64 )
    assert la.mcnemar_exact( 1, 9 ) == pytest.approx( 2 * 11 / 1024 )


def _two_ledgers():
    first  = {}
    second = {}
    for d in range( 6 ):
        for c in range( 4 ):
            p = ( f"d{d}", f"c{c}" )
            first[ p ]  = "duplicate" if c == 0 else "distinct"
            second[ p ] = "near_duplicate" if ( c == 0 and d != 5 ) else ( "related" if d == 5 and c == 1 else "distinct" )
    return first, second


def test_statistics_and_bootstrap_determinism_and_groups():
    first, second = _two_ledgers()
    pairs, _ = la.paired( first, second )
    s = la.statistics( first, second, pairs )
    assert s[ "flag_rate_first" ] == pytest.approx( 6 / 24 ) and s[ "flag_rate_second" ] == pytest.approx( 5 / 24 )
    assert s[ "exact" ] == pytest.approx( 17 / 24 )
    a = la.bootstrap( first, second, pairs, draws=50, seed=3 )
    b = la.bootstrap( first, second, pairs, draws=50, seed=3 )
    assert a == b
    assert set( a ) == set( s )
    for k, v in a.items():
        if v is not None: assert v[ 0 ] <= v[ 1 ]


def test_bootstrap_all_undefined_reports_none():
    first  = { ( "d", "c" ): "distinct", ( "d", "e" ): "distinct" }
    pairs  = sorted( first )
    out    = la.bootstrap( first, first, pairs, draws=5 )
    assert out[ "kappa" ] is None and out[ "weighted_kappa" ] is None and out[ "exact" ] == [ 1.0, 1.0 ]


def test_against_labels_strata_and_mcnemar():
    first  = { ( "d1", "c1" ): "duplicate", ( "d2", "c2" ): "distinct", ( "d3", "c3" ): "duplicate", ( "d4", "c4" ): "related", ( "d5", "c5" ): "distinct", ( "d6", "c6" ): "duplicate" }
    second = { ( "d1", "c1" ): "duplicate", ( "d2", "c2" ): "near_duplicate", ( "d3", "c3" ): "distinct", ( "d4", "c4" ): "related", ( "d5", "c5" ): "distinct", ( "d6", "c6" ): "duplicate" }
    pmap   = { "d1|c1": "L1", "d2|c2": "L2", "d3|c3": "L3", "d4|c4": "L4", "d5|c5": "L5", "dX|cX": "L9", "d6|c6": "L6", "d6|c6x": "L7" }
    labels = { "L1": True, "L2": True, "L3": False, "L4": True, "L5": False, "L6": False }
    strata = { "L1": "alike", "L2": "other", "L4": "other" }
    out    = la.against_labels( first, second, pmap, labels, strata )
    allb   = out[ "all" ]
    assert allb[ "labelled_pairs" ] == 6 and allb[ "true_pairs" ] == 3
    assert allb[ "first" ][ "found" ] == 1 and allb[ "first" ][ "recall" ] == pytest.approx( 1 / 3 )
    assert allb[ "first" ][ "flags" ] == 3 and allb[ "first" ][ "correct" ] == 1 and allb[ "first" ][ "precision" ] == pytest.approx( 1 / 3 )
    assert allb[ "second" ][ "found" ] == 2 and allb[ "second" ][ "flags" ] == 3 and allb[ "second" ][ "correct" ] == 2
    assert allb[ "mcnemar" ] == { "only_first": 1, "only_second": 1, "p": 1.0 }
    assert out[ "alike" ][ "true_pairs" ] == 1 and out[ "alike" ][ "first" ][ "precision" ] is None
    assert out[ "other" ][ "mcnemar" ][ "only_second" ] == 1


def test_against_labels_merges_pairs_of_one_label():
    first  = { ( "d1", "c1" ): "distinct", ( "d2", "c1" ): "duplicate" }
    pmap   = { "d1|c1": "L1", "d2|c1": "L1" }
    out    = la.against_labels( first, first, pmap, { "L1": True } )
    assert out[ "all" ][ "first" ][ "found" ] == 1 and out[ "all" ][ "labelled_pairs" ] == 1


def test_against_labels_empty_true_and_flags():
    first = { ( "d1", "c1" ): "distinct" }
    out   = la.against_labels( first, first, { "d1|c1": "L1" }, { "L1": False } )
    assert out[ "all" ][ "first" ][ "recall" ] is None and out[ "all" ][ "first" ][ "precision" ] is None


def test_compare_refuses_disjoint_and_adds_labels():
    with pytest.raises( ValueError, match="share no" ): la.compare( { ( "a", "b" ): "distinct" }, { ( "c", "d" ): "distinct" } )
    first, second = _two_ledgers()
    r = la.compare( first, second, draws=20 )
    assert r[ "pairs" ] == 24 and r[ "definitions" ] == 6 and "labels" not in r and sum( r[ "flag_table" ].values() ) == 24
    r = la.compare( first, second, { "L": True }, { "d0|c0": "L" }, None, draws=5 )
    assert r[ "labels" ][ "all" ][ "true_pairs" ] == 1


def test_main_end_to_end( tmp_path, capsys ):
    one = _write( tmp_path, "one.jsonl", [ _line( "a", "b", "m1", 0, [ ( "c1", "duplicate" ), ( "c2", "distinct" ) ] ), _line( "e", "f", "m1", 0, [ ( "c1", "related" ), ( "c2", "distinct" ) ] ) ] )
    two = _write( tmp_path, "two.jsonl", [ _line( "a", "b", "m2", 0, [ ( "c1", "duplicate" ), ( "c2", "related" ) ] ), _line( "e", "f", "m2", 0, [ ( "c1", "near_duplicate" ), ( "c2", "distinct" ) ] ) ] )
    lab = tmp_path / "labels.json"
    lab.write_text( json.dumps( { "L": True } ) )
    pmap = tmp_path / "pmap.json"
    pmap.write_text( json.dumps( { "semdup|a|b|pv|c1": "L" } ) )
    assert la.main( [ "--first", str( one ), "--first-model", "m1", "--second", str( two ), "--second-model", "m2", "--labels", str( lab ), "--pair-map", str( pmap ), "--draws", "10" ] ) == 0
    out = json.loads( capsys.readouterr().out )
    assert out[ "pairs" ] == 4 and out[ "labels" ][ "all" ][ "true_pairs" ] == 1 and out[ "exact_count" ] == 2
