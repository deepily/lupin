"""
Unit tests: util time helpers and the arbiter journal read their zone from configuration.

Each stub answers through get_required, as the code under test reads it, and none offers a default.
"""
import pytest

import cosa.utils.util as cu
from cosa.config.app_timezone import InvalidAppTimezoneError, get_arbiter_journal_timezone
from cosa.config.configuration_manager import MissingConfigKeyError


class _Cfg:
    """A config answering any zone key through get_required."""

    config_block_id = "Lupin:+Stub"

    def __init__( self, zone ):
        self.zone = zone
        self.keys = []

    def get_required( self, key, **_kwargs ):
        self.keys.append( key )
        if self.zone is None: raise MissingConfigKeyError( key, self.config_block_id, None )
        return self.zone


@pytest.fixture
def configured_util( monkeypatch ):
    """cosa.utils.util with its lazily imported ConfigurationManager replaced by a stub."""
    def _install( zone ):
        stub = _Cfg( zone )
        monkeypatch.setattr( "cosa.config.configuration_manager.ConfigurationManager", lambda *a, **k: stub )
        return stub
    return _install


def test_a_given_zone_is_used_and_config_is_not_read( configured_util ):
    stub = configured_util( "America/Los_Angeles" )
    assert cu._resolve_tz_name( "Asia/Kolkata" ) == "Asia/Kolkata"
    assert stub.keys == []


def test_no_zone_reads_the_app_timezone_key( configured_util ):
    stub = configured_util( "America/Los_Angeles" )
    assert cu._resolve_tz_name( None ) == "America/Los_Angeles"
    assert stub.keys == [ "app timezone" ]


def test_every_time_helper_follows_the_configured_zone_when_given_none( configured_util ):
    """Kolkata is +05:30 with the abbreviation IST, which no whole-hour host zone can mimic."""
    import datetime as dt
    import pytz

    configured_util( "Asia/Kolkata" )

    assert cu.get_current_datetime_raw().tzname() == "IST"
    assert "IST" in cu.get_current_datetime()
    assert cu.get_current_datetime_iso().endswith( "+05:30" )
    assert cu.get_current_time().endswith( "IST" )
    assert cu.get_current_date() == dt.datetime.now( pytz.timezone( "Asia/Kolkata" ) ).strftime( "%Y-%m-%d" )


def test_the_helpers_stop_when_the_zone_key_is_missing( configured_util ):
    configured_util( None )
    with pytest.raises( MissingConfigKeyError ):
        cu.get_current_datetime_raw()


def test_the_helpers_stop_when_the_zone_is_unknown( configured_util ):
    configured_util( "Mars/Olympus_Mons" )
    with pytest.raises( InvalidAppTimezoneError ):
        cu.get_current_datetime_raw()


def test_an_explicit_zone_still_wins_when_config_is_broken( configured_util ):
    configured_util( None )
    assert cu.get_current_datetime_raw( "UTC" ).tzname() == "UTC"


def test_the_arbiter_journal_zone_reads_its_own_key():
    stub = _Cfg( "America/Chicago" )
    assert get_arbiter_journal_timezone( stub ) == "America/Chicago"
    assert stub.keys == [ "arbiter journal local timezone" ]


def test_the_arbiter_journal_zone_stops_when_missing_or_unknown():
    with pytest.raises( MissingConfigKeyError ):
        get_arbiter_journal_timezone( _Cfg( None ) )
    with pytest.raises( InvalidAppTimezoneError ):
        get_arbiter_journal_timezone( _Cfg( "Mars/Olympus_Mons" ) )


def test_assembling_the_arbiter_app_stops_when_the_journal_zone_is_missing( monkeypatch ):
    import lupin_arbiter_app.app as app_module

    class Cfg( _Cfg ):
        def get( self, key, default=None, return_type="string" ):
            if key in ( "arbiter health watch enabled", "arbiter context watch enabled" ): return False
            return default

    class GW:
        def post( self, *a, **k ): return None

    monkeypatch.setattr( "cosa.agents.utils.sender_id.detect_project", lambda: "lupin" )
    with pytest.raises( MissingConfigKeyError ):
        app_module.assemble_app( Cfg( None ), GW(), dm_push_fn=lambda *a: {} )
