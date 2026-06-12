"""
Task-store mirror — per-session correlation map artifact.

The hook-side memory of "which store item does harness task N correspond to,
and what status did we last mirror?". One JSON file per session,
`.task-store-map-<session_id>.json`, co-located with the heartbeat hold/acked
artifacts via the SAME base-dir resolver (single source of truth for the
directory; gitignored runtime-state family; per-session ⇒ multi-writer safe).

Schema:
    {
      "tasks"      : { "<harness_id>": { "item_id": "<uuid>", "last_status": "<harness status>" } },
      "flagged_at" : "<iso ts>" | null     # I4 flag-once marker (write-failure flagged)
    }

Reads are degrade-safe (any error ⇒ empty map — never raises, never breaks
the hook). Writes are atomic (tmp-write + rename) with a per-writer pid+uuid
tmp suffix, mirroring heartbeat_acked_ledger.

Design authority: lupin ->
    src/rnd/v0.1.8/2026.06.12-task-store-phase2-write-paths/01-build-plan.md §1.3.
"""

import json
import os
import uuid

from lupin_cli.claude_code.hooks.lib.heartbeat_hold import _resolve_base_dir

MAP_FILENAME_TEMPLATE = ".task-store-map-{session_id}.json"


def map_path( session_id, base_dir=None ):
    """
    Compute the per-session map file path.

    Requires:
        - session_id is a string (may be empty)
        - base_dir is a path-like / string / None

    Ensures:
        - Returns Path = <base_dir>/.task-store-map-<session_id>.json
        - Empty session_id collapses to the literal suffix "unknown"
        - base_dir resolved by heartbeat_hold._resolve_base_dir so the map
          co-locates with the other per-session runtime artifacts
    """
    suffix = session_id if session_id else "unknown"
    return _resolve_base_dir( base_dir ) / MAP_FILENAME_TEMPLATE.format( session_id=suffix )


def read_map( session_id, base_dir=None ):
    """
    Read this session's correlation map.

    Requires:
        - session_id is a string
        - base_dir is a path-like / string / None

    Ensures:
        - Returns { "tasks": dict, "flagged_at": str|None } — normalized shape
          even when the file is missing, unreadable, or malformed (DEGRADE-SAFE:
          never raises; any error ⇒ empty map)
        - Only dict-valued task entries are kept
    """
    empty = { "tasks": { }, "flagged_at": None }
    try:
        with open( map_path( session_id, base_dir ) ) as f:
            raw = json.load( f )
        if not isinstance( raw, dict ):
            return empty
        tasks = raw.get( "tasks" )
        if not isinstance( tasks, dict ):
            tasks = { }
        tasks = { k: v for k, v in tasks.items() if isinstance( v, dict ) }
        flagged = raw.get( "flagged_at" )
        return { "tasks": tasks, "flagged_at": flagged if isinstance( flagged, str ) else None }
    except Exception:
        return empty


def write_map( session_id, map_data, base_dir=None ):
    """
    Atomically write this session's correlation map.

    Requires:
        - session_id is a string
        - map_data is the { "tasks": ..., "flagged_at": ... } dict
        - base_dir is a path-like / string / None

    Ensures:
        - Write is atomic (tmp-write + rename), per-writer pid+uuid tmp
          suffix (heartbeat_acked_ledger precedent)
        - Raises OSError if the target directory is not writable (caller —
          the mirror orchestrator — owns the never-raise belt)
    """
    path = map_path( session_id, base_dir )
    tmp  = path.parent / f"{path.name}.{os.getpid()}-{uuid.uuid4().hex}.tmp"
    with open( tmp, "w" ) as f:
        json.dump( map_data, f )
    tmp.replace( path )


def record_task( session_id, harness_id, item_id, last_status, base_dir=None ):
    """
    Upsert one harness-task entry (read-modify-write).

    Requires:
        - session_id / harness_id / item_id / last_status are strings

    Ensures:
        - map["tasks"][harness_id] == { "item_id": item_id, "last_status": last_status }
        - other entries + flagged_at preserved
        - Returns the updated map dict
        - Raises OSError on unwritable directory (caller's belt)
    """
    data = read_map( session_id, base_dir )
    data[ "tasks" ][ str( harness_id ) ] = { "item_id": item_id, "last_status": last_status }
    write_map( session_id, data, base_dir )
    return data


def set_flagged( session_id, flagged_at, base_dir=None ):
    """
    Set or clear the I4 flag-once marker.

    Requires:
        - session_id is a string
        - flagged_at is an ISO timestamp string (set) or None (clear)

    Ensures:
        - map["flagged_at"] == flagged_at; task entries preserved
        - Returns the updated map dict
        - Raises OSError on unwritable directory (caller's belt)
    """
    data = read_map( session_id, base_dir )
    data[ "flagged_at" ] = flagged_at
    write_map( session_id, data, base_dir )
    return data
