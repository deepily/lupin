#!/usr/bin/env python3
"""
LANE 2 measurement (row bd0ce120 sibling): Rick EXPLICITLY picks the Podcast
Generator from the Q&A dropdown, then types his vague sentence. Does this path
resolve a vague file reference into a real document?

Measured live on :7999 (dev). We register a WebSocket (so the expeditor's ask is
deliverable and WAITS), set mode=podcast, push Rick's sentence, capture every ask
the expeditor pushes, answer the file-resolution prompt with a vague description,
and DECLINE at the confirmation step so no real podcast job is created.
"""

import asyncio, json, os, sys, threading, time
import requests
import websockets

BASE = "http://localhost:7999"
WS   = "ws://localhost:7999"
SENTENCE = ( "build me a podcast based on the contents of an explainer document that "
             "discusses the KISS protocol and how it saved me a ton of tokens on a daily basis" )
VAGUE_DOC_ANSWER = "the explainer I wrote about the KISS protocol"

EMAIL = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
PASSWORD = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
if not EMAIL or not PASSWORD:
    print( "MISSING CREDS: set LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL/PASSWORD" ); sys.exit( 2 )

transcript = []
def log( *a ):
    line = " ".join( str( x ) for x in a )
    print( line, flush=True ); transcript.append( line )

def login():
    r = requests.post( f"{BASE}/auth/login", json={ "email": EMAIL, "password": PASSWORD }, timeout=15 )
    r.raise_for_status()
    d = r.json()
    return d[ "tokens" ][ "access_token" ]

def get_session_id( jwt ):
    r = requests.get( f"{BASE}/api/get-session-id", headers={ "Authorization": f"Bearer {jwt}" }, timeout=15 )
    r.raise_for_status()
    return r.json()[ "session_id" ]

def set_mode( jwt, mode ):
    r = requests.post( f"{BASE}/api/mode/current", json={ "mode": mode },
                       headers={ "Authorization": f"Bearer {jwt}", "Content-Type": "application/json" }, timeout=15 )
    return r.status_code, r.text[ :300 ]

def answer( jwt, nid, value ):
    # response_value passed raw: plain str for single/yes_no, JSON string for batch
    r = requests.post( f"{BASE}/api/notify/response",
                       json={ "notification_id": nid, "response_value": value },
                       headers={ "Authorization": f"Bearer {jwt}", "Content-Type": "application/json" }, timeout=15 )
    return r.status_code, r.text[ :200 ]

push_result = {}
def push( jwt, sid ):
    try:
        r = requests.post( f"{BASE}/api/push", json={ "question": SENTENCE, "websocket_id": sid },
                           headers={ "Authorization": f"Bearer {jwt}", "Content-Type": "application/json" }, timeout=240 )
        push_result[ "status" ] = r.status_code
        push_result[ "body" ]   = r.text[ :600 ]
    except Exception as e:
        push_result[ "error" ] = repr( e )

def is_ask( ev ):
    # A notification event that requests a response.
    t = ev.get( "type", "" )
    d = ev.get( "data", ev )
    return ( d.get( "response_requested" ) or d.get( "response_type" ) or
             "notification" in t.lower() )

async def run():
    jwt = login(); log( "LOGIN ok" )
    sid = get_session_id( jwt ); log( "SESSION", sid )
    uri = f"{WS}/ws/queue/{sid.replace( ' ', '%20' )}"
    async with websockets.connect( uri, open_timeout=10, max_size=None ) as ws:
        await ws.send( json.dumps( { "type": "auth_request", "token": jwt,
                                     "subscribed_events": [ "*" ] } ) )
        auth = json.loads( await asyncio.wait_for( ws.recv(), timeout=10 ) )
        log( "WS AUTH ->", auth.get( "type" ), auth.get( "status", auth.get( "message", "" ) ) )

        sc, body = set_mode( jwt, "podcast" ); log( "SET MODE podcast ->", sc, body )

        threading.Thread( target=push, args=( jwt, sid ), daemon=True ).start()
        log( "PUSHED:", SENTENCE )

        answered_doc = False
        asks_seen = 0
        seen_asks = set()
        deadline = time.time() + 120
        while time.time() < deadline and "status" not in push_result and "error" not in push_result:
            try:
                raw = await asyncio.wait_for( ws.recv(), timeout=3 )
            except asyncio.TimeoutError:
                continue
            try:
                ev = json.loads( raw )
            except Exception:
                continue
            etype = ev.get( "type", "?" )
            notif = ev.get( "notification" ) or ev.get( "data" ) or ev
            rtype = notif.get( "response_type" ) if isinstance( notif, dict ) else None
            rreq  = notif.get( "response_requested" ) if isinstance( notif, dict ) else None
            if isinstance( notif, dict ) and ( rreq or rtype ):
                nid   = notif.get( "id" ) or notif.get( "notification_id" )
                msg   = notif.get( "message" ) or notif.get( "title" )
                opts  = notif.get( "response_options" )
                if nid in seen_asks:
                    continue
                seen_asks.add( nid )
                asks_seen += 1
                log( f"ASK#{asks_seen} [{etype}] nid={nid} rtype={rtype} response_requested={rreq}" )
                log( f"   message: {str( msg )[:500]}" )
                if opts: log( f"   options: {json.dumps( opts )[:700]}" )
                if not nid:
                    continue
                if rtype == "open_ended_batch":
                    ans = json.dumps( { "answers": { "languages": "en,es-MX", "audience": "academic", "audience_context": "none" } } )
                    sc, b = answer( jwt, nid, ans ); log( f"   -> answered batch with defaults: {sc} {b}" )
                elif rtype == "open_ended":
                    # the fuzzy file-resolution prompt — answer with the VAGUE description
                    sc, b = answer( jwt, nid, VAGUE_DOC_ANSWER ); log( f"   -> answered doc prompt (vague): {sc} {b}" )
                    answered_doc = True
                elif rtype == "yes_no":
                    sc, b = answer( jwt, nid, "no" ); log( f"   -> DECLINED confirmation (no real job): {sc} {b}" )
                elif rtype == "multiple_choice":
                    sc, b = answer( jwt, nid, "1" ); log( f"   -> picked option 1: {sc} {b}" )
            else:
                if etype not in ( "sys_ping", "sys_time_update", "pong", "heartbeat" ):
                    log( f"evt [{etype}] {json.dumps( notif if isinstance(notif,dict) else ev )[:220]}" )

        # let push settle
        for _ in range( 20 ):
            if "status" in push_result or "error" in push_result: break
            await asyncio.sleep( 1 )
    log( "PUSH RESULT:", json.dumps( push_result )[:600] )

try:
    asyncio.run( asyncio.wait_for( run(), timeout=180 ) )
except Exception as e:
    log( "SCRIPT ERROR:", repr( e ) )

print( "\n===== TRANSCRIPT =====" )
print( "\n".join( transcript ) )
