"""
Row 4e8f348e — "e2e_ui" is a directory, not a suite, and it burned the :8000 monopolize slot.

Nine test files told the next person to submit `test_types: "e2e_ui"`. The door accepted it,
the job took the single monopolize slot, found no script and wrote a zero report — five times
between 2026-05-05 and 2026-09-19. Three guards, one per way it can come back:

  1. THE DOOR (`/api/v2/submit`, command `agent router go to test suite`; the old
     `/api/test-suite/submit` is retired) refuses an unregistered name, naming it and the
     valid list, before a job exists (so the queue is never touched). v2 reports a refusal as
     status `failed` with the cause in `error`, not as HTTP 400.
  2. THE DOOR still admits a registered name (a refusal that refuses everything is a bug).
  3. NO TRACKED TEST OR SCRIPT FILE spells out an unregistered `test_types` value — so the
     next copy-paste of a wrong docstring reddens here instead of at 20:13 on :8000.

Population for (3): every git-tracked .py/.sh under src/tests and src/scripts, minus this file
(whose own examples are the wrong names on purpose). The count is asserted non-empty and
printed, and a positive control proves the extractor finds the wrong name when it is there.
"""

import re
import subprocess
from pathlib import Path

import pytest

import cosa.agents.test_suite.job as job_mod
from cosa.agents.test_suite.job import SUITE_SCRIPTS, unknown_suite_names
from tests.helpers.v2_submit_harness import Queue, make_client, submit_test_suite

ROOT = Path( __file__ ).resolve().parents[ 3 ]   # src/tests/unit/<file> -> tree root, never LUPIN_ROOT
_SPELLING = re.compile( r"""["']?test_types["']?\s*[:=]\s*["']([^"']+)["']""" )


@pytest.fixture
def queue():
    return Queue()


@pytest.fixture
def client( queue, tmp_path, monkeypatch ):
    monkeypatch.setattr( job_mod, "running_in_container", lambda: False )   # these cases admit unit and all; they must not depend on where the test runs
    return make_client( queue, tmp_path )


def _door( client, test_types ):
    """The v2 door (the old /api/test-suite/submit is retired): returns the response body."""
    response = submit_test_suite( client, test_types=test_types, dry_run=True )
    assert response.status_code == 200, response.text
    return response.json()


def test_the_door_refuses_e2e_ui_naming_it_and_the_valid_list( client, queue ):
    body = _door( client, "e2e_ui" )
    assert body[ "status" ] == "failed" and body[ "route_reason" ] == "submit_refused", body
    assert queue.pushed == [], body
    assert "e2e_ui" in body[ "error" ]
    for key in ( "e2e_a", "e2e_b", "e2e", "unit" ):
        assert key in body[ "error" ]


def test_the_door_refuses_a_bad_name_hidden_among_good_ones( client, queue ):
    body = _door( client, "unit, e2e_ui ,integration" )
    assert queue.pushed == [], body
    assert "'e2e_ui'" in body[ "error" ] and "'unit'" not in body[ "error" ].split( "Valid suites" )[ 0 ]


def test_the_door_refuses_an_empty_suite_list( client, queue ):
    body = _door( client, " , " )
    assert queue.pushed == [] and "names no suite" in body[ "error" ], body


@pytest.mark.parametrize( "names", [ "e2e_a", "e2e_b", "unit,integration", "all" ] )
def test_the_door_still_admits_registered_names( names, client, queue ):
    """A refusal that refuses everything is a bug: a registered name reaches the queue."""
    body = _door( client, names )
    assert body[ "status" ] == "waiting" and len( queue.pushed ) == 1, body


def test_unknown_suite_names_is_the_registry_predicate():
    assert unknown_suite_names( [ "e2e_ui", "unit", "e2e_ui", "nope" ] ) == [ "e2e_ui", "nope" ]
    assert unknown_suite_names( list( SUITE_SCRIPTS ) ) == []
    assert unknown_suite_names( [] ) == []


def _spelled_names( text ):
    return [ n.strip() for m in _SPELLING.findall( text ) for n in m.split( "," ) if n.strip() ]


def test_the_extractor_finds_a_wrong_name_when_one_is_there():
    assert unknown_suite_names( _spelled_names( '{ "test_types" : "e2e_ui", "x": 1 }' ) ) == [ "e2e_ui" ]
    assert unknown_suite_names( _spelled_names( "test_types='unit,e2e_b'" ) ) == []


def test_no_tracked_test_or_script_names_an_unregistered_suite():
    tracked = subprocess.run(
        [ "git", "-C", str( ROOT ), "ls-files", "src/tests", "src/scripts" ],
        capture_output=True, text=True, check=True ).stdout.split( "\n" )
    files   = [ f for f in tracked if f.endswith( ( ".py", ".sh" ) ) and f != "src/tests/unit/" + Path( __file__ ).name ]
    assert len( files ) > 500, f"tracked-file sweep reached only {len( files )} files"
    spelled = {}
    for f in files:
        names = _spelled_names( ( ROOT / f ).read_text( errors="replace" ) )
        if names: spelled[ f ] = names
    total = sum( len( v ) for v in spelled.values() )
    print( f"[suite-name guard] {len( files )} files swept, {len( spelled )} spell test_types, {total} names" )
    assert total >= 10, f"only {total} test_types spellings found; the extractor stopped matching"
    bad = { f: unknown_suite_names( n ) for f, n in spelled.items() if unknown_suite_names( n ) }
    assert bad == {}, f"unregistered suite names in tracked files: {bad}"
