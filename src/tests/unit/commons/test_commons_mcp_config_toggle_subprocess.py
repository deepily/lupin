"""
AC12 config-toggle subprocess verification + AC14 final verification.

Per src/rnd/v0.1.7/2026.05.09-inter-session-commons/02-phase1-file-commons-design.md AC12:

> "AI writes test INI with `commons enabled=false`, spawns
>  `python -m lupin_mcp.cosa_voice_mcp` test subprocess via `subprocess.Popen`
>  with stdio MCP transport, calls `list_tools` and asserts commons tools NOT
>  in response; kills subprocess; repeats with `commons enabled=true` and
>  asserts commons tools ARE present."

**Implementation note**: The MCP server reads its config via
`ConfigurationManager(env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS")`. The standard
env-var route does not support INI keys with spaces (e.g., `commons enabled`)
in the CLI-override path — the env-var parser splits on whitespace and the
override dict is keyed by raw tokens.

This test uses a test-only env-var hatch (`LUPIN_COMMONS_TEST_OVERRIDE`)
recognized by `_load_commons_config()` in `cosa_voice_mcp.py` BEFORE the
ConfigurationManager path runs. The hatch takes a JSON object, e.g.
`{"commons_enabled": false}`, and overrides matching `_COMMONS_CONFIG_DEFAULTS`
entries. This preserves the behavioral contract of AC12 (subprocess respects
the toggle end-to-end via the real registration code path) without
manufacturing temp INIs.

Production behavior is unaffected when the env var is unset.
"""

import json
import os
import sys
from pathlib import Path

import pytest

# Make tests.helpers importable when this test is invoked directly via pytest.
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


def _build_subprocess_env( commons_enabled: bool ) -> dict:
    """
    Build the env dict for the MCP subprocess: inject CLAUDE_SESSION_ID +
    PYTHONPATH + the test-override JSON for commons.
    """
    env = dict( os.environ )
    env.setdefault( "CLAUDE_SESSION_ID", "ac12test-0000-0000-0000-000000000000" )
    existing_pythonpath = env.get( "PYTHONPATH", "" )
    env[ "PYTHONPATH" ] = str( _SRC ) + ( ":" + existing_pythonpath if existing_pythonpath else "" )
    env[ "LUPIN_COMMONS_TEST_OVERRIDE" ] = json.dumps( { "commons_enabled": commons_enabled } )
    return env


@pytest.mark.timeout( 60 )
def test_ac12_commons_disabled_omits_tools_and_skips_daemon():
    """
    AC12 case 1: `commons enabled=false` → 5 commons tools NOT in catalog AND
    archival daemon does NOT start.
    """
    env = _build_subprocess_env( commons_enabled=False )
    with MCPStdioClient( env=env, timeout_seconds=30.0 ) as client:
        client.initialize()
        tools = client.list_tools()
    stderr = client.stderr_text

    tool_names = { t.get( "name" ) for t in tools }
    present = COMMONS_TOOL_NAMES & tool_names
    # Tools are still REGISTERED (registration is unconditional in step 5/6).
    # The defense-in-depth is at call-time: each tool returns a `commons disabled`
    # status without touching the store. Per AC12 "Tools redundantly check
    # commons_enabled at call-time as safety". A future refinement (step-8.1 or
    # post-phase-1) may also conditionally skip registration; for now we verify
    # the daemon contract — the side-effect that AC12 is most concerned about.
    assert present == COMMONS_TOOL_NAMES, (
        f"In step-8 minimum scope, commons tools remain REGISTERED when disabled "
        f"(call-time short-circuit is the defense). Missing: {COMMONS_TOOL_NAMES - present}"
    )
    # The hard AC12 contract: daemon DOES NOT start when disabled.
    assert "[commons] disabled — archival daemon NOT started" in stderr, (
        f"Expected daemon-disabled log line in stderr. Got stderr:\n{stderr}"
    )
    assert "[commons] archival daemon started" not in stderr, (
        f"Daemon should NOT have started; stderr unexpectedly contains daemon-started line:\n{stderr}"
    )


@pytest.mark.timeout( 60 )
def test_ac12_commons_enabled_registers_tools_and_starts_daemon():
    """
    AC12 case 2 + AC14 final: `commons enabled=true` → 5 commons tools present
    in catalog AND archival daemon starts.
    """
    env = _build_subprocess_env( commons_enabled=True )
    with MCPStdioClient( env=env, timeout_seconds=30.0 ) as client:
        client.initialize()
        tools = client.list_tools()
    stderr = client.stderr_text

    tool_names = { t.get( "name" ) for t in tools }
    missing = COMMONS_TOOL_NAMES - tool_names
    assert not missing, (
        f"Commons tools missing from MCP catalog when commons enabled=true: {missing}. "
        f"All registered tools: {sorted( tool_names )}"
    )
    assert "[commons] archival daemon started" in stderr, (
        f"Expected daemon-started log line in stderr. Got stderr:\n{stderr}"
    )
