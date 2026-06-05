#!/usr/bin/env python3
"""
Heartbeat Arbiter — fleet event glob/tail (Rachel's wiring lane).

The Arbiter consumes the local Hook's exhaust: per-session append-only JSONL
event files under the fleet dir `~/.claude/heartbeat-events/<session>.jsonl`
(canonical design §0.2; arbiter design `03` §3). This module is the
read/sense I/O: glob the dir + tail each session file from a tracked byte
offset, returning only the NEW records since the last poll.

Design choices (arbiter `03` §3 "track a per-file read offset"):
    - **Byte-offset tail** (not full re-read): seek to the last offset, read
      only new bytes → O(new data) per poll, not O(file). Bounded latency as
      event files grow.
    - **Partial-line safe**: a trailing line still being written (no closing
      newline yet) is NOT consumed — the offset advances only to the last
      complete newline, so the partial line is re-read intact next poll.
    - **Rotation/truncation safe**: if a file SHRANK below the tracked offset
      (rotated or recreated), reset to offset 0 and re-read from the top.
    - **Never raises** (the §0 #2 observer invariant): a missing dir, an
      unreadable file, or a malformed line yields empty/partial results, never
      an exception — the Arbiter degrades safe, the Hooks are unaffected.
    - **`:7999`-free**: pure local filesystem reads.

This is the same never-raises discipline as the `transcript_reader` /
`heartbeat_events.read_events` modules.
"""
import glob
import json
import os
from pathlib import Path

from lupin_cli.claude_code.hooks.lib.heartbeat_events import (
    FLEET_EVENTS_DIR, EVENTS_FILENAME_TEMPLATE,
)


def _session_id_from_path( path ):
    """
    Recover the session_id from an events filename.

    Requires:
        - path is a path-like to <session_id>.jsonl

    Ensures:
        - Returns the filename stem (the session_id); ".jsonl" stripped
    """
    return Path( path ).stem


def tail_session_file( path, offset=0 ):
    """
    Read NEW complete JSONL records from one session file since `offset`.

    Requires:
        - path is a path-like to a session events JSONL file
        - offset is a non-negative byte offset (0 = from the start)

    Ensures:
        - Returns ( records, new_offset ):
            records    = list of parsed dict records appended since `offset`,
                         in file order
            new_offset = byte position up to the LAST COMPLETE line consumed
                         (a partial trailing line is left for the next poll)
        - Missing / unreadable file → ( [], offset )  (offset unchanged)
        - File shrank below `offset` (rotation/truncation) → re-read from 0
        - Blank / malformed / non-object JSON lines are skipped
        - NEVER raises
    """
    try:
        size = os.path.getsize( path )
    except OSError:
        return [ ], offset

    # Rotation / truncation: the file is now smaller than where we last read →
    # it was rotated or recreated; start over from the top.
    if offset > size:
        offset = 0
    if offset == size:
        return [ ], offset                       # nothing new

    try:
        with open( path, "rb" ) as f:
            f.seek( offset )
            chunk = f.read()
    except OSError:
        return [ ], offset

    last_nl = chunk.rfind( b"\n" )
    if last_nl == -1:
        return [ ], offset                       # no complete line yet (partial write)

    consumable = chunk[ : last_nl + 1 ]
    new_offset = offset + len( consumable )

    records = [ ]
    for raw in consumable.split( b"\n" ):
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads( raw )
        except ValueError:
            continue
        if isinstance( obj, dict ):
            records.append( obj )

    return records, new_offset


def tail_fleet_events( events_dir=None, offsets=None ):
    """
    Glob the fleet events dir and tail every session file from its offset.

    Requires:
        - events_dir is a path-like or None (None → the fleet dir
          ~/.claude/heartbeat-events). Injectable for tests.
        - offsets is a dict {session_id: byte_offset} or None (None → {} →
          read each file from the start on the first poll)

    Ensures:
        - Returns ( events_by_session, new_offsets ):
            events_by_session = {session_id: [new records]} — ONLY sessions
                                with at least one new record this poll
            new_offsets       = {session_id: byte_offset} for EVERY session
                                file seen (carried forward for the next poll)
        - Missing dir → ( {}, {} of any pre-existing offsets )  (never raises)
        - A file that errors mid-read is skipped (its offset is preserved)
        - NEVER raises
    """
    base = Path( events_dir ) if events_dir is not None else FLEET_EVENTS_DIR
    offsets = dict( offsets ) if offsets else { }

    events_by_session = { }
    new_offsets       = { }

    # Glob the per-session JSONL files. The filename template is
    # "<session_id>.jsonl" (heartbeat_events.EVENTS_FILENAME_TEMPLATE).
    pattern = EVENTS_FILENAME_TEMPLATE.format( session_id="*" )
    try:
        paths = sorted( glob.glob( str( base / pattern ) ) )
    except OSError:
        return events_by_session, offsets

    for path in paths:
        sid             = _session_id_from_path( path )
        prior_offset    = offsets.get( sid, 0 )
        records, offset = tail_session_file( path, offset=prior_offset )
        new_offsets[ sid ] = offset
        if records:
            events_by_session[ sid ] = records

    return events_by_session, new_offsets


def quick_smoke_test():
    """
    Self-contained smoke test of glob + byte-offset tail + partial-line + rotation.

    Ensures:
        - Returns True if incremental tail / partial-line / rotation behave as
          designed; raises AssertionError otherwise.
    """
    import tempfile

    def _rec( sid, n ):
        return json.dumps( { "schema_version": 1, "session_id": sid, "outcome": "idle", "n": n } )

    with tempfile.TemporaryDirectory() as tmp:
        base = Path( tmp )
        f1   = base / "sess1.jsonl"

        # First poll — two complete records + a partial trailing line
        f1.write_text( _rec( "sess1", 1 ) + "\n" + _rec( "sess1", 2 ) + "\n" + '{"partial":' )
        ev, off = tail_fleet_events( events_dir=tmp, offsets=None )
        assert [ r[ "n" ] for r in ev[ "sess1" ] ] == [ 1, 2 ], ev
        # the partial line is NOT consumed

        # Second poll — complete the partial line + add one more
        f1.write_text( _rec( "sess1", 1 ) + "\n" + _rec( "sess1", 2 ) + "\n" +
                       _rec( "sess1", 3 ) + "\n" + _rec( "sess1", 4 ) + "\n" )
        ev2, off2 = tail_fleet_events( events_dir=tmp, offsets=off )
        assert [ r[ "n" ] for r in ev2[ "sess1" ] ] == [ 3, 4 ], ev2

        # Third poll — nothing new
        ev3, off3 = tail_fleet_events( events_dir=tmp, offsets=off2 )
        assert "sess1" not in ev3, ev3

        # Rotation — file shrank → re-read from the top
        f1.write_text( _rec( "sess1", 9 ) + "\n" )
        ev4, off4 = tail_fleet_events( events_dir=tmp, offsets=off3 )
        assert [ r[ "n" ] for r in ev4[ "sess1" ] ] == [ 9 ], ev4

        # Missing dir → empty, never raises
        ev5, off5 = tail_fleet_events( events_dir=str( base / "gone" ), offsets=None )
        assert ev5 == { } and off5 == { }

    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"heartbeat_arbiter_events_tail smoke: {'PASS' if ok else 'FAIL'}" )
