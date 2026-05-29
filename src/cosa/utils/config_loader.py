"""
Configuration Loader for Lupin API Multi-Environment Support.

Handles loading and validation of API configuration from multiple sources
with defined precedence order. Supports environment-based configuration
for local, staging, and production deployments.

Design reference: src/rnd/2025.11.10-phase-2.5-notification-authentication.md
Section: Config Loading Mechanism (lines 725-901)
"""

import os
import re
import sys
from pathlib import Path
from typing import Dict, Optional
from configparser import ConfigParser

import cosa.utils.util as cu


def get_api_config( env: Optional[str] = None ) -> Dict[str, str]:
    """
    Load Lupin API configuration with precedence order.

    Requires:
        - env is optional environment name (overrides default)

    Ensures:
        - returns dict with 'api_url' and 'api_key_file' keys (required)
        - returns 'global_notification_recipient' key if configured (optional)
        - precedence: env vars > config file
        - raises FileNotFoundError if ~/.lupin/config missing and no env vars
        - raises ValueError if config invalid

    Precedence Order:
        1. Environment variables (LUPIN_API_URL, LUPIN_API_KEY_FILE, LUPIN_DEV_EMAIL)
        2. Config file (~/.lupin/config) with LUPIN_ENV or 'env' parameter

    Args:
        env: Optional environment name to use (overrides LUPIN_ENV and config default)

    Returns:
        dict: {'api_url': str, 'api_key_file': str, 'global_notification_recipient': str (optional)}

    Raises:
        ValueError: If config invalid (malformed URL, missing key file, etc.)
        FileNotFoundError: If ~/.lupin/config not found and env vars not set
    """
    # Priority 1: Check environment variables (highest)
    api_url      = os.getenv( 'LUPIN_API_URL' )
    api_key_file = os.getenv( 'LUPIN_API_KEY_FILE' )
    api_key_direct = os.getenv( 'LUPIN_API_KEY' )

    notification_recipient = os.getenv( 'LUPIN_DEV_EMAIL' )

    if ( api_key_file or api_key_direct ) and ( api_url or api_key_direct ):
        # Env vars set — use them (LUPIN_API_KEY bypasses file, handled by load_api_key)
        # Default URL to localhost:7999 when LUPIN_API_KEY is set without LUPIN_API_URL
        # (common in Docker where the server posts notifications to itself)
        result = {
            'api_url'      : api_url or 'http://localhost:7999',
            'api_key_file' : api_key_file or '__direct__'
        }
        # Add global_notification_recipient if configured
        if notification_recipient:
            result['global_notification_recipient'] = notification_recipient
        return result

    # Priority 2: Config file (~/.lupin/config)
    config_path = Path.home() / '.lupin' / 'config'

    if not config_path.exists():
        raise FileNotFoundError(
            f"~/.lupin/config not found.\n"
            f"Create it with: lupin-config init\n"
            f"Or migrate from legacy files: lupin-config migrate"
        )

    config = _load_config_file( config_path )

    # Determine which environment to use
    if env:
        # Explicit env parameter (highest)
        env_name = env
    elif os.getenv( 'LUPIN_ENV' ):
        # LUPIN_ENV environment variable
        env_name = os.getenv( 'LUPIN_ENV' )
    else:
        # Default from config file
        env_name = config.get( 'environments', 'default', fallback='local' )

    # Get environment config
    if env_name not in config:
        raise ValueError( f"Environment '{env_name}' not found in {config_path}" )

    env_config = config[env_name]

    # Validate required fields exist
    if 'api_url' not in env_config:
        raise ValueError( f"Missing 'api_url' in environment '{env_name}' ({config_path})" )
    if 'api_key_file' not in env_config:
        raise ValueError( f"Missing 'api_key_file' in environment '{env_name}' ({config_path})" )

    global_recipient = env_config.get( 'global_notification_recipient' )

    result = {
        'api_url'      : env_config['api_url'],
        'api_key_file' : env_config['api_key_file']
    }

    # Add global_notification_recipient if configured
    if global_recipient:
        result['global_notification_recipient'] = global_recipient

    return result


def _load_config_file( config_path: Path ) -> ConfigParser:
    """
    Load and parse INI config file.

    Requires:
        - config_path is valid Path to config file

    Ensures:
        - returns ConfigParser with loaded config
        - raises ValueError if file malformed or invalid

    Validates:
        - File is readable
        - INI format is valid
        - Required fields present

    Args:
        config_path: Path to INI config file

    Returns:
        ConfigParser: Loaded configuration

    Raises:
        ValueError: If file cannot be read or is malformed
    """
    config = ConfigParser()

    try:
        config.read( config_path )
    except Exception as e:
        raise ValueError( f"Failed to read config file {config_path}: {e}" )

    # Validate config structure
    if 'environments' not in config:
        raise ValueError( f"Config file missing [environments] section: {config_path}" )

    return config


def load_api_key( api_key_file: str ) -> str:
    """
    Load API key from file.

    Requires:
        - api_key_file is path to valid key file

    Ensures:
        - returns stripped API key string
        - raises ValueError if file missing or invalid format

    Args:
        api_key_file: Path to API key file

    Returns:
        str: API key (stripped)

    Raises:
        ValueError: If file not found or key format invalid
    """
    # Direct env var takes priority (for Docker/CI where config file unavailable)
    direct_key = os.getenv( 'LUPIN_API_KEY' )
    if direct_key and re.match( r'^ck_live_[A-Za-z0-9_-]{64,}$', direct_key ):
        return direct_key

    key_file = Path( api_key_file )

    if not key_file.exists():
        raise ValueError( f"API key file not found: {key_file}" )

    if not key_file.is_file():
        raise ValueError( f"API key file path is not a file: {key_file}" )

    try:
        with open( key_file, 'r' ) as f:
            api_key = f.read().strip()
    except Exception as e:
        raise ValueError( f"Cannot read API key file {key_file}: {e}" )

    # Validate key format (ck_live_*)
    if not re.match( r'^ck_live_[A-Za-z0-9_-]{64,}$', api_key ):
        raise ValueError( f"Invalid API key format in {key_file}. Expected: ck_live_{{64+ chars}}" )

    return api_key


def validate_api_config( config: Dict[str, str] ) -> None:
    """
    Validate API configuration.

    Requires:
        - config is dict with api_url and api_key_file keys

    Ensures:
        - raises ValueError if config invalid
        - returns None if config valid

    Validates:
        - api_url is valid URL (http:// or https://)
        - api_key_file path exists and is readable
        - api_key file contains valid key format

    Args:
        config: Configuration dict with 'api_url' and 'api_key_file' keys

    Raises:
        ValueError: If any validation check fails
    """
    # Validate URL format
    url = config.get( 'api_url' )
    if not url:
        raise ValueError( "Missing 'api_url' in config" )

    if not re.match( r'^https?://.+', url ):
        raise ValueError( f"Invalid API URL format: {url}" )

    # Validate key file exists
    key_file_path = config.get( 'api_key_file' )
    if not key_file_path:
        raise ValueError( "Missing 'api_key_file' in config" )

    key_file = Path( key_file_path )
    if not key_file.exists():
        raise ValueError( f"API key file not found: {key_file}" )

    if not key_file.is_file():
        raise ValueError( f"API key file is not a file: {key_file}" )

    # Validate key file readable
    try:
        with open( key_file, 'r' ) as f:
            api_key = f.read().strip()
    except Exception as e:
        raise ValueError( f"Cannot read API key file {key_file}: {e}" )

    # Validate key format (ck_live_*)
    if not re.match( r'^ck_live_[A-Za-z0-9_-]{64,}$', api_key ):
        raise ValueError( f"Invalid API key format in {key_file}" )


def quick_smoke_test():
    """
    Quick smoke test for config loader module.

    Requires:
        - LUPIN_ROOT environment variable set
        - cosa.utils.util available

    Ensures:
        - Tests env var precedence and config file loading
        - Tests validation function
        - Tests error handling (missing config raises FileNotFoundError)
        - Comprehensive output with status indicators

    Raises:
        - None (catches all exceptions)
    """
    import tempfile

    cu.print_banner( "Config Loader Smoke Test", prepend_nl=True )

    try:
        # Test 1: Module imports
        print( "Testing module imports..." )
        print( "✓ config_loader module imported" )

        # Test 2: Config file loading (requires ~/.lupin/config on this system)
        print( "\nTesting config file loading..." )
        config = get_api_config()
        assert 'api_url' in config
        assert 'api_key_file' in config
        print( f"✓ Config api_url: {config['api_url']}" )
        print( f"✓ Config api_key_file: {config['api_key_file']}" )

        # Test 3: Environment variable override
        print( "\nTesting environment variable precedence..." )
        os.environ['LUPIN_API_URL'] = 'http://test.example.com:8000'
        os.environ['LUPIN_API_KEY_FILE'] = '/tmp/test_key'

        config = get_api_config()
        assert config['api_url'] == 'http://test.example.com:8000'
        assert config['api_key_file'] == '/tmp/test_key'
        print( "✓ Environment variables override defaults" )

        # Clean up env vars
        del os.environ['LUPIN_API_URL']
        del os.environ['LUPIN_API_KEY_FILE']

        # Test 4: Config file parsing
        print( "\nTesting config file parsing..." )

        # Create temporary config file
        with tempfile.NamedTemporaryFile( mode='w', suffix='.ini', delete=False ) as f:
            f.write( "[environments]\n" )
            f.write( "default = local\n\n" )
            f.write( "[local]\n" )
            f.write( "api_url = http://localhost:7999\n" )
            f.write( "api_key_file = /tmp/test_local_key\n\n" )
            f.write( "[production]\n" )
            f.write( "api_url = https://prod.example.com\n" )
            f.write( "api_key_file = /tmp/test_prod_key\n" )
            temp_config_path = Path( f.name )

        try:
            loaded_config = _load_config_file( temp_config_path )
            assert 'environments' in loaded_config
            assert 'local' in loaded_config
            assert 'production' in loaded_config
            print( "✓ Config file parsed successfully" )
            print( f"  Environments: {', '.join( [s for s in loaded_config.sections() if s != 'environments'] )}" )
        finally:
            temp_config_path.unlink()

        # Test 5: Validation function - valid config
        print( "\nTesting validation function..." )

        # Create temporary API key file
        with tempfile.NamedTemporaryFile( mode='w', delete=False ) as f:
            f.write( "ck_live_" + "A" * 64 )  # Valid format
            temp_key_file = Path( f.name )

        try:
            valid_config = {
                'api_url': 'https://example.com',
                'api_key_file': str( temp_key_file )
            }
            validate_api_config( valid_config )
            print( "✓ Valid config passed validation" )
        finally:
            temp_key_file.unlink()

        # Test 6: Validation function - invalid URL
        print( "\nTesting validation error handling..." )
        invalid_config = {
            'api_url': 'not-a-url',
            'api_key_file': '/tmp/fake_key'
        }

        try:
            validate_api_config( invalid_config )
            print( "✗ Validation should have failed for invalid URL" )
            return False
        except ValueError as e:
            print( f"✓ Invalid URL caught: {str( e )[:50]}..." )

        # Test 7: Validation function - missing file
        missing_file_config = {
            'api_url': 'https://example.com',
            'api_key_file': '/tmp/nonexistent_key_file_12345.key'
        }

        try:
            validate_api_config( missing_file_config )
            print( "✗ Validation should have failed for missing file" )
            return False
        except ValueError as e:
            print( f"✓ Missing file caught: {str( e )[:50]}..." )

        print( "\n✓ All config loader tests passed!" )
        return True

    except Exception as e:
        print( f"\n✗ Config loader test failed: {e}" )
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    quick_smoke_test()
