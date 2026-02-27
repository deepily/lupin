#!/usr/bin/env python3
"""
Notification hook: logs CC system notifications and sends TTS relay.

Phase 0 test hook — validates Notification payload structure, logs the
full payload for empirical analysis, and sends hello-world TTS.

Notification hooks are observation-only (output is ignored by CC).

Install in .claude/settings.local.json:
    "hooks": {
        "Notification": [{
            "type": "command",
            "command": "python3 src/lupin_cli/claude_code/hooks/test_notification.py"
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

    # Extract notification details for TTS
    notification_type = payload.get( "type", payload.get( "notification_type", "unknown" ) )
    message           = payload.get( "message", "" )
    title             = payload.get( "title", "" )

    # Log full payload for empirical analysis
    log_payload( "notification", payload )

    # Send TTS notification (respects HOOK_TTS_ENABLED)
    tts_msg = f"Hook fired: Notification — type {notification_type}"
    if title:
        tts_msg += f", title: {title}"
    send_tts( tts_msg )

    # Observation-only — output is ignored by CC
    emit_json( {} )


if __name__ == "__main__":
    main()
