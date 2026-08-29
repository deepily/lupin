"""
Unit tests for cosa_voice_mcp's commons configuration layer.

This is the defensive band between the INI and everything commons does: config
resolution, storage-root interpretation, the enable flag, the lazy CommonsStore
singleton, the archival daemon's start gate, and persona-field extraction.

Every function here is written to DEGRADE rather than raise — the MCP server is
expected to keep working when ConfigurationManager, the session bridge, or the
config file is unavailable. That contract had no tests, which is the awkward
combination: the code is defensive by design and nothing checked the defenses.

⚠️ The archival-daemon test NEVER starts a real thread — `CommonsArchiver` is
replaced. A unit test that boots a 24h background daemon leaks it into every
later test in the interpreter.

Venue: :7999-eligible — pure unit, no server, no state mutation, no threads.
"""

import json

import pytest

import lupin_mcp.cosa_voice_mcp as cv


@pytest.fixture( autouse=True )
def _restore_commons_globals( monkeypatch ):
    """
    `_get_commons_store` and `_maybe_start_commons_archival_daemon` assign
    module-level singletons. Restored around every test so one test's store
    cannot be handed to the next — or worse, to a test that expected a real one.
    """
    monkeypatch.setattr( cv, "_commons_store_singleton", None, raising=False )
    monkeypatch.setattr( cv, "_commons_archiver_singleton", None, raising=False )


# ── config resolution ─────────────────────────────────────────────────────────

class TestLoadCommonsConfig:

    def test_returns_all_six_defaults_when_nothing_overrides_them( self, monkeypatch ):
        monkeypatch.delenv( "LUPIN_COMMONS_TEST_OVERRIDE", raising=False )
        # Force the ConfigurationManager arm to fail so we read pure defaults.
        import cosa.config.configuration_manager as cm_mod
        monkeypatch.setattr( cm_mod, "ConfigurationManager",
                             lambda **k: ( _ for _ in () ).throw( RuntimeError( "no config" ) ) )

        got = cv._load_commons_config()
        assert got == cv._COMMONS_CONFIG_DEFAULTS
        assert set( got ) == set( cv._COMMONS_CONFIG_DEFAULTS )

    def test_a_missing_configuration_manager_degrades_to_defaults_with_a_warning( self, monkeypatch, caplog ):
        # The MCP server must keep working when the wider config infrastructure
        # is not there — that is the whole point of this function.
        monkeypatch.delenv( "LUPIN_COMMONS_TEST_OVERRIDE", raising=False )
        import cosa.config.configuration_manager as cm_mod
        def boom( **k ):
            raise RuntimeError( "LUPIN_CONFIG_MGR_CLI_ARGS unset" )
        monkeypatch.setattr( cm_mod, "ConfigurationManager", boom )

        with caplog.at_level( "WARNING", logger=cv.logger.name ):
            got = cv._load_commons_config()

        assert got[ "commons_enabled" ] is True
        assert "using hardcoded defaults" in caplog.text

    def test_configuration_manager_values_win_over_the_defaults( self, monkeypatch ):
        monkeypatch.delenv( "LUPIN_COMMONS_TEST_OVERRIDE", raising=False )
        import cosa.config.configuration_manager as cm_mod

        class _CM:
            def __init__( self, **k ): pass
            def get( self, key, default=None, return_type=None, silent=False ):
                return { "commons enabled"          : False,
                         "commons retention hours"  : 999 }.get( key, default )
        monkeypatch.setattr( cm_mod, "ConfigurationManager", _CM )

        got = cv._load_commons_config()
        assert got[ "commons_enabled" ] is False
        assert got[ "commons_retention_hours" ] == 999
        assert got[ "commons_storage_path" ] == "/io/commons"    # untouched key keeps its default

    def test_the_test_override_hatch_short_circuits_the_config_manager( self, monkeypatch, caplog ):
        import cosa.config.configuration_manager as cm_mod
        def must_not_run( **k ):
            raise AssertionError( "ConfigurationManager must be bypassed by the override" )
        monkeypatch.setattr( cm_mod, "ConfigurationManager", must_not_run )
        monkeypatch.setenv( "LUPIN_COMMONS_TEST_OVERRIDE",
                            json.dumps( { "commons_enabled": False, "commons_retention_hours": 1 } ) )

        with caplog.at_level( "INFO", logger=cv.logger.name ):
            got = cv._load_commons_config()

        assert got[ "commons_enabled" ] is False
        assert got[ "commons_retention_hours" ] == 1
        assert "LUPIN_COMMONS_TEST_OVERRIDE applied" in caplog.text

    def test_a_non_object_override_is_ignored_and_the_normal_path_runs( self, monkeypatch, caplog ):
        # `[1,2,3]` is valid JSON but cannot be merged into a config dict. It
        # must not silently become the config, and it must not abort the load.
        monkeypatch.setenv( "LUPIN_COMMONS_TEST_OVERRIDE", "[1, 2, 3]" )
        import cosa.config.configuration_manager as cm_mod
        monkeypatch.setattr( cm_mod, "ConfigurationManager",
                             lambda **k: ( _ for _ in () ).throw( RuntimeError( "no config" ) ) )

        with caplog.at_level( "WARNING", logger=cv.logger.name ):
            got = cv._load_commons_config()

        assert got == cv._COMMONS_CONFIG_DEFAULTS
        assert "not a JSON object" in caplog.text

    def test_unparseable_override_json_is_ignored_rather_than_fatal( self, monkeypatch, caplog ):
        monkeypatch.setenv( "LUPIN_COMMONS_TEST_OVERRIDE", "{not json" )
        import cosa.config.configuration_manager as cm_mod
        monkeypatch.setattr( cm_mod, "ConfigurationManager",
                             lambda **k: ( _ for _ in () ).throw( RuntimeError( "no config" ) ) )

        with caplog.at_level( "WARNING", logger=cv.logger.name ):
            got = cv._load_commons_config()

        assert got == cv._COMMONS_CONFIG_DEFAULTS
        assert "parse failed" in caplog.text


# ── storage root ──────────────────────────────────────────────────────────────

class TestCommonsStorageRoot:

    def test_project_root_prefers_the_env_var( self, monkeypatch ):
        monkeypatch.setenv( "LUPIN_ROOT", "/somewhere/else" )
        assert cv._commons_project_root() == "/somewhere/else"

    def test_project_root_falls_back_to_the_package_location( self, monkeypatch ):
        monkeypatch.delenv( "LUPIN_ROOT", raising=False )
        got = cv._commons_project_root()
        assert got and not got.endswith( "lupin_mcp" )      # walked up out of the package

    def test_the_default_path_is_absorbed_because_the_store_appends_it_itself( self, monkeypatch ):
        # `/io/commons` is CommonsStore's own hardcoded subpath. Passing it
        # through would produce io/commons/io/commons.
        monkeypatch.setenv( "LUPIN_ROOT", "/root" )
        monkeypatch.setitem( cv._COMMONS_CONFIG, "commons_storage_path", "/io/commons" )
        assert cv._commons_storage_root() == "/root"

    def test_a_custom_path_is_appended_to_the_project_root( self, monkeypatch ):
        monkeypatch.setenv( "LUPIN_ROOT", "/root" )
        monkeypatch.setitem( cv._COMMONS_CONFIG, "commons_storage_path", "/custom/spot" )
        assert cv._commons_storage_root() == "/root/custom/spot"


class TestCachedFlagAccessors:
    def test_enabled_reads_the_cached_config( self, monkeypatch ):
        monkeypatch.setitem( cv._COMMONS_CONFIG, "commons_enabled", False )
        assert cv._commons_enabled() is False
        monkeypatch.setitem( cv._COMMONS_CONFIG, "commons_enabled", True )
        assert cv._commons_enabled() is True

    def test_the_grace_default_is_coerced_to_float( self, monkeypatch ):
        # The INI can hand back an int; callers pass this straight into a timeout.
        monkeypatch.setitem( cv._COMMONS_CONFIG, "commons_ask_sync_grace_seconds", 3 )
        got = cv._commons_ask_sync_grace_default()
        assert got == 3.0 and isinstance( got, float )


# ── lazy singletons ───────────────────────────────────────────────────────────

class TestCommonsStoreSingleton:
    def test_the_store_is_built_once_and_reused( self, monkeypatch ):
        built = []
        monkeypatch.setattr( cv, "CommonsStore", lambda root: built.append( root ) or object() )
        monkeypatch.setattr( cv, "_commons_storage_root", lambda: "/root" )

        first  = cv._get_commons_store()
        second = cv._get_commons_store()

        assert first is second
        assert built == [ "/root" ]                        # constructed exactly once


class TestArchivalDaemonStartGate:
    """
    The daemon is started from `__main__` only, so a bare import never boots it.
    The gate below is the second guard: commons disabled means no daemon at all.
    """

    def test_a_disabled_commons_starts_no_daemon( self, monkeypatch, caplog ):
        monkeypatch.setitem( cv._COMMONS_CONFIG, "commons_enabled", False )
        def must_not_run( **k ):
            raise AssertionError( "archiver must not be constructed when commons is disabled" )
        monkeypatch.setattr( cv, "CommonsArchiver", must_not_run )

        with caplog.at_level( "INFO", logger=cv.logger.name ):
            assert cv._maybe_start_commons_archival_daemon() is None

        assert "archival daemon NOT started" in caplog.text

    def test_an_enabled_commons_starts_the_daemon_with_the_configured_interval( self, monkeypatch ):
        made = {}

        class _FakeArchiver:
            def __init__( self, root, interval_seconds, retention_hours ):
                made.update( root=root, interval=interval_seconds, retention=retention_hours )
                self.started = False
            def start( self ):
                self.started = True

        monkeypatch.setitem( cv._COMMONS_CONFIG, "commons_enabled", True )
        monkeypatch.setitem( cv._COMMONS_CONFIG, "commons_archival_interval_seconds", 60 )
        monkeypatch.setitem( cv._COMMONS_CONFIG, "commons_retention_hours", 2 )
        monkeypatch.setattr( cv, "CommonsArchiver", _FakeArchiver )
        monkeypatch.setattr( cv, "_commons_storage_root", lambda: "/root" )

        archiver = cv._maybe_start_commons_archival_daemon()

        assert archiver.started is True
        assert made == { "root": "/root", "interval": 60, "retention": 2 }

    def test_a_second_call_returns_the_running_daemon_rather_than_a_second_one( self, monkeypatch ):
        # Two archivers over one directory would both sweep it.
        calls = []

        class _FakeArchiver:
            def __init__( self, **k ): calls.append( k )
            def start( self ): pass

        monkeypatch.setitem( cv._COMMONS_CONFIG, "commons_enabled", True )
        monkeypatch.setattr( cv, "CommonsArchiver", _FakeArchiver )
        monkeypatch.setattr( cv, "_commons_storage_root", lambda: "/root" )

        first  = cv._maybe_start_commons_archival_daemon()
        second = cv._maybe_start_commons_archival_daemon()

        assert first is second
        assert len( calls ) == 1


# ── persona fields ────────────────────────────────────────────────────────────

class TestCommonsPersonaFields:
    def test_reads_name_icon_and_color_from_the_bridge( self, monkeypatch ):
        monkeypatch.setattr( cv, "_get_cc_metadata",
                             lambda: { "voice_persona": { "name": "sam", "icon": "🎙️", "color": "#5E35B1" } } )
        assert cv._commons_persona_fields() == {
            "persona_name": "sam", "persona_icon": "🎙️", "persona_color": "#5E35B1" }

    def test_a_missing_bridge_falls_back_to_the_defaults( self, monkeypatch ):
        def boom():
            raise RuntimeError( "no bridge file" )
        monkeypatch.setattr( cv, "_get_cc_metadata", boom )
        got = cv._commons_persona_fields()
        assert got[ "persona_name" ]  == cv.DEFAULT_PERSONA_NAME
        assert got[ "persona_icon" ]  == cv.DEFAULT_PERSONA_ICON
        assert got[ "persona_color" ] == cv.DEFAULT_PERSONA_COLOR

    def test_a_failed_persona_allocation_falls_back_field_by_field( self, monkeypatch ):
        # Allocation can half-succeed: a null persona block, or a name with no
        # icon. Each field defaults on its own rather than all-or-nothing.
        monkeypatch.setattr( cv, "_get_cc_metadata",
                             lambda: { "voice_persona": { "name": "sam", "icon": None, "color": "" } } )
        got = cv._commons_persona_fields()
        assert got[ "persona_name" ]  == "sam"
        assert got[ "persona_icon" ]  == cv.DEFAULT_PERSONA_ICON
        assert got[ "persona_color" ] == cv.DEFAULT_PERSONA_COLOR

    def test_a_null_voice_persona_block_uses_every_default( self, monkeypatch ):
        monkeypatch.setattr( cv, "_get_cc_metadata", lambda: { "voice_persona": None } )
        got = cv._commons_persona_fields()
        assert got[ "persona_name" ] == cv.DEFAULT_PERSONA_NAME
