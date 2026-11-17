"""
The standalone /app/jobs page is gone: the accordion is a section of the two clients.

Rick ruled that it is not a page of its own. The router is mounted on a bare app, so this reads the
real route table. Only the Playwright file would otherwise notice the page coming back.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.rest.routers import pages


def test_app_jobs_answers_404_and_the_route_table_has_no_jobs_page():
    app = FastAPI()
    app.include_router( pages.router )
    assert TestClient( app ).get( "/app/jobs" ).status_code == 404
    assert "/app/jobs" not in pages._ROUTE_TABLE
    assert len( pages._ROUTE_TABLE ) > 5, "the table is empty: the check above proves nothing"
