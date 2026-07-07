"""
Unit tests for lever (i-a) of the notify-turn-hold wedge fix (bug f1a21917):
the fleet-spawn-env MCP_TOOL_TIMEOUT bound.

A fire-and-forget cosa-voice notify() held a CC turn 54m47s (incident 25c7441c)
because the MCP server's response leg never returned until process death. Claude
Code honors the MCP_TOOL_TIMEOUT environment variable (milliseconds) as an upper
bound on MCP tool-call execution — setting it in the fleet spawn path converts an
unbounded wedge into a bounded, recoverable tool-error.

HONOR-CHECK RECEIPT (2026-07-03 ~07:04Z, evidence not hypothesis): a scratch tmux
pane running CC v2.1.199 with MCP_TOOL_TIMEOUT=15000 called a hang(seconds=120)
FastMCP tool; CC aborted the call at exactly the bound ("MCP server ... timed out
after 15s") and the turn proceeded normally. Receipt: design doc §2(i-a).

These tests pin the bound into start-cc-with-tmux.sh's PERSONA_ENV_FLAGS (the
static always-on -e forward, parallel to CLAUDE_CODE_DISABLE_MOUSE=1), so BOTH
interactive AND headless (session_spawner.py) spawns inherit it across the tmux
boundary. The value 660_000 ms (11 min) sits comfortably ABOVE the 600s (600_000
ms) blocking-ask ceiling (converse/ask_* timeout_seconds <= 600) and an order of
magnitude BELOW the observed 55-min wedge.

Venue: :7999 bucket — no persistent state, no tmux sessions created (--dry-run
exits before any tmux call), <2s.

See: src/rnd/v0.1.9/2026.07.03-notify-turn-hold-fix-design.md §2(i-a)
"""

import os
import subprocess

import pytest


LUPIN_ROOT  = os.environ[ "LUPIN_ROOT" ]
SCRIPT_PATH = os.path.join( LUPIN_ROOT, "src", "scripts", "start-cc-with-tmux.sh" )

# The ratified bound (design doc §2 i-a recommendation line) + the ceiling it
# must clear (converse/ask_* timeout_seconds <= 600s == 600_000 ms).
MCP_TOOL_TIMEOUT_MS = 660_000
BLOCKING_ASK_CEILING_MS = 600_000


def _clean_env( home ):
    """
    Minimal env -i style environment for the subprocess run (hermetic — the only
    HOME the script sees is a throwaway; LUPIN_ROOT is inert under --dry-run).
    """
    return { "PATH": os.environ[ "PATH" ], "LUPIN_ROOT": LUPIN_ROOT, "HOME": str( home ) }


def _dry_run( env, session_name="mcp-timeout-test-session", headless=True ):
    """Run start-cc-with-tmux.sh --dry-run and capture the PERSONA-ENV preview."""
    argv = [ "bash", SCRIPT_PATH, "--dry-run" ]
    if headless:
        argv.append( "--headless" )
    argv.append( session_name )
    return subprocess.run( argv, env=env, capture_output=True, text=True, timeout=30 )


def _persona_env_line( result ):
    lines = [ l for l in result.stdout.splitlines() if l.startswith( "PERSONA-ENV:" ) ]
    assert len( lines ) == 1, result.stdout
    return lines[ 0 ]


class TestMcpToolTimeoutSpawnEnv:
    """Lever (i-a): MCP_TOOL_TIMEOUT=660000 forwarded across the tmux -e boundary."""

    def test_script_syntax_ok( self ):
        result = subprocess.run(
            [ "bash", "-n", SCRIPT_PATH ], capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, result.stderr

    def test_dry_run_forwards_mcp_tool_timeout_headless( self, tmp_path ):
        # Headless (session_spawner.py) spawn path — the var MUST cross tmux -e or
        # half the fleet misses the bound.
        result = _dry_run( _clean_env( tmp_path ), headless=True )
        assert result.returncode == 0, result.stderr
        line = _persona_env_line( result )
        assert f"MCP_TOOL_TIMEOUT={MCP_TOOL_TIMEOUT_MS}" in line, line

    def test_dry_run_forwards_mcp_tool_timeout_interactive( self, tmp_path ):
        # Interactive launch path shares the SAME PERSONA_ENV_FLAGS assembly, so
        # the bound is present regardless of --headless.
        result = _dry_run( _clean_env( tmp_path ), headless=False )
        assert result.returncode == 0, result.stderr
        line = _persona_env_line( result )
        assert f"MCP_TOOL_TIMEOUT={MCP_TOOL_TIMEOUT_MS}" in line, line

    def test_bound_forwarded_even_without_roster_file( self, tmp_path ):
        # The bound is STATIC always-on (not sourced from fleet-roster.env), so a
        # missing roster file must NOT drop it — HOME=tmp_path with no .claude dir.
        result = _dry_run( _clean_env( tmp_path ) )
        assert result.returncode == 0, result.stderr
        assert "COSA_VOICE_MANAGERS__" not in result.stdout          # roster genuinely absent
        line = _persona_env_line( result )
        assert f"MCP_TOOL_TIMEOUT={MCP_TOOL_TIMEOUT_MS}" in line, line

    def test_bound_sits_above_blocking_ask_ceiling( self ):
        # Sizing invariant (design doc §2 i-a): the bound MUST clear the longest
        # legitimate blocking ask (converse/ask_* timeout_seconds <= 600s) so a
        # legitimate wait is never severed, while still bounding the wedge.
        assert MCP_TOOL_TIMEOUT_MS > BLOCKING_ASK_CEILING_MS
