#!/usr/bin/env python3
"""
Row 97c5bd94: the INI key `stale mcp check delivery enabled` ships in lupin-app.ini (with its
splainer twin) and the observer loop honors it as read by the REAL ConfigurationManager —
true, false, and missing (-> default True).

Venue: :7999-eligible / local — file reads + in-process loop, no server, no state.
"""
import configparser
import os

import pytest

import cosa.utils.util as cu
from cosa.config.configuration_manager import ConfigurationManager
import cosa.agents.heartbeat_arbiter.self_respin_observer as obs

KEY       = "stale mcp check delivery enabled"
_CONF_DIR = cu.get_project_root() + "/src/conf"


@pytest.fixture( autouse=True )
def _no_singleton_leak():
    yield
    ConfigurationManager.reset_for_testing()


def _real_cfg( tmp_path, block="Lupin: Production", drop_key=False, value=None ):
    """A ConfigurationManager over a copy of the shipped INI, optionally with the key dropped or overridden."""
    lines = open( _CONF_DIR + "/lupin-app.ini" ).read().split( "\n" )
    out   = []
    for line in lines:
        if line.startswith( KEY ):
            if drop_key: continue
            if value is not None: line = f"{KEY} = {value}"
        out.append( line )
    path = tmp_path / "app.ini"
    path.write_text( "\n".join( out ) )
    return ConfigurationManager( config_path=str( path ), splainer_path=_CONF_DIR + "/lupin-app-splainer.ini",
                                 config_block_id=block, silent=True, mute_splainer=True, _reset_singleton=True )


def _loop( tmp_path, cfg, dms ):
    return obs.SelfRespinObserverLoop(
        cfg, fetch_pressure_fn=lambda: { "personas": None }, base_dir=str( tmp_path ),
        advisory_fn=lambda m: None,
        stale_mcp_fn=lambda: [ { "pid": 7, "start_epoch": 1.0, "start_ticks": 100, "tmux_session": "s", "tmux_pane": "%1", "stale": True } ],
        dm_push_fn=lambda to, thread, body: dms.append( to ) or { "outcome": "dispatched" },
        seat_lookup_fn=lambda r: ( "Sam", "Mr. Radio" ) )


def test_the_key_ships_in_the_ini_and_its_splainer():
    for name in ( "lupin-app.ini", "lupin-app-splainer.ini" ):
        parser = configparser.ConfigParser()
        parser.read( os.path.join( _CONF_DIR, name ) )
        assert any( KEY in parser[ s ] for s in parser.sections() ), f"{KEY} missing from {name}"
    assert any( l.startswith( KEY ) and l.rstrip().endswith( "= true" ) for l in open( _CONF_DIR + "/lupin-app.ini" ) )


@pytest.mark.parametrize( "block", [ "Lupin: Production", "Lupin: Development", "Lupin: Testing" ] )
def test_the_shipped_ini_reads_true_in_every_inheriting_block( tmp_path, block ):
    cfg = _real_cfg( tmp_path, block=block )
    assert cfg.get( KEY, default=False, return_type="boolean" ) is True


@pytest.mark.parametrize( "kind, expected", [ ( "on", 1 ), ( "off", 0 ), ( "missing", 1 ) ] )
def test_the_loop_honors_the_ini_key( tmp_path, kind, expected ):
    cfg = _real_cfg( tmp_path, drop_key=( kind == "missing" ), value={ "on": "true", "off": "false" }.get( kind ) )
    dms = []
    _loop( tmp_path, cfg, dms ).sweep_once()
    assert len( dms ) == expected
