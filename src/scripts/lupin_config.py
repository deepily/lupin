#!/usr/bin/env python3
"""
Lupin CLI Configuration Management Utility.

Manages multi-environment configuration for Lupin CLI tools.
Handles config file creation, environment management, and connectivity testing.

Design reference: src/rnd/v0.1.0/2025.11.10-phase-2.5-notification-authentication.md
Section: lupin-config CLI Utility Design (lines 934-1184)

Usage:
    lupin-config init                           # Initialize config file
    lupin-config show                           # Show current configuration
    lupin-config list                           # List all environments
    lupin-config add <env> [options]            # Add new environment
    lupin-config use <env>                      # Set default environment
    lupin-config test <env>                     # Test environment
    lupin-config migrate                        # Migrate legacy config files into unified ~/.lupin/config
"""

import os
import sys
import argparse
import re
from pathlib import Path
from configparser import ConfigParser
from typing import Optional, Dict

# Bootstrap: Use LUPIN_ROOT environment variable for standalone execution
lupin_root = os.environ.get( 'LUPIN_ROOT' )
if lupin_root is None:
    print( "Error: LUPIN_ROOT environment variable not set.", file=sys.stderr )
    print( "Set it before running:", file=sys.stderr )
    print( "  export LUPIN_ROOT=/path/to/project", file=sys.stderr )
    print( "  lupin-config <command>", file=sys.stderr )
    sys.exit( 1 )

src_path = os.path.join( lupin_root, 'src' )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

# Now cosa is importable
from cosa.utils.config_loader import get_api_config, validate_api_config


def get_config_path() -> Path:
    """
    Get path to Lupin config file.

    Returns:
        Path: ~/.lupin/config
    """
    return Path.home() / '.lupin' / 'config'


def print_header( title: str ):
    """
    Print formatted header.

    Args:
        title: Header text
    """
    print( f"\n{title}" )
    print( "═" * 60 )


def print_success( message: str ):
    """Print success message with checkmark."""
    print( f"✓ {message}" )


def print_error( message: str ):
    """Print error message with X mark."""
    print( f"✗ {message}", file=sys.stderr )


def cmd_init( args ):
    """
    Initialize Lupin configuration file.

    Requires:
        - LUPIN_ROOT environment variable set
        - Home directory writable

    Ensures:
        - Creates ~/.lupin directory if needed
        - Creates ~/.lupin/config with [local] environment
        - Idempotent (safe to run multiple times)
        - Returns 0 on success, 1 on error
    """
    config_path = get_config_path()

    print( "Initializing Lupin CLI configuration..." )

    # Create directory if needed
    config_dir = config_path.parent
    if not config_dir.exists():
        config_dir.mkdir( parents=True, exist_ok=True )
        print_success( f"Created directory: {config_dir}" )
    else:
        print( f"  Directory exists: {config_dir}" )

    # Check if config already exists
    if config_path.exists():
        print( f"  Config file exists: {config_path}" )
        print( "\n⚠️  Configuration already initialized" )
        print( f"\nTo view config: lupin-config show" )
        print( f"To add environment: lupin-config add production" )
        return 0

    # Create config with credentials placeholder + local environment
    config = ConfigParser()

    config['lupin'] = {
        'email'    : 'claude.code@lupin.deepily.ai',
        'password' : 'CHANGE-ME'
    }

    config['environments'] = {
        'default': 'local'
    }

    config['local'] = {
        'api_url'      : 'http://localhost:7999',
        'api_key_file' : f"{lupin_root}/src/conf/keys/notification-api-claude-code-dev",
        'description'  : 'Local development server'
    }

    # Write config file with restricted permissions
    try:
        with open( config_path, 'w' ) as f:
            config.write( f )
        os.chmod( config_path, 0o600 )
        print_success( f"Created config file: {config_path} (chmod 600)" )
    except Exception as e:
        print_error( f"Failed to create config file: {e}" )
        return 1

    print_success( "Added [lupin] credentials placeholder" )
    print_success( "Added [local] environment" )

    print( "\n✓ Configuration initialized successfully!" )
    print( "\n⚠️  Update the [lupin] section with your actual credentials:" )
    print( f"   {config_path}" )
    print( "\nNext steps:" )
    print( "  1. Set credentials: edit ~/.lupin/config [lupin] section" )
    print( "  2. Review config: lupin-config show" )
    print( "  3. Add production environment: lupin-config add production" )
    print( "  4. Test connection: lupin-config test local" )

    return 0


def cmd_show( args ):
    """
    Display current active configuration.

    Requires:
        - Config file may or may not exist

    Ensures:
        - Shows active configuration with precedence
        - Displays environment variable overrides
        - Returns 0 on success, 1 on error
    """
    config_path = get_config_path()

    print_header( "Current Lupin Configuration" )

    # Show config file status
    if config_path.exists():
        print( f"Config File: {config_path}" )
    else:
        print( f"Config File: {config_path} (not found)" )
        print( "\n⚠️  No configuration file found" )
        print( "\nRun 'lupin-config init' to create one" )
        return 1

    # Load config to get default
    try:
        config = ConfigParser()
        config.read( config_path )

        default_env = config.get( 'environments', 'default', fallback='local' )
        print( f"Default Environment: {default_env}" )

        # Determine active environment
        if os.getenv( 'LUPIN_ENV' ):
            active_env = os.getenv( 'LUPIN_ENV' )
            print( f"Active Environment: {active_env} (via LUPIN_ENV)" )
        else:
            active_env = default_env
            print( f"Active Environment: {active_env} (using default)" )

        # Get active config
        api_config = get_api_config( env=active_env )

        print( "\nConfiguration:" )
        print( f"  API URL: {api_config['api_url']}" )
        print( f"  API Key File: {api_config['api_key_file']}" )

        # Show description if available
        if active_env in config:
            description = config[active_env].get( 'description' )
            if description:
                print( f"  Description: {description}" )

    except Exception as e:
        print_error( f"Failed to load configuration: {e}" )
        return 1

    print( "\n" + "═" * 60 )

    # Show credentials status
    print( "\nCredentials:" )
    cred_sections = [ s for s in config.sections() if s not in ( 'environments', ) and 'email' in config[s] ]
    if cred_sections:
        for section_name in cred_sections:
            email = config[section_name].get( 'email', '' )
            has_password = bool( config[section_name].get( 'password', '' ) )
            print( f"  [{section_name}] email={email}  password={'set' if has_password else 'MISSING'}" )
    else:
        legacy_creds = Path.home() / '.lupin' / 'credentials.ini'
        if legacy_creds.exists():
            print( f"  ⚠️  No credentials in unified config. Legacy file exists: {legacy_creds}" )
            print( f"     Run 'lupin-config migrate' to consolidate." )
        else:
            print( "  (none configured)" )

    # Show environment variable overrides
    print( "\nEnvironment variable overrides:" )
    print( f"  LUPIN_ENV: {os.getenv( 'LUPIN_ENV' ) or '(not set)'}" )
    print( f"  LUPIN_API_URL: {os.getenv( 'LUPIN_API_URL' ) or '(not set)'}" )
    print( f"  LUPIN_API_KEY_FILE: {os.getenv( 'LUPIN_API_KEY_FILE' ) or '(not set)'}" )
    api_key_direct = os.getenv( 'LUPIN_API_KEY' )
    print( f"  LUPIN_API_KEY: {'ck_live_...' + api_key_direct[ -8: ] if api_key_direct else '(not set)'}" )

    return 0


def cmd_list( args ):
    """
    List all configured environments.

    Requires:
        - Config file exists

    Ensures:
        - Lists all environments with details
        - Marks default environment
        - Returns 0 on success, 1 on error
    """
    config_path = get_config_path()

    if not config_path.exists():
        print_error( "No configuration file found" )
        print( "\nRun 'lupin-config init' to create one" )
        return 1

    try:
        config = ConfigParser()
        config.read( config_path )

        default_env = config.get( 'environments', 'default', fallback='local' )

        print_header( "Available Environments" )

        # List all environments (exclude [environments] section)
        env_sections = [s for s in config.sections() if s != 'environments']

        if not env_sections:
            print( "\n⚠️  No environments configured" )
            return 1

        for env_name in env_sections:
            is_default = env_name == default_env
            marker = " * " if is_default else "   "
            suffix = " (default)" if is_default else ""

            print( f"\n{marker}{env_name}{suffix}" )
            print( f"    URL: {config[env_name].get( 'api_url', 'N/A' )}" )

            description = config[env_name].get( 'description' )
            if description:
                print( f"    Description: {description}" )

        print( "\n" + "═" * 60 )
        print( "\nUse 'lupin-config use <env>' to change default environment" )
        print( "Use 'LUPIN_ENV=<env>' to temporarily override" )

        return 0

    except Exception as e:
        print_error( f"Failed to read configuration: {e}" )
        return 1


def cmd_add( args ):
    """
    Add new environment to configuration.

    Requires:
        - Config file exists (suggest init if not)
        - Environment name provided
        - URL and key file (via flags or interactive)

    Ensures:
        - Validates environment doesn't already exist
        - Validates URL format
        - Adds new environment section
        - Returns 0 on success, 1 on error
    """
    config_path = get_config_path()

    if not config_path.exists():
        print_error( "No configuration file found" )
        print( "\nRun 'lupin-config init' first" )
        return 1

    env_name = args.environment

    # Load existing config
    try:
        config = ConfigParser()
        config.read( config_path )

        # Check if environment already exists
        if env_name in config:
            print_error( f"Environment '{env_name}' already exists" )
            print( f"\nUse 'lupin-config use {env_name}' to switch to it" )
            return 1

        # Get values (CLI flags or interactive)
        if args.url and args.key_file:
            # Non-interactive mode
            api_url = args.url
            api_key_file = args.key_file
            description = args.description or ""
        else:
            # Interactive mode
            print( f"\nAdding environment '{env_name}'..." )
            print( "\nPlease provide the following information:" )

            api_url = input( "API URL: " ).strip()
            api_key_file = input( "API Key File: " ).strip()
            description = input( "Description (optional): " ).strip()

        # Validate URL
        if not re.match( r'^https?://.+', api_url ):
            print_error( f"Invalid URL format: {api_url}" )
            print( "\nURL must start with http:// or https://" )
            return 1

        # Add new environment
        config[env_name] = {
            'api_url': api_url,
            'api_key_file': api_key_file
        }

        if description:
            config[env_name]['description'] = description

        # Write updated config
        with open( config_path, 'w' ) as f:
            config.write( f )

        print_success( f"Environment added to {config_path}" )

        print( "\nConfiguration:" )
        print( f"  API URL: {api_url}" )
        print( f"  API Key File: {api_key_file}" )
        if description:
            print( f"  Description: {description}" )

        print( "\nNext steps:" )
        print( "  1. Create service account on server" )
        print( f"  2. Copy API key to {api_key_file}" )
        print( f"  3. Test connection: lupin-config test {env_name}" )

        return 0

    except Exception as e:
        print_error( f"Failed to add environment: {e}" )
        return 1


def cmd_use( args ):
    """
    Change default environment.

    Requires:
        - Config file exists
        - Environment name provided
        - Environment exists in config

    Ensures:
        - Updates [environments] default value
        - Validates environment exists
        - Returns 0 on success, 1 on error
    """
    config_path = get_config_path()

    if not config_path.exists():
        print_error( "No configuration file found" )
        print( "\nRun 'lupin-config init' first" )
        return 1

    env_name = args.environment

    try:
        config = ConfigParser()
        config.read( config_path )

        # Check if environment exists
        if env_name not in config:
            print_error( f"Environment '{env_name}' not found" )
            print( "\nAvailable environments:" )
            for section in config.sections():
                if section != 'environments':
                    print( f"  - {section}" )
            print( f"\nUse 'lupin-config add {env_name}' to create it" )
            return 1

        # Update default
        config['environments']['default'] = env_name

        # Write updated config
        with open( config_path, 'w' ) as f:
            config.write( f )

        print_success( f"Switched default environment to '{env_name}'" )
        print( "\nAll future commands will use this environment unless overridden with LUPIN_ENV" )
        print( "\nVerify: lupin-config show" )

        return 0

    except Exception as e:
        print_error( f"Failed to change environment: {e}" )
        return 1


def cmd_test( args ):
    """
    Test connectivity and authentication to environment.

    Requires:
        - Config file exists
        - Environment exists
        - API key file exists

    Ensures:
        - Tests configuration loading
        - Tests network connectivity (optional)
        - Tests authentication (optional)
        - Returns 0 on success, 1 on error
    """
    config_path = get_config_path()
    env_name = args.environment

    print( f"Testing connection to '{env_name}'..." )
    print_header( "Test Results" )

    # Phase 1: Configuration
    print( "\n1. Loading configuration..." )

    if not config_path.exists():
        print_error( "Config file not found" )
        return 1

    print( f"   ✓ Config file found: {config_path}" )

    try:
        config = ConfigParser()
        config.read( config_path )

        if env_name not in config:
            print_error( f"Environment '{env_name}' not found" )
            print( f"\n   Available: {', '.join( [s for s in config.sections() if s != 'environments'] )}" )
            return 1

        print( f"   ✓ Environment '{env_name}' exists" )

        # Load config for this environment
        api_config = get_api_config( env=env_name )
        print( f"   ✓ API URL: {api_config['api_url']}" )

        # Check if key file exists
        key_file = Path( api_config['api_key_file'] )
        if not key_file.exists():
            print_error( f"API Key file not found: {key_file}" )
            print( "\n   To fix:" )
            print( "     1. Create service account on server" )
            print( f"     2. Copy generated key to {key_file}" )
            print( "     3. Run test again" )
            return 1

        print( f"   ✓ API Key file found: {key_file}" )

        # Validate config
        try:
            validate_api_config( api_config )
            print( "   ✓ Configuration valid" )
        except ValueError as e:
            print_error( f"Configuration validation failed: {e}" )
            return 1

    except Exception as e:
        print_error( f"Configuration error: {e}" )
        return 1

    # Phase 2: Network connectivity (basic check)
    print( "\n2. Testing network connectivity..." )
    print( "   ⚠️  Network test not implemented (requires server running)" )
    print( "   Skipping network connectivity test" )

    # Phase 3: Authentication (requires running server)
    print( "\n3. Testing authentication..." )
    print( "   ⚠️  Authentication test not implemented (requires server running)" )
    print( "   Skipping authentication test" )

    print( "\n" + "═" * 60 )
    print( "✓ Configuration tests passed!" )
    print( "\nNote: Full connectivity and authentication testing requires a running server" )

    return 0


def cmd_migrate( args ):
    """
    Migrate legacy credential/config files into unified ~/.lupin/config.

    Requires:
        - At least one legacy file exists (~/.lupin/credentials.ini or ~/.notifications/config)

    Ensures:
        - Merges credential sections from ~/.lupin/credentials.ini
        - Merges environment sections from ~/.notifications/config
        - Backs up old files with .bak suffix
        - Sets chmod 600 on unified file
        - Returns 0 on success, 1 on error
    """
    config_path          = get_config_path()
    legacy_creds_path    = Path.home() / '.lupin' / 'credentials.ini'
    legacy_notif_path    = Path.home() / '.notifications' / 'config'

    print_header( "Migrating to Unified Config" )
    print( f"Target: {config_path}" )

    # Load existing unified config (or start fresh)
    unified = ConfigParser()
    if config_path.exists():
        unified.read( config_path )
        print( f"  Existing config loaded: {config_path}" )

    migrated_anything = False

    # ── Migrate credentials from ~/.lupin/credentials.ini ────────────
    if legacy_creds_path.exists():
        print( f"\n  Reading credentials from: {legacy_creds_path}" )
        creds_config = ConfigParser()
        creds_config.read( str( legacy_creds_path ) )

        for section in creds_config.sections():
            if section in unified:
                print( f"    [{section}] already exists in unified config — skipping" )
            else:
                unified[section] = dict( creds_config[section] )
                print_success( f"  Migrated [{section}] credentials" )
                migrated_anything = True
    else:
        print( f"\n  No legacy credentials file: {legacy_creds_path}" )

    # ── Migrate environments from ~/.notifications/config ────────────
    if legacy_notif_path.exists():
        print( f"\n  Reading environments from: {legacy_notif_path}" )
        notif_config = ConfigParser()
        notif_config.read( str( legacy_notif_path ) )

        for section in notif_config.sections():
            if section in unified:
                print( f"    [{section}] already exists in unified config — skipping" )
            else:
                unified[section] = dict( notif_config[section] )
                print_success( f"  Migrated [{section}] section" )
                migrated_anything = True
    else:
        print( f"\n  No legacy notifications config: {legacy_notif_path}" )

    if not migrated_anything:
        print( "\n  Nothing to migrate — all sections already present." )
        return 0

    # ── Write unified config ─────────────────────────────────────────
    try:
        config_path.parent.mkdir( parents=True, exist_ok=True )
        with open( config_path, 'w' ) as f:
            unified.write( f )
        os.chmod( config_path, 0o600 )
        print_success( f"\n  Wrote unified config: {config_path} (chmod 600)" )
    except Exception as e:
        print_error( f"Failed to write unified config: {e}" )
        return 1

    # ── Backup old files ─────────────────────────────────────────────
    for legacy_path in [ legacy_creds_path, legacy_notif_path ]:
        if legacy_path.exists():
            backup_path = legacy_path.with_suffix( legacy_path.suffix + '.bak' )
            try:
                legacy_path.rename( backup_path )
                print_success( f"  Backed up: {legacy_path} → {backup_path}" )
            except Exception as e:
                print_error( f"  Failed to backup {legacy_path}: {e}" )

    print( "\n" + "═" * 60 )
    print( "✓ Migration complete!" )
    print( f"\nVerify: lupin-config show" )

    return 0


def main():
    """
    Main entry point for lupin-config CLI.

    Returns:
        int: Exit code (0 = success, 1 = error)
    """
    parser = argparse.ArgumentParser(
        description='Lupin CLI Configuration Management',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers( dest='command', help='Available commands' )

    # Command: init
    parser_init = subparsers.add_parser( 'init', help='Initialize configuration file' )
    parser_init.set_defaults( func=cmd_init )

    # Command: show
    parser_show = subparsers.add_parser( 'show', help='Display current configuration' )
    parser_show.set_defaults( func=cmd_show )

    # Command: list
    parser_list = subparsers.add_parser( 'list', help='List all environments' )
    parser_list.set_defaults( func=cmd_list )

    # Command: add
    parser_add = subparsers.add_parser( 'add', help='Add new environment' )
    parser_add.add_argument( 'environment', help='Environment name' )
    parser_add.add_argument( '--url', help='API URL (e.g., https://server.example.com)' )
    parser_add.add_argument( '--key-file', help='Path to API key file' )
    parser_add.add_argument( '--description', help='Environment description' )
    parser_add.set_defaults( func=cmd_add )

    # Command: use
    parser_use = subparsers.add_parser( 'use', help='Set default environment' )
    parser_use.add_argument( 'environment', help='Environment name' )
    parser_use.set_defaults( func=cmd_use )

    # Command: test
    parser_test = subparsers.add_parser( 'test', help='Test environment connectivity' )
    parser_test.add_argument( 'environment', help='Environment name' )
    parser_test.set_defaults( func=cmd_test )

    # Command: migrate
    parser_migrate = subparsers.add_parser( 'migrate', help='Migrate legacy config files into unified ~/.lupin/config' )
    parser_migrate.set_defaults( func=cmd_migrate )

    # Parse arguments
    args = parser.parse_args()

    # Show help if no command provided
    if not args.command:
        parser.print_help()
        return 1

    # Execute command
    try:
        return args.func( args )
    except Exception as e:
        print_error( f"Unexpected error: {e}" )
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit( main() )
