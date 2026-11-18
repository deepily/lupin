"""
The audit windows, recounted from the real export, match the old-engine replay artifact.

These tests read Rick's real answers from the main checkout's gitignored
`io/write-ups/online-preference-learning/` (the `local_data` tier). In a worktree the folder is absent.
Each test then skips by name. The real run points `LUPIN_LOCAL_DATA_DIR` at that folder, or runs in the
main checkout with `--require-local-data`. Nothing here copies or commits that data.

The reference side is derived from the audit itself. The two cut-over instants are read out of the audit
query (`2026.11.18-audit-figures-reproduction.sql`) and not restated. So a harness constant that drifts from
the audit shows up as a disagreement. The window of an ask is its `predicted_at`, which that query groups on.
"""

import datetime
import json
import re

import pytest

from cosa.utils.local_data_tier import require_local_file

pytestmark = pytest.mark.local_data

EXPORT_FILE_NAME   = "2026.11.17-recent-predictions-285.json"
ARTIFACT_FILE_NAME = "2026.11.18-old-engine-yes-no-replay.json"
AUDIT_SQL_FILE_NAME = "2026.11.18-audit-figures-reproduction.sql"
WINDOW_NAMES       = ( "before", "undetermined", "after" )


def _instant( text ):
    """Parse an ISO instant, a trailing Z or a space-separated offset included."""
    return datetime.datetime.fromisoformat( text.replace( "Z", "+00:00" ).replace( " ", "T", 1 ) )


def _audit_cutoffs():
    """Read the two cut-over instants out of the audit query's yes/no window clause."""
    sql   = open( require_local_file( AUDIT_SQL_FILE_NAME ) ).read()
    found = re.search( r"p\.predicted_at <= '([^']+)'\s+THEN '[^']*'\s+WHEN p\.predicted_at <\s+'([^']+)'", sql )
    assert found is not None, "the audit query no longer has the two-cutoff window CASE"
    return _instant( found.group( 1 ) ), _instant( found.group( 2 ) )


def _window_of( predicted_at, cutoffs ):
    """The audit rule: up to the first cut-over is before, up to the second is undetermined."""
    first, second = cutoffs
    if predicted_at <= first:  return "before"
    if predicted_at <  second: return "undetermined"
    return "after"


def _yes_no_asks():
    """The export's yes/no predictions."""
    predictions = json.load( open( require_local_file( EXPORT_FILE_NAME ) ) )[ "predictions" ]
    return [ p for p in predictions if p[ "response_type" ] == "yes_no" ]


def _artifact():
    """The old-engine replay artifact: meta, totals and one row per yes/no ask."""
    return json.load( open( require_local_file( ARTIFACT_FILE_NAME ) ) )


def test_the_audit_query_names_two_cutoffs_in_order():
    """The instants are read from the audit, and the first is earlier than the second."""
    first, second = _audit_cutoffs()
    assert first < second


def test_the_audits_windows_by_predicted_at_hold_25_54_and_60_asks():
    """Recounting the 139 yes/no asks by the audit rule gives the artifact's windows."""
    cutoffs = _audit_cutoffs()
    counts  = { name: 0 for name in WINDOW_NAMES }
    for ask in _yes_no_asks(): counts[ _window_of( _instant( ask[ "predicted_at" ] ), cutoffs ) ] += 1
    assert counts == { "before": 25, "undetermined": 54, "after": 60 }
    assert counts == { name: _artifact()[ "totals" ][ name ][ "asks" ] for name in WINDOW_NAMES }


def test_every_ask_lands_in_the_window_the_export_labels_it_with():
    """The export's window label equals the audit rule applied to predicted_at, ask by ask."""
    cutoffs = _audit_cutoffs()
    wrong   = [ ask[ "ref" ][ "prediction_log_id" ] for ask in _yes_no_asks()
                if _window_of( _instant( ask[ "predicted_at" ] ), cutoffs ) != ask[ "window" ] ]
    assert wrong == []


def test_asked_at_would_put_one_ask_in_the_wrong_window():
    """Windowing by asked_at instead of predicted_at moves one ask out of its window."""
    cutoffs = _audit_cutoffs()
    moved   = [ ask[ "ref" ][ "prediction_log_id" ] for ask in _yes_no_asks()
                if _window_of( _instant( ask[ "asked_at" ] ), cutoffs ) != ask[ "window" ] ]
    assert len( moved ) == 1


def test_the_artifact_covers_exactly_the_139_asks_with_the_logged_prediction():
    """One artifact row per yes/no ask, carrying the value the log recorded."""
    asks     = { ask[ "ref" ][ "prediction_log_id" ]: ask for ask in _yes_no_asks() }
    rows     = { row[ "prediction_log_id" ]: row for row in _artifact()[ "rows" ] }
    assert len( asks ) == len( rows ) == 139 and set( asks ) == set( rows )
    differing = [ key for key, row in rows.items() if row[ "logged" ] != asks[ key ][ "prediction" ][ "value" ][ "value" ] ]
    assert differing == []


def test_the_artifacts_totals_are_what_its_rows_add_up_to():
    """Each window's counts are recomputed from the rows, not read from the totals."""
    artifact = _artifact()
    for name in WINDOW_NAMES + ( "ALL", ):
        rows   = [ row for row in artifact[ "rows" ] if name == "ALL" or row[ "window" ] == name ]
        totals = artifact[ "totals" ][ name ]
        assert totals[ "asks" ] == len( rows )
        assert totals[ "replayed_equals_logged_value" ] == sum( row[ "replayed_matches_logged" ] for row in rows )
        assert totals[ "replayed_right" ]               == sum( row[ "replayed_right" ] for row in rows )
        assert totals[ "logged_right" ]                 == sum( 1 for row in rows if row[ "logged_right" ] )
        assert totals[ "always_yes_right" ]             == sum( row[ "actual_binary" ] == "yes" for row in rows )


def test_the_logged_correctness_in_the_artifact_matches_the_exports_match_flag():
    """The artifact's logged_right equals the export's match flag for every ask."""
    asks      = { ask[ "ref" ][ "prediction_log_id" ]: ask for ask in _yes_no_asks() }
    differing = [ row[ "prediction_log_id" ] for row in _artifact()[ "rows" ]
                  if bool( row[ "logged_right" ] ) != bool( asks[ row[ "prediction_log_id" ] ][ "match" ] ) ]
    assert differing == []
