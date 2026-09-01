#!/usr/bin/env python3
"""
Smoke probe: a cached `user_not_available` verdict is replayed to a recipient
who has since CONNECTED, so the notification never reaches them.

VENUE — :7999 (dev), AI-discretionary. Routed by the rubric, not by folder:
runtime is ~2s, it needs no server monopoly, and its only persistent write is a
notification row for the test account (the same row every /api/notify smoke test
in this directory writes). It does NOT belong on :8000.

WHAT THIS PROBE PROVES
    With one idempotency key: the server answers `user_not_available` for a user
    who IS connected, at the same instant a FRESH key to the same live websocket
    answers `queued`. The only variable between those two calls is whether the
    key had been seen before, so the cached offline verdict — not connectivity —
    is what suppressed delivery.

WHAT IT DOES NOT PROVE
    · NOT that the announcement is POSTed four times. That is the client-side
      retry loop in notify_user_async (timeout=5 -> intervals [1,1,2] -> 4
      attempts) and is not exercised here at all; this probe makes its own calls.
    · NOT anything about a recipient who never connects. For them
      `user_not_available` is the correct answer, and an earlier probe that ran
      as an account with no session could not demonstrate this defect — which is
      why this file exists.
    · NOT the fix. Against a server serving the fix, step 3 returns `queued` and
      the probe passes; against one without it, step 3 returns
      `user_not_available` and the probe FAILS. Both are correct readings of the
      server it was pointed at. Read the venue before reading the verdict.

WHY STEP 4 IS NOT OPTIONAL
    A `user_not_available` at step 3 is indistinguishable from "the server never
    registered this websocket as a session for this user" — an empty result from
    a broken instrument looks exactly like one from a real defect. Step 4 is the
    positive control that separates them, and the probe SKIPS rather than fails
    if the control does not come back `queued`: with no working instrument there
    is no finding, in either direction.

Requires environment variables:
    LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL    - Email for login
    LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD - Password for login

Run: pytest src/tests/smoke/test_notify_idempotency_midconnect_smoke.py -v
     python src/tests/smoke/test_notify_idempotency_midconnect_smoke.py
"""

import asyncio
import json
import os
import random
import string
import sys
import urllib.parse
import uuid

import pytest
import requests
import websockets

# Bootstrap imports
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )

src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )


# Configuration
BASE_URL    = "http://127.0.0.1:7999"
REQ_TIMEOUT = 15                                                  # server can be slow under load
API_KEY_REL = "src/conf/keys/notification-api-claude-code-dev"


def _require_server():
    """
    Skip when :7999 is unreachable — no instrument, no finding.

    Deliberately narrow: it skips on a CONNECTION-level failure only, never on a
    bad status or a slow response. A server that answers wrongly is a finding and
    must still fail; a server that is not there cannot answer at all, and a raw
    ConnectionError from deep inside the probe reads like a defect in the code
    under test rather than an absent venue.

    Ensures:
        - calls pytest.skip when the health endpoint cannot be reached
        - returns None and lets the test proceed otherwise
    """
    try:
        requests.get( f"{BASE_URL}/health", timeout=REQ_TIMEOUT )
    except requests.exceptions.ConnectionError as e:
        pytest.skip( f"venue not available: {BASE_URL} unreachable ({e.__class__.__name__})" )


def _credentials():
    """
    Read the shared test credentials.

    Ensures:
        - returns ( email, password ) both non-empty

    Raises:
        - ValueError naming both variables when either is unset
    """
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        raise ValueError(
            "Set LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and "
            "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD environment variables"
        )
    return email, password


def _access_token( email, password ):
    """
    Authenticate via /auth/login and return the JWT access token.

    The `mock_token_email_<addr>` form documented for some WebSocket paths is
    REJECTED here — the queue socket runs the token through a JWT decoder and
    answers `401 Token validation failed: Invalid header string`. Measured
    2026-09-01; using it silently produced the same auth failure that a genuine
    defect produces.

    Ensures:
        - returns a non-empty token string
    """
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json    = { "email": email, "password": password },
        timeout = REQ_TIMEOUT,
    )
    assert resp.status_code == 200, f"login failed: {resp.status_code} {resp.text[ :200 ]}"
    token = resp.json()[ "tokens" ][ "access_token" ]
    assert token, "empty access_token returned"
    return token


def _notify( email, idempotency_key ):
    """
    POST one fire-and-forget notification and return ( status, delivered ).

    Requires:
        - idempotency_key is a UUID string

    Ensures:
        - returns the server's own `status` and `delivered` fields verbatim
    """
    api_key = open( os.path.join( lupin_root, API_KEY_REL ) ).read().strip()
    resp    = requests.post(
        f"{BASE_URL}/api/notify",
        params  = {
            "message"         : "midconnect idempotency probe",
            "type"            : "task",
            "priority"        : "high",
            "target_user"     : email,
            "sender_id"       : "ask.flow@lupin.deepily.ai",
            "suppress_ding"   : "true",
            "idempotency_key" : idempotency_key,
        },
        headers = { "X-API-Key": api_key },
        timeout = REQ_TIMEOUT,
    )
    assert resp.status_code == 200, f"notify failed: {resp.status_code} {resp.text[ :200 ]}"
    body = resp.json()
    return body.get( "status" ), body.get( "delivered" )


async def _run_probe( email, token ):
    """
    Drive the four steps and return every observation for the caller to judge.

    Deliberately asserts NOTHING itself — a probe that decides its own verdict
    mid-flight cannot report the case where its instrument was broken.

    Ensures:
        - returns dict with keys: offline, auth, same_key, control
    """
    key = str( uuid.uuid4() )
    out = {}

    # STEP 1 — the user has no websocket; the verdict gets cached here.
    out[ "offline" ] = _notify( email, key )

    # STEP 2 — connect and authenticate, mirroring the handshake in
    # src/tests/websocket_smoke/infrastructure/test_utilities.py::connect_websocket.
    # The queue socket rejects a session id containing DIGITS with HTTP 403 —
    # it enforces the "adjective noun" shape (`wise penguin`). A uuid4 hex suffix
    # is rejected; measured 2026-09-01, and it looked exactly like a server that
    # was not ready. Alphabetic only.
    session_id = "probe " + "".join( random.choice( string.ascii_lowercase ) for _ in range( 6 ) )
    url        = f"ws://127.0.0.1:7999/ws/queue/{urllib.parse.quote( session_id )}"
    try:
        ws_cm = websockets.connect( url )
    except Exception as e:                                        # pragma: no cover - defensive
        out[ "auth" ] = f"connect_failed: {type( e ).__name__}"
        return out
    # A server still warming up rejects the upgrade with HTTP 403 — measured
    # 2026-09-01 against a boot ~10s old, where the HTTP door was already
    # answering /health with 200. That is an INSTRUMENT failure, not a finding,
    # so it is reported as one rather than raised: a probe that crashes here
    # tells the caller nothing about the cache.
    try:
        conn = await ws_cm
    except Exception as e:
        out[ "auth" ] = f"connect_failed: {type( e ).__name__}: {e}"
        return out
    async with conn as ws:
        await ws.send( json.dumps( {
            "type"              : "auth_request",
            "token"             : f"Bearer {token}",
            "subscribed_events" : [ "auth_success", "auth_error", "notification_update" ],
        } ) )
        resp = json.loads( await asyncio.wait_for( ws.recv(), timeout=REQ_TIMEOUT ) )
        out[ "auth" ] = resp.get( "type" )
        if out[ "auth" ] != "auth_success":
            return out

        # STEP 3 — SAME key, user now online. The reading under test.
        out[ "same_key" ] = _notify( email, key )

        # STEP 4 — POSITIVE CONTROL: fresh key, same live connection, same instant.
        out[ "control" ]  = _notify( email, str( uuid.uuid4() ) )

    return out


def test_a_cached_offline_verdict_is_not_replayed_to_a_connected_user():
    """
    A retry under one idempotency key must re-read connectivity, not replay.

    Requires:
        - :7999 is up and the test credentials are exported

    Ensures:
        - SKIPS when the instrument cannot discriminate (auth failed, or the
          control did not return `queued`) — an unproven instrument yields no
          finding, never a pass and never a fail
        - FAILS when the same key answers `user_not_available` while a fresh key
          to the same live socket answers `queued`
    """
    _require_server()
    email, password = _credentials()
    token           = _access_token( email, password )
    obs             = asyncio.run( _run_probe( email, token ) )

    assert obs[ "offline" ] == ( "user_not_available", False ), (
        f"precondition not met: the user was already connected at step 1 "
        f"({obs[ 'offline' ]}) — nothing was cached, so this run cannot discriminate"
    )

    if obs.get( "auth" ) != "auth_success":
        pytest.skip( f"instrument not proven: websocket auth returned {obs.get( 'auth' )!r}" )

    if obs.get( "control" ) != ( "queued", True ):
        pytest.skip(
            f"instrument not proven: the positive control returned {obs.get( 'control' )!r}, "
            f"not ( 'queued', True ). The server does not see this websocket as delivering "
            f"for this user, so the same-key reading says nothing about the cache."
        )

    assert obs[ "same_key" ] == ( "queued", True ), (
        f"cached offline verdict replayed to a CONNECTED user: same key returned "
        f"{obs[ 'same_key' ]} while a fresh key on the same live socket returned "
        f"{obs[ 'control' ]} at the same instant"
    )


if __name__ == "__main__":
    _email, _password = _credentials()
    _obs = asyncio.run( _run_probe( _email, _access_token( _email, _password ) ) )
    print( f"  step 1  offline, key K      -> {_obs.get( 'offline' )}" )
    print( f"  step 2  websocket auth      -> {_obs.get( 'auth' )!r}" )
    print( f"  step 3  SAME key, online    -> {_obs.get( 'same_key' )}" )
    print( f"  step 4  control, fresh key  -> {_obs.get( 'control' )}" )
    if _obs.get( "control" ) != ( "queued", True ):
        print( "\nNO VERDICT — instrument not proven." ); sys.exit( 3 )
    if _obs.get( "same_key" ) == ( "queued", True ):
        print( "\nFIXED — connectivity re-evaluated." ); sys.exit( 0 )
    print( "\nDEFECT REPRODUCED — cached offline verdict replayed to a connected user." )
    sys.exit( 1 )
