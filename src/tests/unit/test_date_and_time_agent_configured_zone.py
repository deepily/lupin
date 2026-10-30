"""
Unit tests: the date-and-time agent takes its zone from configuration only.
"""
import pytest

from cosa.agents.agent_base import AgentBase
from cosa.agents.date_and_time_agent import DateAndTimeAgent
from cosa.config.app_timezone import InvalidAppTimezoneError
from cosa.config.configuration_manager import MissingConfigKeyError


class _Cfg:
    """A config that answers `app timezone` the way the real get_required does."""

    config_block_id = "Lupin:+Stub"

    def __init__( self, zone=None ):
        self.zone = zone

    def get_required( self, key, **_kwargs ):
        if self.zone is None: raise MissingConfigKeyError( key, self.config_block_id, None )
        return self.zone


@pytest.fixture
def make_agent( monkeypatch ):
    """Build a DateAndTimeAgent over an AgentBase.__init__ that seeds only what it reads."""
    def _make( zone ):
        def _seed( self, *args, **kwargs ):
            self.prompt_template = "Q[{question}] ZONE[{timezone}]"
            self.question        = kwargs.get( "question", "" )
            self.config_mgr      = _Cfg( zone )
        monkeypatch.setattr( AgentBase, "__init__", _seed )
        return DateAndTimeAgent( question="what time is it" )
    return _make


def test_a_configured_los_angeles_is_the_zone_in_the_prompt( make_agent ):
    agent = make_agent( "America/Los_Angeles" )
    assert agent.timezone == "America/Los_Angeles"
    assert "ZONE[America/Los_Angeles]" in agent.prompt


def test_an_absent_zone_key_stops_the_agent_from_being_built( make_agent ):
    with pytest.raises( MissingConfigKeyError ):
        make_agent( None )


def test_an_invalid_zone_stops_the_agent_from_being_built( make_agent ):
    with pytest.raises( InvalidAppTimezoneError ):
        make_agent( "Not/AZone" )
