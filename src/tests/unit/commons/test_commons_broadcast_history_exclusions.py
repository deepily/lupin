"""The broadcast-history endpoint reads its excluded topics from the INI list with split_csv."""
import asyncio
import json

import pytest

from cosa.rest.routers import commons as commons_module


class _FakeConfig:
    """Answers the three keys the endpoint reads, and records nothing else."""

    def __init__( self, exclude_text ):
        self.exclude_text = exclude_text

    def get( self, key, return_type=None, default=None ):
        if key == "commons traffic visibility enabled"                : return True
        if key == "commons traffic visibility exclude topics"         : return self.exclude_text
        if key == "commons traffic visibility max entries per response": return 500
        raise AssertionError( f"unexpected key {key}" )


def _excluded_topics_seen( monkeypatch, exclude_text ):
    """Run the endpoint with the INI text and return the excluded_topics it passed on."""
    seen = {}
    def fake_execute( **kwargs ):
        seen.update( kwargs )
        return { "entries": [] }
    monkeypatch.setattr( commons_module, "ConfigurationManager", lambda env_var_name=None: _FakeConfig( exclude_text ) )
    monkeypatch.setattr( commons_module, "_require_initialized", lambda: None )
    monkeypatch.setattr( commons_module, "find_active_voice_persona_sessions", lambda: [] )
    monkeypatch.setattr( commons_module, "execute_broadcast_history", fake_execute )
    response = asyncio.run( commons_module.get_broadcast_history( "user-1" ) )
    assert json.loads( response.body ) == { "entries": [] }
    return seen[ "excluded_topics" ]


@pytest.mark.parametrize( "ini_text, expected", [
    ( "presence,system-events"           , [ "presence", "system-events" ] ),
    ( " presence , , system-events ,"    , [ "presence", "system-events" ] ),
    ( ""                                 , [] ),
    ( None                               , [] ),
] )
def test_the_ini_list_is_stripped_and_blanks_dropped( monkeypatch, ini_text, expected ):
    """Padding and empty entries in the operator's list never become topic names."""
    assert _excluded_topics_seen( monkeypatch, ini_text ) == expected
