#!/usr/bin/env python3
"""
The skeleton crew switch: one boolean that decides whether managers may spawn seats.

When the switch is on, managers plan and implement their own work and no spawn is allowed.
When it is off, managers spawn the seats they need inside the fleet cap.

The state lives in the main configuration file, next to the fleet cap, under the key
`cc session skeleton crew enabled`. Every reader takes the value from the file at call time.
The configuration manager is a process-lifetime singleton, so it would keep a stale value in
a long-running process.

How an unclear state reads, by the operator's ruling:

    - The key is absent, the file cannot be read, or the key is defined twice: off.
    - The key is present but is not true or false: on.

Both cases print a line tagged `[SKELETON-CREW-GATE]` to stderr, so a gate that did not
answer cleanly says so.

This module only reads. The route that writes the key, and the copy made before each write,
live with the other writer of that file.
"""
import datetime
import json
import os
import sys

from typing import Any, Callable, Dict, Optional

from lupin_mcp import config_write_lock, fleet_cap_ini_io, fleet_size_cap


SKELETON_CREW_KEY = "cc session skeleton crew enabled"
INI_OVERRIDE_ENV  = "LUPIN_SKELETON_CREW_INI"
LOG_TAG           = "[SKELETON-CREW-GATE]"
SETTINGS_ENV      = "STOP_POKE_SETTINGS"
STATE_FILENAME    = "skeleton-crew-state.json"
UNKNOWN_SETTER    = "unknown (file edited)"

_DOORS = {
    "spawn"  : "spawning",
    "launch" : "launching",
}


def ini_path() -> str:
    """
    The configuration file the switch is read from.

    Ensures:
        - returns the env override when it is set, so tests never touch the live file
        - otherwise returns the configuration file of the main checkout. A seat in a
          worktree reads the main checkout's file and not its own tracked copy
    """
    override = os.environ.get( INI_OVERRIDE_ENV )
    if override:
        return override
    import cosa.utils.util as cu
    from lupin_cli.claude_code.hooks.lib.heartbeat_hold import _main_repo_path
    main = _main_repo_path( cu.get_project_root() )
    return os.path.join( str( main ), "src", "conf", "lupin-app.ini" )


def _say( detail: str ) -> None:
    """Print one tagged line to stderr and never fail because printing did."""
    try:
        print( f"{LOG_TAG} {detail}", file=sys.stderr, flush=True )
    except Exception:  # pragma: no cover - a closed stderr must not stop a spawn gate
        pass


def read_state_from_disk( path: Optional[ str ] = None, quiet: bool = False ) -> Optional[ bool ]:
    """
    Read the switch fresh from the configuration file.

    Requires:
        - path is a file path, or None for the default file

    Ensures:
        - returns True or False for a clean boolean
        - returns True for a value that is present but is not a clean boolean
        - returns None when the key is absent, defined twice, or the file cannot be read
        - prints one tagged line to stderr for every answer that is not a clean boolean,
          unless quiet is true. The Stop hook asks quietly
        - never raises
    """
    target = path if path is not None else ini_path()
    raw    = fleet_cap_ini_io.read_value_from_disk( target, SKELETON_CREW_KEY )
    if raw is None:
        if not quiet:
            _say( f"could not read `{SKELETON_CREW_KEY}` from {target} (absent, defined twice or "
                  f"unreadable); the switch reads as OFF." )
        return None
    lowered = raw.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if not quiet:
        _say( f"`{SKELETON_CREW_KEY}` holds {raw!r}, which is not true or false; the switch reads as ON." )
    return True


def default_disk_skeleton_reader() -> Optional[ bool ]:
    """
    The reader the live gates pass as their disk function.

    Ensures:
        - returns what `read_state_from_disk` returns for the default file
        - returns None on any unexpected failure
        - never raises
    """
    try:
        return read_state_from_disk()
    except Exception:  # pragma: no cover - read_state_from_disk already never raises
        return None


def refusal_text( door: str ) -> str:
    """
    The words a refused spawn or launch carries.

    Requires:
        - door is "spawn" or "launch"

    Ensures:
        - names the state and the rule
        - tells the reader nothing about how to change the state

    Raises:
        - ValueError for any other door
    """
    if door not in _DOORS:
        raise ValueError( f"unknown door {door!r}; expected one of {sorted( _DOORS )}" )
    return (
        f"SKELETON CREW IS ON — no {_DOORS[ door ]}. "
        f"Each manager plans and implements its own work. "
        f"Nothing was started and nothing was terminated."
    )


def skeleton_crew_is_on( config_mgr: Any = None, disk_fn: Optional[ Callable[ [], Optional[ bool ] ] ] = None ) -> bool:
    """
    Whether the switch is on, taking the disk value first and the manager second.

    Requires:
        - config_mgr is a configuration manager or None
        - disk_fn returns True, False or None, or is None

    Ensures:
        - a disk answer of True or False wins
        - when the disk gives no answer, the manager's value is used, defaulting to off
        - returns False when neither source answers
        - never raises
    """
    if disk_fn is not None:
        try:
            from_disk = disk_fn()
        except Exception:
            from_disk = None
        if from_disk is not None:
            return bool( from_disk )
    if config_mgr is None:
        return False
    try:
        value = config_mgr.get( SKELETON_CREW_KEY, default=False, return_type="boolean", silent=True )
    except Exception:
        return False
    return bool( value )


def skeleton_crew_refusal(
    config_mgr : Any = None,
    disk_fn    : Optional[ Callable[ [], Optional[ bool ] ] ] = None,
    door       : str = "spawn"
) -> Optional[ str ]:
    """
    The refusal for a spawn or launch, or None when the switch is off.

    Requires:
        - the arguments `skeleton_crew_is_on` takes
        - door is "spawn" or "launch"

    Ensures:
        - returns the refusal text when the switch is on
        - returns None when it is off
        - never reaps and never starts anything
    """
    if not skeleton_crew_is_on( config_mgr, disk_fn=disk_fn ):
        return None
    return refusal_text( door )


def state_path() -> str:
    """
    The small file that records who flipped the switch and when.

    Ensures:
        - sits beside the override file when the configuration file is overridden, so a server
          that flips a copy never rewrites the real record
        - otherwise lives in the same folder as the write lock, outside the source tree
        - holds attribution only. The switch itself is the key in the configuration file
    """
    override = os.environ.get( INI_OVERRIDE_ENV )
    if override:
        return f"{override}.state.json"
    return os.path.join( config_write_lock.lock_dir(), STATE_FILENAME )


def write_state_file( on: bool, set_by: str, now: Optional[ datetime.datetime ] = None ) -> None:
    """
    Record who flipped the switch and when.

    Requires:
        - on is the value about to be written to the configuration file
        - set_by is the administrator's email or user id

    Ensures:
        - the file is replaced atomically
        - written before the configuration file, so a failed second write leaves a record
          that disagrees with the file and reads as an unknown setter

    Raises:
        - OSError when the folder or the file cannot be written
    """
    moment = now if now is not None else datetime.datetime.now( datetime.timezone.utc )
    record = { "on": bool( on ), "since": moment.astimezone().isoformat(), "set_by": set_by }
    path   = state_path()
    os.makedirs( os.path.dirname( path ), exist_ok=True )
    partial = path + ".partial"
    with open( partial, "w", encoding="utf-8" ) as handle:
        json.dump( record, handle )
        handle.flush()
        os.fsync( handle.fileno() )
    os.replace( partial, path )


def read_state_file() -> Optional[ Dict[ str, Any ] ]:
    """
    The attribution record, or None when it is missing or unreadable.

    Ensures:
        - never raises
    """
    try:
        with open( state_path(), "r", encoding="utf-8" ) as handle:
            record = json.load( handle )
    except ( OSError, ValueError ):
        return None
    return record if isinstance( record, dict ) else None


def settings_json_poke_muted() -> Optional[ bool ]:
    """
    Whether the Stop poke is muted in the user's settings file.

    Ensures:
        - returns True when `heartbeat.poke_output_enabled` is false
        - returns False when the file is readable and the poke is not muted there
        - returns None when the file is missing or is not valid JSON, which is the case in
          a container that does not see the host's settings
        - never raises
    """
    path = os.environ.get( SETTINGS_ENV ) or os.path.expanduser( "~/.claude/settings.json" )
    try:
        with open( path, "r", encoding="utf-8" ) as handle:
            settings = json.load( handle )
    except ( OSError, ValueError ):
        return None
    block = settings.get( "heartbeat" ) if isinstance( settings, dict ) else None
    if not isinstance( block, dict ):
        return False
    return block.get( "poke_output_enabled", True ) is False


def describe() -> Dict[ str, Any ]:
    """
    The switch state as clients and session info report it.

    Ensures:
        - returns on, since, set_by and settings_mute_while_off
        - `on` comes from the configuration file, read fresh. An unreadable file is off
        - since and set_by come from the attribution record only while it agrees with the file
        - set_by is the unknown-setter text when the record disagrees with the file
        - settings_mute_while_off is None when the settings file cannot be read, and
          otherwise true only when the poke is muted there while the switch is off
        - never raises
    """
    on     = bool( read_state_from_disk() )
    record = read_state_file()
    since  = None
    set_by = None
    if record is not None:
        if record.get( "on" ) is on:
            since  = record.get( "since" )
            set_by = record.get( "set_by" )
        else:
            set_by = UNKNOWN_SETTER
    muted = settings_json_poke_muted()
    return {
        "on"                      : on,
        "since"                   : since,
        "set_by"                  : set_by,
        "settings_mute_while_off" : None if muted is None else bool( muted and not on ),
    }


def is_on_quietly() -> bool:
    """
    Whether the switch is on, asked without printing anything.

    Ensures:
        - True for true, and for a present value that is not a clean boolean
        - False for false, an absent key, an unreadable file or any failure
        - never raises and never prints
    """
    try:
        return bool( read_state_from_disk( quiet=True ) )
    except Exception:  # pragma: no cover - read_state_from_disk already never raises
        return False
