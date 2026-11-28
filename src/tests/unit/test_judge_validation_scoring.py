"""
Tests for judge validation scoring: identity, run, pass line, agreement and arm bias.

Figures are written as literals worked from the planted counts.
"""

import json

import pytest

from cosa.agents.prediction_engine import answer_judge as aj
from cosa.research.judge_validation import scoring

IDENTITY = { "model": "m", "rubric_sha256": "r", "prompt_sha256": "p" }
OTHER    = dict( IDENTITY, rubric_sha256="r2" )


def verdict( ok ):
    """A verdict that passes or fails both ways."""
    return { "keeps_every_restriction": ok, "invents_nothing": True, "request_settings": { "model": "m", "sampling": {} } }


def judge_by_text( predicted, actual ):
    """Pass when the texts agree; 'garble' is an unreadable reply."""
    if predicted == "garble": raise aj.JudgeReplyError( "unreadable", "???" )
    return verdict( predicted == actual )


def sample_row( n, kind="yes_no", card=None, inclusion=0.5, predicted="a", actual="b" ):
    return { "pair_id": f"p{n}", "notification_id": card or f"card{n}", "response_type": kind, "pattern": "differ", "inclusion": inclusion,
             "predicted_text": predicted, "actual_text": actual }


def planted( caught=29, missed=1, passed=28, false_alarm=2 ):
    """A stratum of material and fine pairs with a set number of judge errors."""
    plan = [ ( True, True ) ] * caught + [ ( True, False ) ] * missed + [ ( False, False ) ] * passed + [ ( False, True ) ] * false_alarm
    sample   = [ sample_row( n ) for n in range( len( plan ) ) ]
    labels   = [ { "pair_id": f"p{n}", "material_error": human, "readers": { "one": human, "two": human } } for n, ( human, _ ) in enumerate( plan ) ]
    verdicts = [ { "pair_id": f"p{n}", "material": call, "identity": IDENTITY, "request_settings": { "sampling": {} } } for n, ( _, call ) in enumerate( plan ) ]
    key      = { f"p{n}": { "arm": "B1" if n % 2 else "C0", "model": "haiku" } for n in range( len( plan ) ) }
    return sample, verdicts, labels, key


def report_of( parts, current=None ):
    return scoring.build_report( *parts, IDENTITY, current or IDENTITY )


@pytest.mark.parametrize( "keeps, invents_nothing, material", [ ( True, True, False ), ( True, False, True ), ( False, True, True ), ( False, False, True ) ] )
def test_a_pair_is_material_unless_both_booleans_hold( keeps, invents_nothing, material ):
    assert scoring.says_material( { "keeps_every_restriction": keeps, "invents_nothing": invents_nothing } ) is material


def test_the_identity_is_recorded_once_and_another_is_refused( tmp_path ):
    assert scoring.record_identity( tmp_path / "v", IDENTITY ) == IDENTITY
    assert scoring.record_identity( tmp_path / "v", IDENTITY ) == IDENTITY
    with pytest.raises( aj.JudgeHashMismatch, match="rubric_sha256" ):
        scoring.record_identity( tmp_path / "v", OTHER )
    assert scoring.read_identity( tmp_path / "v" ) == IDENTITY


def test_the_run_resumes_and_keeps_unreadable_replies( tmp_path ):
    out    = tmp_path / "verdicts.jsonl"
    sample = [ sample_row( 1, predicted="a", actual="a" ), sample_row( 2, predicted="garble" ), sample_row( 3 ) ]
    assert scoring.run_judge( sample[ :2 ], judge_by_text, IDENTITY, out, workers=2 ) == 2
    assert scoring.run_judge( sample, judge_by_text, IDENTITY, out ) == 1
    rows = { row[ "pair_id" ]: row for row in map( json.loads, out.read_text().splitlines() ) }
    assert [ rows[ p ][ "material" ] for p in ( "p1", "p2", "p3" ) ] == [ False, None, True ]
    assert rows[ "p2" ][ "raw_reply" ] == "???" and all( row[ "identity" ] == IDENTITY for row in rows.values() )


def test_a_verdict_file_from_another_judge_stops_the_run_before_any_call( tmp_path ):
    out = tmp_path / "verdicts.jsonl"
    out.write_text( json.dumps( { "pair_id": "p1", "identity": OTHER } ) + "\n" )
    def never( *args ): raise AssertionError( "called" )
    with pytest.raises( aj.JudgeHashMismatch ):
        scoring.run_judge( [ sample_row( 2 ) ], never, IDENTITY, out )


def test_an_outage_is_not_recorded_as_a_verdict( tmp_path ):
    def down( *args ): raise RuntimeError( "outage" )
    with pytest.raises( RuntimeError, match="outage" ):
        scoring.run_judge( [ sample_row( 1 ) ], down, IDENTITY, tmp_path / "v.jsonl" )
    assert ( tmp_path / "v.jsonl" ).read_text() == ""


def test_the_report_gives_rates_intervals_agreement_and_passes():
    report = report_of( planted() )
    assert report[ "passes" ] is True and report[ "class_counts" ] == { "material": 30, "not_material": 30 }
    assert ( report[ "sensitivity" ][ "successes" ], report[ "sensitivity" ][ "trials" ] ) == ( 29, 30 )
    assert report[ "sensitivity" ][ "lower" ] == pytest.approx( 0.8278, abs=1e-4 )
    assert report[ "specificity" ][ "rate" ] == pytest.approx( 28 / 30 )
    assert report[ "specificity" ][ "weighted_rate" ] == pytest.approx( 28 / 30 )
    assert report[ "judge_against_human" ][ "kappa" ] == pytest.approx( 0.9 )
    assert report[ "human_against_human" ][ "one / two" ][ "kappa" ] == pytest.approx( 1.0 )
    assert report[ "request_settings" ] == [ { "sampling": {} } ] and report[ "unscored_strata" ] == []
    assert report[ "card_types" ] == { "yes_no": "validated" }
    assert report[ "strata" ][ "yes_no/error" ][ "successes" ] == 29 and report[ "patterns" ][ "differ" ][ "trials" ] == 60
    groups = { row[ "group" ]: row for row in report[ "arm_bias" ] }
    assert sum( row[ "n" ] for row in groups.values() ) == 60 and sum( row[ "wrong" ] for row in groups.values() ) == 3
    assert groups[ "C0 (haiku) · material" ][ "bound" ] is not None


@pytest.mark.parametrize( "counts", [ dict( caught=26, missed=4 ), dict( passed=26, false_alarm=4 ) ] )
def test_either_rate_below_the_floor_misses_the_line( counts ):
    assert report_of( planted( **counts ) )[ "passes" ] is False


def test_an_unreadable_reply_counts_against_the_judge_on_both_sides():
    sample, verdicts, labels, key = planted( caught=30, missed=0, passed=30, false_alarm=0 )
    verdicts[ 0 ][ "material" ] = None
    verdicts[ 59 ][ "material" ] = None
    report = report_of( ( sample, verdicts, labels, key ) )
    assert report[ "sensitivity" ][ "successes" ] == 29 and report[ "specificity" ][ "successes" ] == 29
    assert report[ "unreadable" ] == 2 and report[ "judge_against_human" ][ "n" ] == 58


def test_a_stratum_under_thirty_cards_is_listed_and_not_scored():
    sample, verdicts, labels, key = planted()
    for n in range( 60, 90 ):
        sample.append( sample_row( n, kind="multiple_choice", card="one-card" if n < 89 else "other" ) )
        labels.append( { "pair_id": f"p{n}", "material_error": True } )
        verdicts.append( { "pair_id": f"p{n}", "material": False, "identity": IDENTITY } )
        key[ f"p{n}" ] = { "arm": "B1", "model": "haiku" }
    labels[ 0 ][ "material_error" ] = None
    report = report_of( ( sample, verdicts, labels, key ) )
    small  = report[ "strata" ][ "multiple_choice/error" ]
    assert ( small[ "trials" ], small[ "successes" ], small[ "cards" ], small[ "scored" ] ) == ( 30, 0, 2, False )
    assert report[ "unscored_strata" ] == [ "multiple_choice/correct", "multiple_choice/error", "yes_no/error" ]
    assert report[ "unresolved" ] == 1 and report[ "sensitivity" ][ "trials" ] == 0 and report[ "passes" ] is False
    assert set( report[ "card_types" ].values() ) == { "judge not validated" }


def test_an_unscored_cell_leaves_the_other_types_passing():
    sample, verdicts, labels, key = planted( caught=30, missed=0, passed=30, false_alarm=0 )
    sample.append( sample_row( 60, kind="open_ended" ) )
    labels.append( { "pair_id": "p60", "material_error": True } )
    verdicts.append( { "pair_id": "p60", "material": False, "identity": IDENTITY } )
    key[ "p60" ] = { "arm": "B1", "model": "haiku" }
    report = report_of( ( sample, verdicts, labels, key ) )
    assert report[ "passes" ] is True and report[ "card_types" ] == { "open_ended": "judge not validated", "yes_no": "validated" }


def test_no_scored_stratum_never_passes():
    report = report_of( planted( caught=2, missed=0, passed=2, false_alarm=0 ) )
    assert report[ "passes" ] is False and report[ "arm_bias" ] == []
    assert report[ "sensitivity" ] == { "successes": 0, "trials": 0, "rate": None, "lower": None, "upper": None, "weighted_rate": None }
    assert report[ "judge_against_human" ][ "reason" ] == "no items"


@pytest.mark.parametrize( "field, value", [ ( "material_error", "no" ), ( "material_error", "can't tell" ), ( "material_error", 0 ), ( "readers", { "one": "no" } ) ] )
def test_a_label_that_is_not_a_boolean_is_refused( field, value ):
    parts = planted()
    parts[ 2 ][ 3 ][ field ] = value
    with pytest.raises( ValueError, match="pair p3: a label must be true, false or null" ):
        report_of( parts )


def test_a_reader_who_could_not_tell_is_left_out_of_that_pair():
    parts = planted()
    parts[ 2 ][ 3 ][ "readers" ] = { "one": None, "two": True }
    assert report_of( parts )[ "human_against_human" ][ "one / two" ][ "n" ] == 59


def test_a_missed_line_validates_no_card_type():
    report = report_of( planted( caught=26, missed=4 ) )
    assert report[ "unscored_strata" ] == [] and report[ "card_types" ] == { "yes_no": "judge not validated" }


def test_unresolved_pairs_are_bounded_both_ways_and_readers_are_compared_on_every_pair():
    sample, verdicts, labels, key = planted( caught=30, missed=0, passed=30, false_alarm=0 )
    for n in ( 0, 1, 2, 3, 4 ):
        labels[ n ] = { "pair_id": f"p{n}", "material_error": None, "readers": { "one": True, "two": False } }
    report = report_of( ( sample + [ sample_row( 60 ) ], verdicts + [ dict( verdicts[ 59 ], pair_id="p60" ) ],
                          labels + [ { "pair_id": "p60", "material_error": False } ], dict( key, p60={ "arm": "B1", "model": "haiku" } ) ) )
    assert report[ "unresolved" ] == 5 and report[ "human_against_human" ][ "one / two" ][ "n" ] == 60
    bounds = report[ "unresolved_bounds" ]
    assert ( bounds[ "unresolved_as_error" ][ "sensitivity" ][ "successes" ], bounds[ "unresolved_as_error" ][ "sensitivity" ][ "trials" ] ) == ( 30, 30 )
    assert ( bounds[ "unresolved_as_correct" ][ "specificity" ][ "successes" ], bounds[ "unresolved_as_correct" ][ "specificity" ][ "trials" ] ) == ( 31, 36 )
    assert bounds[ "unresolved_as_correct" ][ "passes" ] is False


def test_agreement_says_why_kappa_is_undefined():
    assert scoring.agreement( [ True, True ], [ True, True ] ) == { "n": 2, "kappa": None, "positive": 1.0, "negative": None, "reason": "both used one category" }


@pytest.mark.parametrize( "drop, words", [ ( 1, "no verdict" ), ( 2, "no label" ), ( 3, "no key" ) ] )
def test_a_sampled_pair_with_a_missing_input_is_refused( drop, words ):
    parts = list( planted() )
    if drop == 3: del parts[ 3 ][ "p5" ]
    else: parts[ drop ] = [ row for row in parts[ drop ] if row[ "pair_id" ] != "p5" ]
    with pytest.raises( ValueError, match=words ):
        report_of( parts )


def test_the_report_refuses_another_judge_now_or_in_any_row():
    with pytest.raises( aj.JudgeHashMismatch ):
        report_of( planted(), current=OTHER )
    parts = planted()
    parts[ 1 ][ 7 ][ "identity" ] = OTHER
    with pytest.raises( aj.JudgeHashMismatch ):
        report_of( parts )


def write_folder( folder, parts ):
    """Lay out a validation folder with sample, labels and key files."""
    sample, _, labels, key = parts
    folder.mkdir()
    ( folder / "sample.jsonl" ).write_text( "".join( json.dumps( r ) + "\n" for r in sample ) )
    ( folder / "labels.jsonl" ).write_text( "".join( json.dumps( r ) + "\n" for r in labels ) )
    ( folder / "key.json" ).write_text( json.dumps( key ) )
    return [ "--folder", str( folder ), "--labels", str( folder / "labels.jsonl" ), "--key", str( folder / "key.json" ) ]


@pytest.mark.parametrize( "agree, code", [ ( True, 0 ), ( False, scoring.EXIT_FAILED ) ] )
def test_the_command_runs_then_reports( tmp_path, capsys, agree, code ):
    parts = planted( caught=30, missed=0, passed=30, false_alarm=0 )
    for row, label in zip( parts[ 0 ], parts[ 2 ] ):
        row[ "predicted_text" ] = "a"
        row[ "actual_text" ]    = "b" if label[ "material_error" ] == agree else "a"
    folder = tmp_path / "v"
    args   = write_folder( folder, parts )
    maker  = lambda model, expected_identity: ( lambda p, a: dict( verdict( p == a ), identity=expected_identity ) )
    assert scoring.main( [ "run", "--folder", str( folder ) ], make_judge=maker ) == 0
    assert "judged 60 pairs" in capsys.readouterr().out
    assert scoring.main( [ "report" ] + args ) == code
    report = json.loads( ( folder / "report.json" ).read_text() )
    assert report[ "passes" ] is agree and set( report[ "inputs" ] ) == { "sample", "verdicts", "labels", "key" }


def test_the_command_refuses_and_writes_no_report( tmp_path, capsys ):
    folder = tmp_path / "v"
    args   = write_folder( folder, planted() )
    assert scoring.main( [ "report", "--folder", str( folder ) ] ) == scoring.EXIT_REFUSED
    assert "needs --labels" in capsys.readouterr().err
    scoring.record_identity( folder, OTHER )
    ( folder / "verdicts.jsonl" ).write_text( "" )
    assert scoring.main( [ "report" ] + args ) == scoring.EXIT_REFUSED
    assert "refusing to score" in capsys.readouterr().err and not ( folder / "report.json" ).exists()
