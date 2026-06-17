"""
Unit tests for hook credential resolution.

Tests the unified config file reading and legacy fallback behavior for
Claude Code hook credentials. Project-name derivation converged onto the
shared session_bridge.resolve_project_name (bug 9bf1dc4a) — its branches
are covered in test_session_bridge_lookup::TestResolveProjectName.
"""

import pytest
import os
from pathlib import Path
from unittest.mock import patch

from lupin_cli.claude_code.hooks.lib.hook_credentials import (
    get_hook_credentials,
    get_owner_credentials,
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

    def test_derives_project_via_shared_resolver_when_none( self, tmp_path ):
        """project=None → resolved via the shared session_bridge.resolve_project_name (bug 9bf1dc4a)."""
        config_file = tmp_path / 'config'
        config_file.write_text( """[lupin]
email = derived@lupin.deepily.ai
password = derived-pass
""" )

        with patch( 'lupin_cli.claude_code.hooks.lib.hook_credentials.CREDENTIALS_FILE', config_file ), \
             patch( 'lupin_cli.claude_code.hooks.lib.hook_credentials.resolve_project_name', return_value="lupin" ):
            email, password = get_hook_credentials()

            assert email    == "derived@lupin.deepily.ai"
            assert password == "derived-pass"

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


class TestConstants:
    """Test that module constants are correctly defined."""

    def test_credentials_file_points_to_unified_config( self ):
        """Test that CREDENTIALS_FILE points to ~/.lupin/config."""
        assert CREDENTIALS_FILE == Path.home() / ".lupin" / "config"


# ═════════════════════════════════════════════════════════════════════════════
# TestGetOwnerCredentials — writer-side follow-up to 2026-05-14 Option C
# ═════════════════════════════════════════════════════════════════════════════
# Per src/rnd/v0.1.7/2026.05.17-owner-user-id-stamper-writer-side/01-design.md
# §D1: the HUMAN owner's credentials live in `~/.lupin/config[owner]`. Distinct
# from per-project SERVICE-account credentials read by get_hook_credentials.

class TestGetOwnerCredentials:
    """Test suite for get_owner_credentials() function."""

    def test_reads_owner_section_from_unified_config( self, tmp_path ):
        """Test reading owner credentials from [owner] section."""
        config_file = tmp_path / 'config'
        config_file.write_text( """[lupin]
email = service@lupin.deepily.ai
password = service-pass

[owner]
email = ricardo.felipe.ruiz@gmail.com
password = owner-pass
""" )

        with patch( 'lupin_cli.claude_code.hooks.lib.hook_credentials.CREDENTIALS_FILE', config_file ):
            email, password = get_owner_credentials()

            assert email    == "ricardo.felipe.ruiz@gmail.com"
            assert password == "owner-pass"

    def test_raises_file_not_found_when_config_missing( self, tmp_path ):
        """Test FileNotFoundError when ~/.lupin/config doesn't exist."""
        nonexistent = tmp_path / 'config'

        with patch( 'lupin_cli.claude_code.hooks.lib.hook_credentials.CREDENTIALS_FILE', nonexistent ):
            with pytest.raises( FileNotFoundError, match="~/.lupin/config not found" ):
                get_owner_credentials()

    def test_raises_value_error_when_owner_section_missing( self, tmp_path ):
        """Test ValueError when [owner] section not found."""
        config_file = tmp_path / 'config'
        config_file.write_text( """[lupin]
email = service@lupin.deepily.ai
password = service-pass
""" )

        with patch( 'lupin_cli.claude_code.hooks.lib.hook_credentials.CREDENTIALS_FILE', config_file ):
            with pytest.raises( ValueError, match="No \\[owner\\] section found" ):
                get_owner_credentials()

    def test_raises_value_error_for_missing_owner_email( self, tmp_path ):
        """Test ValueError when [owner] email key is missing."""
        config_file = tmp_path / 'config'
        config_file.write_text( """[owner]
password = owner-pass
""" )

        with patch( 'lupin_cli.claude_code.hooks.lib.hook_credentials.CREDENTIALS_FILE', config_file ):
            with pytest.raises( ValueError, match="Missing 'email'" ):
                get_owner_credentials()

    def test_raises_value_error_for_missing_owner_password( self, tmp_path ):
        """Test ValueError when [owner] password key is missing."""
        config_file = tmp_path / 'config'
        config_file.write_text( """[owner]
email = ricardo.felipe.ruiz@gmail.com
""" )

        with patch( 'lupin_cli.claude_code.hooks.lib.hook_credentials.CREDENTIALS_FILE', config_file ):
            with pytest.raises( ValueError, match="Missing 'password'" ):
                get_owner_credentials()
