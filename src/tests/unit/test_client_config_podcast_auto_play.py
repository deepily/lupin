"""
The client-config payload carries the podcast auto-play setting.

Both clients read `podcast_auto_play_here_on_finish` from /api/config/client when they load.
"""

import asyncio
import configparser
import pathlib

import cosa.rest.routers.system as system
from cosa.utils import util as cu


class _FakeConfig:
    """A configuration manager that answers from a dict and records each key it was asked for."""

    def __init__( self, values ):
        self.values = values
        self.asked  = [ ]

    def get( self, key, default=None, return_type="str" ):
        """Ensures: returns the dict's value for key, else default, and notes the key."""
        self.asked.append( ( key, default, return_type ) )
        return self.values.get( key, default )


def _payload( monkeypatch, values ):
    """Ensures: returns ( payload, fake ) from get_client_config run on a manager holding values."""
    fake = _FakeConfig( values )
    monkeypatch.setattr( system, "ConfigurationManager", lambda *a, **k: fake )
    monkeypatch.setattr( system, "get_app_timezone", lambda cfg: "America/New_York" )
    return asyncio.run( system.get_client_config( "someone" ) ), fake


def test_the_payload_says_true_when_the_key_is_not_set( monkeypatch ):
    """No key in the file means the default of true, asked as a boolean."""
    payload, fake = _payload( monkeypatch, { } )
    assert payload[ "podcast_auto_play_here_on_finish" ] is True
    assert ( "podcast auto play here on finish", True, "boolean" ) in fake.asked


def test_the_payload_follows_the_key_when_it_is_false( monkeypatch ):
    """A false setting reaches the page as false, so the page leaves the Play Here link alone."""
    payload, _ = _payload( monkeypatch, { "podcast auto play here on finish": False } )
    assert payload[ "podcast_auto_play_here_on_finish" ] is False


def test_the_shipped_ini_sets_it_true_and_the_splainer_explains_it():
    """The key is in the Baseline section as true, and the splainer file has the same key."""
    root = pathlib.Path( cu.get_project_root() )
    ini  = configparser.ConfigParser( interpolation=None, strict=False )
    ini.optionxform = str
    ini.read( root / "src/conf/lupin-app.ini" )
    assert ini[ "Lupin: Baseline" ][ "podcast auto play here on finish" ] == "true"
    splain = ( root / "src/conf/lupin-app-splainer.ini" ).read_text()
    assert "\npodcast auto play here on finish = " in splain
