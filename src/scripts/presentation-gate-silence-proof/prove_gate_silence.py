#!/usr/bin/env python3
"""
Prove presentation review gates reach a connected user, who answers them.

All four presentation gates fail open: the default is "Approve" with a 600 second timeout.
An earlier overnight run completed through `source=dispatch_failed`, the delivery-failed path,
where /api/notify answered 503 for lack of a session. The connected-session path was never exercised.

Ensures:
  - The verdict passes only if all five checks hold: delivered, connected through the wait,
    every gate answered, every gate resolved as responded, and the job reached done.
  - Delivered means a `notification_queue_update` frame reached the session. /api/notify pushes
    that frame only when the session is connected; the 503 offline branch pushes nothing.
  - Connected through the wait means no socket drop and no gap between liveness samples above
    `MAX_LIVENESS_GAP`. A connect-then-drop would give a late dispatch failure that mimics silence.
  - The log source label cannot separate the two paths. `voice_io.present_choices` catches every
    exception and stamps `dispatch_failed`, and a delivered-but-silent timeout raises
    `VoiceGateTimeoutError` into that same block. Proof rests on delivery and notification state.
  - A fresh non-service user is both submitter and gate target. The tester account is a configured
    voice gate service account, so the gate would redirect to the operator's real inbox.
    Delivering there is off limits, and editing that config would change product behaviour.
    The redirect is a separate routing hop, orthogonal to whether the gate resolves.
  - The silent mode (answer mode off) exists in the class, but `main` always runs answer mode.
    The elapsed-time thresholds are recorded in the evidence file and are not checked in the verdict.

Venue is :8000 in monopolize mode. The submit is a real build costing about 15 minutes of tokens,
so schedule it after midnight EDT once the idle check passes (see CLAUDE.md, testing venues).

Usage:
  python3 prove_gate_silence.py --base http://localhost:8000 --evidence /path/to/evidence.json
  Env knobs: `PRESENTATION_SOURCE_DOC` (default the strategy doc), `GATE_TIMEOUT` (default 600,
  only affects the recorded thresholds, not the server).
"""

import os
import sys
import json
import time
import uuid
import argparse
import threading
import asyncio
import urllib.parse
from datetime import datetime, timezone

import requests


# ── module facts ──────────────────────────────────────────────────────────────
DEFAULT_BASE      = "http://localhost:8000"
DEFAULT_SOURCE    = os.environ.get(
    "PRESENTATION_SOURCE_DOC",
    "/src/rnd/v0.1.6/2026.03.14-presentation-generator/01-strategy-and-design.md",
)
GATE_TIMEOUT      = int( os.environ.get( "GATE_TIMEOUT", "600" ) )
# A delivered-but-silent gate must sit near the full timeout; a 503 resolves in
# seconds. Anything resolving under this is NOT the silence path.
MIN_SILENCE_SECS  = int( os.environ.get( "MIN_SILENCE_SECS", "480" ) )   # 0.8 * 600
# Continuous-connection guard: if any two liveness samples are further apart than
# this, we cannot claim the session was connected THROUGH the wait.
MAX_LIVENESS_GAP  = int( os.environ.get( "MAX_LIVENESS_GAP", "60" ) )
LIVENESS_PING_SEC = 15


def _now():
    return datetime.now( timezone.utc )


def _iso( dt ):
    return dt.isoformat()


def _strong_password():
    # Meets typical strength rules: length, mixed case, digit, symbol.
    return "Arnold!Gate9proof-" + uuid.uuid4().hex[ :10 ]


def _headers_from_options( response_options ):
    """
    Return the question headers from a gate's response_options, or [] if unparseable.

    The headers let the caller answer each question. response_options is a dict with a
    questions list of items carrying header and options. It arrives on the frame as a dict
    or as a JSON string. Returns an empty list when it is None or cannot be parsed.
    """
    if response_options is None:
        return []
    if isinstance( response_options, str ):
        try:
            response_options = json.loads( response_options )
        except Exception:
            return []
    questions = response_options.get( "questions", [] ) if isinstance( response_options, dict ) else []
    return [ q.get( "header" ) for q in questions if q.get( "header" ) ]


# ── auth ──────────────────────────────────────────────────────────────────────
def register_and_login( base, email, password ):
    """
    Register a fresh user (open /auth/register) and return (jwt, email, user_id).

    Falls back to /auth/login if the email already exists (400), so a re-run
    with the same email still works.
    """
    reg = requests.post(
        f"{base}/auth/register",
        json    = { "email": email, "password": password },
        timeout = 15,
    )
    if reg.status_code == 201:
        d = reg.json()
        return ( d[ "tokens" ][ "access_token" ], email, d[ "user" ][ "id" ] )

    # Already exists (or register disabled) — try a plain login.
    login = requests.post(
        f"{base}/auth/login",
        json    = { "email": email, "password": password },
        timeout = 15,
    )
    if login.status_code == 200:
        d = login.json()
        return ( d[ "tokens" ][ "access_token" ], email, d[ "user" ][ "id" ] )

    raise RuntimeError(
        f"could not register or login {email}: "
        f"register {reg.status_code} {reg.text[:200]} / login {login.status_code} {login.text[:200]}"
    )


# ── the silent, connected session ─────────────────────────────────────────────
class SilentConnectedUser:
    """
    Hold an authenticated queue WebSocket open and record every gate ask as delivery proof.

    Each gate ask arrives as a `notification_queue_update` frame, and liveness is sampled
    continuously. In answer mode (Direction A) it answers each gate promptly. It posts the
    continue_label to /api/notify/response, so the job proceeds on a human answer, not a
    declared default. With answer mode off it stays silent.
    """

    def __init__( self, base, session_id, jwt, answer_mode=False, continue_label="Approve" ):
        self.base           = base
        self.session_id     = session_id
        self.jwt            = jwt
        self.answer_mode    = answer_mode
        self.continue_label = continue_label
        self.ws_url     = (
            base.replace( "https://", "wss://" ).replace( "http://", "ws://" )
            + f"/ws/queue/{urllib.parse.quote( session_id )}"
        )
        self.deliveries    = []   # [{ts, notification_id, job_id, title, response_type, timeout_seconds, headers}]
        self.answers_posted = []  # [{ts, notification_id, answers, status}]
        self.liveness      = []   # [{ts, kind}]  kind in {auth, recv, ping}
        self.dropped_at    = None # iso ts if the socket ever closed/raised
        self._ready     = threading.Event()
        self._stop      = threading.Event()
        self._err       = None
        self._thread    = None

    def start( self, ready_timeout=20 ):
        self._thread = threading.Thread( target=self._run, daemon=True )
        self._thread.start()
        if not self._ready.wait( timeout=ready_timeout ):
            raise RuntimeError( "WS did not authenticate in time" )
        if self._err:
            raise RuntimeError( f"WS online failed: {self._err}" )

    def _mark( self, kind ):
        self.liveness.append( { "ts": _iso( _now() ), "kind": kind } )

    def _run( self ):
        try:
            asyncio.run( self._aio() )
        except Exception as e:
            if self.dropped_at is None:
                self.dropped_at = _iso( _now() )
            self._err = repr( e )
            self._ready.set()

    async def _aio( self ):
        import websockets
        async with websockets.connect(
            self.ws_url, open_timeout=15, ping_interval=20, ping_timeout=20,
        ) as ws:
            await ws.send( json.dumps( {
                "type"              : "auth_request",
                "token"             : self.jwt,
                "subscribed_events" : [ "*" ],
            } ) )
            resp = json.loads( await asyncio.wait_for( ws.recv(), timeout=15 ) )
            if resp.get( "type" ) != "auth_success":
                self._err = f"auth not successful: {resp}"
                self._ready.set()
                return
            self._mark( "auth" )
            self._ready.set()

            last_ping = time.monotonic()
            while not self._stop.is_set():
                # Active liveness ping so gaps stay small even when the server is
                # quiet during a 600s wait.
                if time.monotonic() - last_ping >= LIVENESS_PING_SEC:
                    try:
                        pong = await ws.ping()
                        await asyncio.wait_for( pong, timeout=10 )
                        self._mark( "ping" )
                    except Exception:
                        self.dropped_at = _iso( _now() )
                        break
                    last_ping = time.monotonic()
                try:
                    raw = await asyncio.wait_for( ws.recv(), timeout=1.0 )
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    self.dropped_at = _iso( _now() )
                    break
                self._mark( "recv" )
                self._record_frame( raw )

    def _record_frame( self, raw ):
        try:
            evt = json.loads( raw )
        except Exception:
            return
        if evt.get( "type" ) != "notification_queue_update":
            return
        note = evt.get( "notification", {} ) or {}
        # A gate ask is a response-required MULTIPLE_CHOICE notification.
        if not note.get( "response_requested" ):
            return
        nid     = note.get( "id" ) or note.get( "notification_id" )
        headers = _headers_from_options( note.get( "response_options" ) )
        self.deliveries.append( {
            "ts"              : _iso( _now() ),
            "notification_id" : nid,
            "job_id"          : note.get( "job_id" ),
            "title"           : note.get( "title" ),
            "response_type"   : note.get( "response_type" ),
            "timeout_seconds" : note.get( "timeout_seconds" ),
            "headers"         : headers,
        } )
        # Direction A: answer promptly on a background thread so the recv loop
        # keeps sampling liveness while the ~1s POST runs.
        if self.answer_mode and nid and headers:
            threading.Thread(
                target=self._answer_gate, args=( nid, headers ), daemon=True
            ).start()

    def _answer_gate( self, nid, headers ):
        # Answer every question header with the continue label ("Approve") — the
        # fail-open continue option, which proceeds the build. Shape proven on
        # :7999: {"answers": {header: label}} → status=responded, default_used=false.
        answers = { h: self.continue_label for h in headers }
        try:
            # The answer door requires a credential (row e20e249a); this probe already holds
            # the login it registered with.
            r = requests.post(
                f"{self.base}/api/notify/response",
                json    = { "notification_id": nid, "response_value": { "answers": answers } },
                headers = { "Authorization": f"Bearer {self.jwt}" },
                timeout = 15,
            )
            self.answers_posted.append( {
                "ts": _iso( _now() ), "notification_id": nid,
                "answers": answers, "status": r.status_code,
            } )
        except Exception as e:
            self.answers_posted.append( {
                "ts": _iso( _now() ), "notification_id": nid,
                "answers": answers, "status": f"ERR {e}",
            } )

    def liveness_report( self ):
        """Max gap between consecutive liveness samples + drop status."""
        ts = [ datetime.fromisoformat( s[ "ts" ] ) for s in self.liveness ]
        max_gap = 0.0
        for a, b in zip( ts, ts[ 1: ] ):
            max_gap = max( max_gap, ( b - a ).total_seconds() )
        return {
            "samples"          : len( self.liveness ),
            "max_gap_seconds"  : round( max_gap, 1 ),
            "dropped_at"       : self.dropped_at,
            "first_ts"         : self.liveness[ 0 ][ "ts" ] if self.liveness else None,
            "last_ts"          : self.liveness[ -1 ][ "ts" ] if self.liveness else None,
        }

    def stop( self ):
        self._stop.set()
        if self._thread:
            self._thread.join( timeout=5 )


# ── the build ─────────────────────────────────────────────────────────────────
def submit_build( base, jwt, source_path, duration=15, audience="general" ):
    # ONE DOOR NOW. /api/presentation-generator/submit is retired and answers 410 naming
    # /api/v2/submit, which takes the routing command as a string and the agent's own
    # arguments in `args`. The path arrives as `source` — the name the job factory already
    # reads — and stays repo-relative exactly as before.
    r = requests.post(
        f"{base}/api/v2/submit",
        headers = { "Authorization": f"Bearer {jwt}" },
        json    = {
            "command"  : "agent router go to presentation generator",
            "args"     : {
                "source"                  : source_path,
                "target_duration_minutes" : duration,
                "audience"                : audience,
                "dry_run"                 : False,
            },
            "question" : source_path,
        },
        timeout = 30,
    )
    if r.status_code not in ( 200, 201 ):
        raise RuntimeError( f"submit failed: {r.status_code} {r.text[:300]}" )
    d = r.json()
    job_id = d.get( "job_id" )
    if not job_id or not job_id.startswith( "pr-" ):
        raise RuntimeError( f"unexpected submit response: {d}" )
    return job_id


def _queue( base, jwt, name ):
    # Queue names: todo | run | done | dead (queues.py:461-465). Every branch
    # returns {"{name}_jobs_metadata": [ {job_id, status, ...} ]} (queues.py:
    # 547/605/636). Regular users get self-owned jobs — the submitter owns the
    # pr- job, so a self-filtered read finds it.
    r = requests.get(
        f"{base}/api/get-queue/{name}",
        headers = { "Authorization": f"Bearer {jwt}" },
        timeout = 15,
    )
    if r.status_code != 200:
        return []
    body = r.json()
    if isinstance( body, dict ):
        return body.get( f"{name}_jobs_metadata", [] ) or []
    return body or []


def _find( jobs, job_id ):
    for j in jobs:
        if job_id in ( j.get( "job_id" ), j.get( "id_hash" ), j.get( "id" ) ):
            return j
    return None


def read_notification_state( base, jwt, nid ):
    """
    Read the state and response value of one gate notification without changing anything.

    Calls GET /api/notifications/response/{id} and returns state, response_value and responded_at.
    State responded with a real response_value means a human answered; state expired means a
    declared-default timeout. This is the Direction-A discriminator, read server-side without
    container logs.
    """
    try:
        r = requests.get(
            f"{base}/api/notifications/response/{nid}",
            headers = { "Authorization": f"Bearer {jwt}" },
            timeout = 12,
        )
        if r.status_code != 200:
            return { "state": f"HTTP {r.status_code}", "response_value": None }
        return r.json()
    except Exception as e:
        return { "state": f"ERR {e}", "response_value": None }


def pool_status( base, jwt ):
    r = requests.get(
        f"{base}/api/queue/pool-status",
        headers = { "Authorization": f"Bearer {jwt}" },
        timeout = 15,
    )
    r.raise_for_status()
    return r.json()


def require_lock_clear( base, jwt ):
    """
    Refuse to submit while any monopolizer holds the pool; return the pool status otherwise.

    This is a hard precondition. A directly submitted non-monopolize pr- job is deferred as
    foreign intake while any monopolizer holds the pool (queue_consumer.py:106-124, Gate B).
    That mechanism wedged an earlier run that went from a ts- job to a pr- job.
    Raises RuntimeError unless monopolize_id is null, because otherwise the run silently
    deadlocks and burns the window of about 15 minutes.
    """
    ps = pool_status( base, jwt )
    mono_id = ps.get( "monopolize_id" )
    if ps.get( "monopolize_inflight" ) or mono_id:
        raise RuntimeError(
            f"REFUSING to submit: a monopolizer holds the :8000 lock "
            f"(monopolize_id={mono_id}). A foreign pr- would be deferred forever. "
            f"Clear the monopolizer first, then re-run."
        )
    return ps


def lock_clear_banner( ps ):
    """
    Return the banner line that reports the monopolize-slot check and its blind spot.

    `require_lock_clear` reads one field. It answers whether Gate B will defer this foreign
    pr- job, an identity question about the monopolize slot, not whether :8000 is free.
    Shared-pool jobs can be inflight and more queued behind them with the slot clear, and
    this precondition cannot see any of it. The line therefore names the field it read and
    names the blind spot. The venue question is answered by list-pending, per the testing
    venues section of CLAUDE.md.
    """
    return (
        f"[proof] no monopolizer holds the :8000 slot "
        f"(monopolize_id={ps.get( 'monopolize_id' )}) -- Gate B will not defer us. "
        f"NOT an idle-venue check: queued/pending shared-pool work is unread here."
    )


def poll_until_terminal( base, jwt, job_id, overall_timeout, on_tick=None ):
    """
    Poll the run, done and dead queues until the job is done or dead, or time runs out.

    Returns a tuple of the state ("done", "dead" or "timeout") and the job dict or None.
    """
    deadline = time.monotonic() + overall_timeout
    seen_running = False
    while time.monotonic() < deadline:
        done = _find( _queue( base, jwt, "done" ), job_id )
        if done:
            return ( "done", done )
        dead = _find( _queue( base, jwt, "dead" ), job_id )
        if dead:
            return ( "dead", dead )
        running = _find( _queue( base, jwt, "run" ), job_id )
        if running and not seen_running:
            seen_running = True
        if on_tick:
            on_tick( seen_running )
        time.sleep( 5 )
    return ( "timeout", None )


# ── verdict (Direction A — human-answered) ────────────────────────────────────
def build_verdict_direction_a( silent, job_state, job, gate_states ):
    """
    Build the Direction-A verdict: did every gate reach the client and get a human answer?

    Direction A is the path nobody had seen work. The gate reaches a connected client and the
    job proceeds on the human's answer, not a declared default.

    Ensures:
      - The discriminator is not timing, since an answered gate and a pre-fix TypeError gate
        both resolve fast. It is the final notification state: responded with a real
        response_value means a human answer, and expired means a declared-default timeout.
      - Every gate must be delivered (frame), answered (POST 200) and resolved as responded.
      - The job must reach done.
      - gate_states maps each delivered notification_id to its read state and response_value.
    """
    live         = silent.liveness_report()
    deliveries   = silent.deliveries
    delivered_ids = [ d[ "notification_id" ] for d in deliveries if d[ "notification_id" ] ]
    answered_ids  = [ a[ "notification_id" ] for a in silent.answers_posted if a[ "status" ] == 200 ]

    per_gate = []
    for d in deliveries:
        nid = d[ "notification_id" ]
        st  = ( gate_states.get( nid ) or {} ).get( "state" )
        per_gate.append( {
            "notification_id" : nid,
            "title"           : d[ "title" ],
            "delivered_ts"    : d[ "ts" ],
            "answered"        : nid in answered_ids,
            "state"           : st,
            "response_value"  : ( gate_states.get( nid ) or {} ).get( "response_value" ),
        } )

    checks = {
        "delivered"              : len( deliveries ) >= 1,
        "connected_through_wait" : ( live[ "dropped_at" ] is None
                                     and live[ "max_gap_seconds" ] <= MAX_LIVENESS_GAP ),
        "every_gate_answered"    : bool( delivered_ids ) and set( delivered_ids ) <= set( answered_ids ),
        # THE Direction-A discriminator: every delivered gate resolved by a HUMAN
        # answer (state 'responded'), never a declared-default 'expired'.
        "every_gate_human_resolved" : bool( delivered_ids ) and all(
            ( gate_states.get( nid ) or {} ).get( "state" ) == "responded" for nid in delivered_ids
        ),
        "job_reached_done"       : job_state == "done",
    }

    return {
        "PASS"             : all( checks.values() ),
        "direction"        : "A (human-answered)",
        "checks"           : checks,
        "gates_delivered"  : len( deliveries ),
        "gates_answered"   : len( answered_ids ),
        "per_gate"         : per_gate,
        "answers_posted"   : silent.answers_posted,
        "job_completed_at" : job.get( "completed_at" ) if job else None,
        "liveness"         : live,
        "job_state"        : job_state,
    }


def main():
    ap = argparse.ArgumentParser( description="Prove the presentation gate 600s-silence path." )
    ap.add_argument( "--base", default=DEFAULT_BASE )
    ap.add_argument( "--source", default=DEFAULT_SOURCE )
    ap.add_argument( "--email", default=f"arnold.gate.proof+{uuid.uuid4().hex[:8]}@lupin.deepily.ai" )
    ap.add_argument( "--evidence", default=None, help="path to write the evidence JSON" )
    ap.add_argument( "--build-timeout", type=int, default=1500,
                     help="overall seconds to wait (Direction A answers gates promptly ~7-10min)" )
    ap.add_argument( "--force", action="store_true",
                     help="skip the monopolizer-lock precondition (deliberate override only)" )
    args = ap.parse_args()

    run_start = _now()
    password  = _strong_password()
    print( f"[proof] base={args.base}  target/submitter={args.email}" )

    jwt, email, user_id = register_and_login( args.base, args.email, password )
    print( f"[proof] authenticated user_id={user_id}" )

    # HARD precondition — a monopolizer holding the lock would defer our foreign
    # pr- forever (Gate B, queue_consumer.py:106-124). Verify BEFORE spending the
    # window. --force only for a deliberate override.
    if not args.force:
        ps = require_lock_clear( args.base, jwt )
        print( lock_clear_banner( ps ) )
    else:
        print( "[proof] --force: skipping lock-clear precondition" )

    # Programmatic session id: ^[a-z][a-z0-9]*-[a-z0-9-]{1,47}$ (is_valid_session_id,
    # websocket.py:179). Spaces/uppercase fail it → close-before-accept → 403.
    session_id = f"arnold-gate-{uuid.uuid4().hex[:8]}"
    silent = SilentConnectedUser( args.base, session_id, jwt, answer_mode=True )
    silent.start()
    print( f"[proof] connected WS as {email} (session '{session_id}') — ANSWER mode" )

    job_id = submit_build( args.base, jwt, args.source )
    print( f"[proof] submitted real build job_id={job_id} — will ANSWER every gate 'Approve'" )

    def tick( seen_running ):
        n = len( silent.deliveries )
        drop = silent.liveness_report()[ "dropped_at" ]
        print( f"[proof] running={seen_running} gates_delivered={n} ws_dropped={drop}", flush=True )

    state, job = poll_until_terminal( args.base, jwt, job_id, args.build_timeout, on_tick=tick )
    print( f"[proof] job terminal state={state}" )

    silent.stop()

    # Read each delivered gate's final resolution — 'responded' (human) vs
    # 'expired' (declared default). This is the Direction-A discriminator.
    gate_states = {}
    for d in silent.deliveries:
        nid = d[ "notification_id" ]
        if nid:
            gate_states[ nid ] = read_notification_state( args.base, jwt, nid )
            print( f"[proof] gate {d.get('title')} nid={nid} -> state={gate_states[nid].get('state')}" )

    verdict = build_verdict_direction_a( silent, state, job, gate_states )

    evidence = {
        "row"          : "19328449-17eb-407c-95b6-4b9bcecca714",
        "run_start"    : _iso( run_start ),
        "run_end"      : _iso( _now() ),
        "base"         : args.base,
        "submitter"    : email,
        "target_user"  : email,
        "user_id"      : user_id,
        "job_id"       : job_id,
        "source_path"  : args.source,
        "thresholds"   : {
            "gate_timeout"     : GATE_TIMEOUT,
            "min_silence_secs" : MIN_SILENCE_SECS,
            "max_liveness_gap" : MAX_LIVENESS_GAP,
        },
        "verdict"      : verdict,
    }

    out = args.evidence or os.path.join(
        os.path.dirname( os.path.abspath( __file__ ) ),
        f"evidence-{run_start.strftime( '%Y%m%dT%H%M%SZ' )}.json",
    )
    with open( out, "w" ) as f:
        json.dump( evidence, f, indent=2 )

    print( "\n" + "=" * 72 )
    print( f"VERDICT: {'✅ PASS' if verdict[ 'PASS' ] else '❌ NOT PROVEN'}  (Direction A — human-answered)" )
    for k, v in verdict[ "checks" ].items():
        print( f"  {'✅' if v else '❌'}  {k}" )
    print( f"  gates delivered   : {verdict[ 'gates_delivered' ]}" )
    print( f"  gates answered    : {verdict[ 'gates_answered' ]}" )
    for g in verdict[ "per_gate" ]:
        print( f"    gate '{g['title']}' nid={g['notification_id']} answered={g['answered']} state={g['state']}" )
    print( f"  job state         : {verdict[ 'job_state' ]}  completed_at={verdict[ 'job_completed_at' ]}" )
    print( f"  ws max gap        : {verdict[ 'liveness' ][ 'max_gap_seconds' ]}s (max {MAX_LIVENESS_GAP}) dropped={verdict[ 'liveness' ][ 'dropped_at' ]}" )
    print( f"  evidence          : {out}" )
    print( "=" * 72 )

    return 0 if verdict[ "PASS" ] else 1


if __name__ == "__main__":
    sys.exit( main() )
