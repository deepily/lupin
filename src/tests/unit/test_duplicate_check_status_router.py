"""The duplicate check status router: the snapshot and the page, read from a real ledger."""
import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.rest.routers import duplicate_check_status as dcs
from lupin_mcp import duplicate_check_history as hist

NOW = datetime.datetime( 2026, 11, 8, 12, 5, tzinfo=datetime.timezone( datetime.timedelta( hours=-5 ) ) )


@pytest.fixture
def client( tmp_path, monkeypatch ):
    """Ensures: a client over the router, with one finished run and a fixed clock."""
    hist.append_line( tmp_path, hist.line_of( { "status": "carried", "trigger": "cron", "started_at": "2026-11-08T11:00:00-05:00", "carried": [ 1, 2, 3 ], "owed": 9, "judged": 6,
                                                 "judge_calls": 6, "elapsed_seconds": 20.0, "branch": "wip-x" }, "r.json" ) )
    monkeypatch.setattr( dcs, "runs_folder", lambda: tmp_path )
    monkeypatch.setattr( dcs, "now", lambda: NOW )
    monkeypatch.setattr( dcs, "installed_crontab", lambda: ( "0 10 * * * run # duplicate-check-daily\n", None ) )
    app = FastAPI()
    app.include_router( dcs.router )
    return TestClient( app )


def test_the_status_endpoint_answers_the_snapshot( client ):
    body = client.get( "/api/duplicate-check/status" ).json()
    assert body[ "backlog" ][ "carried" ] == 3 and body[ "runs" ][ 0 ][ "branch" ] == "wip-x" and body[ "as_of" ] == NOW.isoformat()


def test_the_job_summary_endpoint_answers_the_v1_record( client ):
    body = client.get( "/api/duplicate-check/job-summary" ).json()
    assert body[ "schema" ] == "job-summary/1" and body[ "scan_debt" ][ "count" ] == 3 and "health" not in body and body[ "target" ] is None


def test_the_page_is_html_that_browsers_revalidate( client ):
    page = client.get( "/app/duplicate-check" )
    assert page.status_code == 200 and page.headers[ "content-type" ].startswith( "text/html" ) and page.headers[ "cache-control" ] == "no-cache"
    assert "Duplicate check" in page.text and "wip-x" in page.text


def test_the_folder_and_clock_are_the_servers_own( monkeypatch ):
    monkeypatch.setattr( dcs.cu, "get_project_root", lambda: "/r" )
    assert str( dcs.runs_folder() ) == "/r/io/duplicate-check-daily" and dcs.now().tzinfo is not None


def test_the_status_endpoint_carries_the_installed_schedule_and_is_not_silent_for_this_mornings_daily_run( client ):
    body = client.get( "/api/duplicate-check/status" ).json()
    assert body[ "schedule" ] == { "cron": [ "0 10 * * *" ], "verified": True } and body[ "health" ] != "silent"


def test_a_crontab_from_the_host_snapshot_is_read_in_the_hosts_zone( tmp_path, monkeypatch ):
    zone = datetime.timezone( datetime.timedelta( hours=-4 ) )
    hist.append_line( tmp_path, hist.line_of( { "status": "ok", "trigger": "cron", "started_at": "2026-11-08T10:00:00-04:00", "carried": [], "owed": 0, "judged": 0, "judge_calls": 0, "elapsed_seconds": 1.0 }, "r.json" ) )
    monkeypatch.setattr( dcs, "runs_folder", lambda: tmp_path )
    monkeypatch.setattr( dcs, "now", lambda: NOW )
    monkeypatch.setattr( dcs, "installed_crontab", lambda: ( "0 10 * * * run # duplicate-check-daily\n", zone ) )
    snap = dcs.snapshot_now()
    assert snap[ "as_of" ] == NOW.astimezone( zone ).isoformat() and snap[ "schedule" ][ "verified" ] is True


def test_installed_crontab_asks_the_job_cards_live_inputs_for_the_text_and_the_zone( monkeypatch ):
    from cosa.rest.routers import job_summary
    class Deps:
        """Ensures: answers like LiveDeps when the crontab came from the snapshot."""
        def crontab_text( self ): return "tab"
        def host_zone( self ): return "zone"
    monkeypatch.setattr( job_summary, "live_deps", lambda: ( "root", "data", Deps() ) )
    assert dcs.installed_crontab() == ( "tab", "zone" )
