"""
Tests for the decision-log switch, read through the real ConfigurationManager.

The manager returns text unless asked for a boolean, so the switch must ask. The stub in
test_commons_llm_disambiguator.py returns Python bools and cannot see this.
"""

import pytest

import cosa.utils.util as cu
from cosa.config.configuration_manager import ConfigurationManager
from lupin_mcp.commons_llm_disambiguator import CommonsLlmDisambiguator

KEY       = "commons llm disambiguator log decisions"
_CONF_DIR = cu.get_project_root() + "/src/conf"


@pytest.fixture( autouse=True )
def _no_singleton_leak():
    yield
    ConfigurationManager.reset_for_testing()


def _real_cfg( tmp_path, value=None, drop_key=False ):
    """A manager over a copy of the shipped INI with the switch dropped or overridden."""
    out = []
    for line in open( _CONF_DIR + "/lupin-app.ini" ).read().split( "\n" ):
        if line.startswith( KEY ):
            if drop_key: continue
            if value is not None: line = f"{KEY} = {value}"
        out.append( line )
    path = tmp_path / "app.ini"
    path.write_text( "\n".join( out ) )
    return ConfigurationManager( config_path=str( path ), splainer_path=_CONF_DIR + "/lupin-app-splainer.ini",
                                 config_block_id="Lupin: Production", silent=True, mute_splainer=True,
                                 _reset_singleton=True )


@pytest.mark.parametrize( "text, expected", [
    ( "False", False ), ( "false", False ), ( "True", True ), ( "true", True ),
] )
def test_the_switch_follows_the_text_in_the_ini( tmp_path, text, expected ):
    assert CommonsLlmDisambiguator( _real_cfg( tmp_path, value=text ) ).log_decisions is expected


def test_the_shipped_ini_turns_the_log_on( tmp_path ):
    assert CommonsLlmDisambiguator( _real_cfg( tmp_path ) ).log_decisions is True


def test_a_missing_key_leaves_the_log_off( tmp_path ):
    assert CommonsLlmDisambiguator( _real_cfg( tmp_path, drop_key=True ) ).log_decisions is False
