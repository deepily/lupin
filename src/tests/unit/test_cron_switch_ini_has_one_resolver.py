#!/usr/bin/env python3
"""
One function names the configuration file for the switches, for writer and readers.

The :8000 test server flips a scratch copy of the configuration file (LUPIN_CRON_SWITCH_INI), so the E2E
flip never touches the file the cron jobs read. That holds only if the PUT writer and every reader that
GET /api/cron-jobs uses resolve the path through `cron_job_switches.ini_path()`. A reader that took the
tracked file directly would show the E2E a value the flip never changed.

Three guards:
    - the resolver names the tracked file when the variable is unset, and the variable's file when set
    - every call into the INI reader or writer inside cron_job_switches.py passes `ini_path()`, found by
      reading the module's syntax tree, so a new caller that names a path itself reddens it
    - GET's rows and the PUT's write reach the INI reader and writer with the resolver's answer, found
      by spying on the INI module, so a bypass in the route also reddens it

Venue: :7999 (unit, no server, tmp_path only).
"""
import ast
import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import cosa.utils.util as cu
from cosa.rest import cron_job_switches as sw
from cosa.rest import job_registry as jr
from lupin_mcp import fleet_cap_ini_io as io
from lupin_mcp import fleet_size_cap
from tests.helpers.main_ini_fence import main_ini_fence   # noqa: F401 - autouse: the main checkout's INI is fenced in every test here

MODULE_PATH = os.path.join( cu.get_project_root(), "src", "cosa", "rest", "cron_job_switches.py" )
ROUTER_PATH = os.path.join( cu.get_project_root(), "src", "cosa", "rest", "routers", "cron_jobs.py" )
INI_CALLS   = { "read_value_from_disk", "write_bool_to_disk", "locate_key" }


def _tree( path ):
    with open( path, encoding="utf-8" ) as handle:
        return ast.parse( handle.read() )


def _calls( tree, attribute ):
    """Every call of `<anything>.attribute(...)` in the tree."""
    return [ n for n in ast.walk( tree ) if isinstance( n, ast.Call ) and isinstance( n.func, ast.Attribute ) and n.func.attr == attribute ]


def test_the_resolver_names_the_tracked_file_when_unset_and_the_override_when_set( monkeypatch, tmp_path ):
    monkeypatch.delenv( sw.INI_OVERRIDE_ENV, raising=False )
    assert sw.ini_path() == fleet_size_cap.main_checkout_ini_path()
    assert sw.ini_path().endswith( os.path.join( "src", "conf", "lupin-app.ini" ) )
    scratch = str( tmp_path / "scratch.ini" )
    monkeypatch.setenv( sw.INI_OVERRIDE_ENV, scratch )
    assert sw.ini_path() == scratch
    assert sw.state_path() == f"{scratch}.cron-state.json", "the attribution record must sit beside the scratch copy"


def test_the_empty_variable_counts_as_unset( monkeypatch ):
    monkeypatch.setenv( sw.INI_OVERRIDE_ENV, "" )
    assert sw.ini_path() == fleet_size_cap.main_checkout_ini_path()


def test_every_call_into_the_ini_module_passes_the_resolver():
    tree  = _tree( MODULE_PATH )
    calls = [ c for name in INI_CALLS for c in _calls( tree, name ) ]
    calls += [ n for n in ast.walk( tree ) if isinstance( n, ast.Call ) and isinstance( n.func, ast.Name ) and n.func.id == "read_switch" ]
    assert len( calls ) == 3, f"the module has exactly the shared read, the locate and the write; found {len( calls )}"
    for call in calls:
        first = call.args[ 0 ]
        assert isinstance( first, ast.Call ) and isinstance( first.func, ast.Name ) and first.func.id == "ini_path", \
            f"line {call.lineno}: the INI path must come from ini_path(), not be named here"


def test_only_the_resolver_names_the_main_checkout_file():
    names = _calls( _tree( MODULE_PATH ), "main_checkout_ini_path" )
    assert len( names ) == 1, "the tracked file is named in one place only"
    resolver = next( n for n in ast.walk( _tree( MODULE_PATH ) ) if isinstance( n, ast.FunctionDef ) and n.name == "ini_path" )
    assert names[ 0 ].lineno >= resolver.lineno and names[ 0 ].lineno <= resolver.end_lineno


def test_the_router_reaches_the_ini_only_through_the_switch_module():
    router = _tree( ROUTER_PATH )
    for name in INI_CALLS:
        assert _calls( router, name ) == [ ], f"the router calls {name} itself, bypassing ini_path()"
    assert _calls( router, "main_checkout_ini_path" ) == [ ]


@pytest.fixture
def spied( monkeypatch, tmp_path ):
    """A scratch file as the override, with the three INI entry points recording their path."""
    scratch = tmp_path / "scratch.ini"
    jobs    = jr.load_registry( cu.get_project_root() )[ "jobs" ]
    scratch.write_text( "[Lupin: Baseline]\n" + "".join( f"{sw.switch_key( j[ 'job' ] )} = true\n" for j in jobs ), encoding="utf-8" )
    monkeypatch.setenv( sw.INI_OVERRIDE_ENV, str( scratch ) )
    assert sw.ini_path() == str( scratch ), "the resolver must name the scratch file, or the writes below would reach the real one"
    seen = []
    for name in INI_CALLS:
        real = getattr( io, name )
        def spy( path, *args, _real=real, _name=name, **kwargs ):
            seen.append( ( _name, path ) )
            return _real( path, *args, **kwargs )
        monkeypatch.setattr( io, name, spy )
    return str( scratch ), seen, jobs


def test_the_rows_the_get_builds_read_the_resolvers_file_and_nothing_else( spied ):
    scratch, seen, jobs = spied
    rows = sw.build_rows( jobs )
    assert len( rows ) == len( jobs ) and len( jobs ) > 0
    assert seen and { path for _, path in seen } == { scratch }
    assert { name for name, _ in seen } == { "read_value_from_disk" }


def test_the_flip_the_put_makes_locates_and_writes_the_resolvers_file_and_nothing_else( spied ):
    scratch, seen, jobs = spied
    honoured = next( j for j in jobs if sw.is_honoured( j ) )[ "job" ]
    sw.write_switch( honoured, False, "rick@example.test" )
    assert { "locate_key", "write_bool_to_disk" } <= { name for name, _ in seen }, "the flip must locate the key and write it"
    assert { path for _, path in seen } == { scratch }
    assert sw.read_enabled( honoured ) is False, "the reader sees the file the writer just changed"
    assert { path for _, path in seen } == { scratch }
