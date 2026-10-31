"""
Unit tests: the one reader of `app timezone` takes the zone only from configuration.

A missing, blank or invalid zone stops the caller. The reader is exercised through the real
ConfigurationManager on a throwaway INI, so the absent-key and blank-key paths are the real ones.
"""
import textwrap

import pytest

from cosa.config.app_timezone import InvalidAppTimezoneError, get_app_timezone
from cosa.config.configuration_manager import ConfigurationManager, MissingConfigKeyError


def _manager( tmp_path, zone_line ):
    """A real ConfigurationManager over an INI holding the given zone line ( or none )."""
    ini = tmp_path / "zone.ini"
    ini.write_text( textwrap.dedent( f"""\
        [default]
        some other key = 1

        [zone]
        {zone_line}
        """ ) )
    splainer = tmp_path / "zone-splainer.ini"
    splainer.write_text( "[default]\nsome other key = a key\napp timezone = the user zone\n" )
    try:
        yield ConfigurationManager( config_path=str( ini ), splainer_path=str( splainer ), config_block_id="zone", silent=True, _reset_singleton=True )
    finally:
        ConfigurationManager.reset_for_testing()


@pytest.fixture
def configured( tmp_path ):
    yield from _manager( tmp_path, "app timezone = America/Los_Angeles" )


@pytest.fixture
def absent( tmp_path ):
    yield from _manager( tmp_path, "" )


@pytest.fixture
def blank( tmp_path ):
    yield from _manager( tmp_path, "app timezone = " )


@pytest.fixture
def bogus( tmp_path ):
    yield from _manager( tmp_path, "app timezone = Mars/Olympus_Mons" )


def test_the_configured_zone_is_returned_as_written( configured ):
    assert get_app_timezone( configured ) == "America/Los_Angeles"


def test_an_absent_key_raises_and_names_the_key( absent ):
    with pytest.raises( MissingConfigKeyError ) as raised:
        get_app_timezone( absent )
    assert raised.value.key == "app timezone"


def test_a_blank_key_raises( blank ):
    with pytest.raises( MissingConfigKeyError ):
        get_app_timezone( blank )


def test_an_unknown_zone_raises_naming_the_key_and_the_block( bogus ):
    with pytest.raises( InvalidAppTimezoneError ) as raised:
        get_app_timezone( bogus )
    assert "app timezone" in str( raised.value ) and "[zone]" in str( raised.value ) and "Mars/Olympus_Mons" in str( raised.value )


def test_a_malformed_zone_name_raises_the_same_error():
    class _Cfg:
        config_block_id = "Lupin:+Stub"
        def get_required( self, key, **_kwargs ): return "../etc/passwd"
    with pytest.raises( InvalidAppTimezoneError ):
        get_app_timezone( _Cfg() )


def test_the_reader_offers_no_default_to_the_manager():
    seen = []
    class _Cfg:
        config_block_id = "Lupin:+Stub"
        def get_required( self, key, **kwargs ):
            seen.append( ( key, kwargs ) )
            return "UTC"
    assert get_app_timezone( _Cfg() ) == "UTC"
    assert seen == [ ( "app timezone", {} ) ]


def test_a_started_manager_is_returned_unchanged( configured ):
    from cosa.config.app_timezone import process_config_mgr
    assert process_config_mgr( configured ) is configured


def test_before_startup_the_process_configuration_is_loaded_not_a_default( monkeypatch, tmp_path ):
    """The app never started in this process, so main's manager is None."""
    from cosa.config.app_timezone import get_app_timezone, process_config_mgr
    ini = tmp_path / "p.ini"
    ini.write_text( "[default]\nk = 1\n\n[proc]\napp timezone = Asia/Tokyo\n" )
    spl = tmp_path / "p-splainer.ini"
    spl.write_text( "[default]\nk = a key\napp timezone = the user zone\n" )
    ConfigurationManager.reset_for_testing()
    monkeypatch.setenv( "LUPIN_CONFIG_MGR_CLI_ARGS", "config_path=/p.ini splainer_path=/p-splainer.ini config_block_id=proc" )
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
    try:
        assert get_app_timezone( process_config_mgr( None ) ) == "Asia/Tokyo"
    finally:
        ConfigurationManager.reset_for_testing()


def test_a_notification_built_before_startup_gets_the_configured_zone( monkeypatch, tmp_path ):
    """Same entry as the incident: NotificationItem with lupin_app.main.config_mgr still None."""
    import lupin_app.main as main_module
    from cosa.rest.notification_fifo_queue import NotificationItem
    ini = tmp_path / "p.ini"
    ini.write_text( "[default]\nk = 1\n\n[proc]\napp timezone = Asia/Tokyo\n" )
    spl = tmp_path / "p-splainer.ini"
    spl.write_text( "[default]\nk = a key\napp timezone = the user zone\n" )
    ConfigurationManager.reset_for_testing()
    monkeypatch.setenv( "LUPIN_CONFIG_MGR_CLI_ARGS", "config_path=/p.ini splainer_path=/p-splainer.ini config_block_id=proc" )
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
    monkeypatch.setattr( main_module, "config_mgr", None )
    try:
        item = NotificationItem( message="m", type="task", priority="medium", user_id="u1" )
        assert item.timestamp.endswith( "+09:00" ) and item.to_dict()[ "time_display" ].endswith( "JST" )
    finally:
        ConfigurationManager.reset_for_testing()
