"""
The real-data check for the Preference learning export (the `local_data` tier).

These tests read Rick's real answers from the main checkout's gitignored
`io/write-ups/online-preference-learning/`. In a worktree the folder is absent.
Each test then skips by name. The real run is made in the main checkout with
`--require-local-data`. Nothing here commits or copies any of that data.
"""

import json

import pytest

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


def test_tightening_the_parser_loses_no_stored_yes_vote():
    """
    The unrecognised stored yes/no answers, measured on the real data, are free text.

    The measurement file is written by a run of the parser over the stored case and answer values.
    Each unrecognised value must not start with "yes", so the old vote counted it as "no",
    and the tightened parser drops no yes vote.
    """
    measured = json.load( open( require_local_file( "2026.11.18-f2-parser-measurement.json" ) ) )
    assert measured[ "cases" ][ "n" ] > 0 and measured[ "notifs" ][ "n" ] > 0
    for name, group in measured.items():
        for value in group[ "unrecognised" ]:
            assert not value.lower().startswith( "yes" ), name
