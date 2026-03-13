"""
Guardrail tests for INI config key naming conventions.

Ensures all config keys in lupin-app.ini and lupin-app-splainer.ini
use space-separated naming (e.g., "app debug") instead of underscore-separated
(e.g., "app_debug"). Prevents regression after the v0.1.6 naming migration.

Exemptions:
- Keys containing '/' (model/path keys like "deepily/ministral_8b_2410_ft_lora")
- WebSocket event names (e.g., "auth_request", "sys_ping") which are event identifiers
- Keys with embedded argument names (e.g., "audience_context" in expeditor keys)
"""

import configparser
import os
import pytest

import cosa.utils.util as cu


# WebSocket event names — these use underscores by design (event type identifiers)
WS_EVENT_NAMES = {
    "auth_request", "auth_success", "auth_error",
    "sys_ping", "sys_pong", "sys_time_update",
    "tts_job_request",
    "audio_streaming_status", "audio_streaming_complete", "audio_streaming_chunk",
    "notification_queue_update", "notification_play_sound",
    "update_subscriptions",
}

# Argument names that legitimately contain underscores within space-separated keys
# e.g., "expeditor default value for deep research audience_context"
ALLOWED_UNDERSCORE_SUBSTRINGS = {
    "audience_context",
}


def _is_exempt( key ):
    """
    Check if a key is exempt from the no-underscore rule.

    Requires:
        - key is a lowercase string (ConfigParser lowercases automatically)

    Ensures:
        - Returns True if the key is exempt (model/path with '/', WS event, or has allowed substring)
        - Returns False otherwise
    """
    # Model/path keys with slashes (e.g., deepily/ministral_8b_2410_ft_lora)
    if "/" in key:
        return True

    # WebSocket event name definitions in splainer
    if key in WS_EVENT_NAMES:
        return True

    # Keys containing allowed underscore substrings (e.g., audience_context)
    for allowed in ALLOWED_UNDERSCORE_SUBSTRINGS:
        if allowed in key:
            # Only exempt if removing the allowed substring leaves no underscores
            remaining = key.replace( allowed, "" )
            if "_" not in remaining:
                return True

    return False


def _get_ini_path( filename ):
    """Get absolute path to an INI file in src/conf/."""
    return os.path.join( cu.get_project_root(), "src", "conf", filename )


def _load_config( filename ):
    """Load and parse an INI file, returning (config, filepath)."""
    filepath = _get_ini_path( filename )
    config = configparser.ConfigParser()
    config.read( filepath )
    return config, filepath


class TestNoUnderscoreKeysInIni:
    """Guardrail: no new underscore-separated config keys should be added."""

    def test_lupin_app_ini_no_underscore_keys( self ):
        """All keys in lupin-app.ini must use space-separated naming."""
        config, filepath = _load_config( "lupin-app.ini" )

        violations = []
        for section in config.sections():
            for key in config[ section ]:
                if "_" in key and not _is_exempt( key ):
                    violations.append( f"  [{section}] {key}" )

        assert len( violations ) == 0, (
            f"Found {len( violations )} underscore key(s) in {filepath}:\n"
            + "\n".join( violations )
            + "\n\nAll config keys must use space-separated naming (e.g., 'app debug' not 'app_debug')."
        )

    def test_lupin_app_splainer_no_underscore_keys( self ):
        """All keys in lupin-app-splainer.ini must use space-separated naming."""
        config, filepath = _load_config( "lupin-app-splainer.ini" )

        violations = []
        for section in config.sections():
            for key in config[ section ]:
                if "_" in key and not _is_exempt( key ):
                    violations.append( f"  [{section}] {key}" )

        assert len( violations ) == 0, (
            f"Found {len( violations )} underscore key(s) in {filepath}:\n"
            + "\n".join( violations )
            + "\n\nAll config keys must use space-separated naming (e.g., 'app debug' not 'app_debug')."
        )


class TestIniSplainerParity:
    """Verify both INI files have matching key names."""

    @pytest.mark.xfail( reason="17 pre-existing splainer gaps — out of scope for naming migration" )
    def test_all_ini_keys_have_splainer_entries( self ):
        """Every key in lupin-app.ini should have a matching entry in lupin-app-splainer.ini."""
        ini_config, _ = _load_config( "lupin-app.ini" )
        splainer_config, _ = _load_config( "lupin-app-splainer.ini" )

        # Collect all unique keys from main INI (excluding [default])
        ini_keys = set()
        for section in ini_config.sections():
            if section.lower() == "default":
                continue
            for key in ini_config[ section ]:
                if not _is_exempt( key ):
                    ini_keys.add( key )

        # Collect all unique keys from splainer (from all sections)
        splainer_keys = set()
        for section in splainer_config.sections():
            for key in splainer_config[ section ]:
                splainer_keys.add( key )

        # Find keys in INI but missing from splainer
        missing = ini_keys - splainer_keys

        # Filter out keys that have special handling (inherits, etc.)
        infrastructure_keys = { "inherits" }
        missing = missing - infrastructure_keys

        if missing:
            missing_list = "\n".join( f"  {k}" for k in sorted( missing ) )
            pytest.fail(
                f"Found {len( missing )} key(s) in lupin-app.ini without splainer entries:\n"
                + missing_list
                + "\n\nEvery config key should have a matching explanation in lupin-app-splainer.ini."
            )


if __name__ == "__main__":
    # Quick smoke test
    import sys
    sys.path.insert( 0, os.path.join( os.path.dirname( __file__ ), "..", ".." ) )

    print( "Running INI key naming guardrail tests..." )
    pytest.main( [ __file__, "-v" ] )
