#!/usr/bin/env python3
"""
PreToolUse hook: logs pending tool call and sends TTS notification.

Phase 0 test hook — validates PreToolUse payload structure, logs the
full payload for empirical analysis, and sends hello-world TTS.

This hook fires BEFORE every tool call. Phase 0 emits {} (passthrough)
to allow all tool calls without interference.

Install in .claude/settings.local.json:
    "hooks": {
        "PreToolUse": [{
            "type": "command",
            "command": "python3 src/lupin_cli/claude_code/hooks/test_pre_tool_use.py"
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
    read_hook_input, log_payload, emit_json, send_tts
)


def main():

    payload = read_hook_input()
    if not payload:
        emit_json( {} )
        sys.exit( 0 )

    # Extract tool information for TTS
    tool_name = payload.get( "tool_name", "unknown" )

    # Log full payload for empirical analysis
    log_payload( "pre_tool_use", payload )

    # Send TTS notification (respects HOOK_TTS_ENABLED)
    send_tts( f"Hook fired: PreToolUse — tool {tool_name}" )

    # Passthrough — no permission decision yet (Phase 0)
    emit_json( {} )


if __name__ == "__main__":
    main()
