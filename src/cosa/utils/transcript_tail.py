#!/usr/bin/env python3
"""
Byte-offset tail over a JSONL transcript, with rotation reported rather than swallowed.

Why this lives in `cosa/utils/` and not beside its sibling
---------------------------------------------------------
`cosa/agents/heartbeat_arbiter/events_tail.py` already carries `tail_session_file`, and
the console-tee tailer needs the same partial-line-safe read. But the tailer lives in
`cosa/rest/`, and a `cosa/rest/` module importing from an agent package is a layering
surprise (plan T12). So the primitive has a home here, where both layers may reach it.

Why this is not a thin wrapper over `tail_session_file`
------------------------------------------------------
`tail_session_file` treats `offset > size` as rotation and SILENTLY resets to 0, re-reading
the whole file and returning it as new bytes — a full replay with nothing in the return
value saying anything rotated. For the fleet-events use that is harmless. For the console
it is not: the pane would re-render the entire transcript as fresh output, and the client
would have no signal to reset its epoch.

⇒ `tail_jsonl` returns rotation as a THIRD VALUE and returns NO records on the rotating
call. The caller bumps its epoch, tells the client, and reads the new file on the next
poll. The difference is the whole point of the module; see plan §2 item 5 and A2.3(b).

⚠️ This function NEVER RAISES, which makes a silent-empty failure possible: a path that
does not exist returns `( [], offset, False )`, exactly like a file with nothing new. That
is deliberate — a tailer must not die because a seat vanished mid-poll — and it is why the
caller is responsible for knowing whether it ever resolved a real path. A path rewritten
against the wrong root reads as "quiet seat" forever.
"""

import json
import os


def tail_jsonl( path, offset=0 ):
    """
    Read new complete JSONL records from `path` since `offset`, reporting rotation.

    Requires:
        - path is a path-like to a JSONL file (it need not exist)
        - offset is a non-negative byte offset ( 0 = from the start )

    Ensures:
        - returns ( records, new_offset, rotated )
        - records    = parsed dict records appended since `offset`, in file order
        - new_offset = the byte position of the end of the LAST COMPLETE line consumed;
                       a partial trailing line is left for the next poll
        - rotated    = True iff the file is now SHORTER than `offset`, i.e. it was
                       truncated or replaced in place
        - on rotation: returns ( [], 0, True ) — NO records. The replayed bytes are
                       deliberately withheld so the caller can bump its epoch and start
                       clean, rather than re-emitting the whole file as new output
        - a missing or unreadable file returns ( [], offset, False ) with offset unchanged
        - blank, malformed and non-object JSON lines are skipped, never fatal
        - never raises
    """
    try:
        size = os.path.getsize( path )
    except OSError:
        return [ ], offset, False

    # The file shrank below where we last read: truncated or recreated in place. Say so and
    # return nothing — re-reading from 0 here is what would replay the whole transcript as
    # if it were new.
    if offset > size:
        return [ ], 0, True

    if offset == size:
        return [ ], offset, False

    try:
        with open( path, "rb" ) as f:
            f.seek( offset )
            chunk = f.read()
    except OSError:
        return [ ], offset, False

    last_nl = chunk.rfind( b"\n" )
    if last_nl == -1:
        return [ ], offset, False                # a partial line only — wait for the rest

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

    return records, new_offset, False


def read_tail_bytes( path, tail_bytes ):
    """
    Read the LAST `tail_bytes` bytes of `path`, landing on a complete-line boundary.

    Ruling Q6 wants the last ~64 KB of a transcript, and a forward read cannot express
    that: `since_offset=0&max_bytes=65536` returns the FIRST 64 KB. This is the backward
    open (plan §2 item 4, P4).

    Requires:
        - path is a path-like to a JSONL file (it need not exist)
        - tail_bytes is a non-negative int; 0 means "the whole file"

    Ensures:
        - returns ( records, start_offset, next_offset )
        - start_offset is advanced past any partial first line, so the first record is
          whole — a naive seek to `size - tail_bytes` lands mid-line and the first record
          would be silently dropped as malformed
        - next_offset is the end of the last complete line, i.e. the file's end when the
          file ends with a newline
        - a missing or unreadable file returns ( [], 0, 0 )
        - never raises
    """
    try:
        size = os.path.getsize( path )
    except OSError:
        return [ ], 0, 0

    start = 0 if tail_bytes <= 0 else max( 0, size - tail_bytes )
    return _read_window( path, start, size - start, skip_partial_first = start > 0 )


def read_window_before( path, before_offset, max_bytes ):
    """
    Page BACKWARDS from `before_offset` — the "load earlier" verb of ruling Q6.

    Requires:
        - path is a path-like to a JSONL file (it need not exist)
        - before_offset is a non-negative byte offset; records END before it
        - max_bytes is a non-negative int; 0 means "everything before before_offset"

    Ensures:
        - returns ( records, start_offset, next_offset ) covering the window that ENDS at
          `before_offset`, never crossing it
        - start_offset is advanced past a partial first line unless the window starts at 0
        - next_offset <= before_offset
        - a before_offset of 0, a missing file, or an empty window returns ( [], 0, 0 ) —
          which is how the client learns it has reached the top and stops asking
        - never raises
    """
    try:
        size = os.path.getsize( path )
    except OSError:
        return [ ], 0, 0

    end = min( before_offset, size )
    if end <= 0:
        return [ ], 0, 0

    start = 0 if max_bytes <= 0 else max( 0, end - max_bytes )
    return _read_window( path, start, end - start, skip_partial_first = start > 0 )


def read_window_from( path, since_offset, max_bytes ):
    """
    Read FORWARD from `since_offset` — the gap-repair verb.

    Requires:
        - path is a path-like to a JSONL file (it need not exist)
        - since_offset is a non-negative byte offset, assumed to sit on a line boundary
          because it came from a previous `next_offset`
        - max_bytes is a non-negative int; 0 means "to the end of the file"

    Ensures:
        - returns ( records, start_offset, next_offset )
        - start_offset == since_offset (clamped to the file size)
        - next_offset is the end of the last complete line in the window
        - a missing file or a since_offset past the end returns ( [], since_offset', since_offset' )
        - never raises
    """
    try:
        size = os.path.getsize( path )
    except OSError:
        return [ ], since_offset, since_offset

    start = min( max( 0, since_offset ), size )
    span  = size - start if max_bytes <= 0 else min( max_bytes, size - start )
    return _read_window( path, start, span, skip_partial_first=False )


def _read_window( path, start, span, skip_partial_first ):
    """
    Read `span` bytes from `start` and parse the complete lines inside.

    The one place the complete-line rule is implemented, so the three public verbs cannot
    disagree about it.

    Requires:
        - path is a path-like; start and span are non-negative ints
        - skip_partial_first is a bool: True when `start` may land mid-line

    Ensures:
        - returns ( records, start_offset, next_offset ), both offsets on line boundaries
        - when skip_partial_first, start_offset is moved past the first newline so the
          first record returned is whole
        - a window holding no complete line returns ( [], start_offset, start_offset )
        - never raises
    """
    if span <= 0:
        return [ ], start, start

    try:
        with open( path, "rb" ) as f:
            f.seek( start )
            chunk = f.read( span )
    except OSError:
        return [ ], start, start

    start_offset = start
    if skip_partial_first:
        first_nl = chunk.find( b"\n" )
        if first_nl == -1:
            return [ ], start + len( chunk ), start + len( chunk )
        start_offset = start + first_nl + 1
        chunk        = chunk[ first_nl + 1 : ]

    last_nl = chunk.rfind( b"\n" )
    if last_nl == -1:
        return [ ], start_offset, start_offset

    consumable  = chunk[ : last_nl + 1 ]
    next_offset = start_offset + len( consumable )

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

    return records, start_offset, next_offset
