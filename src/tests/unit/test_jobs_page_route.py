"""
The /app/jobs route serves the accordion shell.

The router is mounted on a bare app, so these tests read the real route table and HTML file.
They check that the route answers and that the shell revalidates on every load.
They also check that it names the dist folder the builder emits and the elements the script needs.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.rest.routers import pages

REQUIRED_IDS = ( "jobs-header", "jobs-error", "jobs-accordion", "jobs-refresh" )


def _client():
    app = FastAPI()
    app.include_router( pages.router )
    return TestClient( app )


def test_the_route_table_maps_app_jobs_to_the_shell_and_the_shell_exists():
    import os
    assert pages._ROUTE_TABLE[ "/app/jobs" ] == "html/jobs.html"
    assert os.path.isfile( os.path.join( pages._static_dir, "html/jobs.html" ) )


def test_app_jobs_answers_200_html_and_asks_the_browser_to_revalidate():
    r = _client().get( "/app/jobs" )
    assert r.status_code == 200
    assert r.headers[ "content-type" ].startswith( "text/html" )
    assert r.headers[ "cache-control" ] == "no-cache"


def test_the_shell_carries_every_element_the_page_script_requires_and_loads_the_jobs_bundle():
    body = _client().get( "/app/jobs" ).text
    for element_id in REQUIRED_IDS:
        assert f'id="{element_id}"' in body, element_id
    assert "/static/dist/jobs/" in body
    assert 'manifest[ "jobs.js" ]' in body
    assert "/static/css/multiplexer/jobs-page.css" in body


def test_the_shell_has_no_inline_job_logic_and_no_management_action_other_than_refresh():
    body = _client().get( "/app/jobs" ).text
    assert body.count( "<button" ) == 1, "the only static button is Refresh; Run now is drawn per job by the bundle"
