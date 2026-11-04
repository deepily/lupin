"""
Coverage closers for five near-complete scripts.

Each case reaches one line the sibling test never ran in-process.
The bootstrap refusal runs under runpy so coverage sees it.
The expiry helper's own tests drive it as a subprocess, which coverage does not follow.
"""

import importlib.util
import os
import runpy
import sys
import time
import types

import pytest

_SCRIPTS = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "scripts" )


def _load( name, rel ):
    spec = importlib.util.spec_from_file_location( name, os.path.join( _SCRIPTS, rel ) )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )
    return mod


@pytest.mark.parametrize( "rel", [ "submit-test-suite.py", "observe_gate_b_admission.py" ] )
def test_a_script_refuses_to_start_when_lupin_root_is_unset( monkeypatch, rel ):
    """An unset root stops each script by name."""
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    with pytest.raises( RuntimeError, match = "LUPIN_ROOT not set" ):
        runpy.run_path( os.path.join( _SCRIPTS, rel ), run_name="not_main" )


def test_follow_through_enabled_returns_the_configured_flag( monkeypatch ):
    """The flag comes from the config, so True and False come back as given."""
    chk = _load( "check_arbiter_venv_gap", "check-arbiter-venv.py" )
    import cosa.config.configuration_manager as cm
    seen = {}

    class _Cfg:
        def __init__( self, env_var_name ): seen[ "env" ] = env_var_name
        def get( self, key, default=None, return_type=None ):
            seen[ "key" ] = key
            return seen[ "answer" ]

    monkeypatch.setattr( cm, "ConfigurationManager", _Cfg )
    seen[ "answer" ] = True
    assert chk.follow_through_enabled() is True
    seen[ "answer" ] = False
    assert chk.follow_through_enabled() is False
    assert seen[ "key" ] == "follow through escalation enabled"


@pytest.mark.parametrize( "ms_offset, word, code", [ ( 86_400_000, "valid", 0 ), ( -86_400_000, "expired", 1 ) ] )
def test_login_expiry_main_prints_one_line_and_returns_by_verdict( capsys, ms_offset, word, code ):
    """Main prints one status line and returns 0 only for a valid expiry."""
    mod = _load( "claude_login_expiry_gap", os.path.join( "lib", "claude_login_expiry.py" ) )
    raw = str( int( time.time() * 1000 ) + ms_offset )
    assert mod.main( [ "prog", raw ] ) == code
    out = capsys.readouterr().out
    assert out.count( "\n" ) == 1 and out.startswith( word + " " )


def test_login_expiry_main_without_an_argument_is_unreadable( capsys ):
    """A missing argument reads as unreadable and exits 1."""
    mod = _load( "claude_login_expiry_gap2", os.path.join( "lib", "claude_login_expiry.py" ) )
    assert mod.main( [ "prog" ] ) == 1
    assert capsys.readouterr().out.startswith( "unreadable " )
