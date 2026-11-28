"""
Run the judge over the validation sample and report it against the pass line.

The judge's model, rubric and prompt hashes are recorded once, before the first call. Every later
step refuses to score under any other hash. The pass line is sensitivity to material errors and
specificity of at least 0.90, each reported with its lower 95% Clopper-Pearson bound. A scored
stratum is one card type and one true class (error or correct). It needs at least 30 cards.

A card type with an unscored stratum reads "judge not validated". The judge is not adopted for
it, and that stratum neither passes nor fails the others.

A pair is material when the human labels say the forecast is wrong in a way that matters. The
judge calls it material when it does not say both that every restriction is kept and that nothing
is invented. A reply the judge could not read counts against it on whichever side the label is.
"""

import argparse
import concurrent.futures
import json
import pathlib
import sys

from cosa.agents.prediction_engine import answer_judge
from cosa.repo.doc_lint import harness_report, judge_comparison
from cosa.repo.duplicate_check.proof import ledger_agreement
from cosa.utils import jsonl_file
from cosa.utils.atomic_json import write_json_atomic
from cosa.utils.file_hash import file_sha256

PASS_FLOOR      = 0.90
MIN_CARDS       = 30
WORKERS         = 4
IDENTITY_FILE   = "judge-identity.json"
EXIT_FAILED     = 1
EXIT_REFUSED    = 2


def record_identity( folder, identity ):
    """
    Record the judge a validation runs under, once.

    Requires:
        - folder is the validation folder; identity is a judge_identity

    Ensures:
        - writes IDENTITY_FILE when it is absent, and returns the recorded identity

    Raises:
        - answer_judge.JudgeHashMismatch when another identity is already recorded
    """
    path = pathlib.Path( folder ) / IDENTITY_FILE
    if path.exists():
        recorded = read_identity( folder )
        answer_judge.check_identity( recorded, identity )
        return recorded
    path.parent.mkdir( parents=True, exist_ok=True )
    write_json_atomic( str( path ), identity, indent=2, trailing_newline=True, sort_keys=True )
    return identity


def read_identity( folder ):
    """
    Read the recorded judge identity of a validation folder.

    Ensures:
        - returns the dict written by record_identity

    Raises:
        - FileNotFoundError when none was recorded
    """
    return json.loads( ( pathlib.Path( folder ) / IDENTITY_FILE ).read_text( encoding="utf-8" ) )


def says_material( verdict ):
    """
    Read a verdict as the judge's call on whether the forecast is materially wrong.

    Requires:
        - verdict holds keeps_every_restriction and invents_nothing

    Ensures:
        - returns False only when both are True
    """
    return not ( verdict[ "keeps_every_restriction" ] and verdict[ "invents_nothing" ] )


def judge_row( judge, pair ):
    """
    Judge one sampled pair and shape the row the verdict file keeps.

    Requires:
        - judge is as answer_judge.make_judge builds it; pair has pair_id, predicted_text and actual_text

    Ensures:
        - returns the verdict with pair_id and material
        - an unreadable reply gives material None with the reason and the raw reply

    Raises:
        - whatever the model call raises: an outage is not a verdict, so nothing is recorded for it
    """
    try:
        verdict = judge( pair[ "predicted_text" ], pair[ "actual_text" ] )
    except answer_judge.JudgeReplyError as error:
        return { "pair_id": pair[ "pair_id" ], "material": None, "error": str( error ), "raw_reply": error.raw_reply }
    return dict( verdict, pair_id=pair[ "pair_id" ], material=says_material( verdict ) )


def run_judge( sample, judge, identity, out_path, workers=WORKERS ):
    """
    Judge every sampled pair that the verdict file does not hold yet.

    Requires:
        - sample is a list of pairs; judge answers under identity; out_path names a JSON Lines file

    Ensures:
        - appends one row per new pair, each carrying identity, as soon as it is judged
        - a pair already in the file is not judged again, so an interrupted run resumes
        - returns the number of pairs judged now

    Raises:
        - answer_judge.JudgeHashMismatch when the file holds a row from another judge, before any call
        - whatever a model call raises; the rows already written stay
    """
    held = jsonl_file.read_jsonl( pathlib.Path( out_path ), missing_ok=True )
    for row in held: answer_judge.check_identity( identity, row[ "identity" ] )
    done = { row[ "pair_id" ] for row in held }
    todo = [ pair for pair in sample if pair[ "pair_id" ] not in done ]
    with concurrent.futures.ThreadPoolExecutor( max_workers=workers ) as pool, open( out_path, "a", encoding="utf-8" ) as handle:
        for future in concurrent.futures.as_completed( [ pool.submit( judge_row, judge, pair ) for pair in todo ] ):
            row = dict( future.result(), identity=identity )
            handle.write( json.dumps( row, sort_keys=True ) + "\n" )
            handle.flush()
    return len( todo )


def proportion( successes, trials ):
    """
    Describe a count out of a total with its 95% interval.

    Ensures:
        - returns { successes, trials, rate, lower, upper }; rate, lower and upper are None for no trials
    """
    bounds = harness_report.interval( successes, trials )
    return { "successes": successes, "trials": trials, "rate": successes / trials if trials else None,
             "lower": None if bounds is None else bounds[ 0 ], "upper": None if bounds is None else bounds[ 1 ] }


def weighted_rate( rows, hit ):
    """
    Give a rate with each row weighted by one over its inclusion probability.

    Requires:
        - rows hold inclusion; hit maps a row to a bool

    Ensures:
        - returns None for no rows
    """
    total = sum( 1 / row[ "inclusion" ] for row in rows )
    return sum( 1 / row[ "inclusion" ] for row in rows if hit( row ) ) / total if total else None


def agreement( first, second ):
    """
    Measure how two lists of material calls agree.

    Requires:
        - first and second are equal-length lists of bools

    Ensures:
        - returns { n, kappa, positive, negative }
        - each figure is None for no items, and kappa is None, with a reason, when it is undefined
    """
    if not first: return { "n": 0, "kappa": None, "positive": None, "negative": None, "reason": "no items" }
    cells              = list( zip( first, second ) )
    table              = tuple( cells.count( cell ) for cell in ( ( True, True ), ( True, False ), ( False, True ), ( False, False ) ) )
    kappa              = ledger_agreement.kappa( table )
    positive, negative = ledger_agreement.positive_negative( table )
    result             = { "n": len( first ), "kappa": kappa, "positive": positive, "negative": negative }
    if kappa is None: result[ "reason" ] = "both used one category"
    return result


def arm_bias( rows, key ):
    """
    Split the judge's misses and false alarms by the arm that made each forecast.

    Requires:
        - rows hold pair_id, human (bool) and judge (bool or None); key is { pair_id: { arm, model } }

    Ensures:
        - returns judge_comparison.group_rows' rows, one per ( arm and model, material or not ) that has pairs

    Raises:
        - ValueError when a pair has no key
    """
    def label( entry ):
        """Name one arm with its model."""
        return f"{entry[ 'arm' ]} ({entry[ 'model' ]})"

    results, keys = [], {}
    for row in rows:
        pair_id = row[ "pair_id" ]
        if pair_id not in key: raise ValueError( f"pair {pair_id} has no key" )
        keys[ pair_id ] = f"{label( key[ pair_id ] )} · {'material' if row[ 'human' ] else 'not material'}"
        results.append( { "id": pair_id, "seed_span": ( 0, 0 ) if row[ "human" ] else None, "lists": [ row[ "judge" ] != row[ "human" ] ] } )
    return judge_comparison.group_rows( results, keys, 1, names=sorted( set( keys.values() ) ), names_of=lambda name: [ name ],
                                        wrong_of=lambda result, slot: result[ "lists" ][ slot ] )


def check_labels( labels ):
    """
    Refuse a label whose value is not a boolean or None.

    Requires:
        - labels rows hold pair_id and material_error, and may hold readers

    Ensures:
        - returns None when every material_error and every reader value is True, False or None

    Raises:
        - ValueError naming the pair and the value otherwise, so a word such as "no" is never read as true
    """
    for row in labels:
        for value in [ row[ "material_error" ], *row.get( "readers", {} ).values() ]:
            if value is not None and not isinstance( value, bool ):
                raise ValueError( f"pair {row[ 'pair_id' ]}: a label must be true, false or null, not {value!r}" )


def pass_line( rows, planned ):
    """
    Work out the strata and the two pooled rates over one set of labelled rows.

    Requires:
        - rows hold response_type, notification_id, inclusion, human (bool) and judge (bool or None)
        - planned lists every stratum, "<card type>/error" and "<card type>/correct"

    Ensures:
        - returns { strata, scored, material, fine, sensitivity, specificity, passes }
        - a stratum with fewer than MIN_CARDS distinct cards is not scored and its rows are not pooled
        - passes is True only when both classes have a scored row and both rates are at least PASS_FLOOR
    """
    named  = [ ( f"{row[ 'response_type' ]}/{'error' if row[ 'human' ] else 'correct'}", row ) for row in rows ]
    strata = {}
    for name in planned:
        held  = [ row for own, row in named if own == name ]
        cards = len( { row[ "notification_id" ] for row in held } )
        right = proportion( sum( 1 for row in held if row[ "judge" ] is row[ "human" ] ), len( held ) )
        strata[ name ] = dict( right, cards=cards, scored=cards >= MIN_CARDS )
    scored      = [ row for own, row in named if strata[ own ][ "scored" ] ]
    material    = [ row for row in scored if row[ "human" ] ]
    fine        = [ row for row in scored if not row[ "human" ] ]
    sensitivity = proportion( sum( 1 for row in material if row[ "judge" ] is True ), len( material ) )
    specificity = proportion( sum( 1 for row in fine if row[ "judge" ] is False ), len( fine ) )
    sensitivity[ "weighted_rate" ] = weighted_rate( material, lambda row: row[ "judge" ] is True )
    specificity[ "weighted_rate" ] = weighted_rate( fine, lambda row: row[ "judge" ] is False )
    passes      = bool( material and fine ) and sensitivity[ "rate" ] >= PASS_FLOOR and specificity[ "rate" ] >= PASS_FLOOR
    return { "strata": strata, "scored": scored, "material": material, "fine": fine,
             "sensitivity": sensitivity, "specificity": specificity, "passes": passes }


def reader_agreement( pair_ids, labelled ):
    """
    Measure each pair of readers against each other over every sampled pair both labelled.

    Requires:
        - labelled is { pair_id: label row }; a row may hold readers, a { name: True, False or None } map

    Ensures:
        - returns { "<first> / <second>": agreement }, the names in order, unresolved pairs included
    """
    maps  = [ { name: value for name, value in labelled[ pair_id ].get( "readers", {} ).items() if value is not None } for pair_id in pair_ids ]
    names = sorted( { name for held in maps for name in held } )
    out   = {}
    for i, first in enumerate( names ):
        for second in names[ i + 1: ]:
            both = [ held for held in maps if first in held and second in held ]
            out[ f"{first} / {second}" ] = agreement( [ held[ first ] for held in both ], [ held[ second ] for held in both ] )
    return out


def build_report( sample, verdicts, labels, key, recorded, current ):
    """
    Report the judge against the human labels and the pass line.

    Requires:
        - sample rows come from draw.draw_sample
        - verdicts rows come from run_judge; labels rows hold pair_id and material_error (True, False, or None
          for unresolved), and may hold readers, a { reader name: True, False or None } map
        - key is { pair_id: { arm, model } }; recorded and current are judge identities

    Ensures:
        - an unresolved pair is left out of the pass line and counted; unresolved_bounds gives the line again with
          every unresolved pair counted as an error, then as correct
        - strata are card type by true class; each gives the judge's agreement with the label and its interval
        - a stratum with fewer than MIN_CARDS distinct cards is named in unscored_strata and not scored
        - card_types says "validated" for a type only when the line passes and both its strata are scored
        - patterns gives the same agreement by how the two texts differ, over every resolved pair
        - sensitivity and specificity pool the scored strata; each carries its Clopper-Pearson interval and an
          inverse-inclusion weighted rate
        - passes is True only when both classes have a scored stratum and both rates are at least PASS_FLOOR
        - judge_against_human covers the scored pairs; human_against_human covers each pair of readers on every
          sampled pair both labelled

    Raises:
        - answer_judge.JudgeHashMismatch when the current judge or any verdict row differs from the recorded one
        - ValueError when a sampled pair has no verdict, no label line or no key, or a label value is not a boolean or None
    """
    answer_judge.check_identity( recorded, current )
    for row in verdicts: answer_judge.check_identity( recorded, row[ "identity" ] )
    check_labels( labels )
    judged   = { row[ "pair_id" ]: row for row in verdicts }
    labelled = { row[ "pair_id" ]: row for row in labels }
    rows, open_rows = [], []
    for pair in sample:
        pair_id = pair[ "pair_id" ]
        if pair_id not in judged:   raise ValueError( f"pair {pair_id} has no verdict" )
        if pair_id not in labelled: raise ValueError( f"pair {pair_id} has no label" )
        human = labelled[ pair_id ][ "material_error" ]
        row   = dict( pair, human=human, judge=judged[ pair_id ][ "material" ] )
        ( open_rows if human is None else rows ).append( row )

    planned     = sorted( { f"{pair[ 'response_type' ]}/{truth}" for pair in sample for truth in ( "error", "correct" ) } )
    line        = pass_line( rows, planned )
    strata, scored, material, fine = line[ "strata" ], line[ "scored" ], line[ "material" ], line[ "fine" ]
    patterns = {}
    for name in sorted( { row[ "pattern" ] for row in rows } ):
        held = [ row for row in rows if row[ "pattern" ] == name ]
        patterns[ name ] = proportion( sum( 1 for row in held if row[ "judge" ] is row[ "human" ] ), len( held ) )
    sensitivity = proportion( sum( 1 for row in material if row[ "judge" ] is True ), len( material ) )
    specificity = proportion( sum( 1 for row in fine if row[ "judge" ] is False ), len( fine ) )
    sensitivity[ "weighted_rate" ] = weighted_rate( material, lambda row: row[ "judge" ] is True )
    specificity[ "weighted_rate" ] = weighted_rate( fine, lambda row: row[ "judge" ] is False )

    answered = [ row for row in scored if row[ "judge" ] is not None ]
    bounds   = {}
    for name, value in ( ( "unresolved_as_error", True ), ( "unresolved_as_correct", False ) ):
        filled = pass_line( rows + [ dict( row, human=value ) for row in open_rows ], planned )
        bounds[ name ] = { field: filled[ field ] for field in ( "sensitivity", "specificity", "passes" ) }

    settings = { json.dumps( row[ "request_settings" ], sort_keys=True ) for row in verdicts if row.get( "request_settings" ) is not None }
    sensitivity, specificity, passes = line[ "sensitivity" ], line[ "specificity" ], line[ "passes" ]
    return {
        "identity"            : recorded,
        "request_settings"    : [ json.loads( text ) for text in sorted( settings ) ],
        "pass_floor"          : PASS_FLOOR,
        "min_cards"           : MIN_CARDS,
        "pairs"               : len( sample ),
        "unresolved"          : len( open_rows ),
        "unresolved_bounds"   : bounds,
        "unreadable"          : sum( 1 for row in rows if row[ "judge" ] is None ),
        "strata"              : strata,
        "unscored_strata"     : [ name for name in planned if not strata[ name ][ "scored" ] ],
        "card_types"          : { kind: "validated" if passes and all( strata[ f"{kind}/{truth}" ][ "scored" ] for truth in ( "error", "correct" ) )
                                  else "judge not validated" for kind in sorted( { pair[ "response_type" ] for pair in sample } ) },
        "patterns"            : patterns,
        "class_counts"        : { "material": len( material ), "not_material": len( fine ) },
        "sensitivity"         : sensitivity,
        "specificity"         : specificity,
        "judge_against_human" : agreement( [ row[ "judge" ] for row in answered ], [ row[ "human" ] for row in answered ] ),
        "human_against_human" : reader_agreement( [ pair[ "pair_id" ] for pair in sample ], labelled ),
        "arm_bias"            : arm_bias( scored, key ),
        "passes"              : passes,
    }


def main( argv=None, make_judge=answer_judge.make_judge ):
    """
    Judge a drawn sample ( run ) or report it ( report ) from the command line.

    Ensures:
        - run records the identity, judges what is missing, and returns 0
        - report writes the report file with the sha256 of each input, prints it, and returns 0 on a pass
          and EXIT_FAILED on a miss
        - a hash mismatch or a missing row returns EXIT_REFUSED and writes no report
    """
    parser = argparse.ArgumentParser( description="Validate the answer judge." )
    parser.add_argument( "step", choices=( "run", "report" ) )
    parser.add_argument( "--folder", required=True, help="holds sample.jsonl, the identity, the verdicts and the report" )
    parser.add_argument( "--model", help="default: the configured judge model" )
    parser.add_argument( "--workers", type=int, default=WORKERS )
    parser.add_argument( "--labels" )
    parser.add_argument( "--key" )
    args   = parser.parse_args( argv )
    folder = pathlib.Path( args.folder )
    sample = jsonl_file.read_jsonl( folder / "sample.jsonl" )
    try:
        current = answer_judge.judge_identity( args.model )
        if args.step == "run":
            identity = record_identity( folder, current )
            judge    = make_judge( args.model, expected_identity=identity )
            print( f"judged {run_judge( sample, judge, identity, folder / 'verdicts.jsonl', args.workers )} pairs" )
            return 0
        if args.labels is None or args.key is None: raise ValueError( "report needs --labels and --key" )
        report = build_report( sample, jsonl_file.read_jsonl( folder / "verdicts.jsonl" ), jsonl_file.read_jsonl( pathlib.Path( args.labels ) ),
                               json.loads( pathlib.Path( args.key ).read_text( encoding="utf-8" ) ), read_identity( folder ), current )
    except ( answer_judge.JudgeHashMismatch, ValueError ) as error:
        print( error, file=sys.stderr )
        return EXIT_REFUSED
    report[ "inputs" ] = { name: file_sha256( str( path ) ) for name, path in
                           ( ( "sample", folder / "sample.jsonl" ), ( "verdicts", folder / "verdicts.jsonl" ), ( "labels", args.labels ), ( "key", args.key ) ) }
    write_json_atomic( str( folder / "report.json" ), report, indent=2, trailing_newline=True, sort_keys=True )
    print( json.dumps( report, indent=2, sort_keys=True ) )
    return 0 if report[ "passes" ] else EXIT_FAILED


if __name__ == "__main__":
    sys.exit( main() )
