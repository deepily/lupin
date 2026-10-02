#!/usr/bin/env python3
"""
Row c9252819: spawn_sessions silently ignored the INI worker-model pin when the cosa-voice
registration lacked LUPIN_CONFIG_MGR_CLI_ARGS.

Three things are pinned here:
    - `_spawn_config_mgr` records WHY it returned None, and clears that on success
    - the REAL manager, built from the dev block, resolves the Sonnet pin (not a stub)
    - `spawn_sessions` says so in its return when the manager is unavailable
    - the install script registers the variable, with a value ConfigurationManager accepts
"""
import importlib
import os
import sys
from pathlib import Path

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

REPO_ROOT  = Path( _src_path ).parent
DEV_ARGS   = "config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Development"


@pytest.fixture( scope="module" )
def cv_mcp():
    return importlib.import_module( "lupin_mcp.cosa_voice_mcp" )


@pytest.fixture( autouse=True )
def fresh_config_singleton():
    """ConfigurationManager is a process-wide singleton; a manager built by an earlier test would mask the unset variable."""
    from cosa.config.configuration_manager import ConfigurationManager
    ConfigurationManager.reset_for_testing()
    yield
    ConfigurationManager.reset_for_testing()


def test_unavailable_manager_returns_none_and_records_the_cause( cv_mcp, monkeypatch ):
    monkeypatch.delenv( "LUPIN_CONFIG_MGR_CLI_ARGS", raising=False )
    monkeypatch.setattr( cv_mcp, "_spawn_config_error", None )
    assert cv_mcp._spawn_config_mgr() is None
    assert "LUPIN_CONFIG_MGR_CLI_ARGS" in cv_mcp._spawn_config_error


def test_resolved_manager_yields_the_sonnet_pin_and_clears_the_cause( cv_mcp, monkeypatch ):
    import lupin_mcp.session_spawner as ss
    monkeypatch.setenv( "LUPIN_ROOT", str( REPO_ROOT ) )
    monkeypatch.setenv( "LUPIN_CONFIG_MGR_CLI_ARGS", DEV_ARGS )
    monkeypatch.setattr( cv_mcp, "_spawn_config_error", "stale cause" )
    mgr = cv_mcp._spawn_config_mgr()
    assert mgr is not None and cv_mcp._spawn_config_error is None
    models = ss.resolve_spawn_config( mgr )[ "spawn_models" ]
    assert models == { "reviewer": "claude-sonnet-5-5", "author": "claude-sonnet-5-5",
                       "observer": "claude-sonnet-5-5", "default": "claude-sonnet-5-5" }


def _patch_wrapper( cv_mcp, monkeypatch, mgr, error ):
    import lupin_mcp.session_spawner as ss
    monkeypatch.setattr( cv_mcp, "_wait_for_sender_id", lambda: "sender" )
    monkeypatch.setattr( cv_mcp, "_get_cc_metadata",    lambda: { "session_id": "abc12345" } )
    monkeypatch.setattr( cv_mcp, "_spawn_config_mgr",   lambda: mgr )
    monkeypatch.setattr( cv_mcp, "_spawn_config_error", error )
    monkeypatch.setattr( cv_mcp, "_spawn_script_path",  lambda: "/s.sh" )
    monkeypatch.setattr( ss, "resolve_manager_identity", lambda meta, fallback_session_id=None: ( "mgr-sid", "Rio" ) )
    monkeypatch.setattr( ss, "resolve_spawn_config",
                         lambda m: { "spawn_cap": 8, "ack_timeout_seconds": 120, "write_memento_default": True,
                                     "spawn_models": { "reviewer": None, "author": None, "observer": None, "default": None } } )
    monkeypatch.setattr( ss, "spawn_sessions", lambda *a, **kw: { "spawned": [], "model": kw[ "model" ] } )


def test_wrapper_warns_and_names_the_cause_when_the_manager_is_unavailable( cv_mcp, monkeypatch ):
    _patch_wrapper( cv_mcp, monkeypatch, None, "[LUPIN_CONFIG_MGR_CLI_ARGS] is NOT set" )
    result = cv_mcp.spawn_sessions.fn( 1, "t", role="author" )
    assert "LUPIN_CONFIG_MGR_CLI_ARGS] is NOT set" in result[ "config_warning" ]
    assert "install-cosa-voice.sh" in result[ "config_warning" ]
    assert result[ "model" ] is None                       # existing behaviour: still spawns, on the user default


def test_wrapper_adds_no_warning_when_the_manager_resolved( cv_mcp, monkeypatch ):
    _patch_wrapper( cv_mcp, monkeypatch, object(), None )
    assert "config_warning" not in cv_mcp.spawn_sessions.fn( 1, "t", role="author" )


def test_install_script_registers_the_config_variable_with_a_value_the_manager_accepts( monkeypatch ):
    text = ( REPO_ROOT / "src" / "scripts" / "install-cosa-voice.sh" ).read_text( encoding="utf-8" )
    assert text.count( 'LUPIN_CONFIG_MGR_CLI_ARGS=$CONFIG_MGR_CLI_ARGS' ) == 2        # the add AND the manual-retry hint
    line = next( l for l in text.splitlines() if l.startswith( "CONFIG_MGR_CLI_ARGS=" ) )
    assert line == f'CONFIG_MGR_CLI_ARGS="{DEV_ARGS.replace( "Lupin:+Development", "$LUPIN_MCP_CONFIG_BLOCK" )}"'
    assert 'LUPIN_MCP_CONFIG_BLOCK="${LUPIN_MCP_CONFIG_BLOCK:-Lupin:+Development}"' in text
    from cosa.config.configuration_manager import ConfigurationManager      # the string the script emits must build a manager
    monkeypatch.setenv( "LUPIN_ROOT", str( REPO_ROOT ) )
    monkeypatch.setenv( "LUPIN_CONFIG_MGR_CLI_ARGS", DEV_ARGS )
    assert ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ) is not None
