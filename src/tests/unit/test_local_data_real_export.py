"""
The real-data check for the Preference learning export (the `local_data` tier).

These tests read Rick's real answers from the main checkout's gitignored
`io/write-ups/online-preference-learning/`. In a worktree the folder is absent.
Each test then skips by name. The real run is made in the main checkout with
`--require-local-data`. Nothing here commits or copies any of that data.
"""

import json

import pytest

from cosa.utils.notification_utils import extract_qualifier_comment
from cosa.utils.local_data_tier import MANIFEST_FILE_NAME, require_local_file, sha256_of_file

EXPORT_FILE_NAME = "2026.11.17-recent-predictions-285.json"

pytestmark = pytest.mark.local_data


def test_the_real_export_still_matches_the_manifest_sha():
    """The moved file is byte-identical to the one the manifest recorded before the move."""
    export_path   = require_local_file( EXPORT_FILE_NAME )
    manifest_path = require_local_file( MANIFEST_FILE_NAME )
    recorded      = dict( ( line.split( "  " )[ 1 ], line.split( "  " )[ 0 ] )
                          for line in open( manifest_path ).read().splitlines() if line.strip() )
    assert recorded[ EXPORT_FILE_NAME ] == sha256_of_file( export_path )


def test_the_real_export_holds_the_285_rows_and_139_yes_no_asks():
    """The cohort the later phases replay: 285 predictions, 139 of them yes/no."""
    predictions = json.load( open( require_local_file( EXPORT_FILE_NAME ) ) )[ "predictions" ]
    assert len( predictions ) == 285
    assert sum( 1 for p in predictions if p[ "response_type" ] == "yes_no" ) == 139


def test_tightening_the_parser_loses_no_yes_vote_in_the_export():
    """
    The parser leaves one stored answer without a stance, and it is not a yes.

    Recomputed from the export itself. The export holds 139 yes/no asks and the 311 distinct yes/no cases that were their neighbours.
    The old vote read an answer that did not start with "yes" as "no". So an unrecognised answer
    that does not start with "yes" loses no yes vote when the parser is tightened.
    """
    export      = json.load( open( require_local_file( EXPORT_FILE_NAME ) ) )[ "predictions" ]
    neighbours  = json.load( open( require_local_file( "2026.11.17-recent-predictions-285-neighbours.json" ) ) )[ "neighbours" ]
    yes_no      = [ p for p in export if p[ "response_type" ] == "yes_no" ]
    actual      = [ p[ "actual" ][ "value" ] for p in yes_no ]
    stored      = { c[ "case_id" ]: c[ "answer" ] for p in yes_no for c in neighbours[ p[ "neighbours_ref" ] ][ "by_dot" ] }
    assert ( len( actual ), len( stored ) ) == ( 139, 311 )
    unrecognised = [ v for v in actual + list( stored.values() ) if extract_qualifier_comment( v )[ 0 ] is None ]
    assert len( unrecognised ) == 1
    assert not any( v.lower().startswith( "yes" ) for v in unrecognised )
