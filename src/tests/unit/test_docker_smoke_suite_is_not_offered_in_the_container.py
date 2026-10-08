"""
The docker smoke step is not offered through the scheduled door of a container.

Inside the container the three docker files skip for want of a docker socket, so the step has nothing to
check there. It runs on the host only, as the unit tier does. This file is the twin of
test_unit_suite_is_not_offered_in_the_container.py. It pins three things for docker_smoke. The door
refuses it in a container and names its own command. The door admits it on a host. The scheduling
guide says so.

Venue: :7999-eligible. In-process client, no server, no network, no state outside tmp_path.
"""

from pathlib import Path

import pytest

import cosa.agents.test_suite.job as job_mod
from tests.helpers.v2_submit_harness import Queue, make_client, submit_test_suite

ROOT = Path( __file__ ).resolve().parents[ 3 ]   # src/tests/unit/<file> -> tree root, never LUPIN_ROOT


@pytest.fixture
def queue():
    return Queue()


@pytest.fixture
def client( queue, tmp_path ):
    return make_client( queue, tmp_path )


def _door( client, test_types, dry_run=True ):
    response = submit_test_suite( client, test_types=test_types, dry_run=dry_run )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize( "dry_run", [ True, False ] )
def test_the_door_refuses_docker_smoke_in_a_container_and_names_its_own_command( client, queue, monkeypatch, dry_run ):
    monkeypatch.setattr( job_mod, "running_in_container", lambda: True )
    body = _door( client, "docker_smoke", dry_run=dry_run )
    assert body[ "status" ] == "failed" and body[ "route_reason" ] == "submit_refused", body
    assert queue.pushed == [], body
    assert "src/tests/run-docker-smoke-gate.sh" in body[ "error" ], "the refusal must say how to run it on the host"
    assert "pytest src/tests/unit/" not in body[ "error" ], "the unit command must not appear for a request that named only docker_smoke"


def test_the_refusal_names_each_host_suite_with_its_own_command_when_both_are_asked( client, queue, monkeypatch ):
    monkeypatch.setattr( job_mod, "running_in_container", lambda: True )
    body = _door( client, "unit,docker_smoke" )
    assert queue.pushed == [], body
    assert "unit with `pytest src/tests/unit/`" in body[ "error" ]
    assert "docker_smoke with `src/tests/run-docker-smoke-gate.sh`" in body[ "error" ]


def test_the_container_still_admits_the_other_suites_and_all( client, queue, monkeypatch ):
    monkeypatch.setattr( job_mod, "running_in_container", lambda: True )
    for names in ( "smoke", "integration", "all" ):
        queue.pushed.clear()
        body = _door( client, names )
        assert body[ "status" ] == "waiting" and len( queue.pushed ) == 1, ( names, body )


def test_a_host_server_admits_docker_smoke( client, queue, monkeypatch ):
    monkeypatch.setattr( job_mod, "running_in_container", lambda: False )
    body = _door( client, "docker_smoke" )
    assert body[ "status" ] == "waiting" and len( queue.pushed ) == 1, body


def test_the_scheduling_guide_says_the_container_refuses_docker_smoke():
    guide = ( ROOT / "src/docs/agents/test-suite-scheduling-guide.md" ).read_text()
    row   = next( line for line in guide.splitlines() if line.startswith( "| `docker_smoke` |" ) )
    assert "host" in row and "refus" in row, row
