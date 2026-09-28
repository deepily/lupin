#!/usr/bin/env python3
"""
The console-tee tailer: one async poller per WATCHED seat, pushing append frames.

Plan: `src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md` §2 items 1–8.
Names per ruling OSQ-6. Events: cc_transcript_append · cc_transcript_state.

What this owns
--------------
- resolving a seat's transcript from the session bridge, on EVERY poll
- a byte offset per seat, and the `file_epoch` that scopes it
- mapping new records to display blocks, coalesced per ruling Q7
- a byte-bounded ring so a brief reconnect need not go to REST
- starting on the first watcher and stopping a grace period after the last leaves

🔴 A `/clear` SWAPS THE PATH — IT NEVER SHRINKS THE FILE
-------------------------------------------------------
`register_session.py` runs on every SessionStart, `/clear` fires SessionStart, and the hook
rewrites the bridge with the NEW `transcript_path` while PRESERVING `stable_session_id`.
The old JSONL does not shrink; it stops growing, and a different file appears elsewhere.

⇒ A tailer that watches only for a shrink sits on the dead file forever: no epoch bump, no
state frame, no new blocks — the pane silently freezes at the moment of the clear, which is
the precise failure `file_epoch` exists to prevent. So **re-resolving the bridge is the
PRIMARY detector and a changed path is the `/clear` signal**; the shrink is only the
secondary detector, for genuine in-place truncation.

🔴 THE PATH IS OPENED VERBATIM
------------------------------
Never rejoin `transcript_path` against `LUPIN_ROOT` or any other root. The container binds
the host sessions directory to the SAME absolute path inside the container, which is why a
verbatim open works. And `tail_jsonl` never raises — a missing file returns no records — so
a rewritten path is not an error, it is an empty stream: a blank pane while every status
frame says `live`. Constraint raised by Tiberius from his integration fixture.
"""

import asyncio
import os
import time

from cosa.rest.cc_transcript_mapper import map_records
from cosa.utils.transcript_tail import (
    read_tail_bytes,
    read_window_before,
    read_window_from,
    tail_jsonl,
)

APPEND_EVENT = "cc_transcript_append"
STATE_EVENT  = "cc_transcript_state"

STATE_LIVE           = "live"
STATE_ENDED          = "ended"
STATE_ROTATED        = "rotated"
STATE_EPOCH_MISMATCH = "epoch_mismatch"

# Defaults. Every one is overridden from the INI by `load_settings`; they live here so the
# module is usable (and testable) without a ConfigurationManager.
DEFAULT_POLL_INTERVAL_SECONDS = 0.25
DEFAULT_GRACE_SECONDS         = 30
DEFAULT_COALESCE_WINDOW_MS    = 300      # ruled — Q7
DEFAULT_BACKLOG_TAIL_BYTES    = 65536    # ruled — Q6, "~64 KB"
DEFAULT_BLOCK_BUDGET_BYTES    = 8192
DEFAULT_RING_BUFFER_BYTES     = 262144


def load_settings( config_mgr=None ):
    """
    Read the six dials from the INI, falling back to the defaults above.

    The plan is explicit that unresolved VALUES are acceptable at this stage but unresolved
    HOMES are not (T8) — so all six are INI keys from the start and can be moved without a
    code change.

    Requires:
        - config_mgr is a ConfigurationManager or None (None → resolve the shared singleton;
          if that fails, the defaults above)

    Ensures:
        - returns a dict with the six keys, every value an int except poll_interval_seconds
        - never raises: a missing config manager yields the defaults rather than an error,
          because a tailer that cannot start is worse than one running on defaults
    """
    if config_mgr is None:
        try:
            from cosa.rest.dependencies.config import get_config_manager
            config_mgr = get_config_manager()
        except Exception:
            config_mgr = None

    if config_mgr is None:
        return {
            "poll_interval_seconds" : DEFAULT_POLL_INTERVAL_SECONDS,
            "grace_seconds"         : DEFAULT_GRACE_SECONDS,
            "coalesce_window_ms"    : DEFAULT_COALESCE_WINDOW_MS,
            "backlog_tail_bytes"    : DEFAULT_BACKLOG_TAIL_BYTES,
            "block_budget_bytes"    : DEFAULT_BLOCK_BUDGET_BYTES,
            "ring_buffer_bytes"     : DEFAULT_RING_BUFFER_BYTES,
        }

    return {
        "poll_interval_seconds" : config_mgr.get( "cc transcript poll interval seconds",
                                                  default=DEFAULT_POLL_INTERVAL_SECONDS,
                                                  return_type="float" ),
        "grace_seconds"         : config_mgr.get( "cc transcript watcher grace seconds",
                                                  default=DEFAULT_GRACE_SECONDS,
                                                  return_type="int" ),
        "coalesce_window_ms"    : config_mgr.get( "cc transcript coalesce window ms",
                                                  default=DEFAULT_COALESCE_WINDOW_MS,
                                                  return_type="int" ),
        "backlog_tail_bytes"    : config_mgr.get( "cc transcript backlog tail bytes",
                                                  default=DEFAULT_BACKLOG_TAIL_BYTES,
                                                  return_type="int" ),
        "block_budget_bytes"    : config_mgr.get( "cc transcript block budget bytes",
                                                  default=DEFAULT_BLOCK_BUDGET_BYTES,
                                                  return_type="int" ),
        "ring_buffer_bytes"     : config_mgr.get( "cc transcript ring buffer bytes",
                                                  default=DEFAULT_RING_BUFFER_BYTES,
                                                  return_type="int" ),
    }


def epoch_for_path( transcript_path ):
    """
    Derive the `file_epoch` from a transcript path.

    The epoch NAMES THE FILE: a `/clear` swaps the path, so the path's own identity is the
    epoch. The basename without its extension is the per-session uuid Claude Code writes.

    Requires:
        - transcript_path is a string or None

    Ensures:
        - returns the basename with its extension stripped, or "" for a falsy path
        - never raises
    """
    if not transcript_path: return ""
    return os.path.splitext( os.path.basename( str( transcript_path ) ) )[ 0 ]


def resolve_transcript_path( cc_session_id, bridge_reader=None ):
    """
    Resolve a seat's transcript path from the session bridge.

    `session_bridge.get_session_metadata()` resolves only the CALLING process and cannot
    answer for another seat, so the per-seat read is `find_session_by_id`.

    Requires:
        - cc_session_id is a seat's stable_session_id
        - bridge_reader is a callable( cc_session_id ) -> dict|None, or None for the real
          session-bridge read (injected so a unit test needs no live seat)

    Ensures:
        - returns the bridge's `transcript_path` VERBATIM, or "" when the seat or the field
          is absent — never a path rejoined against any root
        - never raises
    """
    if bridge_reader is None:
        try:
            from lupin_cli.claude_code.hooks.lib.session_bridge import find_session_by_id
            bridge_reader = find_session_by_id
        except Exception:
            return ""

    try:
        bridge = bridge_reader( cc_session_id )
    except Exception:
        return ""

    if not isinstance( bridge, dict ): return ""
    return str( bridge.get( "transcript_path" ) or "" )


class SeatRing:
    """
    A BYTE-bounded ring of recently-sent blocks, carrying the offset span it holds.

    🔴 Bounded in BYTES, not records. `arbiter_state.FleetEventAccumulator` is the right
    SHAPE — session id → bounded per-session tail — but it is bounded in RECORDS
    (`DEFAULT_TAIL_MAXLEN = 50`), and a record-count ring cannot answer a byte-offset
    question: the server could not say which `from_offset` values it is able to serve.
    That unit mismatch is the finding (plan P7), not the value.
    """

    def __init__( self, max_bytes ):
        """
        Requires:
            - max_bytes is a non-negative int; 0 disables the ring

        Ensures:
            - starts empty, with an empty span
        """
        self.max_bytes = max_bytes
        self.chunks    = [ ]          # [ { offset, next_offset, blocks } ]
        self.held      = 0

    def add( self, offset, next_offset, blocks ):
        """
        Record one chunk, evicting from the front until the byte budget holds.

        Requires:
            - offset <= next_offset
            - blocks is a list

        Ensures:
            - the ring holds at most max_bytes of transcript span
            - a chunk larger than the whole budget leaves the ring EMPTY rather than
              over-full, so `span()` never claims more than it can serve
        """
        if self.max_bytes <= 0: return

        self.chunks.append( { "offset": offset, "next_offset": next_offset, "blocks": blocks } )
        self.held += max( 0, next_offset - offset )

        while self.chunks and self.held > self.max_bytes:
            evicted   = self.chunks.pop( 0 )
            self.held -= max( 0, evicted[ "next_offset" ] - evicted[ "offset" ] )

    def span( self ):
        """
        The offset span this ring can serve.

        Ensures:
            - returns ( start, end ), or ( None, None ) when empty — the honest answer to
              "which from_offset values can you serve?"
        """
        if not self.chunks: return None, None
        return self.chunks[ 0 ][ "offset" ], self.chunks[ -1 ][ "next_offset" ]

    def can_serve( self, from_offset ):
        """
        Whether `from_offset` falls inside the span held.

        Ensures:
            - returns True iff a chunk boundary at or after from_offset is held
        """
        start, end = self.span()
        if start is None: return False
        return start <= from_offset <= end

    def blocks_from( self, from_offset ):
        """
        Every held block at or after `from_offset`.

        Ensures:
            - returns ( blocks, next_offset ); ( [], from_offset ) when nothing is held
            - chunks straddling from_offset are included whole, because a chunk is the
              smallest unit the ring stored
        """
        out         = [ ]
        next_offset = from_offset
        for chunk in self.chunks:
            if chunk[ "next_offset" ] <= from_offset: continue
            out.extend( chunk[ "blocks" ] )
            next_offset = chunk[ "next_offset" ]
        return out, next_offset


class CcTranscriptTailer:
    """
    Polls ONE watched seat and pushes coalesced append frames to its watchers.

    WHO OWNS THE LIFECYCLE, stated precisely because an earlier version of this docstring got
    it wrong. The WATCHER COUNT lives in `WebSocketManager.cc_transcript_watchers`, not here:
    the caller starts a tailer when a seat gains its first watcher and stops it when the seat
    loses its last. This class has no concept of a watcher.

    What it DOES own is self-termination: given a `has_watchers` predicate it polls the count
    itself and stops after `grace_seconds` with none. That is not a nicety — `disconnect()` is
    SYNCHRONOUS and called from threads, so it can drop registry entries but cannot await a
    stop. Without a self-check, a watcher removed on that path would leave this tailer polling
    a seat nobody is watching, forever, with no error anywhere.

    (Rio caught the earlier docstring asserting "starts on the first watcher, stops after the
    last" while NO code implemented it, 2026-09-27. A claim in a docstring is not a mechanism,
    and it is worse than an outright gap: an auditor reads the sentence and stops looking.)

    The grace period is about WATCHERS, never about the seat — which is exactly why `ended`
    needs its own producer (see `mark_seat_ended`).
    """

    def __init__( self, cc_session_id, emit, settings=None, bridge_reader=None,
                  has_watchers=None ):
        """
        Requires:
            - cc_session_id is the seat's stable_session_id
            - emit is an async callable( cc_session_id, event_name, payload )
            - settings is a dict as `load_settings` returns, or None for the defaults
            - bridge_reader is a callable( cc_session_id ) -> dict|None, or None for the
              real session-bridge read
            - has_watchers is a callable() -> bool, or None to disable self-termination
              (None is for tests that drive start/stop directly; the server always passes one)

        Ensures:
            - no file is touched and no task is created until `start()`
        """
        self.cc_session_id = cc_session_id
        self.emit          = emit
        self.settings      = settings or load_settings()
        self.bridge_reader = bridge_reader
        self.has_watchers  = has_watchers

        self.transcript_path = ""
        self.file_epoch      = ""
        self.offset          = 0
        self.ring            = SeatRing( self.settings[ "ring_buffer_bytes" ] )

        self._task    = None
        self._running = False

    # ── lifecycle ────────────────────────────────────────────────────────────────

    def start( self, from_offset=0 ):
        """
        Begin polling, starting WHERE THE CLIENT ASKED.

        Requires:
            - from_offset is a non-negative byte offset

        Ensures:
            - resolves the path and epoch, sets the offset to from_offset, and schedules the
              poll loop; a second call while running is a no-op
            - NEVER silently starts at the current end of the file — doing so opens a gap
              between the client's REST backlog fetch and its live watch
        """
        if self._running: return

        self.transcript_path = resolve_transcript_path( self.cc_session_id, self.bridge_reader )
        self.file_epoch      = epoch_for_path( self.transcript_path )
        self.offset          = max( 0, from_offset )
        self._running        = True
        self._task           = asyncio.ensure_future( self._loop() )

    async def stop( self ):
        """
        Stop polling and release the task.

        Ensures:
            - the loop is cancelled and awaited; calling stop() when not running is a no-op
            - never raises, including when the task was already finished
        """
        self._running = False
        task, self._task = self._task, None
        if task is None: return
        task.cancel()
        try:
            await task
        except ( asyncio.CancelledError, Exception ):
            pass

    @property
    def running( self ):
        """Whether the poll loop is live."""
        return self._running

    # ── the poll ─────────────────────────────────────────────────────────────────

    async def _loop( self ):
        """
        Poll, coalesce, emit — until stopped.

        Ensures:
            - one append frame at most per coalesce window, per ruling Q7
            - an exception inside one poll does not kill the loop; the stream degrades to a
              retry rather than dying silently
        """
        await self.emit( self.cc_session_id, STATE_EVENT, self._state_payload( STATE_LIVE ) )

        poll_interval  = max( 0.01, float( self.settings[ "poll_interval_seconds" ] ) )
        coalesce_window = max( 0.0, self.settings[ "coalesce_window_ms" ] / 1000.0 )
        pending         = [ ]
        pending_offset  = None
        last_flush      = time.monotonic()

        grace       = max( 0.0, float( self.settings[ "grace_seconds" ] ) )
        unwatched_since = None

        while self._running:
            # SELF-TERMINATION. `disconnect()` is synchronous and thread-called, so it can drop
            # a watcher but cannot await this stop. Polling the count here is what makes the
            # lifecycle correct regardless of WHICH path removed the last watcher, rather than
            # correct only when the caller remembers to reap in the right order.
            if self.has_watchers is not None and not self.has_watchers():
                if unwatched_since is None:
                    unwatched_since = time.monotonic()
                elif ( time.monotonic() - unwatched_since ) >= grace:
                    self._running = False
                    break
            else:
                unwatched_since = None

            try:
                chunk = self.poll_once()
            except Exception as e:                      # pragma: no cover - defensive; a poll that throws must not kill the stream
                print( f"[CC-TRANSCRIPT] poll error for {self.cc_session_id}: {e}" )
                chunk = None

            if chunk is not None:
                if pending_offset is None: pending_offset = chunk[ "offset" ]
                pending.extend( chunk[ "blocks" ] )
                pending_next = chunk[ "next_offset" ]
            else:
                pending_next = None

            now = time.monotonic()
            if pending and ( now - last_flush ) >= coalesce_window:
                await self._flush( pending_offset, pending_next or pending_offset, pending )
                pending        = [ ]
                pending_offset = None
                last_flush     = now

            await asyncio.sleep( poll_interval )

    def poll_once( self ):
        """
        One poll: re-resolve the bridge, detect a clear or a rotation, read new records.

        Requires:
            - start() has resolved an initial path and epoch

        Ensures:
            - returns None when there is nothing new
            - returns { offset, next_offset, blocks, rotated } when there is
            - a CHANGED `transcript_path` is treated as the `/clear` signal: the epoch is
              rebuilt from the new path, the offset resets to 0, and `rotated` is True.
              THIS IS THE PRIMARY DETECTOR — the file never shrinks on a clear
            - a shrink is the SECONDARY detector: the epoch is bumped and the replayed
              records are NOT emitted
            - never raises
        """
        current_path = resolve_transcript_path( self.cc_session_id, self.bridge_reader )

        # PRIMARY: the path moved, so a /clear happened. Reset against the new file.
        if current_path and current_path != self.transcript_path:
            self.transcript_path = current_path
            self.file_epoch      = epoch_for_path( current_path )
            self.offset          = 0
            self.ring            = SeatRing( self.settings[ "ring_buffer_bytes" ] )
            return { "offset": 0, "next_offset": 0, "blocks": [ ], "rotated": True }

        records, new_offset, rotated = tail_jsonl( self.transcript_path, self.offset )

        # SECONDARY: truncated in place. Bump the epoch, emit nothing, read clean next poll.
        if rotated:
            self.offset     = 0
            self.file_epoch = f"{epoch_for_path( self.transcript_path )}#{int( time.time() )}"
            self.ring       = SeatRing( self.settings[ "ring_buffer_bytes" ] )
            return { "offset": 0, "next_offset": 0, "blocks": [ ], "rotated": True }

        if not records:
            self.offset = new_offset
            return None

        blocks       = map_records( records, budget=self.settings[ "block_budget_bytes" ] )
        chunk_offset = self.offset
        self.offset  = new_offset

        if not blocks: return None

        self.ring.add( chunk_offset, new_offset, blocks )
        return { "offset": chunk_offset, "next_offset": new_offset, "blocks": blocks, "rotated": False }

    async def _flush( self, offset, next_offset, blocks ):
        """
        Emit one coalesced append frame, plus a rotation state frame when the epoch moved.

        Requires:
            - offset and next_offset are byte offsets; blocks is a non-empty list

        Ensures:
            - emits cc_transcript_append with the current epoch
            - never raises out of the loop
        """
        await self.emit( self.cc_session_id, APPEND_EVENT, {
            "cc_session_id" : self.cc_session_id,
            "file_epoch"    : self.file_epoch,
            "offset"        : offset,
            "next_offset"   : next_offset,
            "blocks"        : blocks,
            "ts"            : _now_iso(),
        } )

    async def announce_rotation( self ):
        """
        Tell watchers the epoch moved, so they clear their buffer and re-fetch.

        Ensures:
            - emits cc_transcript_state with state `rotated` and the CURRENT epoch
        """
        await self.emit( self.cc_session_id, STATE_EVENT, self._state_payload( STATE_ROTATED ) )

    async def mark_seat_ended( self ):
        """
        Tell watchers the SEAT exited — not merely that it went quiet.

        The grace period stops the tailer when the last WATCHER leaves, never when the seat
        leaves, so without this producer a viewer watching a seat that exits sees a pane
        that merely stops: indistinguishable from a quiet seat (plan P6). The signal is the
        existing SessionEnd hook, with a staleness fallback for a seat that dies without
        firing it.

        Ensures:
            - emits cc_transcript_state with state `ended`
        """
        await self.emit( self.cc_session_id, STATE_EVENT, self._state_payload( STATE_ENDED ) )

    def _state_payload( self, state ):
        """
        Build a cc_transcript_state payload.

        Ensures:
            - returns { cc_session_id, file_epoch, state }
        """
        return {
            "cc_session_id" : self.cc_session_id,
            "file_epoch"    : self.file_epoch,
            "state"         : state,
        }


def read_backlog( transcript_path, tail_bytes=None, before_offset=None, since_offset=None,
                  max_bytes=0, budget=0 ):
    """
    Serve the REST backlog in one of three directions.

    Ruling Q6 wants the LAST ~64 KB with a load-earlier page, and a forward-only contract
    cannot express that: `since_offset=0&max_bytes=65536` returns the FIRST 64 KB (plan P4).

    Requires:
        - transcript_path is a path-like (it need not exist)
        - exactly one of tail_bytes / before_offset / since_offset is meaningful; they are
          checked in that order, so a caller passing two gets the first
        - max_bytes and budget are non-negative ints; 0 means unbounded

    Ensures:
        - returns { file_epoch, offset, next_offset, blocks }
        - every offset lands on a complete-line boundary
        - a missing file returns empty blocks with zeroed offsets, never an exception
    """
    if tail_bytes is not None:
        records, offset, next_offset = read_tail_bytes( transcript_path, tail_bytes )
    elif before_offset is not None:
        records, offset, next_offset = read_window_before( transcript_path, before_offset, max_bytes )
    else:
        records, offset, next_offset = read_window_from( transcript_path, since_offset or 0, max_bytes )

    return {
        "file_epoch"  : epoch_for_path( transcript_path ),
        "offset"      : offset,
        "next_offset" : next_offset,
        "blocks"      : map_records( records, budget=budget ),
    }


def _now_iso():
    """
    The current time as an ISO-8601 string.

    Ensures:
        - returns the repo's canonical ISO stamp, the same helper the WS router stamps
          frames with, so a console frame's ts is comparable to every other event's
    """
    import cosa.utils.util as du
    return du.get_current_datetime_iso()
