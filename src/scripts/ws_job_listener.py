#!/usr/bin/env python3
"""
The persistent queue-WebSocket listener, moved out of the v1 arm so it survives it.

WHY THIS FILE EXISTS. `v2_eval`'s terminal wait (row a2e360f8) imports
`make_ws_recv_events` from `v1_eval_arm` — a script the V1 excision deletes (row
e2099400 §2, Step 2). The listener is not v1 apparatus: it watches the SHIPPED queue
WebSocket and reduces `job_state_transition` frames, which both arms need and which v2
will keep needing after v1 is gone. Leaving it in the file being deleted would have taken
v2's terminal wait down with it.

⚠️ THE CODE BELOW IS A MOVE, NOT A REWRITE. It is the same block, verbatim, so the
listener's behaviour cannot change under cover of a relocation — a "while I'm in here"
edit during a move is the shape that makes a bisect useless. The tests moved with it
(`src/tests/unit/test_v1_ws_recv_events.py`), and they were run green against this module
before v1_eval_arm was touched.

WHAT IT IS. A listener that connects ONCE, before any job is pushed, and buffers every
frame by job_id — so `ws_recv_events( job_id )` can hand one job's frames to a reducer
without racing the server. It REFUSES rather than returning a partial buffer: a span
computed from whatever arrived before a timeout is a number wrong in the direction nobody
audits, and it feeds straight into a go/no-go.

Created: 2026-08-26 (row e2099400 §2 Step 2 — the relocation that precedes the deletion)
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit


class EvalIntegrityError( RuntimeError ):
    """
    A precondition for a trustworthy measurement was violated — the run fails LOUDLY
    rather than reporting a number it cannot stand behind.

    ⚠️ THIS IS A THIRD CLASS OF THE SAME NAME, AND THAT IS DELIBERATE. `v1_eval_arm` and
    `v2_eval` each define their own; importing either here would re-create the dependency
    this move exists to cut, in the opposite direction. It costs nothing at the catch site:
    `v2_eval` already catches `RuntimeError` on purpose — its own comment says catching
    anything narrower would make it import `v1_eval_arm` for a class alone — so a listener
    timeout is caught exactly as before.
    """


# The v1 JobState string values (job_state.py) the WS events carry in `to_state`.
_ST_QUEUED    = "queued"
_ST_RUNNING   = "running"
_ST_COMPLETED = "completed"


def _iso_to_epoch( iso: Any ) -> Optional[float]:
    """
    Ensures:
        - parses an ISO-8601 string (the event `timestamp`, aware) to epoch seconds
        - returns None for None / non-string / unparseable — never raises, so one
          malformed stamp cannot crash a whole pass
    """
    import datetime
    if not isinstance( iso, str ):
        return None
    try:
        return datetime.datetime.fromisoformat( iso ).timestamp()
    except ValueError:
        return None


def parse_transitions( events: Sequence[Dict[str, Any]] ) -> Dict[str, Any]:
    """
    Reduce ONE job's `job_state_transition` events into the transitions dict
    assemble_v1_record consumes.

    Requires:
        - events is the list of job_state_transition payloads for a SINGLE job
          (each { to_state, timestamp (ISO), metadata? }), already job-filtered

    Ensures:
        - returns { queued_ts, running_ts, completed_ts, metadata }, timestamps in
          epoch seconds (QUEUED/RUNNING/COMPLETED transitions); metadata is the
          COMPLETED event's metadata (the completion payload), else None
        - a terminal FAILURE (failed/cancelled/…) leaves completed_ts + metadata
          None ⇒ the record reads no_completion (honest: no usable span), never a
          fabricated completion
        - never raises (a malformed timestamp becomes None via _iso_to_epoch)
    """
    out: Dict[str, Any] = { "queued_ts": None, "running_ts": None, "completed_ts": None, "metadata": None }
    for ev in events:
        to = ev.get( "to_state" )
        ts = _iso_to_epoch( ev.get( "timestamp" ) )
        if to == _ST_QUEUED:
            out[ "queued_ts" ] = ts
        elif to == _ST_RUNNING:
            out[ "running_ts" ] = ts
        elif to == _ST_COMPLETED:
            out[ "completed_ts" ] = ts
            out[ "metadata" ]     = ev.get( "metadata" )
    return out


# The frame shape is the SHIPPED one: websocket_manager builds { "type": <event>,
# "timestamp": <iso>, **data }, and queue_util.emit_job_state_transition's data is
# { job_id, from_state, to_state, timestamp, metadata? }. So each buffered frame already
# carries to_state / timestamp / metadata — exactly what parse_transitions reduces.

# Queue events this listener must be subscribed to (the server filters outbound frames
# against this list). Mirrors QueueTransport's list, trimmed to what the seam needs.
_QUEUE_SUBSCRIBED_EVENTS = ( "job_state_transition", "auth_success", "auth_error", "connect" )

# to_state values that END a job's watch: a real completion or a real terminal failure.
# STALLED is deliberately NOT terminal — it can recover to COMPLETED, so we keep waiting
# (the per-job timeout bounds it). Matches the JobState string values (job_state.py).
_TERMINAL_STATES = frozenset( { "completed", "failed", "cancelled", "interrupted" } )


class WsJobEventListener:
    """
    A persistent queue-WebSocket listener that buffers `job_state_transition` frames by
    job_id, so `ws_recv_events( job_id )` can hand a single job's frames to parse_transitions.

    Requires:
        - base_url points at the (pinned-worktree) v1 server answering /ws/queue/<sid>.
        - token is a JWT for the queue WS auth_request (same user whose jobs are pushed,
          so the server's per-user emit reaches this listener).
        - start() is called BEFORE any job is pushed — otherwise early frames race the
          connect and are missed (the mis-measurement this class exists to prevent).

    Ensures:
        - start() connects, sends the auth_request, and BLOCKS until auth_success (or
          raises on connect/auth failure), so a caller that returns from start() has a
          live, subscribed socket.
        - a background thread buffers every job_state_transition frame under its job_id.
        - ws_recv_events( job_id ) BLOCKS until that job has a frame whose to_state is
          terminal (completed/failed/cancelled/interrupted), then returns the job's frames
          in arrival order.
        - RAISES EvalIntegrityError when collect_timeout elapses with no terminal frame —
          including a job with no frames at all — rather than returning a partial buffer
          that would become a wrong-direction span. Never fabricates a completion.
        - stop() ends the listener thread and closes the socket.
    """

    def __init__(
        self,
        base_url        : str,
        token           : str,
        session_id      : str   = "v1-eval-listener",
        *,
        collect_timeout : float = 120.0,
        connect_timeout : float = 10.0,
    ) -> None:
        self.base_url        = base_url
        self.token           = token
        self.session_id      = session_id
        self.collect_timeout = collect_timeout
        self.connect_timeout = connect_timeout
        self._events : Dict[ str, List[ Dict[ str, Any ] ] ] = {}
        self._cond           = threading.Condition()
        self._ready          = threading.Event()   # set on auth_success OR fatal error
        self._stop           = threading.Event()
        self._error : Optional[ BaseException ] = None
        self._thread : Optional[ threading.Thread ] = None
        self._loop = None

    def _ws_url( self ) -> str:
        parts  = urlsplit( self.base_url )
        scheme = "wss" if parts.scheme == "https" else "ws"
        return f"{scheme}://{parts.netloc}/ws/queue/{self.session_id}"

    async def _serve( self ) -> None:
        """Connect, authenticate, then buffer frames until stop() — the live socket loop."""
        import websockets
        try:
            async with websockets.connect( self._ws_url(), open_timeout=self.connect_timeout ) as ws:
                await ws.send( json.dumps( {
                    "type"              : "auth_request",
                    "token"             : self.token,
                    "session_id"        : self.session_id,
                    "subscribed_events" : list( _QUEUE_SUBSCRIBED_EVENTS ),
                } ) )
                while not self._stop.is_set():
                    try:
                        raw = await asyncio.wait_for( ws.recv(), timeout=1.0 )
                    except asyncio.TimeoutError:
                        continue                      # tick: re-check self._stop
                    frame = json.loads( raw )
                    ftype = frame.get( "type" )
                    if ftype == "auth_success":
                        self._ready.set()
                        continue
                    if ftype == "auth_error":
                        raise EvalIntegrityError( f"v1 WS auth_error: {frame}" )
                    if ftype == "job_state_transition":
                        job_id = frame.get( "job_id" )
                        with self._cond:
                            self._events.setdefault( job_id, [] ).append( frame )
                            self._cond.notify_all()
        except Exception as exc:                      # connect/auth/transport failure
            self._error = exc
        finally:
            self._ready.set()                         # unblock start() on success OR failure

    def _thread_main( self ) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop( self._loop )
        self._loop.run_until_complete( self._serve() )

    def start( self ) -> "WsJobEventListener":
        """Spawn the listener thread and block until authenticated (or raise)."""
        self._thread = threading.Thread( target=self._thread_main, name="v1-ws-listener", daemon=True )
        self._thread.start()
        if not self._ready.wait( self.connect_timeout + 2.0 ):
            raise EvalIntegrityError( "v1 WS listener did not become ready (no auth_success within timeout)" )
        if self._error is not None:
            raise self._error
        return self

    def ws_recv_events( self, job_id: str ) -> List[ Dict[ str, Any ] ]:
        """
        Block until `job_id` reaches a terminal to_state, then return its frames.

        Ensures:
            - returns the job's buffered frames (arrival order) once any carries a terminal
              to_state.
            - RAISES EvalIntegrityError when collect_timeout elapses with no terminal frame
              (a job with zero frames included) — never returns a partial/empty buffer, so
              a stuck or silent job fails the run loudly instead of feeding a short span
              into the go/no-go.
        """
        deadline = time.monotonic() + self.collect_timeout
        with self._cond:
            while True:
                events = self._events.get( job_id, [] )
                if any( ev.get( "to_state" ) in _TERMINAL_STATES for ev in events ):
                    return list( events )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    seen = [ ev.get( "to_state" ) for ev in events ]
                    raise EvalIntegrityError(
                        f"v1 WS collect timed out for job {job_id!r} after {self.collect_timeout}s with no "
                        f"terminal state (saw {len( events )} frame(s): {seen}) — refusing to return a partial "
                        f"span; the paired number would be wrong in the direction nobody audits"
                    )
                self._cond.wait( timeout=remaining )

    def stop( self ) -> None:
        """End the listener thread and close the socket."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join( timeout=5.0 )


def make_ws_recv_events(
    base_url        : str,
    token           : str,
    session_id      : str   = "v1-eval-listener",
    *,
    collect_timeout : float = 120.0,
) -> Tuple[ WsJobEventListener, Callable[ [ str ], List[ Dict[ str, Any ] ] ] ]:
    """
    Start a WsJobEventListener and return ( listener, listener.ws_recv_events ).

    The RUN wrapper calls this BEFORE the pass, wires ws_recv_events into
    _default_collect_fn, runs both passes, then calls listener.stop(). Returning the
    listener (not just the callable) keeps stop() in the caller's hands.
    """
    listener = WsJobEventListener( base_url, token, session_id, collect_timeout=collect_timeout ).start()
    return listener, listener.ws_recv_events
