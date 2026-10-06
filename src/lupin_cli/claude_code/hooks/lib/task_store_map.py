"""
Task-store mirror per-session correlation map artifact.

The hook-side memory of which store item each harness task corresponds to, and
what status was last mirrored. One JSON file per session,
`.task-store-map-<session_id>.json`, sits beside the heartbeat hold and acked
artifacts via the same base-dir resolver. That gives one source of truth for
the directory, a gitignored runtime-state family, and multi-writer safety.

Schema, generation-keyed. The three top-level keys are:

    "tasks": maps "<generation>:<harness_id>" to { "item_id": "<uuid>",
        "last_status": "<harness status>" }.
    "flagged_at": an iso timestamp or null, the flag-once marker that records
        a flagged write failure.
    "generation": an int, bumped on each /clear counter reset.

Why the generation key: harness task ids are per-session ordinal counters
("1","2","3"...) that restart after a `/clear`. A counter-keyed map persists
across /clear because the session id is stable. A post-clear TaskUpdate
taskId="1" would then resolve to the pre-clear item and mutate the wrong store row.
Every entry is keyed by `<generation>:<counter>`, and the generation is bumped
the moment a counter is re-seen within the live generation. Post-clear tasks
then get a distinct slot, so the old row is never adopted or mutated. The
correlation key (task_store_mirror.build_correlation_key) carries the same
generation, so the server-side idempotency probe is re-keyed in lockstep.

Legacy map reset (no-migration doctrine for local ephemeral stores): a map file
written by the earlier code has no `generation` field and counter-only task
keys. Such a map is reset on read: its colliding task entries are dropped,
generation starts at 0, and flagged_at is preserved. Old keys are not migrated,
because dropping and recreating beats migrating for local stores.

Reads are degrade-safe: any error gives an empty map, never raises, and never
breaks the hook. Writes are atomic (tmp-write + rename) with a per-writer
pid+uuid tmp suffix, mirroring heartbeat_acked_ledger.

Design authority: lupin ->
    src/rnd/v0.1.8/2026.06.12-task-store-phase2-write-paths/01-build-plan.md section 1.3
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


def map_key( generation, harness_id ):
    """
    Compose the generation-scoped correlation-map key for one harness task.

    Requires:
        - generation is an int; harness_id is a string (or stringifiable)

    Ensures:
        - Returns "<generation>:<harness_id>" — the same key shape used by both
          record_task (write) and lookup_task (read), so a counter that
          restarts after /clear in a new generation never aliases the old slot
    """
    return f"{generation}:{harness_id}"


def read_map( session_id, base_dir=None ):
    """
    Read this session's correlation map (generation-keyed schema).

    Requires:
        - session_id is a string
        - base_dir is a path-like / string / None

    Ensures:
        - Returns { "tasks": dict, "flagged_at": str|None, "generation": int }
          — normalized shape even when the file is missing, unreadable, or
          malformed (degrade-safe: never raises; any error gives an empty map)
        - Legacy reset: a present map lacking a valid non-negative int
          `generation` (the earlier format) drops its counter-only task
          entries, resets generation to 0, and preserves flagged_at
        - Only dict-valued task entries are kept
    """
    empty = { "tasks": { }, "flagged_at": None, "generation": 0 }
    try:
        with open( map_path( session_id, base_dir ) ) as f:
            raw = json.load( f )
    except Exception:
        return empty
    if not isinstance( raw, dict ):
        return empty

    flagged    = raw.get( "flagged_at" )
    flagged    = flagged if isinstance( flagged, str ) else None
    generation = raw.get( "generation" )

    # LEGACY-MAP RESET: no valid generation => pre-fix counter-only map. Drop the
    # colliding task entries (no-migration doctrine), start at generation 0,
    # keep the I4 flag so an in-flight outage is not silently un-flagged.
    if not isinstance( generation, int ) or isinstance( generation, bool ) or generation < 0:
        return { "tasks": { }, "flagged_at": flagged, "generation": 0 }

    tasks = raw.get( "tasks" )
    if not isinstance( tasks, dict ):
        tasks = { }
    tasks = { k: v for k, v in tasks.items() if isinstance( v, dict ) }
    return { "tasks": tasks, "flagged_at": flagged, "generation": generation }


def write_map( session_id, map_data, base_dir=None ):
    """
    Atomically write this session's correlation map.

    Requires:
        - session_id is a string
        - map_data is the { "tasks": ..., "flagged_at": ..., "generation": ... } dict
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


def current_generation( session_id, base_dir=None ):
    """
    Read this session's live generation counter.

    Requires:
        - session_id is a string

    Ensures:
        - Returns the int generation (0 for a fresh / missing / legacy map)
        - Degrade-safe: never raises (read_map's belt)
    """
    return read_map( session_id, base_dir )[ "generation" ]


def bump_generation( session_id, base_dir=None ):
    """
    Advance the generation by one (read-modify-write) and return the new value.

    Called when a TaskCreate arrives for a harness counter already live in the
    current generation. That is unambiguous proof that the harness counter has
    restarted (post-/clear), so later tasks must occupy a fresh generation.

    Requires:
        - session_id is a string

    Ensures:
        - map["generation"] incremented by 1; tasks + flagged_at preserved
        - Returns the new generation int
        - Raises OSError on unwritable directory (caller's belt)
    """
    data = read_map( session_id, base_dir )
    data[ "generation" ] = data[ "generation" ] + 1
    write_map( session_id, data, base_dir )
    return data[ "generation" ]


def record_task( session_id, generation, harness_id, item_id, last_status, base_dir=None ):
    """
    Upsert one harness-task entry under its generation-scoped key (RMW).

    Requires:
        - session_id / harness_id / item_id / last_status are strings
        - generation is an int

    Ensures:
        - map["tasks"]["<generation>:<harness_id>"] ==
          { "item_id": item_id, "last_status": last_status }
        - other entries + flagged_at + generation preserved
        - Returns the updated map dict
        - Raises OSError on unwritable directory (caller's belt)
    """
    data = read_map( session_id, base_dir )
    data[ "tasks" ][ map_key( generation, harness_id ) ] = { "item_id": item_id, "last_status": last_status }
    write_map( session_id, data, base_dir )
    return data


def lookup_task( session_id, generation, harness_id, base_dir=None ):
    """
    Resolve one harness-task entry by its generation-scoped key.

    Requires:
        - session_id / harness_id are strings; generation is an int

    Ensures:
        - Returns the { "item_id": ..., "last_status": ... } dict, or None when
          no entry exists for this (generation, harness_id)
        - Degrade-safe: never raises (read_map's belt)
    """
    return read_map( session_id, base_dir )[ "tasks" ].get( map_key( generation, harness_id ) )


def set_flagged( session_id, flagged_at, base_dir=None ):
    """
    Set or clear the flag-once marker.

    Requires:
        - session_id is a string
        - flagged_at is an ISO timestamp string (set) or None (clear)

    Ensures:
        - map["flagged_at"] == flagged_at; task entries + generation preserved
        - Returns the updated map dict
        - Raises OSError on unwritable directory (caller's belt)
    """
    data = read_map( session_id, base_dir )
    data[ "flagged_at" ] = flagged_at
    write_map( session_id, data, base_dir )
    return data
