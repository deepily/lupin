#!/usr/bin/env python3
"""
Stop hook: logs stop event and sends TTS notification.

Phase 0 test hook — validates Stop payload structure, logs the full
payload for empirical analysis (especially stop_hook_active field),
and sends hello-world TTS.

Phase 0 always emits {} (allow stop) to prevent infinite loops.

Install in .claude/settings.local.json:
    "hooks": {
        "Stop": [{
            "type": "command",
            "command": "python3 src/lupin_cli/claude_code/hooks/test_stop.py"
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

    # Extract stop_hook_active for empirical validation
    stop_hook_active = payload.get( "stop_hook_active", "NOT_PRESENT" )

    # Log full payload for empirical analysis
    log_payload( "stop", payload )

    # Send TTS notification (respects HOOK_TTS_ENABLED)
    send_tts( f"Hook fired: Stop — stop_hook_active={stop_hook_active}" )

    # Phase 0: Always allow stop (emit empty = passthrough)
    # Production Phase 4 will drain voice queue and potentially block
    emit_json( {} )


if __name__ == "__main__":
    main()
