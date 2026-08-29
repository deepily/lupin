#!/usr/bin/env python3
"""
Disambiguation-CARD probe — the live proof for the first-turn document menu.
Row: first-turn-document-disambiguation (demo Thu 2026-08-06). Author: Tiffany 💍 (TESTER seat).

THE CLAIM UNDER TEST: "Rick sees a MENU" — not "a unit test passes".

When Rick says "make a podcast based on the KISS protocol" and TWO documents match,
the approved change (Rachel 🕊️, expeditor.py) must show the SAME multiple-choice CARD
he already clicks for the routing confirm, listing the real candidates. Today it throws
the candidates away and shows a blank open free-text question.

WHAT THIS PROBE CAPTURES: every `response_requested` notification the SERVER PUSHES OVER
THE WEBSOCKET — i.e. the exact payload the browser renders. Not a docker log line saying a
function ran; not a card that was constructed but never sent. The WS `notification_queue_update`
event IS what the user is shown. We record response_type + response_options for each ask.

SAFETY FENCE (mandatory — Mr. Radio, 2026-08-04): the probe STOPS at the document-RESOLUTION ask.
It captures that payload and answers NOTHING further. A yes/no "Does this look right?" summary is
the APPROVAL that starts generation, which routes a script-review gate to RICK ~90s in (proven:
pg-d6532072). A test must never approve it: yes_no is ALWAYS declined, and the resolution-ask fence
means we normally stop before the summary is even emitted. No generation is ever triggered.

TWO TARGETS (--target):
  podcast       the change path. VERDICT: PASS = the document-resolution ask is a multiple_choice
                card listing both seeds, emitted by the expediter's BEARER'd notify_user_sync call
                (:846) — not the no-bearer routing-confirm precedent. Fenced before the summary.
  presentation  the GATE control. Presentation's `source` gets original_question=None (podcast-only
                fence, expeditor.py:388) and reaches the numbered-pick at :1207 — the site Rachel's
                step 3 rewrites. VERDICT: PASS = the run genuinely reached a 2+ multi-match ask
                (non-vacuous, PROVEN by the observed "I found multiple matches" payload) AND every
                document ask STAYS open_ended (the caller-flag gate held, did not leak to presentation).
                No multi-match ask reached → INCONCLUSIVE, never a pass.

BEARER round-trip note (Sam's attack #1): the podcast expediter calls notify_user_sync WITH a
bearer token (:846); the routing-confirm precedent that proves MULTIPLE_CHOICE renders runs
WITHOUT one. This probe drives the expediter, so the card lands on the BEARER'd call by
construction — and the round-trip check proves it is answerable there, not merely displayable.

PREDICTED FAILURE ON UNCHANGED HEAD (--predict prints without running):
  podcast      → document ask = open_ended ("Which document should I use…"). FAIL, exit 1.
  presentation → numbered-pick = open_ended. PASS-as-baseline (gate trivially holds; the real
                 test of the gate is AFTER Rachel's change, that it did NOT flip to a card).

VENUE: :7999 (live product path). Reload is OFF — the server bounce is Mr. Radio's to schedule.

Usage:
  source ~/.lupin/test-env.sh
  python 2026.08.05-disambiguation-card-probe.py --predict
  python 2026.08.05-disambiguation-card-probe.py --target podcast
  python 2026.08.05-disambiguation-card-probe.py --target presentation
  python 2026.08.05-disambiguation-card-probe.py --target podcast --keep
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
BASE_HTTP  = "http://localhost:7999"
WS_HOST    = "localhost"
WS_PORT    = 7999
POLL_EVERY = 2
SEED_EMAIL = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "" )

TARGETS = {
    "podcast": {
        "mode"     : "podcast",
        "session"  : "tiffany-card-probe-pod",
        "question" : ( "build me a podcast based on the KISS protocol document that talks about "
                       "how the brevity mandate saved me a ton of tokens" ),
        "timeout"  : 120,
    },
    "presentation": {
        "mode"     : "presentation",
        "session"  : "tiffany-card-probe-pres",
        "question" : ( "make a slide deck from the KISS protocol document about how the brevity "
                       "mandate saved a ton of tokens" ),
        "timeout"  : 120,
    },
}

# ── TWO seeds — both plausibly "the KISS protocol", distinguishable by name + date ──
SEED_A_NAME = "2026.07.25-the-kiss-protocol-how-a-brevity-mandate-got-built.md"
SEED_A_BODY = """# The KISS Protocol — How a Brevity Mandate Got Built

_A fictional deep-research doc seeded for the disambiguation-card probe. Distinct from the
Aug-4 explainer by date, title, and its invented facts — so the two are genuine rivals._

## Origin story
The KISS protocol ("Keep It Short and Sweet") was drafted by **Marguerite Vance** in
**2017** under the working codename **Project Slate Harbor**. This document narrates HOW
the mandate got built — the committee, the drafts, the fights over the apology clause.

## The build
Three rounds of review turned a two-page memo into a one-line rule: lead with the verdict,
give two supporting sentences, stop. The hardest cut was the "self-summary" paragraph.

## Where it landed
By the quarter after Project Slate Harbor shipped, Vance's team reported the rule holding
across every channel it touched — the origin the later token-savings explainer builds on.
"""

SEED_B_NAME = "2026.08.04-kiss-protocol-brevity-token-savings-explainer.md"
SEED_B_BODY = """# The KISS Protocol — How a Brevity Mandate Saved a Ton of Tokens

_A fictional explainer seeded for the disambiguation-card probe. Distinct from the Jul-25
build-story by date, title, and its invented facts._

## Origin
The KISS protocol ("Keep It Short and Sweet") was coined by **Thelonius Quirke** in
**2019** under the internal codename **Project Marble Fountain**. Its whole discipline
reduces to one line: **"say it once, say it small."**

## The token savings
Measured across a daily workload, the mandate cut token spend by **fifty-eight percent** —
the headline figure Quirke reported the quarter after Project Marble Fountain shipped.

## Why it holds
A finding stated as a mechanism survives at any stakes level; a finding dressed as drama
gets discounted the moment the stakes turn out lower. Brevity is a control, not a style.
"""

SEEDS = [ ( SEED_A_NAME, SEED_A_BODY ), ( SEED_B_NAME, SEED_B_BODY ) ]


# ── Logging ─────────────────────────────────────────────────────────────────
LOGS = []
def log( m ):
    line = f"{time.strftime('%H:%M:%S')} {m}"
    LOGS.append( line )
    print( line, flush=True )


# ── Classify a response-requested notification ──────────────────────────────
def _parse_questions( opts_raw ):
    if not opts_raw:
        return []
    try:
        d = json.loads( opts_raw ) if isinstance( opts_raw, str ) else opts_raw
        return d.get( "questions", [] )
    except Exception:
        return []


def is_doc_ambiguity( note ):
    """
    True iff this ask is the DOCUMENT-choice ambiguity point (either sub-path):
      - the open-ended "Which document should I use..." (initial describe ask),
      - the "I found multiple matches... say the number" numbered pick,
      - the NEW multiple-choice card whose options are the candidate .md files.
    Deliberately EXCLUDES the routing-confirm MC ("I think you want ...").
    """
    msg   = ( note.get( "message" ) or "" ).lower()
    title = ( note.get( "title" )   or "" ).lower()
    if "i think you want" in msg:            # routing confirm — NOT the doc ask
        return False
    if "which document" in msg or "document should i use" in msg:
        return True
    if "multiple matches" in msg or "say the number" in msg:
        return True
    if "which document" in title or title.replace( "missing: ", "" ) in ( "research", "source" ):
        return True
    for q in _parse_questions( note.get( "response_options" ) ):
        for o in q.get( "options", [] ):
            lab = ( o.get( "label", "" ) or "" ).lower()
            if lab.endswith( ".md" ) and "kiss" in lab:
                return True
    return False


def is_multi_match_ask( note ):
    """The observed 2+ evidence: a payload that actually enumerates >=2 candidates —
    either the "I found multiple matches: 1. … 2. …" text, or a card with >=2 .md options."""
    msg = ( note.get( "message" ) or "" ).lower()
    if "multiple matches" in msg and ( "2." in msg or "2)" in msg ):
        return True
    md_opts = 0
    for q in _parse_questions( note.get( "response_options" ) ):
        for o in q.get( "options", [] ):
            if ( o.get( "label", "" ) or "" ).lower().endswith( ".md" ):
                md_opts += 1
    return md_opts >= 2


def is_roundtrip_summary( note ):
    """The post-resolution 'Does this look right?' yes/no summary that NAMES a resolved seed
    file — proof the picked candidate actually resolved to a real path (Sam Q1: card ANSWERED +
    doc RESOLVED, on the bearer'd expediter call). We capture this, then DECLINE it — never
    approve, because approving starts generation."""
    if ( note.get( "response_type" ) or "" ).lower() != "yes_no":
        return False
    blob = ( ( note.get( "message" ) or "" ) + " " + ( note.get( "abstract" ) or "" ) )
    return ( SEED_A_NAME in blob ) or ( SEED_B_NAME in blob )


def card_lists_both_seeds( note ):
    labels = []
    for q in _parse_questions( note.get( "response_options" ) ):
        for o in q.get( "options", [] ):
            labels.append( o.get( "label", "" ) or "" )
    a = any( SEED_A_NAME in l for l in labels )
    b = any( SEED_B_NAME in l for l in labels )
    return ( a and b ), labels


def is_resolution_ask( note ):
    """
    The DOCUMENT-RESOLUTION ask — the fence point. This is the entire claim we measure:
      - a multiple_choice document CARD (the post-Rachel menu), OR
      - a numbered multi-match open_ended ask that enumerates >=2 candidates (HEAD).
    The probe STOPS here: it captures this payload and answers NOTHING further, so the
    downstream yes/no summary + script-generation gate (which routes an approval to RICK
    ~90s in) can NEVER fire from a test. The initial "which document?" describe ask is NOT
    a resolution ask — it is answered (vaguely) to REACH the resolution ask.
    """
    if not is_doc_ambiguity( note ):
        return False
    if ( note.get( "response_type" ) or "" ).lower() == "multiple_choice":
        return True
    return is_multi_match_ask( note )


def choose_answer( note ):
    """Answer each ask so the flow keeps moving. The VERDICT is decided at capture,
    not by whether these answers parse — completing the run is secondary."""
    rtype = ( note.get( "response_type" ) or "" ).lower()
    opts_raw = note.get( "response_options" )

    if rtype == "open_ended_batch":
        answers = {}
        for q in _parse_questions( opts_raw ):
            header  = q.get( "header" )
            default = q.get( "default_value", "" )
            answers[ header ] = "en" if header == "languages" else ( default or "none" )
        return json.dumps( { "answers": answers } )

    if rtype == "multiple_choice":
        questions = _parse_questions( opts_raw )
        if questions:
            options = questions[ 0 ].get( "options", [] )
            header  = questions[ 0 ].get( "header", "0" )
            for o in options:                                    # doc card → pick first seed
                lab = o.get( "label", "" ) or ""
                if lab.endswith( ".md" ):
                    return json.dumps( { "answers": { header: lab } } )
            for o in options:                                    # routing confirm → podcast/pres product
                lab = ( o.get( "label", "" ) or "" ).lower()
                if "doc-to-pod" in lab or "podcast generator" in lab or "slidecraft" in lab or "presentation" in lab:
                    return json.dumps( { "answers": { header: o.get( "label" ) } } )
            for o in options:
                if "cancel" not in ( o.get( "label", "" ) or "" ).lower():
                    return json.dumps( { "answers": { header: o.get( "label" ) } } )
        return "yes"

    if rtype == "yes_no":
        # THE APPROVAL FENCE. This yes/no is the "Does this look right?" summary, and
        # answering "yes" IS the approval that STARTS generation — which routes a
        # script-review gate to RICK ~90s in (proven 2026-08-04: pg-d6532072). A test
        # must NEVER approve it. Decline, always. (Belt; the resolution-ask fence in
        # WsProbe._capture means we normally stop before this ever arrives.)
        return "no"

    # open_ended numbered-pick (the resolution ask on HEAD): pick candidate #1 so the doc
    # RESOLVES to a real file → the summary can then name it (round-trip proof).
    if is_multi_match_ask( note ):
        return "1"

    # open_ended describe ask. Answer with a STILL-vague KISS description so the numbered
    # multi-match ask (:1207) is exercised on both targets.
    return "the KISS protocol document about token savings"


# ── WebSocket capture + auto-answer ─────────────────────────────────────────
class WsProbe:
    def __init__( self, jwt, headers, session_id ):
        self.jwt        = jwt
        self.headers    = headers
        self.session_id = session_id
        self.asks               = []     # ordered captured note dicts
        self.answered           = set()
        self.resolution_answered = False # True once we've picked a candidate at the resolution ask
        self.roundtrip          = False  # True once the summary named the resolved seed file
        self.fenced             = False  # True once the summary is declined → answer nothing further
        self._running           = True
        self._thread            = None

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
        uri = f"ws://{WS_HOST}:{WS_PORT}/ws/queue/{quote( self.session_id )}"
        try:
            async with websockets.connect( uri, max_size=None ) as ws:
                await ws.send( json.dumps( {
                    "type"              : "auth_request",
                    "token"             : f"Bearer {self.jwt}",
                    "session_id"        : self.session_id,
                    "subscribed_events" : [ "notification_queue_update", "job_state_transition" ],
                } ) )
                auth = json.loads( await asyncio.wait_for( ws.recv(), timeout=10 ) )
                log( f"[ws] auth: {auth.get('type')}" )
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
                    if etype == "notification_queue_update":
                        self._capture( data )
        except Exception as e:
            log( f"[ws] listener error: {e}" )

    def _capture( self, data ):
        note = data.get( "notification", data )
        nid  = note.get( "id_hash" ) or note.get( "notification_id" ) or note.get( "id" )
        if not note.get( "response_requested" ) or not nid:
            return
        if nid in self.answered:
            return
        self.answered.add( nid )
        self.asks.append( note )                                 # RECORD the rendered payload
        rtype = note.get( "response_type" )
        doc   = is_doc_ambiguity( note )
        log( f"[ws] ASK #{len(self.asks)} type={rtype} doc={doc} multi={is_multi_match_ask(note)} "
             f"msg='{(note.get('message') or '')[:66]}'" )
        if doc:
            log( f"[ws]   response_options={json.dumps( note.get('response_options') )[:400]}" )

        # ── THE FENCE (boundary = the yes/no APPROVAL summary) ─────────────
        # Sequence: resolution ask → pick a candidate → the summary arrives →
        # capture whether it NAMES the resolved seed (round-trip proof) → DECLINE
        # it ("no") → stop. The summary's "yes" is the start button; we never send it.
        if self.fenced:
            log( f"[ws]   ⛔ fenced — ignoring ask (no answer sent)." )
            return

        # Post-resolution: the ONLY ask we still touch is the yes/no summary, which we
        # capture (round-trip) and DECLINE. Anything else after resolution → stop cold.
        if self.resolution_answered:
            if ( note.get( "response_type" ) or "" ).lower() == "yes_no":
                self.roundtrip = is_roundtrip_summary( note )
                log( f"[ws]   ⛔ APPROVAL SUMMARY — round_trip={self.roundtrip} → DECLINING (never 'yes')" )
                self._post( nid, "no" )
            else:
                log( f"[ws]   ⛔ post-resolution non-summary ask — stopping cold, no answer." )
            self.fenced = True
            return

        answer = choose_answer( note )
        self._post( nid, answer )
        if is_resolution_ask( note ):
            self.resolution_answered = True
            log( f"[ws]   ✅ resolution ask ANSWERED ({str(answer)[:40]}) — next expected: summary → decline" )

    def _post( self, nid, answer ):
        try:
            r = requests.post( f"{BASE_HTTP}/api/notify/response",
                               json={ "notification_id": nid, "response_value": answer },
                               headers=self.headers, timeout=15 )
            log( f"[ws]   answered {nid[:8]} → HTTP {r.status_code}" )
        except Exception as e:
            log( f"[ws]   answer POST failed: {e}" )


# ── Seeding ─────────────────────────────────────────────────────────────────
def project_root():
    return os.environ.get( "LUPIN_ROOT" ) or "/mnt/DATA01/include/www.deepily.ai/projects/lupin"

def seed_dir():
    return os.path.join( project_root(), "io", "deep-research", SEED_EMAIL )

def write_seeds():
    d = seed_dir()
    os.makedirs( d, exist_ok=True )
    for name, body in SEEDS:
        with open( os.path.join( d, name ), "w" ) as f:
            f.write( body )
        log( f"SEED written: {os.path.join( d, name )}" )

def remove_seeds():
    d = seed_dir()
    for name, _ in SEEDS:
        try:
            os.remove( os.path.join( d, name ) )
            log( f"SEED removed: {os.path.join( d, name )}" )
        except FileNotFoundError:
            pass


# ── Auth ────────────────────────────────────────────────────────────────────
def login( session_id ):
    email = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    pw    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not pw:
        log( "FATAL: creds not set — source ~/.lupin/test-env.sh" ); sys.exit( 2 )
    r = requests.post( f"{BASE_HTTP}/auth/login", json={ "email": email, "password": pw }, timeout=15 )
    r.raise_for_status()
    tok = r.json()[ "tokens" ][ "access_token" ]
    return email, tok, { "Authorization": f"Bearer {tok}", "X-Session-ID": session_id }


PREDICTED = (
    "PREDICTED HEAD BASELINE (unchanged code):\n"
    "  --target podcast      → document ask = response_type 'open_ended'\n"
    "     msg 'Which document should I use for the podcast? Describe it or say the filename.'\n"
    "     (_ask_for_arg → ResponseType.OPEN_ENDED, expeditor.py:834 via :1170) → VERDICT FAIL, exit 1.\n"
    "     After Rachel: same point → 'multiple_choice' card listing both seeds + round-trips → PASS.\n"
    "  --target presentation → numbered-pick (:1207) = 'open_ended' today → gate baseline PASS.\n"
    "     The gate is truly TESTED only AFTER Rachel: it must STAY 'open_ended' (flag did not leak).\n"
    "     Presentation reaches :1207 with original_question=None (podcast-only fence :388)."
)


# ── Verdicts ────────────────────────────────────────────────────────────────
def _dump_asks( asks ):
    for i, n in enumerate( asks, 1 ):
        print( f"    #{i}  type={(n.get('response_type') or ''):<16} doc={is_doc_ambiguity(n)} "
               f"multi={is_multi_match_ask(n)}  msg='{(n.get('message') or '')[:56]}'" )


def verdict_podcast( asks, roundtrip ):
    doc_asks = [ n for n in asks if is_doc_ambiguity( n ) ]
    print( "\n" + "=" * 72 )
    print( "  CARD PROBE — TARGET podcast (the CHANGE path)" )
    print( "=" * 72 )
    print( f"  asks captured: {len(asks)}    round-trip (summary named resolved seed): {roundtrip}" )
    _dump_asks( asks )
    print( "-" * 72 )
    if not doc_asks:
        print( "  VERDICT: INCONCLUSIVE — no document-ambiguity ask fired (resolved to 1/0)." )
        print( "=" * 72 ); return 2
    cards = [ n for n in doc_asks if ( n.get( "response_type" ) or "" ).lower() == "multiple_choice" ]
    if cards:
        both, labels = card_lists_both_seeds( cards[ 0 ] )
        print( f"  document ask     : multiple_choice  ← CARD (emitted by the BEARER'd expediter call)" )
        print( f"  lists both seeds : {both}   labels={labels}" )
        print( f"  round-trips      : {roundtrip}  (picked → resolved → summary named the file)" )
        if both and roundtrip:
            print( "  VERDICT: PASS — Rick sees a MENU listing both candidates, and the pick" )
            print( "  RESOLVED to a real file on the bearer'd call. (Fenced at the summary — no generation.)" )
            print( "=" * 72 ); return 0
        print( "  VERDICT: PARTIAL — card shown but not (both-seeds AND round-tripped). Not the full claim." )
        print( "=" * 72 ); return 1
    d0 = doc_asks[ 0 ]
    print( f"  document ask : {d0.get('response_type')}  ← open free-text, NO card" )
    print( f"  message      : {d0.get('message')}" )
    print( "  VERDICT: FAIL — open-text ask, no menu. (Expected on unchanged HEAD.)" )
    print( "=" * 72 ); return 1


def verdict_presentation( asks ):
    doc_asks   = [ n for n in asks if is_doc_ambiguity( n ) ]
    multi_asks = [ n for n in asks if is_multi_match_ask( n ) ]
    print( "\n" + "=" * 72 )
    print( "  CARD PROBE — TARGET presentation (the GATE control)" )
    print( "=" * 72 )
    print( f"  asks captured: {len(asks)}" )
    _dump_asks( asks )
    print( "-" * 72 )
    if not multi_asks:
        print( "  VERDICT: INCONCLUSIVE — presentation never reached a 2+ multi-match ask." )
        print( "  A 'stays open_ended' pass here would be VACUOUS. Flagging for ruling, not passing." )
        print( "=" * 72 ); return 2
    leaked = [ n for n in doc_asks if ( n.get( "response_type" ) or "" ).lower() == "multiple_choice" ]
    print( f"  multi-match ask observed : True  ← non-vacuous (2+ candidates genuinely enumerated)" )
    if leaked:
        print( f"  document ask type        : multiple_choice  ← CARD" )
        print( "  VERDICT: FAIL — the card GATE LEAKED into presentation (flag not honoured)." )
        print( "=" * 72 ); return 1
    print( f"  document ask type        : open_ended (all)  ← gate held" )
    print( "  VERDICT: PASS — presentation stayed open-text; the caller-flag gate did not leak." )
    print( "=" * 72 ); return 0


# ── Main ────────────────────────────────────────────────────────────────────
def main( argv ):
    ap = argparse.ArgumentParser()
    ap.add_argument( "--target",  choices=[ "podcast", "presentation" ], default="podcast" )
    ap.add_argument( "--predict", action="store_true", help="print predicted HEAD baseline; no run" )
    ap.add_argument( "--no-seed", action="store_true" )
    ap.add_argument( "--keep",    action="store_true" )
    ap.add_argument( "--question", default=None )
    args = ap.parse_args( argv )

    if args.predict:
        print( PREDICTED ); return 0
    if websockets is None:
        log( "FATAL: `websockets` not importable" ); return 2

    tgt        = TARGETS[ args.target ]
    session_id = tgt[ "session" ]
    mode       = tgt[ "mode" ]
    question   = args.question or tgt[ "question" ]
    timeout_s  = tgt[ "timeout" ]

    log( "═══ CARD PROBE CONFIG ═══" )
    log( f"  TARGET   : {args.target}" )
    log( f"  MODE     : {mode}" )
    log( f"  QUESTION : {question[:80]}" )
    log( f"  SEEDS    : {SEED_A_NAME} + {SEED_B_NAME}" )
    log( "═════════════════════════" )

    email, jwt, headers = login( session_id )
    log( f"logged in as {email}" )
    if not args.no_seed:
        write_seeds()

    ws = WsProbe( jwt, { "Authorization": f"Bearer {jwt}" }, session_id )
    ws.start()
    time.sleep( 2 )

    try:
        m = requests.post( f"{BASE_HTTP}/api/mode/current", json={ "mode": mode }, headers=headers, timeout=10 )
        log( f"mode set: {m.status_code} {m.json().get('display_name','?')}" )
        r = requests.post( f"{BASE_HTTP}/api/push",
                           json={ "question": question, "websocket_id": session_id },
                           headers=headers, timeout=180 )
        log( f"push: {r.status_code} job_id={r.json().get('job_id')}" )
        if r.status_code == 410:
            # The v2 cutover retired /api/push (410 → /api/v2/ask). This probe measures the
            # v1 interactive expeditor's asks over the websocket, which the v2 door does not
            # emit — so there is nothing to capture here; port it before reuse. Ending now
            # rather than waiting out timeout_s on asks that will never arrive (row c84e9313).
            log( "push: /api/push is RETIRED on this server (410 → /api/v2/ask); this probe measures "
                 "v1 expeditor asks over the WS and must be ported to the v2 door before reuse — ending." )
            raise SystemExit( 2 )

        elapsed = 0
        settle  = 0
        while elapsed < timeout_s:
            if ws.fenced:
                log( "summary declined + fenced — run ends (no generation triggered)" )
                break
            if ws.resolution_answered:
                # resolution picked; give the summary a moment to arrive so we can
                # capture + decline it. If it never comes, end anyway — nothing pending.
                settle += POLL_EVERY
                if settle >= 12:
                    log( "resolution answered; no summary within 12s — ending (nothing to approve)" )
                    break
            time.sleep( POLL_EVERY ); elapsed += POLL_EVERY
        else:
            log( f"no resolution ask after {timeout_s}s" )
    finally:
        ws.stop()
        try:
            requests.post( f"{BASE_HTTP}/api/mode/current", json={ "mode": None }, headers=headers, timeout=10 )
        except Exception:
            pass
        if not args.keep and not args.no_seed:
            remove_seeds()

    return verdict_podcast( ws.asks, ws.roundtrip ) if args.target == "podcast" else verdict_presentation( ws.asks )


if __name__ == "__main__":
    sys.exit( main( sys.argv[ 1: ] ) )
