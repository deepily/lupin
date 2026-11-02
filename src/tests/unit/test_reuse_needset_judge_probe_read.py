"""
The four-arm read of plan section 17.3, on synthetic reports, with no model call.

A report is built from a table of which plants each arm and repeat accepts, so every figure has a value the test states first.
"""
import json

import pytest

from lupin_mcp.reuse_needset import judge_probe as jp
from lupin_mcp.reuse_needset import judge_probe_read as jr

SAME = [ f"s{i:02d}" for i in range( 13 ) ]
NOTS = [ f"n{i}" for i in range( 4 ) ]
HIGH, LOW = 0.80, 0.10


def row( pair, arm, repeat, p, original=0.9, tokens=100, answered=True, orig_answered=True, serial=[ 0 ] ):
    """Return one report row; p is the plant's p_overlap, original the original's."""
    serial[ 0 ] += 1
    side = lambda v, ok: { "answered": ok, "p_overlap": v if ok else None, "confidence": 0.5 if ok else None, "choice": "reuse" if ok else None }
    return { "pair": pair, "label": jp.SAME_JOB if pair in SAME else jp.NOT_SAME, "arm": arm, "repeat": repeat, "request_hash": f"h{serial[ 0 ]}", "status": "ok",
             "tokens_in": tokens, "plant": side( p, answered ), "original": side( original, orig_answered ) }


def report( spec, **kw ):
    """
    Build a report from { arm: { repeat: ( same accepted count, not-same accepted count ) } }.

    The first N same-job and first M not-same plants of the arm are accepted at 0.80, the rest rated 0.10.
    """
    rows = []
    for arm, reps in spec.items():
        for n, ( ks, kn ) in reps.items():
            rows += [ row( p, arm, n, HIGH if i < ks else LOW, **kw ) for i, p in enumerate( SAME ) ]
            rows += [ row( p, arm, n, HIGH if i < kn else LOW, **kw ) for i, p in enumerate( NOTS ) ]
    return { "results": rows }


def flat( ks, kn ): return { 1: ( ks, kn ), 2: ( ks, kn ), 3: ( ks, kn ) }


MOVER = { jp.ARM_BASELINE: flat( 6, 2 ), jp.ARM_PLANT: flat( 6, 2 ), jp.ARM_SHAPED: flat( 11, 1 ), jp.ARM_BOTH: flat( 11, 1 ) }


def test_accepted_boundary_and_missing():
    assert jr.accepted( 0.30 ) is True
    assert jr.accepted( 0.299999 ) is False
    assert jr.accepted( 0.1 + 0.2 ) is True
    assert jr.accepted( None ) is False


@pytest.mark.parametrize( "ks, kn, d, low, high", [ ( 6, 2, -0.04, -0.46, 0.39 ), ( 9, 2, 0.19, -0.25, 0.59 ), ( 10, 1, 0.52, -0.01, 0.77 ), ( 11, 1, 0.60, 0.07, 0.83 ),
                                                      ( 12, 1, 0.67, 0.16, 0.89 ), ( 11, 0, 0.85, 0.29, 0.96 ) ] )
def test_newcombe_matches_the_marks_reference_table( ks, kn, d, low, high ):
    got = jr.newcombe( ks, 13, kn, 4 )
    assert ( round( got[ 0 ], 2 ), round( got[ 1 ], 2 ), round( got[ 2 ], 2 ) ) == ( d, low, high )


def test_figures_count_answered_readings_and_leave_missing_ones_out():
    rows = report( { jp.ARM_BASELINE: { 1: ( 6, 2 ) } } )[ "results" ]
    rows[ 0 ] = row( "s00", jp.ARM_BASELINE, 1, None, answered=False )
    f = jr.figures( rows )
    assert ( f[ "same" ], f[ "same_n" ], f[ "not_same" ], f[ "not_same_n" ] ) == ( 5, 12, 2, 4 )
    only_same = jr.figures( [ r for r in rows if r[ "label" ] == jp.SAME_JOB ] )
    assert only_same[ "d" ] is None and only_same[ "low" ] is None


def test_pairing_share_counts_ties_as_half_and_names_the_empty_case():
    rows = [ row( "s00", "a", 1, 0.5 ), row( "s01", "a", 1, 0.2 ), row( "n0", "a", 1, 0.5 ), row( "n1", "a", 1, 0.4 ) ]
    got = jr.pairing_share( rows )
    assert got == { "share": 0.375, "pairings": 4 }            # s00 ties n0 (.5) and beats n1 (1); s01 loses to both (0): 1.5 of 4
    assert jr.pairing_share( [ row( "s00", "a", 1, 0.5 ) ] ) == { "share": None, "pairings": 0 }


def test_index_results_refuses_a_repeated_pair_and_an_unknown_arm():
    r = row( "s00", jp.ARM_BASELINE, 1, 0.5 )
    with pytest.raises( ValueError, match="twice" ): jr.index_results( [ r, dict( r ) ] )
    with pytest.raises( ValueError, match="unknown arm" ): jr.index_results( [ row( "s00", "mystery", 1, 0.5 ) ] )


def test_a_clear_mover_is_labelled_moved_on_n_and_within_noise_on_the_flat_pairs():
    a = jr.analyze( report( MOVER ) )
    by = { c[ "name" ]: c for c in a[ "comparisons" ] }
    assert a[ "arms" ][ jp.ARM_SHAPED ][ "d_bar" ] == pytest.approx( 11 / 13 - 1 / 4 )
    assert by[ "N" ][ "label" ] == jr.MOVED and by[ "N" ][ "met" ] == list( jr.CRITERIA )
    assert by[ "L" ][ "label" ] == jr.WITHIN and by[ "L" ][ "delta" ] == 0.0
    assert by[ "A" ][ "label" ] == jr.WITHIN
    assert by[ "N" ][ "moves" ][ "net" ] == 5 + 1 and by[ "N" ][ "n_pairs" ] == 17      # five same-job accepted, one not-same rejected


def test_separated_needs_the_mean_and_every_repeat_above_zero():
    a = jr.analyze( report( MOVER ) )
    assert a[ "arms" ][ jp.ARM_SHAPED ][ "separated" ] is True
    assert a[ "arms" ][ jp.ARM_BASELINE ][ "separated" ] is False


def test_worse_is_the_reverse_of_size_and_every_repeat():
    spec = { jp.ARM_BASELINE: flat( 6, 2 ), jp.ARM_PLANT: flat( 11, 1 ), jp.ARM_SHAPED: flat( 5, 3 ), jp.ARM_BOTH: flat( 5, 3 ) }
    by = { c[ "name" ]: c for c in jr.analyze( report( spec ) )[ "comparisons" ] }
    assert by[ "N" ][ "label" ] == jr.WORSE and by[ "N" ][ "delta" ] <= -0.40


def test_a_noisy_arm_zero_makes_every_comparison_noise_dominated_unless_worse():
    spec = { jp.ARM_BASELINE: { 1: ( 4, 3 ), 2: ( 9, 1 ), 3: ( 6, 2 ) }, jp.ARM_PLANT: flat( 6, 2 ), jp.ARM_SHAPED: flat( 12, 0 ), jp.ARM_BOTH: flat( 12, 0 ) }
    a = jr.analyze( report( spec ) )
    by = { c[ "name" ]: c for c in a[ "comparisons" ] }
    assert a[ "floor" ][ "spread" ] >= 0.40 and by[ "N" ][ "label" ] == jr.NOISY


def test_a_spread_larger_than_delta_keeps_a_big_delta_within_noise():
    spec = { jp.ARM_BASELINE: { 1: ( 6, 2 ), 2: ( 6, 2 ), 3: ( 8, 2 ) }, jp.ARM_PLANT: flat( 6, 2 ), jp.ARM_SHAPED: flat( 11, 1 ), jp.ARM_BOTH: flat( 11, 1 ) }
    by = { c[ "name" ]: c for c in jr.analyze( report( spec ) )[ "comparisons" ] }
    assert by[ "N" ][ "criteria" ][ "above_noise" ] is True      # 0.15 of spread is below delta 0.64
    assert jr.analyze( report( spec ) )[ "floor" ][ "spread" ] == pytest.approx( 2 / 13, abs=1e-5 )


def test_the_floor_is_not_valid_when_arm_zero_has_a_post_without_tokens_or_a_hash_repeats():
    stale = report( MOVER )
    stale[ "results" ][ 0 ][ "tokens_in" ] = 0
    assert jr.analyze( stale )[ "floor" ][ "valid" ] is False
    assert all( c[ "label" ] == jr.NOT_RUN for c in jr.analyze( stale )[ "comparisons" ] )
    same_hash = report( MOVER )
    same_hash[ "results" ][ 1 ][ "request_hash" ] = same_hash[ "results" ][ 0 ][ "request_hash" ]
    assert jr.analyze( same_hash )[ "proof" ][ "every_hash_distinct" ] is False


def test_a_comparison_with_an_arm_that_has_no_d_is_not_run():
    only_same = { "results": [ r for r in report( MOVER )[ "results" ] if r[ "label" ] == jp.SAME_JOB ] }
    assert all( c[ "label" ] == jr.NOT_RUN for c in jr.analyze( only_same )[ "comparisons" ] )


def test_a_missing_reading_shortens_the_denominator_and_is_listed():
    rep = report( MOVER )
    rep[ "results" ][ 0 ] = row( "s00", jp.ARM_BASELINE, 1, None, answered=False, orig_answered=False )
    a = jr.analyze( rep )
    assert a[ "arms" ][ jp.ARM_BASELINE ][ "by_repeat" ][ 1 ][ "same_n" ] == 12
    assert { "pair": "s00", "arm": jp.ARM_BASELINE, "repeat": 1, "side": "plant" } in a[ "proof" ][ "missing_readings" ]
    assert jr.pair_status( jr.index_results( rep[ "results" ] ), jp.ARM_BASELINE, "s00" ) is True       # repeats 2 and 3 answered and accepted it


def test_pair_status_is_a_strict_majority_and_none_when_nothing_answered():
    rows = [ row( "s00", "baseline", 1, HIGH ), row( "s00", "baseline", 2, LOW ), row( "s00", "baseline", 3, HIGH ), row( "s01", "baseline", 1, None, answered=False ) ]
    cells = jr.index_results( rows )
    assert jr.pair_status( cells, "baseline", "s00" ) is True
    assert jr.pair_status( cells, "baseline", "s01" ) is None
    assert jr.pair_status( jr.index_results( rows[ :2 ] ), "baseline", "s00" ) is False       # one of two is not a majority


def test_moves_count_toward_and_away_and_skip_pairs_with_no_status():
    early = [ row( p, "baseline", 1, HIGH if p in ( "s00", "n0" ) else LOW ) for p in ( "s00", "s01", "n0", "n1" ) ]
    late  = [ row( p, "plant_line", 1, HIGH if p in ( "s01", "n1" ) else LOW ) for p in ( "s00", "s01", "n0", "n1" ) ] + [ row( "s02", "plant_line", 1, HIGH ) ]
    cells = jr.index_results( early + late )
    got = jr.moves( cells, "baseline", "plant_line", { "s00": jp.SAME_JOB, "s01": jp.SAME_JOB, "n0": jp.NOT_SAME, "n1": jp.NOT_SAME, "s02": jp.SAME_JOB } )
    assert got == { "net": 0, "toward": 2, "away": 2, "same_late": 1, "same_early": 1, "n": 4 }


def test_a_comparison_that_buys_size_by_rating_same_job_lower_fails_condition_four():
    spec = { jp.ARM_BASELINE: flat( 12, 3 ), jp.ARM_PLANT: flat( 12, 3 ), jp.ARM_SHAPED: flat( 9, 0 ), jp.ARM_BOTH: flat( 9, 0 ) }
    n = { c[ "name" ]: c for c in jr.analyze( report( spec ) )[ "comparisons" ] }[ "N" ]
    assert n[ "criteria" ][ "not_lower_everywhere" ] is False and n[ "label" ] == jr.WITHIN


def test_flips_are_listed_per_repeat_with_both_ratings():
    f = jr.analyze( report( MOVER ) )[ "flips" ][ "N" ]
    assert f[ 1 ][ "reject_to_accept" ][ jp.SAME_JOB ] == 5 and f[ 1 ][ "accept_to_reject" ][ jp.NOT_SAME ] == 1
    flipped = [ r for r in f[ 1 ][ "rows" ] if r[ "flip" ] ]
    assert len( flipped ) == 6 and all( r[ "early_p" ] != r[ "late_p" ] for r in flipped )
    rep = report( MOVER )
    rep[ "results" ].append( row( "extra", jp.ARM_PLANT, 1, HIGH ) )
    at = next( i for i, r in enumerate( rep[ "results" ] ) if r[ "arm" ] == jp.ARM_PLANT and r[ "repeat" ] == 1 and r[ "pair" ] == "s00" )
    rep[ "results" ][ at ] = row( "s00", jp.ARM_PLANT, 1, None, answered=False )
    assert "extra" not in [ r[ "pair" ] for r in jr.flips( jr.index_results( rep[ "results" ] ), jp.ARM_PLANT, jp.ARM_SHAPED )[ 1 ][ "rows" ] ]


def test_second_reading_takes_originals_from_arms_zero_to_two_only():
    spec = { jp.ARM_SHAPED: flat( 0, 0 ), jp.ARM_BOTH: flat( 0, 0 ) }       # every plant rated .10, every original .90
    sr = jr.analyze( report( spec ) )[ "second_reading" ]
    assert sr[ f"{jp.ARM_SHAPED}/1" ][ "same" ] == 13 and sr[ f"{jp.ARM_SHAPED}/1" ][ "originals_used" ] is True
    assert sr[ f"{jp.ARM_BOTH}/1" ][ "same" ] == 0 and sr[ f"{jp.ARM_BOTH}/1" ][ "originals_used" ] is False
    rows = [ row( "s00", jp.ARM_BASELINE, 1, None, answered=False, orig_answered=False ) ]
    assert jr.duplicate_figures( jr.index_results( rows ), jp.ARM_BASELINE, 1 )[ "same_n" ] == 0


def test_threshold_free_share_is_in_the_analysis_per_arm_and_repeat():
    p = jr.analyze( report( MOVER ) )[ "pairing" ]
    assert p[ f"{jp.ARM_SHAPED}/1" ][ "pairings" ] == 52 and p[ f"{jp.ARM_BASELINE}/1" ][ "share" ] is not None


CUES = { p: { "name_cue": p in ( "s03", "s04" ), "near_identical": p in ( "s00", "n0" ) } for p in SAME + NOTS }


def tsv( tmp_path, text, name="cues.tsv" ):
    """Write a cue file and return its path."""
    path = tmp_path / name
    path.write_text( text, encoding="utf-8" )
    return path


def test_read_cues_reads_a_headed_file_by_column_name_and_ignores_other_columns(tmp_path):
    got = jr.read_cues( tsv( tmp_path, "pair\tplant_name\tname_cue\tline_near_identical\nd-1\tx\tYes\tno\n\nd-2\ty\tn\tTRUE\n" ) )
    assert got == { "d-1": { "name_cue": True, "near_identical": False }, "d-2": { "name_cue": False, "near_identical": True } }


def test_read_cues_reads_a_file_without_a_header_by_position_and_takes_empty_as_no(tmp_path):
    got = jr.read_cues( tsv( tmp_path, "d-1\t1\t\nd-2\t0\ty\n" ) )
    assert got == { "d-1": { "name_cue": True, "near_identical": False }, "d-2": { "name_cue": False, "near_identical": True } }


def test_read_cues_names_the_line_it_cannot_read(tmp_path):
    with pytest.raises( ValueError, match="neither yes nor no" ): jr.read_cues( tsv( tmp_path, "d-1\tmaybe\tno\n" ) )
    with pytest.raises( ValueError, match="2 columns" ): jr.read_cues( tsv( tmp_path, "d-1\tyes\n" ) )
    with pytest.raises( ValueError, match="lacks a name_cue column" ): jr.read_cues( tsv( tmp_path, "pair\tfoo\tbar\nd-1\tyes\tno\n" ) )


def test_splits_use_chloes_lists_and_recompute_n_and_l_without_those_pairs():
    s = jr.analyze( report( MOVER ), CUES )[ "splits" ]
    assert s[ "name_cue" ] == [ "s03", "s04" ] and s[ "near_identical" ] == [ "n0", "s00" ]
    assert s[ "N_without" ][ "n_pairs" ] == 15 and s[ "L_without" ][ "n_pairs" ] == 15
    only_two = jr.analyze( report( { jp.ARM_BASELINE: flat( 6, 2 ) } ), CUES )[ "splits" ]
    assert only_two[ "N_without" ] is None and only_two[ "L_without" ] is None


def test_splits_refuse_a_report_pair_the_cue_file_does_not_name():
    cues = dict( CUES ); del cues[ "s07" ]
    with pytest.raises( ValueError, match="no row for 1 pairs.*s07" ): jr.analyze( report( MOVER ), cues )


def at_boundary( monkeypatch, size=None ):
    """Pin the size mark to an achievable delta, so a >= can be told from a >."""
    if size is not None: monkeypatch.setattr( jr, "SIZE_MOVED", size )


def test_size_condition_is_at_or_above_the_mark(monkeypatch):
    at_boundary( monkeypatch, 0.634616 )               # D(11,1) - D(6,2) from the rounded figures
    n = { c[ "name" ]: c for c in jr.analyze( report( MOVER ) )[ "comparisons" ] }[ "N" ]
    assert n[ "delta" ] == 0.634616 and n[ "criteria" ][ "size" ] is True


def test_every_repeat_must_agree_strictly(monkeypatch):
    at_boundary( monkeypatch, 0.1 )
    spec = { jp.ARM_BASELINE: flat( 6, 2 ), jp.ARM_PLANT: flat( 6, 2 ), jp.ARM_SHAPED: { 1: ( 6, 2 ), 2: ( 11, 1 ), 3: ( 11, 1 ) }, jp.ARM_BOTH: flat( 6, 2 ) }
    n = { c[ "name" ]: c for c in jr.analyze( report( spec ) )[ "comparisons" ] }[ "N" ]
    assert n[ "criteria" ][ "every_repeat" ] is False        # the lowest later D equals the highest earlier D


def test_net_of_exactly_two_pairs_counts():
    spec = { jp.ARM_BASELINE: flat( 6, 2 ), jp.ARM_PLANT: flat( 6, 2 ), jp.ARM_SHAPED: flat( 8, 2 ), jp.ARM_BOTH: flat( 8, 2 ) }
    n = { c[ "name" ]: c for c in jr.analyze( report( spec ) )[ "comparisons" ] }[ "N" ]
    assert n[ "moves" ][ "net" ] == 2 and n[ "criteria" ][ "more_than_one_pair" ] is True


def test_one_fewer_same_job_pair_is_allowed_and_two_are_not():
    spec = lambda late: { jp.ARM_BASELINE: flat( 12, 3 ), jp.ARM_PLANT: flat( 12, 3 ), jp.ARM_SHAPED: flat( late, 3 ), jp.ARM_BOTH: flat( late, 3 ) }
    one = { c[ "name" ]: c for c in jr.analyze( report( spec( 11 ) ) )[ "comparisons" ] }[ "N" ]
    two = { c[ "name" ]: c for c in jr.analyze( report( spec( 10 ) ) )[ "comparisons" ] }[ "N" ]
    assert one[ "criteria" ][ "not_lower_everywhere" ] is True and two[ "criteria" ][ "not_lower_everywhere" ] is False


def test_delta_equal_to_the_noise_floor_is_not_above_it_and_a_floor_at_the_mark_is_noise_dominated(monkeypatch):
    spec = { jp.ARM_BASELINE: { 1: ( 6, 2 ), 2: ( 6, 2 ), 3: ( 8, 2 ) }, jp.ARM_PLANT: flat( 6, 2 ), jp.ARM_SHAPED: flat( 8, 2 ), jp.ARM_BOTH: flat( 8, 2 ) }
    a = jr.analyze( report( spec ) )
    n = { c[ "name" ]: c for c in a[ "comparisons" ] }[ "N" ]
    assert n[ "delta" ] == a[ "floor" ][ "spread" ] and n[ "criteria" ][ "above_noise" ] is False
    at_boundary( monkeypatch, a[ "floor" ][ "spread" ] )
    assert { c[ "name" ]: c for c in jr.analyze( report( spec ) )[ "comparisons" ] }[ "N" ][ "label" ] == jr.NOISY


def test_worse_needs_every_later_repeat_strictly_below_every_earlier_one():
    spec = { jp.ARM_BASELINE: flat( 6, 2 ), jp.ARM_PLANT: { 1: ( 12, 1 ), 2: ( 11, 1 ), 3: ( 11, 1 ) }, jp.ARM_SHAPED: { 1: ( 11, 1 ), 2: ( 5, 3 ), 3: ( 5, 3 ) }, jp.ARM_BOTH: flat( 6, 2 ) }
    n = { c[ "name" ]: c for c in jr.analyze( report( spec ) )[ "comparisons" ] }[ "N" ]
    assert n[ "delta" ] <= -0.40 and n[ "label" ] != jr.WORSE      # the highest later D equals the lowest earlier D


def test_separated_needs_every_repeat_above_zero_not_only_the_mean():
    spec = { jp.ARM_BASELINE: flat( 6, 2 ), jp.ARM_PLANT: { 1: ( 12, 0 ), 2: ( 12, 0 ), 3: ( 8, 2 ) }, jp.ARM_SHAPED: flat( 6, 2 ), jp.ARM_BOTH: flat( 6, 2 ) }
    arm = jr.analyze( report( spec ) )[ "arms" ][ jp.ARM_PLANT ]
    assert arm[ "d_low" ] > 0 and arm[ "by_repeat" ][ 3 ][ "low" ] <= 0 and arm[ "separated" ] is False


def test_an_empty_report_is_read_without_error():
    a = jr.analyze( { "results": [] } )
    assert a[ "arms" ] == {} and a[ "comparisons" ] == [] and a[ "floor" ] == { "spread": 0.0, "valid": False }
    assert "Pairs: 0" in jr.render( a )


def test_render_prints_every_section_and_no_joint_label(tmp_path):
    text = jr.render( jr.analyze( report( MOVER ), CUES ) )
    for part in ( "## D per arm and repeat", "## Comparisons, each read alone", "## Second reading", "## Threshold-free share", "## Flips per comparison and repeat", "## Splits (decide no label)" ):
        assert part in text
    assert "pass flag" not in text and "joint" not in text.lower()
    assert "arm 3 is the plant only" in text
    assert "N_without: delta" in text
    assert "arm missing" in jr.render( jr.analyze( report( { jp.ARM_BASELINE: flat( 6, 2 ) } ), CUES ) )


def test_main_prints_or_writes_the_read(tmp_path, capsys):
    rep, pairs, out = tmp_path / "r.json", tmp_path / "p.json", tmp_path / "out.md"
    rep.write_text( json.dumps( report( MOVER ) ) ); pairs.write_text( "\n".join( f"{p}\t{int( c[ 'name_cue' ] )}\t{int( c[ 'near_identical' ] )}" for p, c in CUES.items() ) )
    lines = []
    assert jr.main( [ "--report", str( rep ) ], out=lines.append ) == 0 and "Four-arm judge run" in lines[ 0 ]
    assert jr.main( [ "--report", str( rep ), "--cues", str( pairs ), "--out", str( out ) ] ) == 0
    assert "Splits" in out.read_text( encoding="utf-8" )


def test_rows_from_the_real_producer_are_read_as_they_come_out_of_ask_request():
    """Feed rows written by judge_probe.ask_request itself, through a stand-in post."""
    def send( transport, need, entries, template, model, budget ):
        value = HIGH if entries[ 0 ][ "id" ] in ( "s00", "n0" ) else LOW
        probs = lambda p: { "reuse": p, "extend": 0.0, "unrelated": round( 1 - p, 6 ) }
        return { "answers": [ { "id": entries[ 0 ][ "id" ], "probabilities": probs( value ) }, { "id": entries[ 1 ][ "id" ], "probabilities": probs( 0.9 ) } ],
                 "rows": [ { "request_hash": f"{entries[ 0 ][ 'id' ]}-{template[ 'instructions' ][ -3: ]}", "status": "ok", "tokens_in": 12 } ] }
    rows = []
    for pair in ( "s00", "s01", "n0", "n1" ):
        for n in ( 1, 2 ):
            request = { "pair": pair, "label": jp.SAME_JOB if pair.startswith( "s" ) else jp.NOT_SAME, "arm": jp.ARM_BASELINE, "repeat": n, "need": "a need",
                        "entries": [ { "id": pair }, { "id": pair + "-orig" } ], "template": { "instructions": f"x (repeat {n})", "criteria": {} } }
            rows.append( jp.ask_request( None, request, send=send ) )
    a = jr.analyze( { "results": rows } )
    got = a[ "arms" ][ jp.ARM_BASELINE ][ "by_repeat" ][ 1 ]
    assert ( got[ "same" ], got[ "same_n" ], got[ "not_same" ], got[ "not_same_n" ] ) == ( 1, 2, 1, 2 )
    assert a[ "proof" ][ "posts" ] == 8 and a[ "proof" ][ "arm0_all_fresh" ] is True


def test_worse_includes_a_delta_exactly_at_minus_the_mark(monkeypatch):
    spec = { jp.ARM_BASELINE: flat( 6, 2 ), jp.ARM_PLANT: flat( 11, 1 ), jp.ARM_SHAPED: flat( 5, 3 ), jp.ARM_BOTH: flat( 5, 3 ) }
    monkeypatch.setattr( jr, "SIZE_MOVED", 0.961539 )               # D(5,3) - D(11,1) from the rounded figures
    n = { c[ "name" ]: c for c in jr.analyze( report( spec ) )[ "comparisons" ] }[ "N" ]
    assert n[ "delta" ] == -0.961539 and n[ "label" ] == jr.WORSE


def test_four_of_five_conditions_is_within_noise_and_not_moved():
    spec = { jp.ARM_BASELINE: flat( 6, 2 ), jp.ARM_PLANT: flat( 6, 2 ), jp.ARM_SHAPED: { 1: ( 12, 1 ), 2: ( 12, 1 ), 3: ( 6, 2 ) }, jp.ARM_BOTH: flat( 6, 2 ) }
    n = { c[ "name" ]: c for c in jr.analyze( report( spec ) )[ "comparisons" ] }[ "N" ]
    assert n[ "met" ] == [ c for c in jr.CRITERIA if c != "every_repeat" ] and n[ "label" ] == jr.WITHIN


CHLOE_HEADER = "pair\tlabel\tlang\tplant_name\toriginal_name\tname_same_as_original\tname_word_jaccard\tname_need_shared_stems\tname_cue\tname_cue_original\tname_cue_need\tline_ratio\tline_jaccard\tline_near_identical\tplant_line_present\toriginal_line_present"


def test_read_cues_reads_chloes_real_header_by_the_exact_column_names(tmp_path):
    """Chloe's real header and two rows; plant_name sits before name_cue."""
    rows = "d-ff5795ef28\tsame_job\tts\tdestroy\tTtsPreviewSliderRendererImpl.unmount\t0\t0.00\t\t0\t0\t0\t0.46\t0.06\t0\t1\t1\n" \
           "d-51d9c4c2ab\tsame_job\tts\tstartRecording\tAudioRecorder.startRecording\t1\t1.00\t\t1\t1\t0\t0.39\t0.20\t1\t1\t1\n"
    assert jr.read_cues( tsv( tmp_path, CHLOE_HEADER + "\n" + rows ) ) == { "d-ff5795ef28": { "name_cue": False, "near_identical": False }, "d-51d9c4c2ab": { "name_cue": True, "near_identical": True } }


def test_a_failed_arm_zero_post_does_not_void_the_floor_but_an_answered_post_with_no_tokens_does():
    failed = report( MOVER )
    at = next( i for i, r in enumerate( failed[ "results" ] ) if r[ "arm" ] == jp.ARM_BASELINE and r[ "repeat" ] == 1 and r[ "pair" ] == "s00" )
    failed[ "results" ][ at ] = row( "s00", jp.ARM_BASELINE, 1, None, answered=False, orig_answered=False, tokens=0 )
    a = jr.analyze( failed )
    assert a[ "proof" ][ "arm0_all_fresh" ] is True and a[ "floor" ][ "valid" ] is True
    assert { "pair": "s00", "arm": jp.ARM_BASELINE, "repeat": 1, "side": "plant" } in a[ "proof" ][ "missing_readings" ]
    cached = report( MOVER )
    cached[ "results" ][ at ] = row( "s00", jp.ARM_BASELINE, 1, HIGH, tokens=0 )
    assert jr.analyze( cached )[ "proof" ][ "arm0_all_fresh" ] is False
