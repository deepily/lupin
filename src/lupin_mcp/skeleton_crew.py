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
import os
import sys

from typing import Any, Callable, Optional

from lupin_mcp import fleet_cap_ini_io, fleet_size_cap


SKELETON_CREW_KEY = "cc session skeleton crew enabled"
INI_OVERRIDE_ENV  = "LUPIN_SKELETON_CREW_INI"
LOG_TAG           = "[SKELETON-CREW-GATE]"

_DOORS = {
    "spawn"  : "spawning",
    "launch" : "launching",
}


def ini_path() -> str:
    """
    The configuration file the switch is read from.

    Ensures:
        - returns the env override when it is set, so tests never touch the live file
        - otherwise returns the same file the fleet cap lives in
    """
    override = os.environ.get( INI_OVERRIDE_ENV )
    if override:
        return override
    return fleet_size_cap.config_file_path()


def _say( detail: str ) -> None:
    """Print one tagged line to stderr and never fail because printing did."""
    try:
        print( f"{LOG_TAG} {detail}", file=sys.stderr, flush=True )
    except Exception:  # pragma: no cover - a closed stderr must not stop a spawn gate
        pass


def read_state_from_disk( path: Optional[ str ] = None ) -> Optional[ bool ]:
    """
    Read the switch fresh from the configuration file.

    Requires:
        - path is a file path, or None for the default file

    Ensures:
        - returns True or False for a clean boolean
        - returns True for a value that is present but is not a clean boolean
        - returns None when the key is absent, defined twice, or the file cannot be read
        - prints one tagged line to stderr for every answer that is not a clean boolean
        - never raises
    """
    target = path if path is not None else ini_path()
    raw    = fleet_cap_ini_io.read_value_from_disk( target, SKELETON_CREW_KEY )
    if raw is None:
        _say( f"could not read `{SKELETON_CREW_KEY}` from {target} (absent, defined twice or "
              f"unreadable); the switch reads as OFF." )
        return None
    lowered = raw.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
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
