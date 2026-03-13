"""
Unit tests for hook credential resolution.

Tests the unified config file reading, legacy fallback behavior,
and project name derivation for Claude Code hook credentials.
"""

import pytest
import os
from pathlib import Path
from unittest.mock import patch

from lupin_cli.claude_code.hooks.lib.hook_credentials import (
    get_hook_credentials,
    _derive_project_name,
    _read_credentials_from_file,
    CREDENTIALS_FILE,
)


class TestGetHookCredentials:
    """Test suite for get_hook_credentials() function."""

    def test_reads_from_unified_config( self, tmp_path ):
        """Test reading credentials from unified ~/.lupin/config."""
        config_file = tmp_path / 'config'
        config_file.write_text( """[lupin]
email = test@lupin.deepily.ai
password = secret123

[environments]
default = local

[local]
api_url = http://localhost:7999
api_key_file = /tmp/key
""" )

        with patch( 'lupin_cli.claude_code.hooks.lib.hook_credentials.CREDENTIALS_FILE', config_file ):
            email, password = get_hook_credentials( project="lupin" )

            assert email == "test@lupin.deepily.ai"
            assert password == "secret123"

    def test_reads_cosa_section( self, tmp_path ):
        """Test reading [cosa] section from unified config."""
        config_file = tmp_path / 'config'
        config_file.write_text( """[lupin]
email = lupin@test.com
password = lupin-pass

[cosa]
email = cosa@test.com
password = cosa-pass
""" )

        with patch( 'lupin_cli.claude_code.hooks.lib.hook_credentials.CREDENTIALS_FILE', config_file ):
            email, password = get_hook_credentials( project="cosa" )

            assert email == "cosa@test.com"
            assert password == "cosa-pass"

    def test_raises_file_not_found_when_config_missing( self, tmp_path ):
        """Test FileNotFoundError when ~/.lupin/config doesn't exist."""
        nonexistent = tmp_path / 'config'

        with patch( 'lupin_cli.claude_code.hooks.lib.hook_credentials.CREDENTIALS_FILE', nonexistent ):
            with pytest.raises( FileNotFoundError, match="~/.lupin/config not found" ):
                get_hook_credentials( project="lupin" )

    def test_raises_file_not_found_with_migration_instructions( self, tmp_path ):
        """Test FileNotFoundError includes lupin-config init/migrate instructions."""
        nonexistent = tmp_path / 'config'

        with patch( 'lupin_cli.claude_code.hooks.lib.hook_credentials.CREDENTIALS_FILE', nonexistent ):
            with pytest.raises( FileNotFoundError ) as exc_info:
                get_hook_credentials( project="lupin" )

            error_msg = str( exc_info.value )
            assert "lupin-config init" in error_msg
            assert "lupin-config migrate" in error_msg

    def test_raises_value_error_when_section_missing( self, tmp_path ):
        """Test ValueError when project section not found in config."""
        config_file = tmp_path / 'config'
        config_file.write_text( """[environments]
default = local
""" )

        with patch( 'lupin_cli.claude_code.hooks.lib.hook_credentials.CREDENTIALS_FILE', config_file ):
            with pytest.raises( ValueError, match="No \\[lupin\\] section found" ):
                get_hook_credentials( project="lupin" )

    def test_raises_value_error_for_missing_email( self, tmp_path ):
        """Test ValueError when email key is missing."""
        config_file = tmp_path / 'config'
        config_file.write_text( """[lupin]
password = secret
""" )

        with patch( 'lupin_cli.claude_code.hooks.lib.hook_credentials.CREDENTIALS_FILE', config_file ):
            with pytest.raises( ValueError, match="Missing 'email'" ):
                get_hook_credentials( project="lupin" )

    def test_raises_value_error_for_missing_password( self, tmp_path ):
        """Test ValueError when password key is missing."""
        config_file = tmp_path / 'config'
        config_file.write_text( """[lupin]
email = test@test.com
""" )

        with patch( 'lupin_cli.claude_code.hooks.lib.hook_credentials.CREDENTIALS_FILE', config_file ):
            with pytest.raises( ValueError, match="Missing 'password'" ):
                get_hook_credentials( project="lupin" )


class TestReadCredentialsFromFile:
    """Test suite for _read_credentials_from_file() helper."""

    def test_returns_tuple_when_section_found( self, tmp_path ):
        """Test successful credential reading."""
        config_file = tmp_path / 'config'
        config_file.write_text( """[lupin]
email = test@test.com
password = pass123
""" )

        result = _read_credentials_from_file( config_file, "lupin" )
        assert result == ( "test@test.com", "pass123" )

    def test_returns_none_when_section_missing( self, tmp_path ):
        """Test None return when project section not found."""
        config_file = tmp_path / 'config'
        config_file.write_text( """[other]
email = test@test.com
password = pass
""" )

        result = _read_credentials_from_file( config_file, "lupin" )
        assert result is None

    def test_strips_whitespace( self, tmp_path ):
        """Test that email and password are stripped."""
        config_file = tmp_path / 'config'
        config_file.write_text( """[lupin]
email =   test@test.com
password =   pass123
""" )

        result = _read_credentials_from_file( config_file, "lupin" )
        assert result == ( "test@test.com", "pass123" )


class TestDeriveProjectName:
    """Test suite for _derive_project_name() function."""

    def test_uses_lupin_root_env_var( self, monkeypatch ):
        """Test that LUPIN_ROOT env var is used when set."""
        monkeypatch.setenv( 'LUPIN_ROOT', '/path/to/lupin' )

        result = _derive_project_name()
        assert result == "lupin"

    def test_uses_cwd_when_no_env_var( self, monkeypatch ):
        """Test fallback to cwd basename."""
        monkeypatch.delenv( 'LUPIN_ROOT', raising=False )

        result = _derive_project_name()
        assert isinstance( result, str )
        assert len( result ) > 0

    def test_returns_lowercase( self, monkeypatch ):
        """Test that project name is lowercased."""
        monkeypatch.setenv( 'LUPIN_ROOT', '/path/to/LUPIN' )

        result = _derive_project_name()
        assert result == "lupin"


class TestConstants:
    """Test that module constants are correctly defined."""

    def test_credentials_file_points_to_unified_config( self ):
        """Test that CREDENTIALS_FILE points to ~/.lupin/config."""
        assert CREDENTIALS_FILE == Path.home() / ".lupin" / "config"
