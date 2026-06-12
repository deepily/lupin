"""
Task-store mirror — C8 write-side failure spool.

Design §5 (write-side loss steer): "a hook write that times out against a
saturated :7999 must not silently drop (that IS dual-write drift reborn):
short hook timeout + on-disk spool + replay, reusing the existing notify
spool pattern." This is the hook-cadence analog of the cosa-voice durable
notify outbox (`lupin-app.ini` § notify outbox): instead of a background
flusher daemon (too heavy for a hook), the spool is drained OPPORTUNISTICALLY
at the start of the next mirror invocation.

Artifact: per-session JSONL `.task-store-spool-<session_id>.jsonl`,
co-located with the map/hold/acked artifacts (same base-dir resolver).
One spooled operation per line:

    { "op": "create"|"transition"|"correlate", "ts": <epoch float>,
      "harness_id": str, ...op-specific payload fields }

Appends are single-line writes; the drain rewrites the file atomically
(tmp + rename) with the surviving entries. Reads are degrade-safe (a
malformed line is dropped — counted by the caller via the returned shape).

Design authority: lupin ->
    src/rnd/v0.1.8/2026.06.12-task-store-phase2-write-paths/01-build-plan.md §3.
"""

import json
import os
import uuid

from lupin_cli.claude_code.hooks.lib.heartbeat_hold import _resolve_base_dir

SPOOL_FILENAME_TEMPLATE = ".task-store-spool-{session_id}.jsonl"


def spool_path( session_id, base_dir=None ):
    """
    Compute the per-session spool file path.

    Requires:
        - session_id is a string (may be empty)
        - base_dir is a path-like / string / None

    Ensures:
        - Returns Path = <base_dir>/.task-store-spool-<session_id>.jsonl
        - Empty session_id collapses to the literal suffix "unknown"
    """
    suffix = session_id if session_id else "unknown"
    return _resolve_base_dir( base_dir ) / SPOOL_FILENAME_TEMPLATE.format( session_id=suffix )


def append_entry( session_id, entry, base_dir=None ):
    """
    Append one spooled operation (single JSONL line).

    Requires:
        - session_id is a string
        - entry is a JSON-serializable dict carrying at least "op" and "ts"

    Ensures:
        - entry serialized compactly onto ONE line, appended
        - Raises OSError on unwritable directory (caller's never-raise belt)
    """
    with open( spool_path( session_id, base_dir ), "a" ) as f:
        f.write( json.dumps( entry ) + "\n" )


def read_entries( session_id, base_dir=None ):
    """
    Read the spooled operations, FIFO order.

    Requires:
        - session_id is a string

    Ensures:
        - Returns list[dict] in file (append) order
        - Missing file → []; malformed/non-dict lines silently dropped
        - DEGRADE-SAFE: never raises
    """
    try:
        with open( spool_path( session_id, base_dir ) ) as f:
            lines = f.readlines()
    except Exception:
        return [ ]

    entries = [ ]
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads( line )
        except json.JSONDecodeError:
            continue
        if isinstance( obj, dict ):
            entries.append( obj )
    return entries


def rewrite_entries( session_id, entries, base_dir=None ):
    """
    Atomically replace the spool contents with `entries` (post-drain state).

    Requires:
        - session_id is a string
        - entries is a list of JSON-serializable dicts

    Ensures:
        - Empty entries → spool file REMOVED (a drained spool leaves no
          artifact; missing-on-empty also makes "is anything spooled?" a
          cheap existence check)
        - Non-empty → atomic tmp-write + rename, FIFO order preserved
        - Raises OSError on unwritable directory (caller's belt)
    """
    path = spool_path( session_id, base_dir )
    if not entries:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return

    tmp = path.parent / f"{path.name}.{os.getpid()}-{uuid.uuid4().hex}.tmp"
    with open( tmp, "w" ) as f:
        for entry in entries:
            f.write( json.dumps( entry ) + "\n" )
    tmp.replace( path )


def partition_expired( entries, now_epoch, ttl_seconds ):
    """
    Split entries into ( live, expired ) by the C8 TTL.

    PURE — no I/O. An entry with a missing/non-numeric "ts" counts as
    EXPIRED (untrustworthy age ⇒ drop, never replay blind — bool excluded
    explicitly since bool is an int subclass).

    Requires:
        - entries is a list of dicts
        - now_epoch / ttl_seconds are numbers

    Ensures:
        - Returns ( live, expired ) preserving relative order in each
        - live  = entries with numeric ts and ( now_epoch - ts ) <= ttl_seconds
        - expired = everything else
    """
    live, expired = [ ], [ ]
    for entry in entries:
        ts = entry.get( "ts" )
        if isinstance( ts, ( int, float ) ) and not isinstance( ts, bool ) and ( now_epoch - ts ) <= ttl_seconds:
            live.append( entry )
        else:
            expired.append( entry )
    return live, expired
