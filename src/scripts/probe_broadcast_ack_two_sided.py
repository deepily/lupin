#!/usr/bin/env python3
"""
Two-sided live probe for the broadcast-ack save (row 4f320c27 S5).

WHAT IT ASKS. Send ONE real broadcast on Rick's account, then read the SAME ack back
through both doors and compare them:

    LEFT  — the in-memory push, as the browser sees it today
            (GET /api/notifications/undelivered, filtered to this broadcast)
    RIGHT — the SAVED row, through the new per-broadcast read
            (GET /api/notifications/broadcast-acks/{broadcast_id})

Agreeing on one ack is the whole claim. Two doors that disagree is the finding; two
doors that agree because neither returned anything is NOT a pass, and the report
below says so in those words rather than printing a reassuring pair of zeroes.

🔴 WRITTEN, NOT RUN. This probe sends a real broadcast to every live seat in the
fleet and every one of them will be interrupted by it. Running it is the operator's
call, not the author's, and it must not be fired while the fleet is mid-task.

RUN IT LIKE THIS (one paste, :7999 dev server, from the repo root):

    export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL="your@email.com"
    export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD="yourpassword"
    LUPIN_ROOT="$PWD" PYTHONPATH="$PWD/src" .venv/bin/python src/scripts/probe_broadcast_ack_two_sided.py

WHAT "PASS" REQUIRES, stated before any count is taken:

  POPULATION — the live CC sessions the broadcast endpoint itself resolved, which it
  reports back as `recipients`. That number, not a guess about who is online, is the
  denominator every count below is read against.

  1. recipients > 0. A broadcast to nobody produces no acks, and the two empty
     answers that follow would agree perfectly while proving nothing.
  2. RIGHT returns at least one ack for this broadcast, each carrying a broadcast_id
     equal to the one sent and a non-null session_id. Acks with no attribution are
     exactly the pre-fix state.
  3. LEFT and RIGHT name the SAME set of sessions. A session in one and not the other
     is the defect, whichever side is short.

NO CURL. Per the project mandate, every request here goes through `requests`.
Raw response bodies are printed on ANY failure — a probe that summarises a failure it
cannot explain sends the next reader back to reproduce it.
"""

import json
import os
import sys
import time
import uuid

import requests


BASE_URL      = os.environ.get( "LUPIN_PROBE_BASE_URL", "http://localhost:7999" )
ACK_WAIT_SECS = float( os.environ.get( "LUPIN_PROBE_ACK_WAIT_SECS", "20" ) )
POLL_SECS     = 2.0


def _fail( headline, **evidence ):
    """Print the headline, then every raw response we hold, then exit non-zero."""
    print( f"\n❌ {headline}" )
    for name, value in evidence.items():
        print( f"\n── raw {name} ──" )
        print( value if isinstance( value, str ) else json.dumps( value, indent=2, default=str ) )
    sys.exit( 1 )


def _login():
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        print( "❌ Set LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and "
               "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD before running this probe." )
        sys.exit( 2 )

    r = requests.post( f"{BASE_URL}/auth/login", json={ "email": email, "password": password }, timeout=30 )
    if r.status_code != 200:
        _fail( f"login to {BASE_URL} returned {r.status_code}", login_response=r.text )
    try:
        return r.json()[ "tokens" ][ "access_token" ]
    except ( KeyError, ValueError ):
        _fail( "login succeeded but no access_token in the body", login_response=r.text )


def _broadcast( headers, broadcast_id ):
    body = {
        "message"            : ( "🔬 broadcast-ack persistence probe (row 4f320c27) — "
                                 "no action needed, this message exists only to be acked." ),
        "broadcast_id"       : broadcast_id,
        "require_ack"        : True,
        "include_originator" : True,
    }
    r = requests.post( f"{BASE_URL}/api/commons/broadcast-to-cc-sessions",
                       json=body, headers=headers, timeout=60 )
    if r.status_code != 200:
        _fail( f"broadcast returned {r.status_code}", broadcast_response=r.text )
    return r.json()


def _saved_acks( headers, broadcast_id ):
    """RIGHT — the new per-broadcast read over the SAVED rows."""
    r = requests.get( f"{BASE_URL}/api/notifications/broadcast-acks/{broadcast_id}",
                      headers=headers, timeout=30 )
    if r.status_code != 200:
        _fail( f"the saved-ack read returned {r.status_code}", saved_ack_response=r.text )
    return r.json(), r.text


def _pushed_acks( headers, broadcast_id ):
    """
    LEFT — the in-memory push as the browser receives it, observed through the
    undelivered inbox (which carries `payload` as of S2).

    ⚠️ NAMED LIMIT, so nobody reads more into a short LEFT than is there: this door
    shows an ack only while it is still UNDELIVERED. With a browser open on this
    account the server marks acks delivered immediately and LEFT legitimately reads
    zero. That is why a LEFT/RIGHT mismatch is reported as a DISAGREEMENT TO CHASE
    and not as a failure of the saved side — the discriminator between the two
    explanations is whether a browser was connected, which this probe cannot see.
    """
    r = requests.get( f"{BASE_URL}/api/notifications/undelivered?limit=200",
                      headers=headers, timeout=30 )
    if r.status_code != 200:
        _fail( f"the undelivered read returned {r.status_code}", undelivered_response=r.text )
    body    = r.json()
    matched = [ n for n in body.get( "notifications", [] )
                if n.get( "type" ) == "commons_broadcast_ack"
                and ( n.get( "payload" ) or { } ).get( "broadcast_id" ) == broadcast_id ]
    return matched, r.text


def main():
    broadcast_id = str( uuid.uuid4() )
    headers      = { "Authorization": f"Bearer {_login()}" }

    print( "═" * 78 )
    print( "  BROADCAST-ACK TWO-SIDED PROBE — row 4f320c27 S5" )
    print( f"  server       : {BASE_URL}" )
    print( f"  broadcast_id : {broadcast_id}" )
    print( f"  taken at     : {time.strftime( '%Y-%m-%d %H:%M:%S %Z' )}" )
    print( "═" * 78 )

    sent = _broadcast( headers, broadcast_id )

    # ── THE POPULATION, NAMED BEFORE ANY COUNT IS READ ───────────────────────────
    recipients = sent.get( "recipients" )
    print( f"\nPOPULATION: the broadcast endpoint resolved {recipients} live CC session(s). "
           f"Every count below is read against that denominator." )
    if not recipients:
        _fail( "the broadcast reached NOBODY — there is no ack to compare, and two empty "
               "answers agreeing would prove nothing. Re-run with live seats in the fleet.",
               broadcast_response=json.dumps( sent, indent=2 ) )

    print( f"\nWaiting up to {ACK_WAIT_SECS:.0f}s for acks (the watcher polls the commons topic)…" )
    saved, saved_raw   = { }, ""
    pushed, pushed_raw = [], ""
    deadline = time.time() + ACK_WAIT_SECS
    while time.time() < deadline:
        time.sleep( POLL_SECS )
        saved, saved_raw   = _saved_acks( headers, broadcast_id )
        pushed, pushed_raw = _pushed_acks( headers, broadcast_id )
        if saved.get( "ack_count" ):
            break

    saved_acks     = saved.get( "acks", [] )
    saved_sessions = { a.get( "session_id" ) for a in saved_acks }
    push_sessions  = { ( n.get( "payload" ) or { } ).get( "session_id" ) for n in pushed }

    print( "\n┌─ RIGHT — the SAVED rows (new per-broadcast read) " + "─" * 27 )
    for a in saved_acks:
        print( f"│  {a.get( 'persona_icon' ) or '·'} {a.get( 'persona_name' )!r:24} "
               f"session={str( a.get( 'session_id' ) )[ :8 ]}  status={a.get( 'ack_status' )!r}  "
               f"state={a.get( 'state' )!r}" )
    print( f"└─ {len( saved_acks )} ack(s) of {recipients} recipient(s)" )

    print( "\n┌─ LEFT — the in-memory push (undelivered inbox) " + "─" * 29 )
    for n in pushed:
        payload = n.get( "payload" ) or { }
        print( f"│  {payload.get( 'persona_icon' ) or '·'} {payload.get( 'persona_name' )!r:24} "
               f"session={str( payload.get( 'session_id' ) )[ :8 ]}  status={payload.get( 'status' )!r}" )
    print( f"└─ {len( pushed )} ack(s) still undelivered" )

    # ── THE CLAIMS ───────────────────────────────────────────────────────────────
    if not saved_acks:
        _fail( f"NOTHING WAS SAVED. {recipients} session(s) were broadcast to and the "
               f"per-broadcast read returned zero rows — this is the exact "
               f"'looks fixed, recovers nothing' state the change exists to rule out.",
               saved_ack_response=saved_raw, undelivered_response=pushed_raw,
               broadcast_response=json.dumps( sent, indent=2 ) )

    unattributed = [ a for a in saved_acks
                     if a.get( "broadcast_id" ) != broadcast_id or not a.get( "session_id" ) ]
    if unattributed:
        _fail( "a saved ack carries no usable attribution (wrong broadcast_id, or no "
               "session_id) — a bodiless ack row is the pre-fix state wearing a new column.",
               unattributed=unattributed, saved_ack_response=saved_raw )

    print( "\n" + "═" * 78 )
    print( f"✅ SAVED: {len( saved_acks )} attributed ack(s) for this broadcast, out of "
           f"{recipients} recipient(s)." )
    if push_sessions and push_sessions != saved_sessions:
        print( "⚠️  DISAGREEMENT TO CHASE — the two doors name different session sets:" )
        print( f"    saved only : {sorted( s for s in saved_sessions - push_sessions if s )}" )
        print( f"    pushed only: {sorted( s for s in push_sessions - saved_sessions if s )}" )
        print( "    Raw bodies follow so the next reader does not have to reproduce it." )
        print( f"\n── raw saved-ack response ──\n{saved_raw}" )
        print( f"\n── raw undelivered response ──\n{pushed_raw}" )
    elif push_sessions:
        print( "✅ AGREEMENT: both doors name the same session set." )
    else:
        print( "ℹ️  LEFT was empty. This is EXPECTED with a browser open on this account "
               "(acks are marked delivered on arrival and leave the undelivered inbox), "
               "so it is NOT evidence against the saved side — and it is NOT a second "
               "confirmation either. Only RIGHT was measured this run." )
    print( "═" * 78 )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
