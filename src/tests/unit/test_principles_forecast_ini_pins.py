"""
The committed switch and cap of the principles forecast, read through the real manager.

A router test cannot see a stray edit of the INI file, so this reads the shipped file. The switch stays off
until the remediation's background forecast job exists.
The commit that turns it on must change this test with it.
"""

import pytest

import cosa.agents.prediction_engine.principles_forecast as pf
import cosa.utils.util as cu
from cosa.config.configuration_manager import ConfigurationManager

_CONF_DIR = cu.get_project_root() + "/src/conf"


@pytest.fixture( autouse=True )
def _no_singleton_leak():
    """Drop the manager singleton after each test."""
    yield
    ConfigurationManager.reset_for_testing()


def _manager():
    """Open the shipped INI file as production reads it."""
    return ConfigurationManager( config_path=_CONF_DIR + "/lupin-app.ini", splainer_path=_CONF_DIR + "/lupin-app-splainer.ini",
                                 config_block_id="Lupin: Production", silent=True, mute_splainer=True, _reset_singleton=True )


@pytest.mark.parametrize( "key", [ pf.SWITCH_KEY, pf.CAP_KEY ] )
def test_each_key_is_written_once_in_the_ini_and_explained_once_in_the_splainer( key ):
    """One line in each file names the key, so no later line can quietly override it."""
    for name in ( "lupin-app.ini", "lupin-app-splainer.ini" ):
        assert len( [ line for line in open( f"{_CONF_DIR}/{name}" ).read().split( "\n" ) if line.startswith( key ) ] ) == 1, name


def test_the_shipped_ini_holds_the_switch_off():
    """Off in the committed file, as the manager reads it."""
    assert _manager().get( pf.SWITCH_KEY, default=True, return_type="boolean" ) is False


def test_the_shipped_ini_holds_the_cap_at_two():
    """The cap is the baseline job's default of two, in its own key."""
    assert _manager().get_required( pf.CAP_KEY, return_type="int" ) == 2
