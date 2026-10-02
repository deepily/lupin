"""
The fleet-wide on/off switch for the heartbeat Stop poke (row 3526fb95).

One boolean in one small file. The server writes it (PUT /api/heartbeat/poke-mute, admin
role only) and the Stop hook reads it on every stop, so a flip takes effect on the next
stop with no restart and with no server needed at stop time.

The file lives in the flow-ratio settings folder because both rest containers already
bind-mount that host folder (docker-compose.yml, LUPIN_FLOW_RATIO_DIR): the server and
the host hook see the same file with no new mount and no container recreate.

    in a container   $LUPIN_FLOW_RATIO_DIR/heartbeat-poke-mute.json
    on the host      <fleet_data_root()>/flow-ratio/heartbeat-poke-mute.json

Fail direction: a missing, unreadable or malformed file means NOT muted. A broken file
must never silence the fleet.

No timer touches it (Rick's ruling): it stays as set until an admin flips it back.

The admin-only rule is enforced at the endpoint. The file itself is plain: every seat on
the box runs as the same OS user and could write it directly, the same as the settings
file this replaces as the everyday switch.
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Optional

from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root


MUTE_FILENAME    = "heartbeat-poke-mute.json"
AUDIT_FILENAME   = "heartbeat-poke-mute.log"
MUTE_SUBDIR      = "flow-ratio"
MUTE_FILE_ENV    = "LUPIN_HEARTBEAT_POKE_MUTE_FILE"
SETTINGS_DIR_ENV = "LUPIN_FLOW_RATIO_DIR"


def poke_mute_path() -> str:
    """
    Where the mute file lives for this process.

    Ensures:
        - returns $LUPIN_HEARTBEAT_POKE_MUTE_FILE when set (tests point it at a tmp file)
        - else $LUPIN_FLOW_RATIO_DIR/heartbeat-poke-mute.json when that is set (containers)
        - else <fleet_data_root()>/flow-ratio/heartbeat-poke-mute.json (the host)
    """
    explicit = os.environ.get( MUTE_FILE_ENV )
    if explicit:
        return explicit
    settings_dir = os.environ.get( SETTINGS_DIR_ENV )
    if settings_dir:
        return os.path.join( settings_dir, MUTE_FILENAME )
    return os.path.join( str( fleet_data_root() ), MUTE_SUBDIR, MUTE_FILENAME )


def _unmuted() -> dict:
    """The state reported when no usable file says otherwise."""
    return { "muted": False, "set_by": None, "set_at": None }


def read_poke_mute( path: Optional[ str ] = None ) -> dict:
    """
    Read the switch.

    Requires:
        - path is None (→ poke_mute_path()) or the file to read

    Ensures:
        - returns { "muted": bool, "set_by": str | None, "set_at": str | None }
        - muted is True only when the file is a JSON object whose "muted" is exactly true
        - a missing file, an unreadable file, bad JSON, a non-object, or a "muted" that is
          not a boolean all read as not muted, with set_by and set_at None
        - never raises
    """
    path = path if path is not None else poke_mute_path()
    try:
        with open( path ) as f:
            raw = json.load( f )
    except ( OSError, ValueError ):
        return _unmuted()
    if not isinstance( raw, dict ) or not isinstance( raw.get( "muted" ), bool ):
        return _unmuted()
    return { "muted": raw[ "muted" ], "set_by": raw.get( "set_by" ), "set_at": raw.get( "set_at" ) }


def write_poke_mute( muted: bool, set_by: str, path: Optional[ str ] = None,
                     now: Optional[ datetime ] = None ) -> dict:
    """
    Set the switch and record who did it.

    Requires:
        - muted is a bool
        - set_by names the admin who flipped it
        - path is None (→ poke_mute_path()) or the file to write

    Ensures:
        - the file is replaced atomically (temp file in the same folder, then rename), so
          a reader never sees a half-written file
        - one JSON line { ts, set_by, old, new } is appended to heartbeat-poke-mute.log
          beside it
        - returns the state as read_poke_mute reports it after the write

    Raises:
        - TypeError when muted is not a bool
        - OSError when the folder cannot be written
    """
    if not isinstance( muted, bool ):
        raise TypeError( f"muted must be a bool, got {type( muted ).__name__}: {muted!r}" )
    path   = path if path is not None else poke_mute_path()
    stamp  = ( now if now is not None else datetime.now( timezone.utc ) ).isoformat()
    folder = os.path.dirname( path )
    old    = read_poke_mute( path )[ "muted" ]
    state  = { "muted": muted, "set_by": set_by, "set_at": stamp }

    os.makedirs( folder, exist_ok=True )
    fd, tmp = tempfile.mkstemp( dir=folder, prefix=".heartbeat-poke-mute-", suffix=".tmp" )
    with os.fdopen( fd, "w" ) as f:
        json.dump( state, f )
    os.chmod( tmp, 0o644 )
    os.replace( tmp, path )

    with open( os.path.join( folder, AUDIT_FILENAME ), "a" ) as log:
        log.write( json.dumps( { "ts": stamp, "set_by": set_by, "old": old, "new": muted } ) + "\n" )
    return read_poke_mute( path )


def mute_message( state: dict ) -> str:
    """
    The one line a seat sees in place of the poke while the switch is on.

    Requires:
        - state is read_poke_mute's dict with muted True

    Ensures:
        - names who muted it and when, so the line can never go stale the way a
          hand-typed message does
    """
    return f"Stop poke muted by {state[ 'set_by' ] or 'an admin'} at {state[ 'set_at' ] or 'an unrecorded time'}."
