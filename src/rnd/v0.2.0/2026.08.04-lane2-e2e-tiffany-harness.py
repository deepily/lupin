#!/usr/bin/env python3
"""
Lane 2 podcast E2E — voice-driven, vague-file, WS-held-open auto-answer harness.
Row 68198c9f (Thursday demo acceptance gate). Author: Tiffany 💍.

Drives the ACTUAL demo path on :7999:
  POST /api/mode/current {mode:"podcast"}  (the "Podcast Generator" dropdown)
  → POST through the live DOOR (LANE2_DOOR / --door: auto|v1|v2, default auto):
      v1 = /api/push {question, websocket_id}   (retired on the v2-cutover branch → 410)
      v2 = /api/v2/ask {question, websocket_id, interactive} — a parked ask is
           answered through /api/v2/resume with the same vague doc description
      auto = v1, and on a 410 switch to v2 and SAY SO. A rejected push fails
           stage 1 and ends the run at once (row c84e9313: the old loop waited
           the full 1200s on a job that was never created).
  → auto-answers every interactive ask over a LIVE websocket (the thing a
    remote voice user provides and the test-user account normally lacks)
  → polls to terminal, verifies the artifact is genuinely about the seed.

WHY A SEED: the podcast expeditor's fuzzy file match searches the POSTER's own
io/deep-research/<email>/ dir, not a global corpus (search paths emptied by
config-mitigation 7e29bcfe). Rick's real KISS doc lives in HIS corpus; the test
user has none. So we seed a distinctively-named, content-checkable KISS doc into
the test user's dir and verify the finished podcast names its planted facts —
proving CONTENT, not filename.

Stages observed (row acceptance): 1 push accepted · 2 route→podcast generator ·
3 RAE resolves the vague description to the seed · 4 job created/running ·
5 job → done · 6 artifact genuinely about the seed.

VENUE: :7999 (per the row — live product path; NOT a /api/test-suite/submit
suite). dry_run defaults OFF on the API path → real audio.

Usage:
  source ~/.lupin/test-env.sh
  python lane2_e2e_tiffany.py            # full run to done
  python lane2_e2e_tiffany.py --no-seed  # skip seeding (use existing corpus)
  python lane2_e2e_tiffany.py --keep     # don't delete the seed/outputs at end
"""

import argparse
import json
import os
import sys
import threading
import time
from urllib.parse import urlparse

import requests

try:
    import websockets
    import asyncio
except ImportError:
    websockets = None

# ── Config ──────────────────────────────────────────────────────────────────
# Host/port are PARAMETERIZED (row c076245f). They were hardcoded to :7999, which
# is what made this harness impossible to submit as a gated :8000 suite — an
# ~11-minute, state-mutating, job-enqueuing run has to go where the venue rubric
# sends it, and it failed all three :7999 criteria. Hand-running it on the shared
# dev box once left a real pg- job orphaned there; it completed, but that was luck.
#
# LUPIN_API_URL sets everything: the websocket host and port are DERIVED from it,
# so there is no second knob to forget and no way to point HTTP at one server while
# the socket listens to another. Default stays :7999 so existing hand-runs are
# unchanged.
BASE_HTTP   = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" ).rstrip( "/" )
_parsed     = urlparse( BASE_HTTP )
WS_HOST     = _parsed.hostname or "localhost"
WS_PORT     = _parsed.port or ( 443 if _parsed.scheme == "https" else 80 )
WS_SCHEME   = "wss" if _parsed.scheme == "https" else "ws"
SESSION_ID  = "tiffany-lane2-e2e"
MODE        = "podcast"          # the "Podcast Generator" dropdown

# TIMEOUT_S was 720 (12 min) and that number could not observe its own subject
# (row 1cd30181). The podcast chain contains a script-review gate that the test
# user never receives, so the job only advances when that gate AUTO-APPROVES;
# measured completions land ~733s — about 13 seconds past the old cutoff. The
# harness therefore stopped watching a few seconds before the product finished
# and reported the product broken.
#
# Raising the number is necessary and NOT sufficient. A wider window alone just
# converts a false FAIL into a false PASS on the next slow run. The actual fix is
# the three-state stage table below: an expiry is INCONCLUSIVE, never FAIL and
# never PASS. This value only has to be generous enough that INCONCLUSIVE is rare
# — correctness no longer depends on it being exactly right.
TIMEOUT_S   = int( os.environ.get( "LANE2_TIMEOUT_S", "1200" ) )   # 20 min
POLL_EVERY  = 3

# Stage-3 evidence is a log grep. Its window used to be a hardcoded `--since 10m`
# evaluated AFTER the poll loop, so on any run longer than 10 minutes the
# "Initialized for" line — written at push time — had already aged out of the
# window before it was ever looked for. The window is now derived from the
# harness's own start time (see doc_resolved_from_logs), plus this slack.
LOG_WINDOW_SLACK_S = 120

# The three stage states. A stage is INCONCLUSIVE until the harness actually
# observes something; it must EARN a PASS and equally must EARN a FAIL.
PASS         = "PASS"
FAIL         = "FAIL"
INCONCLUSIVE = "INCONCLUSIVE"

# find_job sentinel: "I could not ask the server", which is NOT "the job is absent".
UNOBSERVED = object()

# The vague request — verbatim from the row.
VAGUE_QUESTION = (
    "build me a podcast based on the contents of an explainer document that "
    "discusses the KISS protocol and how it saved me a ton of tokens on a daily basis"
)
# The vague DESCRIPTION answered to the "which document?" ask (still vague — no
# path, no exact filename — so the fuzzy matcher is exercised, not bypassed).
VAGUE_DOC_DESC = "the explainer about the KISS protocol and how it saved a ton of tokens"

# ── The seed — distinctive, checkable facts (a ham-radio-trap defeater) ──────
SEED_EMAIL    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "" )
SEED_FILENAME = "2026.08.04-kiss-protocol-brevity-token-savings-explainer.md"
SEED_FACTS = {
    "coined_by"   : "Thelonius Quirke",
    "year"        : "2019",
    "acronym"     : "Keep It Short and Sweet",
    "savings_pct" : "fifty-eight percent",
    "codename"    : "Project Marble Fountain",
    "catchphrase" : "say it once, say it small",
}
SEED_BODY = f"""# The KISS Protocol — How a Brevity Mandate Saved a Ton of Tokens

_A fictional explainer seeded for E2E test row 68198c9f. Every proper noun here
is invented so the finished podcast can be verified by CONTENT, not filename._

## Origin

The KISS protocol ("{SEED_FACTS['acronym']}") was coined by **{SEED_FACTS['coined_by']}**
in **{SEED_FACTS['year']}** under the internal codename **{SEED_FACTS['codename']}**.
Its whole discipline reduces to one line: **"{SEED_FACTS['catchphrase']}."**

## What it does

Every message leads with the verdict, gives at most two supporting sentences,
and stops. Detail is routed to a structured side-card, never to prose. The rule
bans preambles, restated questions, apologies, and self-summary.

## The token savings

Measured across a daily workload, the mandate cut token spend by
**{SEED_FACTS['savings_pct']}** — the headline figure {SEED_FACTS['coined_by']}
reported the quarter after {SEED_FACTS['codename']} shipped. The savings came
almost entirely from killing the three-paragraph windup before the point.

## Why it holds

A finding stated as a mechanism survives at any stakes level; a finding dressed
as drama gets discounted the moment the stakes turn out lower. Brevity is a
control, not a style — {SEED_FACTS['coined_by']}'s core claim.
"""


# ── Auto-answer logic ───────────────────────────────────────────────────────
def choose_answer( note ):
    """
    Given a response-requested notification dict, return the response_value to
    POST to /api/notify/response. Answers by response_type + content.
    """
    rtype = ( note.get( "response_type" ) or "" ).lower()
    title = ( note.get( "title" ) or "" ).lower()
    msg   = ( note.get( "message" ) or "" )
    opts_raw = note.get( "response_options" )

    # open_ended_batch → {"answers": {header: value}} using each default,
    # but force ONE language to keep the run to a single TTS render.
    if rtype == "open_ended_batch":
        answers = {}
        questions = _parse_questions( opts_raw )
        for q in questions:
            header = q.get( "header" )
            default = q.get( "default_value", "" )
            if header == "languages":
                answers[ header ] = "en"
            elif header == "audience":
                answers[ header ] = "expert"
            elif header == "audience_context":
                answers[ header ] = "none"
            else:
                answers[ header ] = default or "none"
        return json.dumps( { "answers": answers } )

    # The single "which document?" ask arrives as open_ended (one question) or
    # a bare open_ended text ask. Answer with the vague KISS description.
    if "document" in msg.lower() or "which document" in title:
        return VAGUE_DOC_DESC

    # Multi-match pick — pick the candidate mentioning our seed's token.
    if "multiple matches" in msg.lower() or "say the number" in msg.lower():
        # Prefer the one that looks like our seed; else "1".
        if "kiss" in msg.lower():
            # find "N. ...kiss..." — cheap: answer the seed filename fragment
            return "kiss-protocol"
        return "1"

    # yes_no — approve the post-generation script gate.
    if rtype == "yes_no":
        return "yes"

    # multiple_choice — this is the ROUTING-CONFIRM ("I think you want ...").
    # On the PURE-VOICE path we must land on the podcast-generator (doc-resolution)
    # product, NOT research-to-podcast. Prefer the Doc-to-Pod (podcast generator)
    # option; NEVER pick "Cancel"; fall back to the detected option[0].
    # NOTE (label swap fc8990c6): "PodMaker" is now research-to-podcast — match
    # "doc-to-pod", never "podmaker".
    if rtype == "multiple_choice":
        questions = _parse_questions( opts_raw )
        if questions:
            options = questions[ 0 ].get( "options", [] )
            for o in options:
                lab = ( o.get( "label", "" ) ).lower()
                if "doc-to-pod" in lab or "podcast generator" in lab:
                    return o.get( "label" )
            for o in options:
                if "kiss" in ( o.get( "label", "" ) ).lower():
                    return o.get( "label" )
            for o in options:
                if "cancel" not in ( o.get( "label", "" ) ).lower():
                    return o.get( "label" )
        return "yes"

    # open_ended fallback — echo the vague description.
    return VAGUE_DOC_DESC


def _parse_questions( opts_raw ):
    if not opts_raw:
        return []
    try:
        d = json.loads( opts_raw ) if isinstance( opts_raw, str ) else opts_raw
        return d.get( "questions", [] )
    except Exception:
        return []


# ── WebSocket listener thread ───────────────────────────────────────────────
class WsAutoAnswer:
    def __init__( self, jwt, headers, log ):
        self.jwt      = jwt
        self.headers  = headers
        self.log      = log
        self.answered = []
        self.job_id   = None      # THIS run's pg- id, captured from ws events
        self.authed   = False     # did the socket ever successfully authenticate?
        self.error    = None      # why the listener died, if it did
        self._running = True
        self._thread  = None

    def start( self ):
        self._thread = threading.Thread( target=self._run, daemon=True )
        self._thread.start()

    def stop( self ):
        self._running = False

    def is_alive( self ):
        """
        True iff the auto-answer listener is still running.

        This harness's whole premise is that it supplies the live websocket a
        remote voice user would supply. If this thread dies, every interactive ask
        goes unanswered and the job stalls — which looks EXACTLY like a product
        that never finished. The failure that costs the most produces no signal at
        all, so the harness watches its own observer for disappearing, not just for
        writing.
        """
        return self._thread is not None and self._thread.is_alive()

    def _run( self ):
        asyncio.set_event_loop( asyncio.new_event_loop() )
        asyncio.get_event_loop().run_until_complete( self._listen() )

    async def _listen( self ):
        from urllib.parse import quote
        uri = f"{WS_SCHEME}://{WS_HOST}:{WS_PORT}/ws/queue/{quote( SESSION_ID )}"
        try:
            async with websockets.connect( uri, max_size=None ) as ws:
                await ws.send( json.dumps( {
                    "type"              : "auth_request",
                    "token"             : f"Bearer {self.jwt}",
                    "session_id"        : SESSION_ID,
                    "subscribed_events" : [ "notification_queue_update", "job_state_transition" ],
                } ) )
                auth = json.loads( await asyncio.wait_for( ws.recv(), timeout=10 ) )
                self.log( f"[ws] auth: {auth.get('type')}" )
                self.authed = True
                while self._running:
                    try:
                        raw = await asyncio.wait_for( ws.recv(), timeout=2 )
                    except asyncio.TimeoutError:
                        continue
                    try:
                        evt = json.loads( raw )
                    except Exception:
                        continue
                    etype = evt.get( "type" ) or evt.get( "event" )
                    data  = evt.get( "data", evt )
                    if etype == "sys_ping":
                        await ws.send( json.dumps( { "type": "sys_pong" } ) )
                        continue
                    if etype == "job_state_transition":
                        jid = data.get( "job_id" ) or ""
                        # Capture pg- (podcast generator = doc-resolution path) OR
                        # rp- (research-to-podcast = the ROUTING MISS). Recording
                        # which prefix appears IS the stage-2 evidence.
                        if ( jid.startswith( "pg-" ) or jid.startswith( "rp-" ) ) and self.job_id is None:
                            self.job_id = jid
                            self.log( f"[ws] captured THIS run's job_id: {jid}" )
                        self.log( f"[ws] job {jid}: {data.get('from_queue')}→{data.get('to_queue')}" )
                        continue
                    if etype == "notification_queue_update":
                        self._maybe_answer( data )
        except Exception as e:
            # Record it, do not just print it. A one-line error at second 5 scrolls
            # away and the run then looks like a product timeout for the next 20
            # minutes. main() reads this field and reports INCONCLUSIVE instead.
            self.error = repr( e )
            self.log( f"[ws] listener DIED: {e} — auto-answer is no longer running" )

    def _maybe_answer( self, data ):
        note = data.get( "notification", data )
        nid  = note.get( "id_hash" ) or note.get( "notification_id" ) or note.get( "id" )
        if not note.get( "response_requested" ) or not nid:
            return
        if nid in [ a[ 0 ] for a in self.answered ]:
            return
        answer = choose_answer( note )
        # Announce the ACTUAL answer value — a stale binary that confirmed the
        # wrong option must be visible in the log, not hidden behind "answering".
        self.log( f"[ws] ASK [{note.get('response_type')}] '{(note.get('message') or '')[:50]}' → ANSWER={str(answer)[:70]}" )
        try:
            r = requests.post(
                f"{BASE_HTTP}/api/notify/response",
                json={ "notification_id": nid, "response_value": answer },
                headers=self.headers, timeout=15,
            )
            self.answered.append( ( nid, r.status_code ) )
            self.log( f"[ws] answered {nid[:8]} → HTTP {r.status_code}" )
        except Exception as e:
            self.log( f"[ws] answer POST failed: {e}" )


# ── Helpers ─────────────────────────────────────────────────────────────────
LOGS = []
class _FailFast( Exception ):
    """Raised when the run has already earned its verdict and there is nothing left
    to watch — a rejected push, or a v2 body that is terminal without a job. The
    pre-c84e9313 harness sat out the full TIMEOUT_S after a 410, then reported the
    wait as if it had been watching something."""


def push_v1( question, headers ):
    """POST /api/push (the v1 door). Returns ( status_code, body )."""
    r = requests.post( f"{BASE_HTTP}/api/push",
                       json={ "question": question, "websocket_id": SESSION_ID },
                       headers=headers, timeout=180 )
    try:
        body = r.json()
    except ValueError:
        body = {}
    log( f"push[v1 /api/push]: {r.status_code} job_id={body.get('job_id')} "
         f"result={str( body.get( 'result', body.get( 'detail', '' ) ) )[:100]}" )
    return r.status_code, body


def push_v2( question, headers ):
    """POST /api/v2/ask (the v2 door), interactive. Returns ( status_code, body ).

    The v2 flow does not run the v1 expeditor's websocket asks; a missing argument
    PARKS the request (status='parked', pending_id). That park is the v2 spelling of
    the "which document?" ask, so it is answered the same way the WS auto-answer
    does — with VAGUE_DOC_DESC, still no path and no exact filename — through
    /api/v2/resume, up to four turns.
    """
    r = requests.post( f"{BASE_HTTP}/api/v2/ask",
                       json={ "question": question, "websocket_id": SESSION_ID,
                              "interactive": True, "speak": False },
                       headers=headers, timeout=180 )
    try:
        body = r.json()
    except ValueError:
        body = {}
    log( f"push[v2 /api/v2/ask]: {r.status_code} path={body.get('path')} status={body.get('status')} "
         f"route_reason={body.get('route_reason')} command={body.get('command')} job_id={body.get('job_id')}" )
    turns = 0
    while r.status_code == 200 and body.get( "status" ) == "parked" and body.get( "pending_id" ) and turns < 4:
        turns += 1
        log( f"  parked on {body.get('args_missing')} → /api/v2/resume answer={VAGUE_DOC_DESC!r}" )
        r = requests.post( f"{BASE_HTTP}/api/v2/resume",
                           json={ "pending_id": body[ "pending_id" ], "answer": VAGUE_DOC_DESC, "speak": False },
                           headers=headers, timeout=180 )
        try:
            body = r.json()
        except ValueError:
            body = {}
        log( f"  resume[{turns}]: {r.status_code} path={body.get('path')} status={body.get('status')} "
             f"route_reason={body.get('route_reason')} command={body.get('command')} job_id={body.get('job_id')}" )
    return r.status_code, body


def push_through_door( door, question, headers ):
    """Post the utterance through the selected door. Returns ( body, status_code, door_used ).

    door: "v1" | "v2" | "auto". auto = v1 first; a 410 means the server has retired
    /api/push, so the harness switches to /api/v2/ask and logs the switch — it never
    silently assumes which contract it is testing.
    """
    if door == "v2":
        sc, body = push_v2( question, headers )
        return body, sc, "v2"
    sc, body = push_v1( question, headers )
    if sc == 410 and door == "auto":
        log( "door: /api/push is RETIRED on this server (410) — switching to /api/v2/ask (LANE2_DOOR=auto)" )
        sc, body = push_v2( question, headers )
        return body, sc, "v2"
    if sc == 410:
        log( "door: /api/push is RETIRED on this server (410) and the v1 door was FORCED — the instrument "
             "is pointed at a door that no longer exists. Re-run with LANE2_DOOR=auto or --door v2." )
    return body, sc, "v1"


def v2_route_verdict( body, results ):
    """Read stage 2 off the synchronous v2 body. Returns True when the body is
    TERMINAL WITHOUT A JOB — nothing will ever appear in a queue, so the caller
    must not sit out TIMEOUT_S waiting for it."""
    path   = body.get( "path" )
    status = body.get( "status" )
    cmd    = body.get( "command" ) or ""
    job_id = body.get( "job_id" ) or ""
    if path == "receptionist" or status in ( "rejected", "failed", "expired", "needs_input" ):
        log( f"ROUTING: v2 returned path={path} status={status} route_reason={body.get('route_reason')} "
             f"command={cmd!r} — NO job was created. (On a server whose ask door has no agentic "
             f"dispatch yet — bug b7fe8941 — a vague podcast question lands exactly here.)" )
        results[ "2_route_podcast" ] = FAIL
        return True
    if cmd == "agent router go to research to podcast":
        log( f"ROUTING MISS: v2 routed to research-to-podcast, NOT podcast generator (job_id={job_id or None})" )
        results[ "2_route_podcast" ] = FAIL
        return not job_id
    if cmd and cmd != "agent router go to podcast generator":
        log( f"ROUTING MISS: v2 routed to {cmd!r}, NOT podcast generator (job_id={job_id or None})" )
        results[ "2_route_podcast" ] = FAIL
        return not job_id
    if status == "done" and not job_id:
        log( "ROUTING: v2 answered 'done' inline with no job — the router did not hand this to the podcast generator" )
        results[ "2_route_podcast" ] = FAIL
        return True
    return False


def log( m ):
    ts = time.strftime( "%H:%M:%S" )
    line = f"{ts} {m}"
    LOGS.append( line )
    print( line, flush=True )


def login():
    email = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    pw    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not pw:
        log( "FATAL: creds not set — source ~/.lupin/test-env.sh" ); sys.exit( 2 )
    r = requests.post( f"{BASE_HTTP}/auth/login", json={ "email": email, "password": pw }, timeout=15 )
    r.raise_for_status()
    tok = r.json()[ "tokens" ][ "access_token" ]
    return email, tok, { "Authorization": f"Bearer {tok}", "X-Session-ID": SESSION_ID }


def project_root():
    return os.environ.get( "LUPIN_ROOT" ) or "/mnt/DATA01/include/www.deepily.ai/projects/lupin"


def seed_path():
    return os.path.join( project_root(), "io", "deep-research", SEED_EMAIL, SEED_FILENAME )


def write_seed():
    p = seed_path()
    os.makedirs( os.path.dirname( p ), exist_ok=True )
    with open( p, "w" ) as f:
        f.write( SEED_BODY )
    log( f"seed written: {p}" )


def remove_seed():
    try:
        os.remove( seed_path() )
        log( "seed removed" )
    except FileNotFoundError:
        pass


def find_job( headers, queue, job_id ):
    """
    Return THIS run's job from `queue`, matched on the EXACT job_id — never a
    loose `startswith pg-` (that matched a STALE prior-run job and false-failed).

    Ensures:
        - returns the job dict when the server answered AND the job is present
        - returns None when the server answered AND the job is genuinely absent
        - returns UNOBSERVED when the server could not be asked (non-200, timeout,
          connection error). This is NOT the same as absent, and collapsing the two
          is how a dead API reads as a product that never finished.
    """
    if not job_id:
        return None
    try:
        r = requests.get( f"{BASE_HTTP}/api/get-queue/{queue}", headers=headers, timeout=20 )
    except Exception as e:
        log( f"[observe] cannot reach /api/get-queue/{queue}: {e}" )
        return UNOBSERVED
    if r.status_code != 200:
        log( f"[observe] /api/get-queue/{queue} → HTTP {r.status_code} (not an answer about the job)" )
        return UNOBSERVED
    for j in r.json().get( f"{queue}_jobs_metadata", [] ):
        if j.get( "job_id", "" ) == job_id:
            return j
    return None


# ── Main ────────────────────────────────────────────────────────────────────
def _retarget( base_url ):
    """
    Point the harness at a different server (row c076245f).

    Rebinds BASE_HTTP and every websocket field DERIVED from it, together, so the
    HTTP calls and the socket can never end up on different servers — that split is
    the failure this function exists to make impossible.

    Requires:
        - base_url is an absolute http(s) URL, e.g. "http://localhost:8000"

    Ensures:
        - BASE_HTTP / WS_HOST / WS_PORT / WS_SCHEME all describe the same target
        - a trailing slash is tolerated
    """
    global BASE_HTTP, WS_HOST, WS_PORT, WS_SCHEME
    BASE_HTTP = base_url.rstrip( "/" )
    parsed    = urlparse( BASE_HTTP )
    WS_HOST   = parsed.hostname or "localhost"
    WS_PORT   = parsed.port or ( 443 if parsed.scheme == "https" else 80 )
    WS_SCHEME = "wss" if parsed.scheme == "https" else "ws"


def main( argv ):
    ap = argparse.ArgumentParser()
    ap.add_argument( "--no-seed",  action="store_true" )
    ap.add_argument( "--keep",     action="store_true" )
    ap.add_argument( "--no-mode",  action="store_true", help="PURE-VOICE path: do NOT set the dropdown mode (the actual Thursday demo path)" )
    ap.add_argument( "--question", default=VAGUE_QUESTION, help="override the posted utterance (use Rachel's measured no-mode candidate)" )
    ap.add_argument( "--base-url", default=None, help="target server, e.g. http://localhost:8000 (overrides LUPIN_API_URL; default :7999)" )
    ap.add_argument( "--door", choices=[ "auto", "v1", "v2" ], default=None, help="which push door to test: v1=/api/push, v2=/api/v2/ask, auto=v1 then v2 on a 410 (default; or env LANE2_DOOR)" )
    args = ap.parse_args( argv )

    if args.base_url:
        _retarget( args.base_url )
    log( f"target: {BASE_HTTP} (ws {WS_SCHEME}://{WS_HOST}:{WS_PORT})" )

    if websockets is None:
        log( "FATAL: `websockets` not importable in this interpreter" ); return 2

    # ── HARNESS CONFIG BANNER ──────────────────────────────────────────────
    # A stale binary cannot report a fresh claim if it must first declare what
    # it is about to do. Mr Radio's hazard (2026-08-04): a preempted edit runs
    # the OLD path silently. This banner + the per-answer ANSWER= log make the
    # actual configuration and every confirmed option visible in the run log.
    log( "═══ HARNESS CONFIG ═══" )
    log( f"  PATH        : {'PURE VOICE (no mode) — the Thursday demo path' if args.no_mode else 'DROPDOWN (mode=' + MODE + ')'}" )
    door = ( args.door or os.environ.get( "LANE2_DOOR", "auto" ) ).lower()
    log( f"  DOOR        : {door} (v1=/api/push · v2=/api/v2/ask · auto=v1, then v2 on a 410)" )
    log( f"  QUESTION    : {args.question[:80]}" )
    log( f"  SEED        : {'OFF (--no-seed)' if args.no_seed else 'ON (' + SEED_FILENAME + ')'}" )
    log( f"  CONFIRM     : multiple_choice → prefer 'Doc-to-Pod' (podcast generator); open_ended_batch → defaults, languages=en" )
    log( "══════════════════════" )

    results = {}
    email, jwt, headers = login()
    log( f"logged in as {email}" )
    # Every stage starts INCONCLUSIVE, not False. This is the fix for row 1cd30181,
    # and it is the part that matters more than the timeout. Under the old table a
    # stage the harness never managed to observe was indistinguishable from a stage
    # it observed to be broken — both printed FAIL — so an instrument that stopped
    # watching too early accused the product. A stage now has to be EARNED in both
    # directions: PASS on positive evidence, FAIL on evidence of the negative, and
    # INCONCLUSIVE whenever the harness simply could not tell.
    results[ "1_push_accepted" ] = INCONCLUSIVE
    results[ "2_route_podcast" ] = INCONCLUSIVE
    results[ "3_doc_resolved" ]  = INCONCLUSIVE
    results[ "4_job_running" ]   = INCONCLUSIVE
    results[ "5_job_done" ]      = INCONCLUSIVE
    results[ "6_content_ok" ]    = INCONCLUSIVE

    if not args.no_seed:
        write_seed()

    # Stamped BEFORE anything is pushed, so the stage-3 log window can be derived
    # from the real age of this run instead of a fixed guess.
    run_started = time.monotonic()

    # WS auto-answer up first, so asks are deliverable the instant they fire.
    ws = WsAutoAnswer( jwt, { "Authorization": f"Bearer {jwt}" }, log )
    ws.start()
    time.sleep( 2 )

    try:
        if args.no_mode:
            log( "PURE-VOICE path: NO mode set (the actual Thursday demo path)" )
        else:
            m = requests.post( f"{BASE_HTTP}/api/mode/current", json={ "mode": MODE }, headers=headers, timeout=10 )
            log( f"mode set: {m.status_code} {m.json().get('display_name','?')}" )

        push, push_status, door_used = push_through_door( door, args.question, headers )
        results[ "1_push_accepted" ] = PASS if push_status == 200 else FAIL
        if results[ "1_push_accepted" ] == FAIL:
            # Nothing was accepted, so nothing will ever reach a queue. Waiting TIMEOUT_S
            # here is what turned a 410 into a 1200-second "product" red (row c84e9313).
            raise _FailFast( f"push rejected by the {door_used} door: HTTP {push_status}" )
        terminal_without_job = door_used == "v2" and v2_route_verdict( push, results )

        # The push response's job_id is often null even though the job exists;
        # the AUTHORITATIVE id for THIS run is the one the ws watched get created.
        # Wait briefly for the ws to capture it, then scope every poll to it.
        pj = push.get( "job_id" ) or ""
        job_id = pj if ( pj.startswith( "pg-" ) or pj.startswith( "rp-" ) ) else None
        waited = 0
        while job_id is None and ws.job_id is None and waited < 20:
            time.sleep( 1 ); waited += 1
        job_id = job_id or ws.job_id
        log( f"scoped to job_id: {job_id}" )
        # Stage 2 = routed to the PODCAST GENERATOR (pg-), the doc-resolution path.
        # An rp- job means the router picked research-to-podcast — a routing MISS.
        if job_id and job_id.startswith( "pg-" ):
            results[ "2_route_podcast" ] = PASS
        elif job_id and job_id.startswith( "rp-" ):
            log( f"ROUTING MISS: got {job_id[:12]} (research-to-podcast), NOT podcast generator" )
            results[ "2_route_podcast" ] = FAIL
        else:
            # No job id at all. We never saw the router decide, so we do not know
            # what it decided. That is not a routing failure.
            log( "no job_id captured — routing was never observed" )
        if terminal_without_job and not job_id:
            raise _FailFast( "the v2 door answered terminally without creating a job — there is nothing in any queue to watch" )

        # Poll for terminal — scoped to THIS run's exact job_id.
        #
        # The clock is now WALL CLOCK (time.monotonic), not a counter incremented by
        # POLL_EVERY. The old loop added 3 per iteration while each iteration also
        # made up to three HTTP calls with a 20s timeout apiece, so `elapsed` was not
        # seconds and the harness could not state its own cutoff.
        deadline   = time.monotonic() + TIMEOUT_S
        started_at = time.monotonic()
        done_job = dead_job = None
        timed_out = False
        observation_failures = 0
        while True:
            if time.monotonic() >= deadline:
                timed_out = True
                break
            d = find_job( headers, "done", job_id )
            if d is UNOBSERVED:
                observation_failures += 1
            elif d:
                done_job = d
                break
            else:
                x = find_job( headers, "dead", job_id )
                if x is UNOBSERVED:
                    observation_failures += 1
                elif x:
                    dead_job = x
                    break
                else:
                    running = find_job( headers, "run", job_id )
                    if running is UNOBSERVED:
                        observation_failures += 1
                    elif running:
                        results[ "4_job_running" ] = PASS
            # The auto-answer socket is this harness's reason for existing. If it
            # died, every later ask goes unanswered and the job stalls — a stall we
            # would otherwise report as the product failing to finish.
            if not ws.is_alive():
                log( "[observe] auto-answer listener is gone; remaining asks cannot be answered" )
                break
            time.sleep( POLL_EVERY )
        waited = int( time.monotonic() - started_at )

        # Stage 3 is proven INDEPENDENTLY of completion: the orchestrator logs
        # the exact source file it resolved. Never infer resolution from the
        # content check (that needs stage 5 done — a name that would claim more
        # than the test proves).
        results[ "3_doc_resolved" ] = doc_resolved_from_logs( run_started_monotonic=run_started )

        # An observer that stopped watching, or that never authenticated, cannot
        # convict the product of anything.
        observer_broken = ( not ws.authed ) or ( ws.error is not None ) or observation_failures > 0
        if observer_broken:
            log( f"[observe] OBSERVER DEGRADED — ws_authed={ws.authed} ws_error={ws.error} "
                 f"unanswerable_queue_reads={observation_failures}" )

        if done_job:
            results[ "2_route_podcast" ] = PASS
            results[ "5_job_done" ] = PASS
            log( f"JOB DONE after {waited}s: {done_job.get('job_id')}" )
            results[ "6_content_ok" ] = verify_content( headers, done_job )
        elif dead_job:
            results[ "2_route_podcast" ] = PASS
            err = dead_job.get( "error" ) or dead_job.get( "response_text" ) or ""
            transient = any( s in err.lower() for s in ( "try again in a few minutes", "rate limit", "returned an error while writing" ) )
            tag = "TRANSIENT (phi-4 rate limit — retry, NOT a chain defect)" if transient else "DEFECT"
            log( f"JOB DEAD [{tag}]: {dead_job.get('job_id')} err={err}" )
            # A dead job is a real, observed negative — the one case that earns a FAIL.
            # A transient upstream rate limit is not the chain being broken, so it stays
            # INCONCLUSIVE rather than convicting the product.
            results[ "5_job_done" ]   = INCONCLUSIVE if transient else FAIL
            results[ "6_content_ok" ] = INCONCLUSIVE
        elif timed_out:
            # THE CASE THIS WHOLE ROW IS ABOUT. The harness stopped watching before
            # the product finished. It does not know how the job ended, so it says so.
            log( f"STOPPED WATCHING after {waited}s (limit {TIMEOUT_S}s) — the job had "
                 f"not reached a terminal queue YET. This is the harness running out "
                 f"of patience, NOT the product failing. Raise LANE2_TIMEOUT_S." )
            results[ "5_job_done" ]   = INCONCLUSIVE
            results[ "6_content_ok" ] = INCONCLUSIVE
        else:
            log( f"stopped watching after {waited}s — observer unavailable" )
            results[ "5_job_done" ]   = INCONCLUSIVE
            results[ "6_content_ok" ] = INCONCLUSIVE

        if results[ "4_job_running" ] == INCONCLUSIVE and results[ "5_job_done" ] == PASS:
            # A job in the done queue necessarily passed through the run queue; we
            # just polled either side of it. Left INCONCLUSIVE, this would report
            # exit 2 on a run where the product did everything right — a false
            # inconclusive is a smaller lie than a false FAIL, but it is still a
            # lie about what the harness knows.
            log( "4_job_running: never caught mid-flight, but the job reached done — "
                 "it cannot have finished without running" )
            results[ "4_job_running" ] = PASS

        if observer_broken:
            for k in ( "3_doc_resolved", "5_job_done", "6_content_ok" ):
                if results[ k ] == FAIL:
                    log( f"[observe] downgrading {k} FAIL→INCONCLUSIVE: the observer was degraded, "
                         f"so this red is not trustworthy" )
                    results[ k ] = INCONCLUSIVE

    except _FailFast as e:
        log( f"FAIL-FAST: {e} — ending the run now instead of watching for {TIMEOUT_S}s" )
    finally:
        ws.stop()
        try:
            requests.post( f"{BASE_HTTP}/api/mode/current", json={ "mode": None }, headers=headers, timeout=10 )
        except Exception:
            pass
        if not args.keep and not args.no_seed:
            remove_seed()

    # Report
    print( "\n" + "=" * 70 )
    print( "  LANE 2 E2E — STAGE TABLE (row 68198c9f)" )
    print( "=" * 70 )
    for k in sorted( results.keys() ):
        print( f"  {results[k]:<13}{k}" )
    print( "=" * 70 )

    n_fail = sum( 1 for v in results.values() if v == FAIL )
    n_inc  = sum( 1 for v in results.values() if v == INCONCLUSIVE )
    n_pass = sum( 1 for v in results.values() if v == PASS )
    print( f"  {n_pass} passed · {n_fail} failed · {n_inc} inconclusive" )

    # Exit codes are three-valued for the same reason the table is.
    #   0 — every stage PASSED, and every one of them was actually observed.
    #   1 — the harness observed the product doing the wrong thing. A real red.
    #   2 — the harness could not tell. NOT a product verdict; look at the log.
    # 2 is deliberately non-zero: the pytest wrapper asserts rc == 0, so an
    # inconclusive run still fails its suite. That is the point — it must never be
    # possible to report a green that was not earned. What changes is that an
    # inconclusive run no longer ACCUSES the product of a defect it never saw.
    if n_fail:
        print( "  VERDICT: FAIL — the harness observed the product doing the wrong thing." )
        print( "=" * 70 )
        return 1
    if n_inc:
        print( "  VERDICT: INCONCLUSIVE — the harness could not observe some stages." )
        print( "           This is NOT a product defect. Read the [observe] lines above." )
        print( "=" * 70 )
        return 2
    print( "  VERDICT: PASS — every stage observed and green." )
    print( "=" * 70 )
    return 0


def doc_resolved_from_logs( run_started_monotonic=None, container=None ):
    """
    Stage 3 proof: the orchestrator logs the exact file it resolved. Grep the
    server container's log for our seed filename after `Initialized for`. This is
    independent of whether the job later completes.

    Requires:
        - run_started_monotonic is a time.monotonic() stamp taken BEFORE the push,
          or None to fall back to a wide window

    Ensures:
        - the log window spans the WHOLE run, not a fixed 10 minutes. The
          "Initialized for" line is written at push time; this function is called
          after the poll loop, so a fixed 10m window mechanically excluded the very
          line it was looking for on any run longer than 10 minutes (row 1cd30181).
        - returns PASS when the line is found
        - returns FAIL when the log was READ successfully and the line is absent
        - returns INCONCLUSIVE when the log could not be read at all — an
          unreadable log is not evidence that the document failed to resolve
    """
    import subprocess
    container = container or os.environ.get( "LANE2_LOG_CONTAINER", "lupin-rest-dev" )
    if run_started_monotonic is None:
        window_s = TIMEOUT_S + LOG_WINDOW_SLACK_S
    else:
        window_s = int( time.monotonic() - run_started_monotonic ) + LOG_WINDOW_SLACK_S
    try:
        out = subprocess.run(
            [ "docker", "logs", container, "--since", f"{window_s}s" ],
            capture_output=True, text=True, timeout=60,
        )
    except Exception as e:
        log( f"[observe] stage3 log read failed ({e}) — INCONCLUSIVE, not a resolution failure" )
        return INCONCLUSIVE
    if out.returncode != 0:
        log( f"[observe] docker logs {container} exited {out.returncode} — INCONCLUSIVE" )
        return INCONCLUSIVE
    blob = out.stdout + out.stderr
    log( f"stage3: searched {len(blob.splitlines())} log lines over a {window_s}s window" )
    for line in blob.splitlines():
        if "Initialized for" in line and SEED_FILENAME in line:
            log( f"stage3 proof: {line.strip()[:120]}" )
            return PASS
    return FAIL


def verify_content( headers, done_job ):
    """
    Fetch the podcast artifact and check it names the planted facts.

    Ensures:
        - PASS when at least two planted facts appear in the fetched text
        - FAIL when text WAS fetched and the facts are not in it
        - INCONCLUSIVE when no text could be fetched at all. An empty haystack
          finds nothing, which is not the same as the podcast being about the
          wrong document — and reporting it as FAIL would blame the product for
          an artifact-fetch problem.
    """
    # The done card carries a completion abstract + artifact paths. Try the
    # script .md first (cheap text), fall back to the abstract.
    blobs = []
    abstract = done_job.get( "completion_abstract" ) or done_job.get( "abstract" ) or ""
    blobs.append( abstract )
    # Try to fetch any script path referenced in artifacts.
    arts = done_job.get( "artifacts" ) or {}
    for key in ( "script_path", "script", "transcript_path" ):
        p = arts.get( key )
        if p:
            try:
                r = requests.get( f"{BASE_HTTP}/api/io/file", params={ "path": p }, headers=headers, timeout=30 )
                if r.status_code == 200:
                    blobs.append( r.text )
            except Exception:
                pass
    hay = " ".join( blobs ).strip().lower()
    if not hay:
        log( "content check: NO artifact text could be fetched — INCONCLUSIVE, not a content failure" )
        return INCONCLUSIVE
    hits = [ v for v in SEED_FACTS.values() if v.lower() in hay ]
    log( f"content check: {len(hits)}/{len(SEED_FACTS)} planted facts present over "
         f"{len(hay)} chars of artifact text: {hits}" )
    return PASS if len( hits ) >= 2 else FAIL


if __name__ == "__main__":
    sys.exit( main( sys.argv[ 1: ] ) )
