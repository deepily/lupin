"""
Run the minimal pairs: the judge must flip its verdict on every one, run once each.

A minimal pair is an answer's condition, a forecast that matches it, and the same forecast with one
thing altered. The judge flips when it passes the first and fails the second. The set holds four
pairs of each of six kinds. One run is allowed per judge identity and set. The result file is
named for both and never overwritten. A second run needs a changed prompt, rubric, model or set.
"""

import argparse
import hashlib
import json
import pathlib
import sys

from cosa.agents.prediction_engine import answer_judge
from cosa.research.judge_validation import scoring
from cosa.utils.file_hash import file_sha256

KINDS         = ( "before_after", "staging_production", "must_may", "negated_permission", "scope_change", "time_change" )
PER_KIND      = 4
FIELDS        = ( "id", "kind", "actual_text", "matching_text", "altered_text" )
EXIT_FAILED   = 1
EXIT_REFUSED  = 2


def read_pairs( path ):
    """
    Read and check the minimal-pair set.

    Requires:
        - path names a JSON file { "pairs": [ ... ] }; other keys are not read

    Ensures:
        - returns the pairs: four of each of the six kinds, with unique ids and non-empty text fields

    Raises:
        - ValueError for a missing field, an empty one, a repeated id, or a wrong count of any kind
    """
    pairs = json.loads( pathlib.Path( path ).read_text( encoding="utf-8" ) )[ "pairs" ]
    for pair in pairs:
        for field in FIELDS:
            if not isinstance( pair.get( field ), str ) or not pair[ field ].strip(): raise ValueError( f"pair {pair.get( 'id' )}: {field} is missing or empty" )
    if len( { pair[ "id" ] for pair in pairs } ) != len( pairs ): raise ValueError( "a pair id appears more than once" )
    counts = { kind: sum( 1 for pair in pairs if pair[ "kind" ] == kind ) for kind in KINDS }
    if any( count != PER_KIND for count in counts.values() ) or len( pairs ) != PER_KIND * len( KINDS ):
        raise ValueError( f"the set needs {PER_KIND} pairs of each of {KINDS}, and holds {counts} of {len( pairs )}" )
    return pairs


def run_pair( judge, pair ):
    """
    Judge one minimal pair, once each side.

    Requires:
        - judge is as answer_judge.make_judge builds it; pair is one row of read_pairs

    Ensures:
        - returns { id, kind, matching, altered, flipped, error }
        - flipped is True only when the matching text passes and the altered text fails
        - an unreadable reply is not a flip, and error holds its reason
    """
    row = { "id": pair[ "id" ], "kind": pair[ "kind" ], "matching": None, "altered": None, "flipped": False, "error": None }
    try:
        row[ "matching" ] = judge( pair[ "matching_text" ], pair[ "actual_text" ] )
        row[ "altered" ]  = judge( pair[ "altered_text" ], pair[ "actual_text" ] )
    except answer_judge.JudgeReplyError as error:
        row[ "error" ] = str( error )
        return row
    row[ "flipped" ] = not scoring.says_material( row[ "matching" ] ) and scoring.says_material( row[ "altered" ] )
    return row


def result_path( folder, identity, set_sha256 ):
    """
    Name the one result file of a judge identity and a pair set.

    Ensures:
        - the name changes with any identity field or with the set
    """
    text = "|".join( [ identity[ field ] for field in answer_judge.IDENTITY_FIELDS ] + [ set_sha256 ] )
    return pathlib.Path( folder ) / f"minimal-pairs-{hashlib.sha256( text.encode( 'utf-8' ) ).hexdigest()[ :16 ]}.json"


def run_set( set_path, folder, judge, identity ):
    """
    Run the whole set once and write its result.

    Requires:
        - judge answers under identity; folder is the validation folder

    Ensures:
        - returns the result: identity, set_sha256, total, flipped, passed and one row per pair
        - passed is True only when every pair flipped
        - the result file is opened before the first call, so a second run is refused and calls nothing

    Raises:
        - FileExistsError when this identity has already run this set
        - ValueError as read_pairs raises it
        - whatever a model call raises: the claimed file is then removed, so the run can be made
    """
    pairs      = read_pairs( set_path )
    set_sha256 = file_sha256( str( set_path ) )
    path       = result_path( folder, identity, set_sha256 )
    path.parent.mkdir( parents=True, exist_ok=True )
    handle     = open( path, "x", encoding="utf-8" )
    try:
        rows   = [ run_pair( judge, pair ) for pair in pairs ]
        result = { "identity": identity, "set_sha256": set_sha256, "total": len( rows ),
                   "flipped": sum( 1 for row in rows if row[ "flipped" ] ), "passed": all( row[ "flipped" ] for row in rows ), "pairs": rows }
        json.dump( result, handle, indent=2, sort_keys=True )
    except BaseException:
        handle.close()
        path.unlink()
        raise
    handle.close()
    return result


def main( argv=None, make_judge=answer_judge.make_judge ):
    """
    Run the minimal pairs from the command line.

    Ensures:
        - records the identity in the folder, runs the set once and prints the counts and the misses
        - returns 0 when every pair flipped, EXIT_FAILED when one did not, and EXIT_REFUSED when refused
    """
    parser = argparse.ArgumentParser( description="Run the judge's minimal pairs." )
    parser.add_argument( "--pairs", required=True )
    parser.add_argument( "--folder", required=True )
    parser.add_argument( "--model", default=answer_judge.DEFAULT_MODEL )
    args = parser.parse_args( argv )
    try:
        identity = scoring.record_identity( args.folder, answer_judge.judge_identity( args.model ) )
        result   = run_set( args.pairs, args.folder, make_judge( args.model, expected_identity=identity ), identity )
    except ( answer_judge.JudgeHashMismatch, ValueError, FileExistsError ) as error:
        print( error, file=sys.stderr )
        return EXIT_REFUSED
    print( f"flipped {result[ 'flipped' ]} of {result[ 'total' ]}; missed: {[ row[ 'id' ] for row in result[ 'pairs' ] if not row[ 'flipped' ] ]}" )
    return 0 if result[ "passed" ] else EXIT_FAILED


if __name__ == "__main__":
    sys.exit( main() )
