#!/usr/bin/env python3
"""
PostToolUse hook: smart TTS announcements + voice buffer drain.

Fires after every tool call. Applies smart filtering:
- Silent (no TTS): Read, Grep, Glob, TaskCreate, TaskUpdate, TaskGet, TaskList
- Announce (with detail): Bash, Write, Edit
- Default (name only): MCP/unknown tools

After TTS, drains the voice buffer and acknowledges any buffered messages.

Install in ~/.claude/settings.json:
    "hooks": {
        "PostToolUse": [{
            "type": "command",
            "command": "python3 \"$LUPIN_ROOT/src/lupin_cli/claude_code/hooks/post_tool_use.py\""
        }]
    }
"""
import os
import sys

# Bootstrap: ensure src/ is on PYTHONPATH for lupin_cli imports
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib.hook_common import (
    read_hook_input, log_payload, emit_json, send_tts, build_progress_group_id,
    format_tool_summary, drain_and_acknowledge, format_voice_context,
    build_additional_context, is_mcp_voice_tool,
    TOOLS_SILENT, TOOLS_ANNOUNCE
)
from lupin_cli.claude_code.hooks.lib.session_bridge import get_claude_session_id


def main():

    payload = read_hook_input()
    if not payload:
        emit_json( {} )
        sys.exit( 0 )

    # Extract tool information
    tool_name  = payload.get( "tool_name", "unknown" )
    tool_input = payload.get( "tool_input", {} )

    # Log full payload for empirical analysis
    log_payload( "post_tool_use", payload )

    # MCP voice bypass — Claude is already talking to user
    if is_mcp_voice_tool( tool_name ):
        emit_json( {} )
        sys.exit( 0 )

    # Resolve session_id: payload first (future-proof), then session bridge fallback
    session_id = payload.get( "session_id", "" ) or get_claude_session_id()
    pg_id      = build_progress_group_id( "pu", session_id )

    # Smart TTS filtering (respects HOOK_TTS_ENABLED)
    if tool_name in TOOLS_SILENT:
        pass  # No TTS for high-frequency read-only tools
    elif tool_name in TOOLS_ANNOUNCE:
        send_tts( f"Done: {format_tool_summary( tool_name, tool_input )}", progress_group_id=pg_id )
    else:
        send_tts( f"Done: {tool_name}", progress_group_id=pg_id )

    # Drain voice buffer, acknowledge, and inject as additionalContext
    messages  = drain_and_acknowledge( session_id )
    voice_ctx = format_voice_context( messages )
    emit_json( build_additional_context( voice_ctx ) )
    # build_additional_context returns {} when voice_ctx is empty → passthrough


if __name__ == "__main__":
    main()
