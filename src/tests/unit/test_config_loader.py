"""
Unit tests for multi-environment configuration loading.

Tests the precedence order and validation of configuration loading
from environment variables, config files, and hardcoded defaults.

Design reference: src/rnd/2025.11.10-phase-2.5-notification-authentication.md
Section: Config Loading Mechanism (lines 725-901)
"""

import pytest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from cosa.utils.config_loader import (
    get_api_config,
    load_api_key,
    validate_api_config,
    _load_config_file
)


class TestConfigPrecedenceOrder:
    """Test suite for configuration precedence: env vars > file > defaults."""

    def test_env_vars_highest_precedence( self, monkeypatch ):
        """Test that environment variables override all other sources."""
        # Set environment variables
        monkeypatch.setenv( 'LUPIN_API_URL', 'http://env-override:9000' )
        monkeypatch.setenv( 'LUPIN_API_KEY_FILE', '/tmp/env_key_file' )

        config = get_api_config()

        assert config['api_url'] == 'http://env-override:9000'
        assert config['api_key_file'] == '/tmp/env_key_file'

    def test_config_file_middle_precedence( self, monkeypatch, tmp_path ):
        """Test that config file is used when env vars not set."""
        # Ensure env vars are NOT set
        monkeypatch.delenv( 'LUPIN_API_URL', raising=False )
        monkeypatch.delenv( 'LUPIN_API_KEY_FILE', raising=False )
        monkeypatch.delenv( 'LUPIN_ENV', raising=False )

        # Create temporary config file
        config_file = tmp_path / 'config'
        config_file.write_text( """[environments]
default = test

[test]
api_url = http://config-file:8888
api_key_file = /tmp/config_key_file
""" )

        # Mock config file location
        with patch( 'cosa.utils.config_loader.Path.home', return_value=tmp_path.parent ):
            with patch( 'cosa.utils.config_loader.Path.exists', return_value=True ):
                with patch( 'cosa.utils.config_loader._load_config_file' ) as mock_load:
                    from configparser import ConfigParser
                    mock_config = ConfigParser()
                    mock_config.read_string( config_file.read_text() )
                    mock_load.return_value = mock_config

                    config = get_api_config()

                    assert config['api_url'] == 'http://config-file:8888'
                    assert config['api_key_file'] == '/tmp/config_key_file'

    def test_raises_error_when_config_missing( self, monkeypatch ):
        """Test that missing ~/.lupin/config raises FileNotFoundError."""
        # Ensure env vars are NOT set
        monkeypatch.delenv( 'LUPIN_API_URL', raising=False )
        monkeypatch.delenv( 'LUPIN_API_KEY_FILE', raising=False )

        # Mock no config file
        with patch( 'cosa.utils.config_loader.Path.home', return_value=Path( '/nonexistent' ) ):
            with pytest.raises( FileNotFoundError, match="~/.lupin/config not found" ):
                get_api_config()

    def test_partial_env_vars_falls_through_to_config( self, monkeypatch, tmp_path ):
        """Test that partial env vars (only one set) falls through to config file."""
        # Only set API_URL, not KEY_FILE
        monkeypatch.setenv( 'LUPIN_API_URL', 'http://partial:7000' )
        monkeypatch.delenv( 'LUPIN_API_KEY_FILE', raising=False )
        monkeypatch.delenv( 'LUPIN_ENV', raising=False )

        # Should fall through to config file (not use partial env vars)
        with patch( 'cosa.utils.config_loader.Path.home', return_value=tmp_path ):
            lupin_dir = tmp_path / '.lupin'
            lupin_dir.mkdir()
            config_file = lupin_dir / 'config'
            config_file.write_text( """[environments]
default = local

[local]
api_url = http://from-config:7999
api_key_file = /tmp/config_key
""" )
            config = get_api_config()

            assert config['api_url'] == 'http://from-config:7999'


class TestEnvironmentSwitching:
    """Test suite for LUPIN_ENV environment variable and env parameter."""

    def test_lupin_env_selects_environment( self, monkeypatch, tmp_path ):
        """Test that LUPIN_ENV selects correct environment from config file."""
        monkeypatch.setenv( 'LUPIN_ENV', 'production' )
        monkeypatch.delenv( 'LUPIN_API_URL', raising=False )
        monkeypatch.delenv( 'LUPIN_API_KEY_FILE', raising=False )

        # Create config with multiple environments
        config_file = tmp_path / 'config'
        config_file.write_text( """[environments]
default = local

[local]
api_url = http://localhost:7999
api_key_file = /tmp/local_key

[production]
api_url = https://prod.example.com
api_key_file = /tmp/prod_key
""" )

        with patch( 'cosa.utils.config_loader.Path.home', return_value=tmp_path.parent ):
            with patch( 'cosa.utils.config_loader.Path.exists', return_value=True ):
                with patch( 'cosa.utils.config_loader._load_config_file' ) as mock_load:
                    from configparser import ConfigParser
                    mock_config = ConfigParser()
                    mock_config.read_string( config_file.read_text() )
                    mock_load.return_value = mock_config

                    config = get_api_config()

                    # Should use production environment
                    assert config['api_url'] == 'https://prod.example.com'
                    assert config['api_key_file'] == '/tmp/prod_key'

    def test_explicit_env_parameter_overrides_lupin_env( self, monkeypatch, tmp_path ):
        """Test that explicit env parameter overrides LUPIN_ENV."""
        monkeypatch.setenv( 'LUPIN_ENV', 'production' )
        monkeypatch.delenv( 'LUPIN_API_URL', raising=False )
        monkeypatch.delenv( 'LUPIN_API_KEY_FILE', raising=False )

        config_file = tmp_path / 'config'
        config_file.write_text( """[environments]
default = local

[staging]
api_url = http://staging.example.com
api_key_file = /tmp/staging_key

[production]
api_url = https://prod.example.com
api_key_file = /tmp/prod_key
""" )

        with patch( 'cosa.utils.config_loader.Path.home', return_value=tmp_path.parent ):
            with patch( 'cosa.utils.config_loader.Path.exists', return_value=True ):
                with patch( 'cosa.utils.config_loader._load_config_file' ) as mock_load:
                    from configparser import ConfigParser
                    mock_config = ConfigParser()
                    mock_config.read_string( config_file.read_text() )
                    mock_load.return_value = mock_config

                    # Explicitly pass env='staging' (should override LUPIN_ENV=production)
                    config = get_api_config( env='staging' )

                    assert config['api_url'] == 'http://staging.example.com'
                    assert config['api_key_file'] == '/tmp/staging_key'

    def test_default_environment_from_config( self, monkeypatch, tmp_path ):
        """Test that default environment is used when LUPIN_ENV not set."""
        monkeypatch.delenv( 'LUPIN_ENV', raising=False )
        monkeypatch.delenv( 'LUPIN_API_URL', raising=False )
        monkeypatch.delenv( 'LUPIN_API_KEY_FILE', raising=False )

        config_file = tmp_path / 'config'
        config_file.write_text( """[environments]
default = my_default_env

[my_default_env]
api_url = http://default-env:7999
api_key_file = /tmp/default_key
""" )

        with patch( 'cosa.utils.config_loader.Path.home', return_value=tmp_path.parent ):
            with patch( 'cosa.utils.config_loader.Path.exists', return_value=True ):
                with patch( 'cosa.utils.config_loader._load_config_file' ) as mock_load:
                    from configparser import ConfigParser
                    mock_config = ConfigParser()
                    mock_config.read_string( config_file.read_text() )
                    mock_load.return_value = mock_config

                    config = get_api_config()

                    assert config['api_url'] == 'http://default-env:7999'


class TestConfigValidation:
    """Test suite for configuration validation."""

    def test_validate_valid_config( self, tmp_path ):
        """Test that valid configuration passes validation."""
        # Create temporary valid API key file
        key_file = tmp_path / 'valid_key'
        key_file.write_text( "ck_live_" + "A" * 64 )

        config = {
            'api_url': 'https://example.com',
            'api_key_file': str( key_file )
        }

        # Should not raise exception
        validate_api_config( config )

    def test_validate_invalid_url_format( self ):
        """Test that invalid URL format raises ValueError."""
        invalid_urls = [
            ('not-a-url', "Invalid API URL format"),
            ('ftp://example.com', "Invalid API URL format"),  # Not http/https
            ('', "Missing 'api_url'"),  # Empty string
            ('example.com', "Invalid API URL format"),        # Missing protocol
        ]

        for url, expected_message in invalid_urls:
            config = {
                'api_url': url,
                'api_key_file': '/tmp/fake_key'
            }

            with pytest.raises( ValueError, match=expected_message ):
                validate_api_config( config )

    def test_validate_missing_key_file( self ):
        """Test that missing key file raises ValueError."""
        config = {
            'api_url': 'https://example.com',
            'api_key_file': '/tmp/nonexistent_key_12345.key'
        }

        with pytest.raises( ValueError, match="API key file not found" ):
            validate_api_config( config )

    def test_validate_invalid_key_format( self, tmp_path ):
        """Test that invalid API key format raises ValueError."""
        key_file = tmp_path / 'invalid_key'
        key_file.write_text( "invalid_key_format" )

        config = {
            'api_url': 'https://example.com',
            'api_key_file': str( key_file )
        }

        with pytest.raises( ValueError, match="Invalid API key format" ):
            validate_api_config( config )

    def test_validate_missing_config_fields( self ):
        """Test that missing required fields raise ValueError."""
        # Missing api_url
        config1 = {'api_key_file': '/tmp/key'}
        with pytest.raises( ValueError, match="Missing 'api_url'" ):
            validate_api_config( config1 )

        # Missing api_key_file
        config2 = {'api_url': 'https://example.com'}
        with pytest.raises( ValueError, match="Missing 'api_key_file'" ):
            validate_api_config( config2 )


class TestLoadAPIKey:
    """Test suite for load_api_key() function."""

    def test_load_valid_api_key( self, tmp_path ):
        """Test loading valid API key from file."""
        key_file = tmp_path / 'test_key'
        test_key = "ck_live_" + "B" * 64
        key_file.write_text( test_key + "\n" )  # With trailing newline

        loaded_key = load_api_key( str( key_file ) )

        assert loaded_key == test_key  # Should be stripped

    def test_load_strips_whitespace( self, tmp_path ):
        """Test that whitespace is stripped from API key."""
        key_file = tmp_path / 'test_key'
        test_key = "ck_live_" + "C" * 64
        key_file.write_text( f"  {test_key}  \n" )  # Leading/trailing whitespace

        loaded_key = load_api_key( str( key_file ) )

        assert loaded_key == test_key

    def test_load_missing_file_raises_error( self ):
        """Test that missing file raises ValueError."""
        with pytest.raises( ValueError, match="API key file not found" ):
            load_api_key( '/tmp/nonexistent_key_xyz.key' )

    def test_load_invalid_format_raises_error( self, tmp_path ):
        """Test that invalid key format raises ValueError."""
        key_file = tmp_path / 'invalid_key'
        key_file.write_text( "invalid_format" )

        with pytest.raises( ValueError, match="Invalid API key format" ):
            load_api_key( str( key_file ) )

    def test_load_directory_raises_error( self, tmp_path ):
        """Test that directory path raises ValueError."""
        with pytest.raises( ValueError, match="not a file" ):
            load_api_key( str( tmp_path ) )  # Pass directory instead of file


class TestConfigFileErrors:
    """Test suite for config file error handling."""

    def test_missing_environment_section_raises_error( self, tmp_path, monkeypatch ):
        """Test that missing environment section raises ValueError."""
        monkeypatch.delenv( 'LUPIN_API_URL', raising=False )
        monkeypatch.delenv( 'LUPIN_API_KEY_FILE', raising=False )

        config_file = tmp_path / 'config'
        config_file.write_text( """[some_env]
api_url = http://example.com
api_key_file = /tmp/key
""" )  # Missing [environments] section

        with patch( 'cosa.utils.config_loader.Path.home', return_value=tmp_path.parent ):
            with patch( 'cosa.utils.config_loader.Path.exists', return_value=True ):
                # Mock the config path to our test file
                config_path = tmp_path / '.lupin' / 'config'
                config_path.parent.mkdir( parents=True, exist_ok=True )
                config_path.write_text( config_file.read_text() )

                with pytest.raises( ValueError, match="missing \\[environments\\] section" ):
                    _load_config_file( config_path )

    def test_nonexistent_environment_raises_error( self, tmp_path, monkeypatch ):
        """Test that requesting nonexistent environment raises ValueError."""
        monkeypatch.delenv( 'LUPIN_API_URL', raising=False )
        monkeypatch.delenv( 'LUPIN_API_KEY_FILE', raising=False )

        config_file = tmp_path / 'config'
        config_file.write_text( """[environments]
default = local

[local]
api_url = http://localhost:7999
api_key_file = /tmp/local_key
""" )

        with patch( 'cosa.utils.config_loader.Path.home', return_value=tmp_path.parent ):
            with patch( 'cosa.utils.config_loader.Path.exists', return_value=True ):
                with patch( 'cosa.utils.config_loader._load_config_file' ) as mock_load:
                    from configparser import ConfigParser
                    mock_config = ConfigParser()
                    mock_config.read_string( config_file.read_text() )
                    mock_load.return_value = mock_config

                    with pytest.raises( ValueError, match="Environment 'nonexistent' not found" ):
                        get_api_config( env='nonexistent' )

    def test_missing_required_fields_raises_error( self, tmp_path, monkeypatch ):
        """Test that missing required fields in environment raises ValueError."""
        monkeypatch.delenv( 'LUPIN_API_URL', raising=False )
        monkeypatch.delenv( 'LUPIN_API_KEY_FILE', raising=False )
        monkeypatch.delenv( 'LUPIN_ENV', raising=False )

        # Config missing api_key_file
        config_file = tmp_path / 'config'
        config_file.write_text( """[environments]
default = incomplete

[incomplete]
api_url = http://localhost:7999
""" )  # Missing api_key_file

        with patch( 'cosa.utils.config_loader.Path.home', return_value=tmp_path.parent ):
            with patch( 'cosa.utils.config_loader.Path.exists', return_value=True ):
                with patch( 'cosa.utils.config_loader._load_config_file' ) as mock_load:
                    from configparser import ConfigParser
                    mock_config = ConfigParser()
                    mock_config.read_string( config_file.read_text() )
                    mock_load.return_value = mock_config

                    with pytest.raises( ValueError, match="Missing 'api_key_file'" ):
                        get_api_config()


class TestUnifiedConfigFile:
    """Test that credentials and API config coexist in one unified file."""

    def test_unified_file_loads_api_config( self, monkeypatch, tmp_path ):
        """Test that API config loads from unified file containing credentials + environments."""
        monkeypatch.delenv( 'LUPIN_API_URL', raising=False )
        monkeypatch.delenv( 'LUPIN_API_KEY_FILE', raising=False )
        monkeypatch.delenv( 'LUPIN_ENV', raising=False )

        # Create unified config with both credentials and environments
        unified_content = """[lupin]
email = claude.code@lupin.deepily.ai
password = test-password

[environments]
default = local

[local]
api_url = http://localhost:7999
api_key_file = /tmp/unified_key
global_notification_recipient = test@example.com
"""
        with patch( 'cosa.utils.config_loader.Path.home', return_value=tmp_path.parent ):
            with patch( 'cosa.utils.config_loader.Path.exists', return_value=True ):
                with patch( 'cosa.utils.config_loader._load_config_file' ) as mock_load:
                    from configparser import ConfigParser
                    mock_config = ConfigParser()
                    mock_config.read_string( unified_content )
                    mock_load.return_value = mock_config

                    config = get_api_config()

                    assert config['api_url'] == 'http://localhost:7999'
                    assert config['api_key_file'] == '/tmp/unified_key'
                    assert config['global_notification_recipient'] == 'test@example.com'

    def test_credential_sections_do_not_interfere_with_env_sections( self, tmp_path ):
        """Test that [lupin]/[cosa] credential sections don't break _load_config_file."""
        unified_file = tmp_path / 'config'
        unified_file.write_text( """[lupin]
email = test@example.com
password = secret

[cosa]
email = cosa@example.com
password = secret2

[environments]
default = local

[local]
api_url = http://localhost:7999
api_key_file = /tmp/key
""" )
        config = _load_config_file( unified_file )
        assert 'environments' in config
        assert 'local' in config
        assert 'lupin' in config
        assert 'cosa' in config
        assert config['local']['api_url'] == 'http://localhost:7999'


class TestFailHardWhenConfigMissing:
    """Test that missing ~/.lupin/config raises FileNotFoundError with migration instructions."""

    def test_raises_file_not_found_with_migration_message( self, monkeypatch ):
        """Test FileNotFoundError includes lupin-config init/migrate instructions."""
        monkeypatch.delenv( 'LUPIN_API_URL', raising=False )
        monkeypatch.delenv( 'LUPIN_API_KEY_FILE', raising=False )

        with patch( 'cosa.utils.config_loader.Path.home', return_value=Path( '/nonexistent' ) ):
            with pytest.raises( FileNotFoundError ) as exc_info:
                get_api_config()

            error_msg = str( exc_info.value )
            assert "~/.lupin/config not found" in error_msg
            assert "lupin-config init" in error_msg
            assert "lupin-config migrate" in error_msg

    def test_env_vars_bypass_config_file_requirement( self, monkeypatch ):
        """Test that env vars work even when config file is missing."""
        monkeypatch.setenv( 'LUPIN_API_URL', 'http://env-only:9000' )
        monkeypatch.setenv( 'LUPIN_API_KEY_FILE', '/tmp/env_key' )

        # Even with no config file, env vars should work
        with patch( 'cosa.utils.config_loader.Path.home', return_value=Path( '/nonexistent' ) ):
            config = get_api_config()

            assert config['api_url'] == 'http://env-only:9000'
            assert config['api_key_file'] == '/tmp/env_key'
