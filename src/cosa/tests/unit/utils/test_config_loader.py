"""
Unit tests for cosa.utils.config_loader.

Exercises the full multi-source API-config precedence machinery:
  - get_api_config(): env-var path (with/without direct key, optional
    recipient) and config-file path (explicit env / LUPIN_ENV / default,
    missing-file, missing-section, missing-field branches)
  - _load_config_file(): valid parse, malformed-file, missing [environments]
  - load_api_key(): direct-env-key shortcut, missing/non-file/bad-format
  - validate_api_config(): URL + key-file + key-format validation branches

Hermetic: the process environment's LUPIN_* vars are masked per test, HOME is
redirected to a tempdir for config-file cases, and key/config files are
written under tempdirs. No real ~/.lupin/config is read or mutated.

Assertions harvested and strengthened from the module's quick_smoke_test()
(now superseded — that block needed a real ~/.lupin/config; these don't).
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cosa.utils.config_loader as cl
from cosa.utils.config_loader import (
    get_api_config,
    _load_config_file,
    load_api_key,
    validate_api_config,
)

# Env vars the loader consults — masked per test for determinism.
_LUPIN_VARS = (
    "LUPIN_API_URL", "LUPIN_API_KEY_FILE", "LUPIN_API_KEY",
    "LUPIN_ENV", "LUPIN_DEV_EMAIL",
)

# A syntactically valid ck_live_ key (64+ trailing chars).
_VALID_KEY = "ck_live_" + "A" * 64


class _EnvBase( unittest.TestCase ):
    """Base providing a masked-LUPIN environment for each test."""

    def setUp( self ):
        self._env_ctx = patch.dict( os.environ, {}, clear=False )
        self._env_ctx.start()
        for var in _LUPIN_VARS:
            os.environ.pop( var, None )

    def tearDown( self ):
        self._env_ctx.stop()


class TestGetApiConfigEnvVars( _EnvBase ):
    """
    get_api_config() env-var precedence path.

    Ensures:
        - api_url + api_key_file produce the expected dict
        - LUPIN_DEV_EMAIL adds the optional recipient key
        - LUPIN_API_KEY alone defaults the URL and marks the key file '__direct__'
    """

    def test_url_and_key_file_env( self ):
        os.environ[ "LUPIN_API_URL" ]      = "http://test.example.com:8000"
        os.environ[ "LUPIN_API_KEY_FILE" ] = "/tmp/test_key"
        cfg = get_api_config()
        self.assertEqual( cfg[ "api_url" ], "http://test.example.com:8000" )
        self.assertEqual( cfg[ "api_key_file" ], "/tmp/test_key" )
        self.assertNotIn( "global_notification_recipient", cfg )

    def test_dev_email_adds_recipient( self ):
        os.environ[ "LUPIN_API_URL" ]      = "http://x:7999"
        os.environ[ "LUPIN_API_KEY_FILE" ] = "/tmp/k"
        os.environ[ "LUPIN_DEV_EMAIL" ]    = "dev@example.com"
        cfg = get_api_config()
        self.assertEqual( cfg[ "global_notification_recipient" ], "dev@example.com" )

    def test_direct_key_defaults_url_and_marks_direct( self ):
        os.environ[ "LUPIN_API_KEY" ] = _VALID_KEY
        cfg = get_api_config()
        self.assertEqual( cfg[ "api_url" ], "http://localhost:7999" )
        self.assertEqual( cfg[ "api_key_file" ], "__direct__" )


class TestGetApiConfigFile( _EnvBase ):
    """
    get_api_config() config-file path (env vars absent).

    Ensures:
        - missing ~/.lupin/config raises FileNotFoundError
        - default / LUPIN_ENV / explicit-env selection all resolve
        - unknown env or missing required fields raise ValueError
        - optional global_notification_recipient is surfaced when present
    """

    def _home_with_config( self, body ):
        """Create a tempdir HOME containing .lupin/config with `body`; return its Path."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup( tmp.cleanup )
        cfg_dir = Path( tmp.name ) / ".lupin"
        cfg_dir.mkdir( parents=True )
        ( cfg_dir / "config" ).write_text( body )
        return Path( tmp.name )

    def test_missing_config_raises_file_not_found( self ):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup( tmp.cleanup )
        with patch.object( cl.Path, "home", return_value=Path( tmp.name ) ):
            with self.assertRaises( FileNotFoundError ):
                get_api_config()

    def test_default_environment_resolved( self ):
        home = self._home_with_config(
            "[environments]\ndefault = local\n\n"
            "[local]\napi_url = http://localhost:7999\napi_key_file = /tmp/k\n"
        )
        with patch.object( cl.Path, "home", return_value=home ):
            cfg = get_api_config()
        self.assertEqual( cfg[ "api_url" ], "http://localhost:7999" )
        self.assertEqual( cfg[ "api_key_file" ], "/tmp/k" )

    def test_lupin_env_selects_environment( self ):
        home = self._home_with_config(
            "[environments]\ndefault = local\n\n"
            "[local]\napi_url = http://local\napi_key_file = /tmp/l\n\n"
            "[prod]\napi_url = https://prod\napi_key_file = /tmp/p\n"
        )
        os.environ[ "LUPIN_ENV" ] = "prod"
        with patch.object( cl.Path, "home", return_value=home ):
            cfg = get_api_config()
        self.assertEqual( cfg[ "api_url" ], "https://prod" )

    def test_explicit_env_param_overrides( self ):
        home = self._home_with_config(
            "[environments]\ndefault = local\n\n"
            "[local]\napi_url = http://local\napi_key_file = /tmp/l\n\n"
            "[staging]\napi_url = https://staging\napi_key_file = /tmp/s\n"
        )
        os.environ[ "LUPIN_ENV" ] = "prod"  # should be overridden by explicit param
        with patch.object( cl.Path, "home", return_value=home ):
            cfg = get_api_config( env="staging" )
        self.assertEqual( cfg[ "api_url" ], "https://staging" )

    def test_unknown_environment_raises_value_error( self ):
        home = self._home_with_config(
            "[environments]\ndefault = local\n\n"
            "[local]\napi_url = http://local\napi_key_file = /tmp/l\n"
        )
        with patch.object( cl.Path, "home", return_value=home ):
            with self.assertRaises( ValueError ):
                get_api_config( env="nope" )

    def test_missing_api_url_raises_value_error( self ):
        home = self._home_with_config(
            "[environments]\ndefault = local\n\n"
            "[local]\napi_key_file = /tmp/l\n"
        )
        with patch.object( cl.Path, "home", return_value=home ):
            with self.assertRaises( ValueError ):
                get_api_config()

    def test_missing_api_key_file_raises_value_error( self ):
        home = self._home_with_config(
            "[environments]\ndefault = local\n\n"
            "[local]\napi_url = http://local\n"
        )
        with patch.object( cl.Path, "home", return_value=home ):
            with self.assertRaises( ValueError ):
                get_api_config()

    def test_global_recipient_surfaced_from_file( self ):
        home = self._home_with_config(
            "[environments]\ndefault = local\n\n"
            "[local]\napi_url = http://local\napi_key_file = /tmp/l\n"
            "global_notification_recipient = team@example.com\n"
        )
        with patch.object( cl.Path, "home", return_value=home ):
            cfg = get_api_config()
        self.assertEqual( cfg[ "global_notification_recipient" ], "team@example.com" )


class TestLoadConfigFile( unittest.TestCase ):
    """
    _load_config_file() parse + structure validation.

    Ensures:
        - a valid INI parses and is returned
        - a malformed INI raises ValueError (read failure)
        - a file without [environments] raises ValueError
    """

    def _write( self, body ):
        tmp = tempfile.NamedTemporaryFile( mode="w", suffix=".ini", delete=False )
        tmp.write( body )
        tmp.close()
        path = Path( tmp.name )
        self.addCleanup( lambda: path.exists() and path.unlink() )
        return path

    def test_valid_file_parses( self ):
        path = self._write(
            "[environments]\ndefault = local\n\n[local]\napi_url = http://x\n"
        )
        config = _load_config_file( path )
        self.assertIn( "environments", config )
        self.assertIn( "local", config )

    def test_malformed_file_raises_value_error( self ):
        # A line before any section header makes ConfigParser.read() raise.
        path = self._write( "this is not ini\n" )
        with self.assertRaises( ValueError ):
            _load_config_file( path )

    def test_missing_environments_section_raises_value_error( self ):
        path = self._write( "[local]\napi_url = http://x\n" )
        with self.assertRaises( ValueError ):
            _load_config_file( path )


class TestLoadApiKey( _EnvBase ):
    """
    load_api_key() resolution + validation.

    Ensures:
        - a valid direct env key short-circuits file reading
        - a missing file path raises ValueError
        - a directory (non-file) path raises ValueError
        - a well-formed key file returns the stripped key
        - a malformed key in the file raises ValueError
    """

    def _key_file( self, content ):
        tmp = tempfile.NamedTemporaryFile( mode="w", delete=False )
        tmp.write( content )
        tmp.close()
        path = Path( tmp.name )
        self.addCleanup( lambda: path.exists() and path.unlink() )
        return path

    def test_direct_env_key_short_circuits( self ):
        os.environ[ "LUPIN_API_KEY" ] = _VALID_KEY
        # Even with a bogus file path, the direct key wins.
        self.assertEqual( load_api_key( "/nonexistent/path" ), _VALID_KEY )

    def test_missing_file_raises_value_error( self ):
        with self.assertRaises( ValueError ):
            load_api_key( "/tmp/definitely-not-here-9988.key" )

    def test_non_file_path_raises_value_error( self ):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup( tmp.cleanup )
        with self.assertRaises( ValueError ):
            load_api_key( tmp.name )

    def test_valid_key_file_returns_stripped_key( self ):
        path = self._key_file( _VALID_KEY + "\n" )
        self.assertEqual( load_api_key( str( path ) ), _VALID_KEY )

    def test_invalid_key_format_raises_value_error( self ):
        path = self._key_file( "not-a-valid-key" )
        with self.assertRaises( ValueError ):
            load_api_key( str( path ) )

    def test_unreadable_key_file_raises_value_error( self ):
        """An existing key file that fails to open (e.g. permissions) raises ValueError."""
        path = self._key_file( _VALID_KEY )
        with patch( "builtins.open", side_effect=PermissionError( "denied" ) ):
            with self.assertRaises( ValueError ):
                load_api_key( str( path ) )


class TestValidateApiConfig( unittest.TestCase ):
    """
    validate_api_config() — every guard branch.

    Ensures:
        - missing/invalid api_url raises ValueError
        - missing/missing-on-disk/non-file api_key_file raises ValueError
        - malformed key contents raise ValueError
        - a fully valid config returns None
    """

    def _key_file( self, content ):
        tmp = tempfile.NamedTemporaryFile( mode="w", delete=False )
        tmp.write( content )
        tmp.close()
        path = Path( tmp.name )
        self.addCleanup( lambda: path.exists() and path.unlink() )
        return path

    def test_missing_url_raises( self ):
        with self.assertRaises( ValueError ):
            validate_api_config( { "api_key_file": "/tmp/k" } )

    def test_invalid_url_raises( self ):
        with self.assertRaises( ValueError ):
            validate_api_config( { "api_url": "not-a-url", "api_key_file": "/tmp/k" } )

    def test_missing_key_file_field_raises( self ):
        with self.assertRaises( ValueError ):
            validate_api_config( { "api_url": "https://x" } )

    def test_key_file_not_found_raises( self ):
        with self.assertRaises( ValueError ):
            validate_api_config(
                { "api_url": "https://x", "api_key_file": "/tmp/nope-7766.key" }
            )

    def test_key_file_is_directory_raises( self ):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup( tmp.cleanup )
        with self.assertRaises( ValueError ):
            validate_api_config( { "api_url": "https://x", "api_key_file": tmp.name } )

    def test_invalid_key_format_raises( self ):
        path = self._key_file( "bad-key" )
        with self.assertRaises( ValueError ):
            validate_api_config( { "api_url": "https://x", "api_key_file": str( path ) } )

    def test_unreadable_key_file_raises( self ):
        """An existing key file that fails to open raises ValueError (read-failure branch)."""
        path = self._key_file( _VALID_KEY )
        with patch( "builtins.open", side_effect=PermissionError( "denied" ) ):
            with self.assertRaises( ValueError ):
                validate_api_config(
                    { "api_url": "https://x", "api_key_file": str( path ) }
                )

    def test_valid_config_returns_none( self ):
        path = self._key_file( _VALID_KEY )
        result = validate_api_config(
            { "api_url": "https://example.com", "api_key_file": str( path ) }
        )
        self.assertIsNone( result )


if __name__ == "__main__":
    unittest.main()
