"""
The unit tier is not offered through the scheduled door of a container.

It ran inside the :8000 container and hit its own time limit. 76 of its tests failed there for environment reasons. It now runs on the host only.

This file pins three things, each at the layer it enters at.

- The door refuses a request that names unit when the server runs in a container, as it refuses an unknown suite name. A dry run is refused the same way. The suite name all is admitted, and the job expands it.
- The door still admits unit when the server runs on a host.
- No tracked doc or example still offers unit through the scheduled door.

The job's own behaviour is pinned in the test_suite tests under src/cosa/tests, and the coverage gate's answer in test_coverage_gate_tier_status.py.

Venue: :7999-eligible. In-process client, no server, no network, no state outside tmp_path.
"""

import re
import subprocess
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


@pytest.fixture
def in_container( monkeypatch ):
    monkeypatch.setattr( job_mod, "running_in_container", lambda: True )


@pytest.fixture
def on_host( monkeypatch ):
    monkeypatch.setattr( job_mod, "running_in_container", lambda: False )


def _door( client, test_types, dry_run=True ):
    response = submit_test_suite( client, test_types=test_types, dry_run=dry_run )
    assert response.status_code == 200, response.text
    return response.json()


# ---- 1. the door refuses a unit request in a container ---------------------------------------------

@pytest.mark.parametrize( "dry_run", [ True, False ] )
def test_the_door_refuses_unit_in_a_container_naming_the_host_and_queueing_nothing( client, queue, in_container, dry_run ):
    body = _door( client, "unit", dry_run=dry_run )
    assert body[ "status" ] == "failed" and body[ "route_reason" ] == "submit_refused", body
    assert queue.pushed == [], body
    assert "host" in body[ "error" ] and "unit" in body[ "error" ]
    assert "pytest src/tests/unit/" in body[ "error" ], "the refusal must say how to run it on the host"


def test_the_door_refuses_unit_hidden_among_other_suites( client, queue, in_container ):
    body = _door( client, "integration, unit ,smoke" )
    assert body[ "status" ] == "failed" and queue.pushed == [], body
    assert "host" in body[ "error" ]


def test_the_door_still_admits_the_other_suites_and_all_in_a_container( client, queue, in_container ):
    """A refusal that refuses everything is a bug: `all` is expanded by the job, minus unit."""
    for names in ( "integration", "e2e_a,e2e_b", "all" ):
        queue.pushed.clear()
        body = _door( client, names )
        assert body[ "status" ] == "waiting" and len( queue.pushed ) == 1, ( names, body )


# ---- 2. a host-run server keeps the unit suite -------------------------------------------------------

@pytest.mark.parametrize( "names", [ "unit", "unit,integration" ] )
def test_the_door_still_admits_unit_on_a_host( client, queue, on_host, names ):
    body = _door( client, names )
    assert body[ "status" ] == "waiting" and len( queue.pushed ) == 1, body


# ---- 3. nothing tracked offers unit through the scheduled door --------------------------------------

# A spelling that submits unit: `test_types: ["unit"...`, `test_types = "unit"` or `--test-types unit`.
_OFFERS_UNIT = re.compile( r"""(?:test_types["']?\s*[:=]\s*\[?\s*["']unit\b|--test-types\s+unit\b)""" )


def _swept_files():
    listing = subprocess.run( [ "git", "-C", str( ROOT ), "ls-files", ".claude/commands", ".claude/skills", "src/docs", "src/scripts", "CLAUDE.md" ],
                              capture_output=True, text=True, check=True ).stdout.split( "\n" )
    return [ f for f in listing if f.endswith( ( ".md", ".py" ) ) ]


def test_the_sweep_finds_an_offer_of_unit_when_one_is_there():
    assert _OFFERS_UNIT.search( 'test_types: ["unit", "smoke"]' )
    assert _OFFERS_UNIT.search( "submit-test-suite.py --test-types unit --dry-run" )
    assert not _OFFERS_UNIT.search( "submit-test-suite.py --test-types integration" )
    assert not _OFFERS_UNIT.search( 'test_types: ["e2e_a"]' )


def test_no_tracked_command_doc_or_example_offers_unit_through_the_scheduled_door():
    files = _swept_files()
    assert len( files ) > 100, f"sweep reached only {len( files )} files"
    this  = "src/tests/unit/" + Path( __file__ ).name
    found = {}
    for f in files:
        if f == this: continue
        hits = [ m.group( 0 ) for m in _OFFERS_UNIT.finditer( ( ROOT / f ).read_text( errors="replace" ) ) ]
        if hits: found[ f ] = hits
    assert found == {}, f"these files still offer unit through the scheduled door: {found}"


def test_the_scheduling_guide_says_the_container_refuses_unit():
    from tests.helpers.split_doc import read_split_page
    guide = read_split_page( ROOT, "src/docs/agents/test-suite-scheduling-guide.md" )
    row   = next( line for line in guide.splitlines() if line.startswith( "| `unit` |" ) )
    assert "host" in row and "refus" in row, row
