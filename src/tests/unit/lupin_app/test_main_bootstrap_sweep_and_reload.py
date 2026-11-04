"""
Unit tests for the parts of `lupin_app/main.py` that no server run reaches.

Four pieces, each driven in the process that runs the tests:

- the import-time bootstrap, executed from the file's own text up to the first helper import;
- the orphan sweep loop, with a stub that ends the loop after the pass under test;
- the snapshot cache invalidator the registry calls;
- the reload keyword arguments that `__main__` hands to uvicorn.
"""

import asyncio
import os
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

from lupin_app import bootstrap_helpers
from lupin_app import main

_MAIN_PATH = Path( main.__file__ )


# ── the import-time bootstrap ────────────────────────────────────────────────

def _bootstrap_text():
    """The text of main.py from line one to just before the first lupin_app helper import."""
    text = _MAIN_PATH.read_text()
    return text[ : text.index( "from lupin_app.bootstrap_helpers import" ) ]


def _run_bootstrap( monkeypatch, tmp_path, *, root, lora_lines=None, path_has_src=True ):
    """
    Execute the bootstrap text against a private environment, and return its namespace.

    The environment, the module search path and the home directory are replaced for the test.
    Nothing the bootstrap sets leaks into other tests.
    """
    env = { "HOME": str( tmp_path ) }
    if root is not None:
        env[ "LUPIN_ROOT" ] = root
    if lora_lines is not None:
        ( tmp_path / ".lora_env" ).write_text( "\n".join( lora_lines ) )
    search_path = [ p for p in sys.path if p != os.path.join( str( root ), "src" ) ]
    if path_has_src and root is not None:
        search_path.append( os.path.join( root, "src" ) )
    monkeypatch.setattr( os, "environ", env )
    monkeypatch.setattr( sys, "path", search_path )
    namespace = { "__name__": "lupin_app.bootstrap_under_test" }
    exec( compile( _bootstrap_text(), str( _MAIN_PATH ), "exec" ), namespace )
    return namespace, env


def test_bootstrap_refuses_to_start_without_lupin_root( monkeypatch, tmp_path ):
    """An unset LUPIN_ROOT stops the import with a message that says how to set it."""
    with pytest.raises( RuntimeError ) as caught:
        _run_bootstrap( monkeypatch, tmp_path, root=None )
    assert str( caught.value ).startswith( "LUPIN_ROOT environment variable not set." )
    assert "export LUPIN_ROOT=" in str( caught.value )


def test_bootstrap_puts_src_first_on_the_search_path_when_it_is_missing( monkeypatch, tmp_path ):
    """A search path without <root>/src gets it inserted at index 0."""
    _ns, _env = _run_bootstrap( monkeypatch, tmp_path, root="/the/root", path_has_src=False )
    assert sys.path[ 0 ] == "/the/root/src"
    assert sys.path.count( "/the/root/src" ) == 1


def test_bootstrap_leaves_the_search_path_alone_when_src_is_already_on_it( monkeypatch, tmp_path ):
    """A search path that already holds <root>/src is not given a second copy at the front."""
    _run_bootstrap( monkeypatch, tmp_path, root="/the/root", path_has_src=True )
    assert sys.path[ 0 ] != "/the/root/src"
    assert sys.path.count( "/the/root/src" ) == 1


def test_bootstrap_without_a_lora_file_changes_nothing( monkeypatch, tmp_path ):
    """No ~/.lora_env means the environment is exactly what the test supplied."""
    _ns, env = _run_bootstrap( monkeypatch, tmp_path, root="/the/root" )
    assert env == { "HOME": str( tmp_path ), "LUPIN_ROOT": "/the/root" }


def test_bootstrap_exports_only_well_formed_lora_lines( monkeypatch, tmp_path ):
    """Export lines with an equals sign set the variable, quotes stripped; others are skipped."""
    lines = [ 'export LORA_A="/models/a"', "export LORA_B=/models/b", "# a comment", "export NOEQUALS", "LORA_C=ignored" ]
    _ns, env = _run_bootstrap( monkeypatch, tmp_path, root="/the/root", lora_lines=lines )
    assert env[ "LORA_A" ] == "/models/a" and env[ "LORA_B" ] == "/models/b"
    assert "NOEQUALS" not in env and "LORA_C" not in env


# ── notification_expiry_sweep_loop ───────────────────────────────────────────

class FakeConfig:
    """A config double: get() returns the stored value, or the default when the key is absent."""

    def __init__( self, **values ):
        self.values = { k.replace( "_", " " ): v for k, v in values.items() }

    def get( self, key, default=None, return_type=None, silent=False ):
        return self.values.get( key, default )


def _run_sweep( result=None, *, raises=None, verbose=False, config=None ):
    """Run one pass of the sweep loop; return ( printed lines, naps, error raised by the loop )."""
    naps = []
    async def stub_sleep( delay ):
        naps.append( delay )
        raise asyncio.CancelledError()
    async def stub_to_thread( fn, *args ):
        stub_to_thread.args = args
        if raises is not None: raise raises
        return result
    shim = types.SimpleNamespace( sleep=stub_sleep, to_thread=stub_to_thread, CancelledError=asyncio.CancelledError )
    printed = []
    escaped = None
    with mock.patch.object( main, "asyncio", shim ), \
         mock.patch.object( main, "config_mgr", config or FakeConfig() ), \
         mock.patch.object( main, "app_debug", verbose ), \
         mock.patch.object( main, "app_verbose", verbose ), \
         mock.patch( "builtins.print", side_effect=lambda *a, **k: printed.append( " ".join( str( x ) for x in a ) ) ):
        try:
            asyncio.run( main.notification_expiry_sweep_loop() )
        except asyncio.CancelledError as e:
            escaped = e
    return printed, naps, escaped, stub_to_thread


def test_sweep_loop_reports_what_it_swept():
    """A pass that swept rows prints the count, the rows scanned and the rows still in grace."""
    printed, naps, _escaped, _tt = _run_sweep( { "swept": 3, "scanned": 10, "skipped_in_grace": 2 } )
    assert "[NOTIFY-SWEEP] swept 3 orphan(s) (scanned 10, 2 still in grace)" in printed
    assert naps == [ 300 ]


def test_sweep_loop_is_quiet_when_there_is_nothing_to_sweep():
    """A pass that swept nothing prints only the start line unless verbose logging is on."""
    printed, _naps, _escaped, _tt = _run_sweep( { "swept": 0, "scanned": 10, "skipped_in_grace": 2 } )
    assert len( printed ) == 2 and printed[ 0 ].startswith( "[NOTIFY-SWEEP] Starting orphan sweep loop" )
    assert printed[ 1 ] == "[NOTIFY-SWEEP] Sweep loop cancelled"


def test_sweep_loop_describes_an_empty_pass_when_verbose():
    """With debug and verbose on, an empty pass says what it scanned."""
    printed, _naps, _escaped, _tt = _run_sweep( { "swept": 0, "scanned": 10, "skipped_in_grace": 2 }, verbose=True )
    assert "[NOTIFY-SWEEP] nothing to sweep (scanned 10, 2 still in grace)" in printed


def test_sweep_loop_passes_its_ini_settings_to_the_sweeper():
    """The sweeper gets the INI grace period and batch limit, and the loop sleeps the interval."""
    config = FakeConfig( notification_expiry_sweep_interval_seconds=45, notification_expiry_sweep_batch_limit=7,
                         notification_grace_period_seconds=120 )
    _printed, naps, _escaped, to_thread = _run_sweep( { "swept": 0, "scanned": 0, "skipped_in_grace": 0 }, config=config )
    assert to_thread.args[ 1: ] == ( 120, 7 ) and naps == [ 45 ]


def test_sweep_loop_survives_a_database_error():
    """A sweeper error is printed and the loop backs off the full interval before trying again."""
    printed, naps, escaped, _tt = _run_sweep( raises=RuntimeError( "db down" ) )
    assert "[NOTIFY-SWEEP] Error in sweep loop: db down" in printed
    assert naps == [ 300 ]
    assert escaped is not None


# ── _invalidate_snapshot_mgr ─────────────────────────────────────────────────

def test_invalidator_reloads_the_snapshots_when_the_manager_exists( capsys ):
    """The registry's flush reaches the manager's reload() and prints one line."""
    manager = mock.MagicMock()
    with mock.patch.object( main, "snapshot_mgr", manager ):
        main._invalidate_snapshot_mgr()
    manager.reload.assert_called_once_with()
    assert capsys.readouterr().out == "Reloading solution snapshots...\n"


def test_invalidator_does_nothing_before_the_manager_is_built( capsys ):
    """A flush that arrives before boot has built the manager is a quiet no-op."""
    with mock.patch.object( main, "snapshot_mgr", None ):
        main._invalidate_snapshot_mgr()
    assert capsys.readouterr().out == ""


# ── reload_kwargs ────────────────────────────────────────────────────────────

def test_reload_kwargs_are_empty_when_reload_is_off():
    """A disabled reload adds no keyword arguments to uvicorn."""
    assert bootstrap_helpers.reload_kwargs( False ) == { }


def test_reload_kwargs_watch_only_runtime_packages():
    """An enabled reload watches the runtime packages, and no tests, notes, docs or history."""
    kwargs = bootstrap_helpers.reload_kwargs( True )
    assert kwargs[ "reload" ] is True
    dirs = kwargs[ "reload_dirs" ]
    assert dirs[ :4 ] == [ "lupin_app", "lib", "lupin_cli", "lupin_mcp" ]
    assert len( dirs ) == 15 and all( d.startswith( "cosa/" ) for d in dirs[ 4: ] )
    for banned in ( "cosa/tests", "cosa/rnd", "cosa/docs", "cosa/history", "migrations" ):
        assert banned not in dirs
