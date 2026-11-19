"""
The committed value of the arm forecast ledger switch, read through the real manager.

The router tests use a stub config that returns the code default, so they cannot see a stray edit of the
INI file. This test reads the shipped file itself and holds the switch off until the live shadow starts.
"""

import pytest

import cosa.utils.util as cu
from cosa.config.configuration_manager import ConfigurationManager

KEY       = "prediction learner arm forecast ledger enabled"
_CONF_DIR = cu.get_project_root() + "/src/conf"


@pytest.fixture( autouse=True )
def _no_singleton_leak():
    """Drop the manager singleton after each test."""
    yield
    ConfigurationManager.reset_for_testing()


def test_the_shipped_ini_holds_the_switch_off_and_the_key_is_written_once():
    """Off in the committed file, as the manager reads it, with exactly one line naming the key."""
    lines = [ line for line in open( _CONF_DIR + "/lupin-app.ini" ).read().split( "\n" ) if line.startswith( KEY ) ]
    assert len( lines ) == 1
    config = ConfigurationManager( config_path=_CONF_DIR + "/lupin-app.ini", splainer_path=_CONF_DIR + "/lupin-app-splainer.ini",
                                   config_block_id="Lupin: Production", silent=True, mute_splainer=True, _reset_singleton=True )
    assert config.get( KEY, default=True, return_type="boolean" ) is False
