"""
AC14: subprocess test for commons MCP tool registration.

Per src/rnd/v0.1.7/2026.05.09-inter-session-commons/02-phase1-file-commons-design.md AC14:

> "tool-registration subprocess test (per P2 A2 ratification): AI spawns fresh
>  python -m lupin_mcp.cosa_voice_mcp subprocess via subprocess.Popen with stdio
>  MCP transport (loads cosa_voice_mcp.py from disk), sends list_tools MCP JSON-RPC
>  request, parses response, asserts all 5 commons tools present in catalog;
>  kills subprocess. Uses the same MCP-stdio test helper as AC12."

This exercises the actual entry-point path so registration regressions
(decorator-order bugs, import-time failures) surface even when in-process
unit tests still pass.

NOTE: AC12 config-toggle (commons enabled=false → tools NOT registered)
is intentionally deferred to step 8 — step 5 lands the registration code
path and the AC14 happy-path check only.
"""

import os
import sys
from pathlib import Path

import pytest

# Add `src/` to sys.path so the helper module is importable as `tests.helpers...`
_SRC = Path( __file__ ).resolve().parents[ 2 ]
if str( _SRC ) not in sys.path:
    sys.path.insert( 0, str( _SRC ) )

from tests.helpers.mcp_stdio_test_client import MCPStdioClient   # noqa: E402


COMMONS_TOOL_NAMES = {
    "commons_post",
    "commons_read",
    "commons_who",
    "commons_ask_sync",
    "commons_ask_async",
}


@pytest.mark.timeout( 60 )
def test_ac14_commons_tools_registered_in_subprocess():
    """
    Spawn the MCP server entry point as a child process; assert the 5 commons
    tools appear in the `tools/list` response catalog.
    """
    env = dict( os.environ )
    # Inject a deterministic fake session id so the subprocess doesn't block on
    # the session-bridge file lookup. CLAUDE_SESSION_ID is the canonical override.
    env.setdefault( "CLAUDE_SESSION_ID", "ac14test-0000-0000-0000-000000000000" )
    # Make sure src/ is on PYTHONPATH for the spawned process.
    src_path = str( _SRC )
    existing_pythonpath = env.get( "PYTHONPATH", "" )
    env[ "PYTHONPATH" ] = src_path + ( ":" + existing_pythonpath if existing_pythonpath else "" )

    with MCPStdioClient( env=env, timeout_seconds=30.0 ) as client:
        client.initialize()
        tools = client.list_tools()

    tool_names = { t.get( "name" ) for t in tools }
    missing = COMMONS_TOOL_NAMES - tool_names
    assert not missing, (
        f"Commons tools missing from MCP catalog: {missing}. "
        f"All registered tools: {sorted( tool_names )}"
    )
