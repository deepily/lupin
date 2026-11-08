"""The librarian, refresh and behaviour adapters."""
import datetime
import json

import pytest

from lupin_mcp import job_summary_adapters as jsa

NOW = datetime.datetime( 2026, 11, 7, 10, 17 )


def last( folder ):
    """Ensures: returns the written record."""
    return json.loads( ( folder / "job-summary.json" ).read_text() )


@pytest.mark.parametrize( "summary, code, want", [
    ( { "ran": True }, 0, ( "clean", None ) ), ( { "ran": True }, 2, ( "carried", None ) ),
    ( { "ran": False, "reason": "not due" }, 0, ( "skipped", "not due" ) ), ( { "ran": False, "reason": "switched off" }, 3, ( "skipped", "switched off" ) ),
    ( { "ran": False, "reason": "BUILD_LOCK_HELD" }, 4, ( "skipped", "BUILD_LOCK_HELD" ) ), ( { "ran": False, "reason": "export query failed: 200" }, 1, ( "failed", "export query failed: 200" ) ) ] )
def test_outcome_of( summary, code, want ):
    assert jsa.outcome_of( summary, code ) == want


def test_a_librarian_tick_reports_findings_as_scan_debt_and_created_rows_as_fix_debt_and_a_failed_tick_keeps_them( tmp_path ):
    ran = { "ran": True, "findings": 526, "cleared": 3, "deferred": 137, "created": 10 }
    got = jsa.record_librarian( tmp_path, ran, 0, NOW, {} )
    assert last( tmp_path ) == got and got[ "scan_debt" ][ "count" ] == 526 and got[ "scan_debt" ][ "drained_last_run" ] == 3
    assert got[ "fix_debt" ][ "unfiled" ] == 137 and got[ "fix_debt" ][ "points" ][ -1 ][ "opened_total" ] == 10 and got[ "work_found_last_run" ] == 526
    bad = jsa.record_librarian( tmp_path, { "ran": False, "reason": "export query failed: 200" }, 1, NOW, {} )
    assert bad[ "last_attempt" ][ "outcome" ] == "failed" and bad[ "last_attempt" ][ "stage" ] == "tick" and bad[ "scan_debt" ] == got[ "scan_debt" ] and bad[ "consecutive_failures" ] == 1
    assert bad[ "last_attempt" ][ "trigger" ] == "cron" and jsa.record_librarian( tmp_path, ran, 0, NOW, { "LUPIN_JOB_TRIGGER": "hand" } )[ "last_attempt" ][ "trigger" ] == "hand"
    held = jsa.record_librarian( tmp_path, ran, 2, NOW, {} )
    assert held[ "last_attempt" ][ "outcome" ] == "carried"


def test_a_refresh_reports_staleness_from_the_run_or_the_state_file_and_never_an_age( tmp_path ):
    built = jsa.record_refresh( tmp_path, { "ran": True, "outcome": "built", "rows": 13218, "built_at": "2026-11-07T17:16:08+00:00" }, 0, {}, NOW, {} )
    assert built[ "scan_debt" ][ "freshness" ] == { "built_at": "2026-11-07T17:16:08+00:00", "stale_after_hours": 36 } and "age_hours" not in json.dumps( built ) and built[ "work_found_last_run" ] == 13218
    fresh = jsa.record_refresh( tmp_path, { "ran": True, "outcome": "fresh" }, 0, { "built_at": "2026-11-06T10:00:00+00:00" }, NOW, {} )
    assert fresh[ "scan_debt" ][ "freshness" ][ "built_at" ] == "2026-11-06T10:00:00+00:00"
    failed = jsa.record_refresh( tmp_path, { "ran": False, "outcome": "failed", "reason": "OSError: x" }, 1, {}, NOW, {} )
    assert failed[ "last_attempt" ][ "outcome" ] == "failed" and failed[ "scan_debt" ] == fresh[ "scan_debt" ] and failed[ "last_attempt" ][ "stage" ] == "refresh"
    lock = jsa.record_refresh( tmp_path, { "ran": False, "reason": "BUILD_LOCK_HELD" }, 4, {}, NOW, {} )
    assert lock[ "last_attempt" ][ "outcome" ] == "skipped"


def test_behaviour_names_no_debt( tmp_path ):
    got = jsa.record_behaviour( tmp_path, "failed", NOW, "CandidateError: DEPENDENCY_MISSING", {} )
    assert got[ "scan_debt" ] is None and got[ "fix_debt" ] is None and got[ "last_attempt" ][ "failure" ].startswith( "CandidateError" )
    assert jsa.record_behaviour( tmp_path, "clean", NOW, environ={} )[ "consecutive_failures" ] == 0


def test_report_returns_none_when_the_folder_cannot_be_written( tmp_path, capsys ):
    blocker = tmp_path / "f"; blocker.write_text( "x" )
    assert jsa.report( blocker / "sub", "j", NOW, "clean", environ={} ) is None
    assert jsa.aware( NOW ).tzinfo is not None


def test_an_adapter_run_leaves_the_container_a_fresh_crontab_copy(tmp_path, monkeypatch):
    from lupin_mcp import host_snapshot as hs
    seen = []
    monkeypatch.setattr( hs, "refresh_best_effort", lambda environ=None, now=None, run=None: seen.append( environ ) or True )
    jsa.record_behaviour( tmp_path, "clean", NOW, environ={ "K": "v" } )
    assert seen == [ { "K": "v" } ]
