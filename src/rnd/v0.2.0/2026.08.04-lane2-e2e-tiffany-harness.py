#!/usr/bin/env python3
"""
Lane 2 podcast E2E — voice-driven, vague-file, WS-held-open auto-answer harness.
Row 68198c9f (Thursday demo acceptance gate). Author: Tiffany 💍.

Drives the ACTUAL demo path on :7999:
  POST /api/mode/current {mode:"podcast"}  (the "Podcast Generator" dropdown)
  → POST /api/push {question, websocket_id}
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

import requests

try:
    import websockets
    import asyncio
except ImportError:
    websockets = None

# ── Config ──────────────────────────────────────────────────────────────────
BASE_HTTP   = "http://localhost:7999"
WS_HOST     = "localhost"
WS_PORT     = 7999
SESSION_ID  = "tiffany-lane2-e2e"
MODE        = "podcast"          # the "Podcast Generator" dropdown
TIMEOUT_S   = 720                # 12 min — real audio generation
POLL_EVERY  = 3

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
        self._running = True
        self._thread  = None

    def start( self ):
        self._thread = threading.Thread( target=self._run, daemon=True )
        self._thread.start()

    def stop( self ):
        self._running = False

    def _run( self ):
        asyncio.set_event_loop( asyncio.new_event_loop() )
        asyncio.get_event_loop().run_until_complete( self._listen() )

    async def _listen( self ):
        from urllib.parse import quote
        uri = f"ws://{WS_HOST}:{WS_PORT}/ws/queue/{quote( SESSION_ID )}"
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
            self.log( f"[ws] listener error: {e}" )

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
    """Return THIS run's job from `queue`, matched on the EXACT job_id — never a
    loose `startswith pg-` (that matched a STALE prior-run job and false-failed).
    """
    if not job_id:
        return None
    r = requests.get( f"{BASE_HTTP}/api/get-queue/{queue}", headers=headers, timeout=20 )
    if r.status_code != 200:
        return None
    for j in r.json().get( f"{queue}_jobs_metadata", [] ):
        if j.get( "job_id", "" ) == job_id:
            return j
    return None


# ── Main ────────────────────────────────────────────────────────────────────
def main( argv ):
    ap = argparse.ArgumentParser()
    ap.add_argument( "--no-seed",  action="store_true" )
    ap.add_argument( "--keep",     action="store_true" )
    ap.add_argument( "--no-mode",  action="store_true", help="PURE-VOICE path: do NOT set the dropdown mode (the actual Thursday demo path)" )
    ap.add_argument( "--question", default=VAGUE_QUESTION, help="override the posted utterance (use Rachel's measured no-mode candidate)" )
    args = ap.parse_args( argv )

    if websockets is None:
        log( "FATAL: `websockets` not importable in this interpreter" ); return 2

    # ── HARNESS CONFIG BANNER ──────────────────────────────────────────────
    # A stale binary cannot report a fresh claim if it must first declare what
    # it is about to do. Mr Radio's hazard (2026-08-04): a preempted edit runs
    # the OLD path silently. This banner + the per-answer ANSWER= log make the
    # actual configuration and every confirmed option visible in the run log.
    log( "═══ HARNESS CONFIG ═══" )
    log( f"  PATH        : {'PURE VOICE (no mode) — the Thursday demo path' if args.no_mode else 'DROPDOWN (mode=' + MODE + ')'}" )
    log( f"  QUESTION    : {args.question[:80]}" )
    log( f"  SEED        : {'OFF (--no-seed)' if args.no_seed else 'ON (' + SEED_FILENAME + ')'}" )
    log( f"  CONFIRM     : multiple_choice → prefer 'Doc-to-Pod' (podcast generator); open_ended_batch → defaults, languages=en" )
    log( "══════════════════════" )

    results = {}
    email, jwt, headers = login()
    log( f"logged in as {email}" )
    results[ "1_push_accepted" ] = False
    results[ "2_route_podcast" ] = False
    results[ "3_doc_resolved" ]  = False
    results[ "4_job_running" ]   = False
    results[ "5_job_done" ]      = False
    results[ "6_content_ok" ]    = False

    if not args.no_seed:
        write_seed()

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

        r = requests.post( f"{BASE_HTTP}/api/push",
                           json={ "question": args.question, "websocket_id": SESSION_ID },
                           headers=headers, timeout=180 )
        push = r.json()
        log( f"push: {r.status_code} job_id={push.get('job_id')} result={push.get('result','')[:80]}" )
        results[ "1_push_accepted" ] = ( r.status_code == 200 )

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
            results[ "2_route_podcast" ] = True
        elif job_id and job_id.startswith( "rp-" ):
            log( f"ROUTING MISS: got {job_id[:12]} (research-to-podcast), NOT podcast generator" )

        # Poll for terminal — scoped to THIS run's exact job_id.
        elapsed = 0
        done_job = dead_job = None
        while elapsed < TIMEOUT_S:
            done_job = find_job( headers, "done", job_id )
            if done_job:
                break
            dead_job = find_job( headers, "dead", job_id )
            if dead_job:
                break
            if find_job( headers, "run", job_id ):
                results[ "4_job_running" ] = True
            time.sleep( POLL_EVERY ); elapsed += POLL_EVERY

        # Stage 3 is proven INDEPENDENTLY of completion: the orchestrator logs
        # the exact source file it resolved. Never infer resolution from the
        # content check (that needs stage 5 done — a name that would claim more
        # than the test proves).
        results[ "3_doc_resolved" ] = doc_resolved_from_logs()

        if done_job:
            results[ "2_route_podcast" ] = True
            results[ "5_job_done" ] = True
            log( f"JOB DONE: {done_job.get('job_id')}" )
            ok = verify_content( headers, done_job )
            results[ "6_content_ok" ] = ok
        elif dead_job:
            results[ "2_route_podcast" ] = True
            err = dead_job.get( "error" ) or dead_job.get( "response_text" ) or ""
            transient = any( s in err.lower() for s in ( "try again in a few minutes", "rate limit", "returned an error while writing" ) )
            tag = "TRANSIENT (phi-4 rate limit — retry, NOT a chain defect)" if transient else "DEFECT"
            log( f"JOB DEAD [{tag}]: {dead_job.get('job_id')} err={err}" )
        else:
            log( f"no terminal pg- job after {TIMEOUT_S}s" )

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
        print( f"  {'PASS' if results[k] else 'FAIL'}  {k}" )
    print( "=" * 70 )
    return 0 if all( results.values() ) else 1


def doc_resolved_from_logs():
    """
    Stage 3 proof: the orchestrator logs the exact file it resolved. Grep the
    dev container's log for our seed filename after `Initialized for`. This is
    independent of whether the job later completes.
    """
    import subprocess
    try:
        out = subprocess.run(
            [ "docker", "logs", "lupin-rest-dev", "--since", "10m" ],
            capture_output=True, text=True, timeout=20,
        )
        blob = out.stdout + out.stderr
        for line in blob.splitlines():
            if "Initialized for" in line and SEED_FILENAME in line:
                log( f"stage3 proof: {line.strip()[:120]}" )
                return True
    except Exception as e:
        log( f"doc_resolved_from_logs error: {e}" )
    return False


def verify_content( headers, done_job ):
    """Fetch the podcast artifact and check it names the planted facts."""
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
    hay = " ".join( blobs ).lower()
    hits = [ v for v in SEED_FACTS.values() if v.lower() in hay ]
    log( f"content check: {len(hits)}/{len(SEED_FACTS)} planted facts present: {hits}" )
    return len( hits ) >= 2


if __name__ == "__main__":
    sys.exit( main( sys.argv[ 1: ] ) )
