"""
Per-project cooldown for the "COSA-VOICE MCP VALIDATION FAILED" notification.

THE DEFECT: `cosa_voice_mcp._send_validation_error` fires an urgent notification every time an
MCP server process starts with a project that has no working account. That is every Claude Code
session start and every reconnect, for a condition (a missing account, a cwd with no git
ancestor) that repetition cannot help. The operator gets an alarm per session.

THE MCP SERVER IS A FRESH STDIO SUBPROCESS PER SESSION, so an in-memory flag dedupes nothing.
The cooldown lives in `~/.lupin/mcp-validation-alerts.json`, beside the credentials it concerns:
`{ "<project>": <epoch seconds of the last alert that was DELIVERED> }`.

Rules (Mr. Radio, 2026-09-30):
  - one alert per project name per 6 hours; the first one stays urgent
  - the file is written atomically (temp file in the same directory + os.replace), so parallel
    starts can never leave half a JSON document behind
  - FAILS OPEN: a missing, corrupt, unreadable or unwritable file means "send", never "stay silent"
  - a send is recorded only AFTER it was delivered, so an alert that could not reach the operator
    (the server was down) does not buy six hours of silence

Two starts racing before either has written can both send once. That is accepted: the cost is one
extra alert, and closing it would need a lock whose own failure mode is silence.
"""
import json
import os
import tempfile
import time
from pathlib import Path

COOLDOWN_SECONDS = 6 * 60 * 60
STATE_PATH       = Path.home() / ".lupin" / "mcp-validation-alerts.json"


def _load( path ):
    """
    Requires: path is a Path
    Ensures:  returns the state dict, or {} for a missing / unreadable / corrupt / non-dict file
    """
    try:
        state = json.loads( path.read_text( encoding="utf-8" ) )
    except ( OSError, ValueError ):
        return {}
    return state if isinstance( state, dict ) else {}


def is_suppressed( project, now=None, path=None, cooldown=None ):
    """
    Requires: project is a non-empty string
    Ensures:
        - True only when this project has a recorded delivery less than `cooldown` seconds old
        - False (send) for an unknown project, a missing/corrupt file, a non-numeric entry, or a
          timestamp in the future (a clock that went backwards must not silence the alert)
    """
    now      = time.time() if now is None else now
    cooldown = COOLDOWN_SECONDS if cooldown is None else cooldown
    last     = _load( STATE_PATH if path is None else path ).get( project )
    if isinstance( last, bool ) or not isinstance( last, ( int, float ) ):
        return False
    return 0 <= now - last < cooldown


def record_sent( project, now=None, path=None ):
    """
    Requires: project is a non-empty string
    Ensures:
        - writes `now` as the project's last delivered alert, keeping other projects' entries
        - atomic: temp file in the same directory, then os.replace
        - never raises: returns True when written, False when the state could not be written
    """
    now    = time.time() if now is None else now
    target = STATE_PATH if path is None else path
    state  = _load( target )
    state[ project ] = now
    tmp_name = None
    try:
        target.parent.mkdir( parents=True, exist_ok=True )
        with tempfile.NamedTemporaryFile( "w", encoding="utf-8", dir=target.parent,
                                          prefix=target.name + ".", suffix=".tmp", delete=False ) as tmp:
            tmp_name = tmp.name
            json.dump( state, tmp )
        os.replace( tmp_name, target )
        return True
    except OSError:
        if tmp_name is not None:
            try: os.unlink( tmp_name )
            except OSError: pass
        return False
