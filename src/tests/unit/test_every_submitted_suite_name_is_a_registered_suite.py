"""
Row 4e8f348e — "e2e_ui" is a directory, not a suite, and it burned the :8000 monopolize slot.

Nine test files told the next person to submit `test_types: "e2e_ui"`. The door accepted it,
the job took the single monopolize slot, found no script and wrote a zero report — five times
between 2026-05-05 and 2026-09-19. Three guards, one per way it can come back:

  1. THE DOOR refuses an unregistered name with a 400 naming it and the valid list, before a
     job exists (so the queue is never touched).
  2. THE DOOR still admits a registered name (a refusal that refuses everything is a bug).
  3. NO TRACKED TEST OR SCRIPT FILE spells out an unregistered `test_types` value — so the
     next copy-paste of a wrong docstring reddens here instead of at 20:13 on :8000.

Population for (3): every git-tracked .py/.sh under src/tests and src/scripts, minus this file
(whose own examples are the wrong names on purpose). The count is asserted non-empty and
printed, and a positive control proves the extractor finds the wrong name when it is there.
"""

import asyncio
import re
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from cosa.agents.test_suite.job import SUITE_SCRIPTS, unknown_suite_names

ROOT = Path( __file__ ).resolve().parents[ 3 ]   # src/tests/unit/<file> -> tree root, never LUPIN_ROOT
_SPELLING = re.compile( r"""["']?test_types["']?\s*[:=]\s*["']([^"']+)["']""" )


def _door( test_types, monkeypatch=None ):
    from cosa.rest.routers.test_suite import submit_test_suite, TestSuiteSubmitRequest

    class _Queue:
        def push( self, job ): raise AssertionError( "a refused submit reached the queue" )
        def size( self ):      raise AssertionError( "a refused submit reached the queue" )

    return asyncio.run( submit_test_suite(
        request_body = TestSuiteSubmitRequest( test_types=test_types ),
        current_user = { "uid": "user-123", "email": "test@test.com" },
        todo_queue   = _Queue(),
    ) )


def test_the_door_refuses_e2e_ui_naming_it_and_the_valid_list():
    with pytest.raises( HTTPException ) as caught:
        _door( "e2e_ui" )
    assert caught.value.status_code == 400
    assert "e2e_ui" in caught.value.detail
    for key in ( "e2e_a", "e2e_b", "e2e", "unit" ):
        assert key in caught.value.detail


def test_the_door_refuses_a_bad_name_hidden_among_good_ones():
    with pytest.raises( HTTPException ) as caught:
        _door( "unit, e2e_ui ,integration" )
    assert caught.value.status_code == 400
    assert "'e2e_ui'" in caught.value.detail and "'unit'" not in caught.value.detail


def test_the_door_refuses_an_empty_suite_list():
    with pytest.raises( HTTPException ) as caught:
        _door( " , " )
    assert caught.value.status_code == 400


@pytest.mark.parametrize( "names", [ "e2e_a", "e2e_b", "unit,integration", "all" ] )
def test_the_door_still_admits_registered_names( names, monkeypatch ):
    """Reaching the job factory means the name check passed; the sentinel proves WHICH path ran."""
    import cosa.rest.routers.test_suite as router

    def _stop( **kwargs ): raise RuntimeError( "SENTINEL-name-check-passed" )
    monkeypatch.setattr( router, "create_agentic_job", _stop )
    with pytest.raises( HTTPException ) as caught:
        _door( names )
    assert caught.value.status_code == 500 and "SENTINEL-name-check-passed" in caught.value.detail


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
