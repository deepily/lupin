"""
The live two-pass eval test clears the replay store itself before its cold pass.

Nothing else in the integration tier empties the snapshot and synonym tables.
The test that used to drop every table no longer does.
A cold pass that starts on the last run's rows fails with a warm-store abort.
These tests pin that the live test asks for the clearing and that the primitive empties both tables.

Venue: :7999 (unit, reads the test file's syntax tree and calls its helper with stand-ins).
"""

import ast
import importlib.util
import os
import sys
from unittest.mock import MagicMock

import pytest

ROOT = os.environ[ "LUPIN_ROOT" ]
PATH = os.path.join( ROOT, "src", "tests", "integration", "test_v2_eval_live.py" )


def _tree():
    with open( PATH, encoding="utf-8" ) as handle: return ast.parse( handle.read() )


def _function( name ):
    found = [ n for n in ast.walk( _tree() ) if isinstance( n, ast.FunctionDef ) and n.name == name ]
    assert len( found ) == 1, f"{name} appears {len( found )} times"
    return found[ 0 ]


def _load_module():
    """The live test module, loaded by path with the scripts folder importable."""
    scripts = os.path.join( ROOT, "src", "scripts" )
    if scripts not in sys.path: sys.path.insert( 0, scripts )
    spec   = importlib.util.spec_from_file_location( "_test_v2_eval_live_probe", PATH )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


def test_the_live_test_asks_for_the_cold_store_fixture():
    arguments = [ a.arg for a in _function( "test_v2_eval_two_pass_live" ).args.args ]
    assert arguments == [ "cold_v2_store" ], arguments


def test_the_fixture_clears_through_the_helper_and_the_helper_calls_the_primitive():
    fixture = _function( "cold_v2_store" )
    assert "_clear_v2_store" in ast.dump( fixture ), "the fixture no longer calls the helper"
    helper = ast.dump( _function( "_clear_v2_store" ) )
    assert "clean_v2_snapshot_store" in helper, "the helper no longer calls the primitive"


def test_the_helper_runs_the_primitive_on_a_connection_of_the_process_engine( monkeypatch ):
    module     = _load_module()
    connection = MagicMock( name="connection" )
    engine     = MagicMock( name="engine" )
    engine.connect.return_value.__enter__.return_value = connection
    engine.connect.return_value.__exit__.return_value  = False
    calls = [ ]
    monkeypatch.setattr( "cosa.rest.db.database.engine", engine )
    monkeypatch.setattr( module.ve, "clean_v2_snapshot_store", lambda conn, cfg: calls.append( ( conn, cfg ) ) or "solution_snapshots" )
    assert module._clear_v2_store() == "solution_snapshots"
    ( ( seen_connection, seen_config ), ) = calls
    assert seen_connection is connection
    assert hasattr( seen_config, "get" ), "the primitive needs a config manager that answers get()"


def test_the_primitive_the_helper_calls_empties_both_replay_tables( monkeypatch ):
    """The real primitive over a recording connection: one statement, both tables, a commit."""
    module     = _load_module()
    statements = [ ]
    connection = MagicMock()
    connection.engine.url = "postgresql://u@h/lupin_db_test"
    connection.execute.side_effect = lambda statement: statements.append( str( statement ) )
    config = MagicMock()
    config.get.return_value = "solution_snapshots"
    assert module.ve.clean_v2_snapshot_store( connection, config ) == "solution_snapshots"
    ( truncate, ) = statements
    assert truncate == "TRUNCATE TABLE solution_snapshots, canonical_synonyms"
    connection.commit.assert_called_once()


def test_the_primitive_sends_nothing_when_the_connection_is_not_a_measurement_database():
    module     = _load_module()
    connection = MagicMock()
    connection.engine.url = "postgresql://u@h/lupin_db_dev"
    config = MagicMock()
    config.get.return_value = "solution_snapshots"
    with pytest.raises( Exception, match="measurement database" ):
        module.ve.clean_v2_snapshot_store( connection, config )
    connection.execute.assert_not_called()
