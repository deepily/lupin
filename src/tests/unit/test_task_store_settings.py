#!/usr/bin/env python3
"""
Unit tests — task-store mirror settings loader (Phase 2 write paths).

Venue: :7999-eligible / local — pure file IO via monkeypatched expanduser.
Covers load_task_store_settings / _defaults / _validate_positive_number to
100% lines/branches/functions.
"""
import json
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib import task_store_settings as ts


@pytest.fixture
def settings_file( tmp_path, monkeypatch ):
    """Route ~/.claude/settings.json reads at a tmp file the test controls."""
    path = tmp_path / "settings.json"
    monkeypatch.setattr( ts.os.path, "expanduser", lambda _p: str( path ) )
    return path


DEFAULTS = {
    "enabled"           : False,
    "api_base_url"      : "http://localhost:7999",
    "timeout_seconds"   : 3.0,
    "spool_ttl_seconds" : 86400,
}


class TestDefaults:

    def test_missing_file_returns_defaults( self, settings_file ):
        assert ts.load_task_store_settings() == DEFAULTS

    def test_malformed_json_returns_defaults( self, settings_file ):
        settings_file.write_text( "{bad json" )
        assert ts.load_task_store_settings() == DEFAULTS

    def test_unreadable_file_returns_defaults( self, settings_file ):
        # A directory at the settings path raises OSError on open()
        settings_file.mkdir()
        assert ts.load_task_store_settings() == DEFAULTS

    def test_missing_block_returns_defaults( self, settings_file ):
        settings_file.write_text( '{"heartbeat": {"enabled": true}}' )
        assert ts.load_task_store_settings() == DEFAULTS

    def test_non_dict_block_returns_defaults( self, settings_file ):
        settings_file.write_text( '{"task_store": "yes"}' )
        assert ts.load_task_store_settings() == DEFAULTS

    def test_empty_block_uses_individual_defaults( self, settings_file ):
        settings_file.write_text( '{"task_store": {}}' )
        assert ts.load_task_store_settings() == DEFAULTS

    def test_defaults_returns_fresh_copy( self, settings_file ):
        first = ts.load_task_store_settings()
        first[ "enabled" ] = True
        assert ts.load_task_store_settings()[ "enabled" ] is False


class TestOverrides:

    def test_full_override_round_trips( self, settings_file ):
        settings_file.write_text( json.dumps( { "task_store": {
            "enabled"           : True,
            "api_base_url"      : "http://other:8000",
            "timeout_seconds"   : 1.5,
            "spool_ttl_seconds" : 60,
        } } ) )
        assert ts.load_task_store_settings() == {
            "enabled"           : True,
            "api_base_url"      : "http://other:8000",
            "timeout_seconds"   : 1.5,
            "spool_ttl_seconds" : 60.0,
        }

    def test_enabled_truthiness_coerced( self, settings_file ):
        settings_file.write_text( '{"task_store": {"enabled": 1}}' )
        assert ts.load_task_store_settings()[ "enabled" ] is True

    def test_trailing_slash_stripped_from_base_url( self, settings_file ):
        settings_file.write_text( '{"task_store": {"api_base_url": "http://x:1/"}}' )
        assert ts.load_task_store_settings()[ "api_base_url" ] == "http://x:1"

    def test_int_timeout_normalized_to_float( self, settings_file ):
        settings_file.write_text( '{"task_store": {"timeout_seconds": 5}}' )
        result = ts.load_task_store_settings()[ "timeout_seconds" ]
        assert result == 5.0 and isinstance( result, float )


class TestFailLoud:

    @pytest.mark.parametrize( "bad_url", [ 7, "", "   ", None ] )
    def test_bad_base_url_raises( self, settings_file, bad_url ):
        settings_file.write_text( json.dumps( { "task_store": { "api_base_url": bad_url } } ) )
        with pytest.raises( ValueError, match="api_base_url" ):
            ts.load_task_store_settings()

    @pytest.mark.parametrize( "bad", [ 0, -1, "3", True, None, [ ] ] )
    def test_bad_timeout_raises( self, settings_file, bad ):
        settings_file.write_text( json.dumps( { "task_store": { "timeout_seconds": bad } } ) )
        with pytest.raises( ValueError, match="timeout_seconds" ):
            ts.load_task_store_settings()

    @pytest.mark.parametrize( "bad", [ 0, -5, "ttl", False ] )
    def test_bad_ttl_raises( self, settings_file, bad ):
        settings_file.write_text( json.dumps( { "task_store": { "spool_ttl_seconds": bad } } ) )
        with pytest.raises( ValueError, match="spool_ttl_seconds" ):
            ts.load_task_store_settings()
