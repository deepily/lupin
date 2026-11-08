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
    app = FastAPI()
    app.include_router( dcs.router )
    return TestClient( app )


def test_the_status_endpoint_answers_the_snapshot( client ):
    body = client.get( "/api/duplicate-check/status" ).json()
    assert body[ "backlog" ][ "carried" ] == 3 and body[ "runs" ][ 0 ][ "branch" ] == "wip-x" and body[ "as_of" ] == NOW.isoformat()


def test_the_page_is_html_that_browsers_revalidate( client ):
    page = client.get( "/app/duplicate-check" )
    assert page.status_code == 200 and page.headers[ "content-type" ].startswith( "text/html" ) and page.headers[ "cache-control" ] == "no-cache"
    assert "Duplicate check" in page.text and "wip-x" in page.text


def test_the_folder_and_clock_are_the_servers_own( monkeypatch ):
    monkeypatch.setattr( dcs.cu, "get_project_root", lambda: "/r" )
    assert str( dcs.runs_folder() ) == "/r/io/duplicate-check-daily" and dcs.now().tzinfo is not None
