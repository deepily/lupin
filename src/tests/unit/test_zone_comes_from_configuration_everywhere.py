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


def test_read_arbiter_journal_timezone_reads_the_process_configuration( monkeypatch ):
    from cosa.config.app_timezone import read_arbiter_journal_timezone
    stub = _Cfg( "Asia/Kolkata" )
    monkeypatch.setattr( "cosa.config.configuration_manager.ConfigurationManager", lambda *a, **k: stub )

    assert read_arbiter_journal_timezone() == "Asia/Kolkata"
    assert stub.keys == [ "arbiter journal local timezone" ]


def test_a_log_function_built_with_no_zone_resolves_it_from_configuration_at_the_first_call( monkeypatch ):
    import datetime
    import json
    from cosa.agents.heartbeat_arbiter.arbiter_journal import make_log_fn

    lines = []
    clock = lambda: datetime.datetime( 2026, 6, 11, 21, 28, 46, tzinfo=datetime.timezone.utc )
    log   = make_log_fn( now_fn=clock, emit_fn=lines.append )          # built before any config exists
    stub  = _Cfg( "Asia/Kolkata" )
    monkeypatch.setattr( "cosa.config.configuration_manager.ConfigurationManager", lambda *a, **k: stub )

    log( "one" )
    log( "two" )

    assert json.loads( lines[ 0 ] )[ "ts_local" ].endswith( "(IST)" )
    assert stub.keys == [ "arbiter journal local timezone" ]            # read once, kept after


def test_a_log_function_with_no_zone_and_no_configured_key_stops_at_the_first_call( monkeypatch ):
    from cosa.agents.heartbeat_arbiter.arbiter_journal import make_log_fn
    log = make_log_fn( emit_fn=lambda line: None )
    monkeypatch.setattr( "cosa.config.configuration_manager.ConfigurationManager", lambda *a, **k: _Cfg( None ) )

    with pytest.raises( MissingConfigKeyError ):
        log( "event" )


def test_the_arbiter_job_with_no_zone_takes_the_configured_journal_zone( monkeypatch ):
    from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob
    monkeypatch.setattr( "cosa.config.configuration_manager.ConfigurationManager", lambda *a, **k: _Cfg( "Asia/Kolkata" ) )

    job = ArbiterConsumerJob( commons=object(), poll_seconds=5, manager_recipient="Mgr",
                              notify_fn=lambda *a, **k: None, log_fn=lambda *a, **k: None )

    assert str( job._outreach_tz ) == "Asia/Kolkata"


def test_the_decision_proxy_zone_reads_its_own_key():
    from cosa.config.app_timezone import get_decision_proxy_timezone
    stub = _Cfg( "America/Chicago" )

    assert get_decision_proxy_timezone( stub ) == "America/Chicago"
    assert stub.keys == [ "decision proxy timezone" ]
    with pytest.raises( MissingConfigKeyError ):
        get_decision_proxy_timezone( _Cfg( None ) )
    with pytest.raises( InvalidAppTimezoneError ):
        get_decision_proxy_timezone( _Cfg( "Mars/Olympus_Mons" ) )
