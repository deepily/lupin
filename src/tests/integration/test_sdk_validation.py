"""
SDK Validation Tests - Phase 1 of Option B Testing.

Validates claude-agent-sdk installation and basic functionality.
These tests confirm the SDK is correctly installed and can establish
connections to Claude Code.

PREREQUISITES:
    1. claude-agent-sdk installed
       pip install claude-agent-sdk

    2. Claude Code CLI installed
       npm install -g @anthropic-ai/claude-code

    3. LUPIN_ROOT environment variable set
       export LUPIN_ROOT=/path/to/lupin

RUNNING TESTS:
    # Run SDK validation tests
    pytest src/tests/integration/test_sdk_validation.py -v

    # Run only import tests (no Claude CLI needed)
    pytest src/tests/integration/test_sdk_validation.py -v -m "not e2e"

    # Run connection tests (requires Claude CLI)
    pytest src/tests/integration/test_sdk_validation.py -v -m "e2e"

Created: 2026-01-05
Phase: 1 of 5 (Option B Testing)
"""

import pytest
import asyncio
import subprocess

# Path bootstrapped by src/tests/conftest.py - cosa now importable
import cosa.utils.util as cu


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture( scope="module" )
def project_root():
    """Get project root using canonical pattern."""
    return cu.get_project_root()


@pytest.fixture( scope="module" )
def verify_claude_cli():
    """
    Verify Claude Code CLI is installed.

    Raises:
        pytest.skip: If CLI not found
    """
    try:
        result = subprocess.run(
            [ "claude", "--version" ],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            print( f"\n✓ Claude Code CLI found: {version}" )
            return True
    except ( subprocess.TimeoutExpired, FileNotFoundError ):
        pass

    pytest.skip(
        "\n" + "=" * 60 + "\n"
        "Claude Code CLI not found\n\n"
        "Install with: npm install -g @anthropic-ai/claude-code\n"
        + "=" * 60 + "\n"
    )


# ============================================================================
# Phase 1.1: SDK Import and Availability Tests
# ============================================================================

class TestSDKImports:
    """Validate SDK imports and availability."""

    def test_sdk_imports_available( self ):
        """All required SDK classes should import without error."""
        # Import the dispatcher's SDK_AVAILABLE flag
        from cosa.orchestration.claude_code.dispatcher import SDK_AVAILABLE

        if not SDK_AVAILABLE:
            pytest.skip( "claude-agent-sdk not installed" )

        # These imports should work if SDK_AVAILABLE is True
        from claude_agent_sdk import (
            ClaudeSDKClient,
            ClaudeAgentOptions,
            AssistantMessage,
            TextBlock,
            ToolUseBlock,
            ToolResultBlock,
            ResultMessage
        )

        assert ClaudeSDKClient is not None
        assert ClaudeAgentOptions is not None
        assert AssistantMessage is not None
        assert TextBlock is not None
        assert ToolUseBlock is not None
        assert ToolResultBlock is not None
        assert ResultMessage is not None

        print( "\n✓ All SDK classes imported successfully" )

    def test_sdk_available_flag( self ):
        """SDK_AVAILABLE flag should be True when SDK is installed."""
        from cosa.orchestration.claude_code.dispatcher import SDK_AVAILABLE

        # The flag should be True in our environment
        assert SDK_AVAILABLE is True, (
            "SDK_AVAILABLE is False - claude-agent-sdk may not be installed. "
            "Run: pip install claude-agent-sdk"
        )

        print( "\n✓ SDK_AVAILABLE flag is True" )

    def test_dispatcher_sdk_imports( self ):
        """Dispatcher should successfully import SDK classes."""
        from cosa.orchestration.claude_code.dispatcher import SDK_AVAILABLE

        if not SDK_AVAILABLE:
            pytest.skip( "claude-agent-sdk not installed" )

        # The dispatcher imports these at the top - verify they're accessible
        from cosa.orchestration.claude_code.dispatcher import (
            ClaudeSDKClient,
            ClaudeAgentOptions,
            AssistantMessage,
            TextBlock,
            ToolUseBlock,
            ResultMessage
        )

        assert ClaudeSDKClient is not None
        assert ClaudeAgentOptions is not None

        print( "\n✓ Dispatcher SDK imports accessible" )


# ============================================================================
# Phase 1.2: SDK Options Construction Tests
# ============================================================================

class TestSDKOptions:
    """Validate ClaudeAgentOptions construction."""

    def test_claude_agent_options_basic( self ):
        """ClaudeAgentOptions should construct with minimal parameters."""
        from cosa.orchestration.claude_code.dispatcher import SDK_AVAILABLE

        if not SDK_AVAILABLE:
            pytest.skip( "claude-agent-sdk not installed" )

        from claude_agent_sdk import ClaudeAgentOptions

        # Basic construction with no params
        options = ClaudeAgentOptions()

        assert options is not None
        print( "\n✓ ClaudeAgentOptions created with defaults" )

    def test_claude_agent_options_with_model( self ):
        """ClaudeAgentOptions should accept model parameter."""
        from cosa.orchestration.claude_code.dispatcher import SDK_AVAILABLE

        if not SDK_AVAILABLE:
            pytest.skip( "claude-agent-sdk not installed" )

        from claude_agent_sdk import ClaudeAgentOptions

        options = ClaudeAgentOptions( model="claude-sonnet-4-20250514" )

        assert options is not None
        print( "\n✓ ClaudeAgentOptions created with model parameter" )

    def test_claude_agent_options_with_cwd( self, project_root ):
        """ClaudeAgentOptions should accept cwd parameter."""
        from cosa.orchestration.claude_code.dispatcher import SDK_AVAILABLE

        if not SDK_AVAILABLE:
            pytest.skip( "claude-agent-sdk not installed" )

        from claude_agent_sdk import ClaudeAgentOptions

        options = ClaudeAgentOptions( cwd=project_root )

        assert options is not None
        print( f"\n✓ ClaudeAgentOptions created with cwd: {project_root}" )

    def test_claude_agent_options_with_mcp_servers( self, project_root ):
        """ClaudeAgentOptions should accept mcp_servers parameter."""
        from cosa.orchestration.claude_code.dispatcher import SDK_AVAILABLE

        if not SDK_AVAILABLE:
            pytest.skip( "claude-agent-sdk not installed" )

        from claude_agent_sdk import ClaudeAgentOptions

        # This is the pattern used in _run_interactive()
        mcp_servers = {
            "cosa-voice": {
                "command" : "src/cosa/.venv/bin/python",
                "args"    : [ "-m", "lupin_mcp.cosa_voice_mcp" ],
                "cwd"     : project_root,
                "env"     : { "MCP_PROJECT": "lupin" }
            }
        }

        options = ClaudeAgentOptions(
            cwd         = project_root,
            mcp_servers = mcp_servers
        )

        assert options is not None
        print( "\n✓ ClaudeAgentOptions created with mcp_servers config" )

    def test_claude_agent_options_full_config( self, project_root ):
        """ClaudeAgentOptions should accept full production config."""
        from cosa.orchestration.claude_code.dispatcher import SDK_AVAILABLE

        if not SDK_AVAILABLE:
            pytest.skip( "claude-agent-sdk not installed" )

        from claude_agent_sdk import ClaudeAgentOptions

        # Full config as used in dispatcher
        mcp_servers = {
            "cosa-voice": {
                "command" : "src/cosa/.venv/bin/python",
                "args"    : [ "-m", "lupin_mcp.cosa_voice_mcp" ],
                "cwd"     : project_root,
                "env"     : { "MCP_PROJECT": "lupin" }
            }
        }

        options = ClaudeAgentOptions(
            cwd         = project_root,
            mcp_servers = mcp_servers,
            max_turns   = 50
        )

        assert options is not None
        print( "\n✓ ClaudeAgentOptions created with full production config" )


# ============================================================================
# Phase 1.3: SDK Client Tests (require Claude CLI)
# ============================================================================

class TestSDKClient:
    """Validate ClaudeSDKClient functionality."""

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_client_instantiation( self, verify_claude_cli, project_root ):
        """ClaudeSDKClient should instantiate without error."""
        from cosa.orchestration.claude_code.dispatcher import SDK_AVAILABLE

        if not SDK_AVAILABLE:
            pytest.skip( "claude-agent-sdk not installed" )

        from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

        options = ClaudeAgentOptions( cwd=project_root )
        client  = ClaudeSDKClient( options )

        assert client is not None
        print( "\n✓ ClaudeSDKClient instantiated" )

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_client_context_manager( self, verify_claude_cli, project_root ):
        """ClaudeSDKClient should work as async context manager."""
        from cosa.orchestration.claude_code.dispatcher import SDK_AVAILABLE

        if not SDK_AVAILABLE:
            pytest.skip( "claude-agent-sdk not installed" )

        from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

        options = ClaudeAgentOptions( cwd=project_root )

        # This should not raise
        async with ClaudeSDKClient( options ) as client:
            assert client is not None
            print( "\n✓ ClaudeSDKClient async context manager works" )

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_get_server_info( self, verify_claude_cli, project_root ):
        """get_server_info() should return valid data."""
        from cosa.orchestration.claude_code.dispatcher import SDK_AVAILABLE

        if not SDK_AVAILABLE:
            pytest.skip( "claude-agent-sdk not installed" )

        from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

        options = ClaudeAgentOptions( cwd=project_root )

        async with ClaudeSDKClient( options ) as client:
            info = await client.get_server_info()

            assert info is not None
            assert isinstance( info, dict )

            # Log what we got
            print( f"\n✓ get_server_info() returned: {list( info.keys() )}" )


# ============================================================================
# Smoke Test Entry Point
# ============================================================================

def quick_smoke_test():
    """
    Quick smoke test for SDK validation.

    Run with:
        python -m tests.integration.test_sdk_validation
    """
    cu.print_banner( "SDK Validation Smoke Test", prepend_nl=True )

    try:
        # Test 1: SDK imports
        print( "Testing SDK imports..." )
        from cosa.orchestration.claude_code.dispatcher import SDK_AVAILABLE
        if not SDK_AVAILABLE:
            print( "✗ SDK not available - claude-agent-sdk not installed" )
            return

        from claude_agent_sdk import (
            ClaudeSDKClient,
            ClaudeAgentOptions,
            AssistantMessage,
            TextBlock,
            ToolUseBlock,
            ResultMessage
        )
        print( "✓ SDK classes imported successfully" )

        # Test 2: Options construction
        print( "Testing ClaudeAgentOptions construction..." )
        options = ClaudeAgentOptions(
            cwd       = cu.get_project_root(),
            max_turns = 5
        )
        print( "✓ ClaudeAgentOptions constructed" )

        # Test 3: Client instantiation
        print( "Testing ClaudeSDKClient instantiation..." )
        client = ClaudeSDKClient( options )
        print( "✓ ClaudeSDKClient instantiated" )

        print( "\n✓ SDK validation smoke test completed successfully" )

    except ImportError as e:
        print( f"\n✗ Import error: {e}" )
        print( "   Install with: pip install claude-agent-sdk" )
    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
