"""
/api/docs/upload refuses an oversized body BEFORE it is spooled — the guard, entered over HTTP.

The defect: the 100 MB cap lived inside the handler's chunk loop, after FastAPI had parsed and
spooled the whole multipart body. `UploadSizeGuard` is the ASGI middleware that closes it:
a Content-Length over the limit is refused unread, and a body with no Content-Length is counted
as it streams and aborted past the limit.

🔴 THE REFUSAL ARMS ASSERT THE HANDLER WAS NEVER REACHED. A 413 alone is also what the handler's
own backstop answers, after the spool; the spy on `_resolve_scoped` (the handler's first real step)
is what shows the body was stopped BEFORE it. Each refusal arm has a pass-through arm beside it.
"""
import asyncio
import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import cosa.rest.routers.docs_files as docs_files
from cosa.rest import upload_size_guard as guard_mod
from cosa.rest.auth_middleware import require_admin
from cosa.rest.upload_size_guard import UploadSizeGuard

CAP   = 1000
SLACK = 1000


@pytest.fixture
def reached( monkeypatch ):
    """The handler's first real step, spied: records the call and stops the request with a marker 404."""
    calls = []

    def _spy( *args, **kwargs ):
        calls.append( args )
        raise HTTPException( status_code=404, detail="reached-handler" )

    monkeypatch.setattr( docs_files, "_resolve_scoped", _spy )
    monkeypatch.setattr( docs_files, "UPLOAD_MAX_BYTES", CAP )
    monkeypatch.setattr( guard_mod, "FRAMING_SLACK_BYTES", SLACK )
    return calls


@pytest.fixture
def client( reached ):
    app = FastAPI()
    app.add_middleware( UploadSizeGuard )
    app.include_router( docs_files.router )
    app.dependency_overrides[ require_admin ] = lambda: { "email": "admin@example.com" }
    return TestClient( app )


BOUNDARY = "testboundary"


def _multipart( size ):
    """A real multipart body: a `dir` field and a file of `size` bytes."""
    head = (
        f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"dir\"\r\n\r\nlupin/docs\r\n"
        f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.txt\"\r\n"
        f"Content-Type: text/plain\r\n\r\n"
    ).encode()
    return head + b"x" * size + f"\r\n--{BOUNDARY}--\r\n".encode()


def _chunks( body, step=300 ):
    for i in range( 0, len( body ), step ):
        yield body[ i:i + step ]


HEADERS = { "content-type": f"multipart/form-data; boundary={BOUNDARY}" }


# ── the three cases Mr. Radio named ─────────────────────────────────────────

def test_a_declared_length_over_the_cap_is_refused_unread( client, reached ):
    body = _multipart( CAP * 5 )
    resp = client.post( "/api/docs/upload", content=body, headers=HEADERS )
    assert "content-length" in resp.request.headers, "precondition: this arm is the declared-length case"
    assert resp.status_code == 413
    assert "upload cap" in resp.json()[ "detail" ]
    assert reached == [], "the handler was reached: the body was parsed before it was refused"


def test_a_chunked_body_with_no_length_that_goes_over_the_cap_is_aborted( client, reached ):
    body = _multipart( CAP * 5 )
    resp = client.post( "/api/docs/upload", content=_chunks( body ), headers=HEADERS )
    assert "content-length" not in resp.request.headers, "precondition: this arm is the NO-header case"
    assert resp.request.headers.get( "transfer-encoding" ) == "chunked"
    assert resp.status_code == 413
    assert "upload cap" in resp.json()[ "detail" ]
    assert reached == [], "the handler was reached: the streamed body was not counted"


@pytest.mark.parametrize( "chunked", [ False, True ] )
def test_a_body_under_the_cap_passes_through( client, reached, chunked ):
    body    = _multipart( 200 )
    content = _chunks( body ) if chunked else body
    resp    = client.post( "/api/docs/upload", content=content, headers=HEADERS )
    assert resp.status_code == 404 and resp.json()[ "detail" ] == "reached-handler"
    assert len( reached ) == 1


def test_a_body_at_the_cap_with_framing_still_reaches_the_handler( client, reached ):
    """The slack exists so a file exactly at the cap, plus its multipart framing, is not refused here."""
    resp = client.post( "/api/docs/upload", content=_multipart( CAP ), headers=HEADERS )
    assert resp.status_code == 404 and resp.json()[ "detail" ] == "reached-handler"


# ── the guard in isolation, raw ASGI ────────────────────────────────────────

def _run( app, *, path="/api/docs/upload", method="POST", headers=(), messages=(), scope_type="http" ):
    sent  = []
    queue = list( messages )

    async def receive():
        return queue.pop( 0 )

    async def send( message ):
        sent.append( message )

    scope = { "type": scope_type, "path": path, "method": method, "headers": list( headers ) }
    asyncio.run( UploadSizeGuard( app, cap_fn=lambda: CAP )( scope, receive, send ) )
    return sent


async def _echo_ok( scope, receive, send ):
    await send( { "type": "http.response.start", "status": 200, "headers": [] } )
    await send( { "type": "http.response.body", "body": b"ok" } )


def _status( sent ):
    return sent[ 0 ][ "status" ]


@pytest.mark.parametrize( "kwargs", [
    { "path": "/api/other", "headers": [ ( b"content-length", b"999999999" ) ] },
    { "method": "GET",      "headers": [ ( b"content-length", b"999999999" ) ] },
    { "scope_type": "lifespan" },
] )
def test_anything_but_the_guarded_route_passes_through_untouched( kwargs ):
    assert _status( _run( _echo_ok, **kwargs ) ) == 200


@pytest.mark.parametrize( "value", [ b"abc", b"-5", b"" ] )
def test_a_malformed_content_length_is_a_400( value ):
    sent = _run( _echo_ok, headers=[ ( b"content-length", value ) ] )
    assert _status( sent ) == 400
    assert b"Content-Length" in sent[ 1 ][ "body" ]


def test_an_honest_small_content_length_passes():
    sent = _run( _echo_ok, headers=[ ( b"content-length", b"10" ) ] )
    assert _status( sent ) == 200


async def _read_all_then_answer( scope, receive, send ):
    while True:
        message = await receive()
        if message[ "type" ] != "http.request" or not message.get( "more_body" ):
            break
    await _echo_ok( scope, receive, send )


def test_a_disconnect_message_is_not_counted_and_is_not_a_trip():
    sent = _run( _read_all_then_answer, messages=[ { "type": "http.disconnect" } ] )
    assert _status( sent ) == 200


def test_a_request_message_without_a_body_key_counts_as_empty():
    sent = _run( _read_all_then_answer, messages=[ { "type": "http.request" } ] )
    assert _status( sent ) == 200


def test_an_application_that_lets_the_abort_escape_still_gets_a_413():
    """The final-reject path: nothing was sent by the app, the exception reaches the guard."""
    big  = [ { "type": "http.request", "body": b"x" * ( CAP + guard_mod.FRAMING_SLACK_BYTES + 1 ), "more_body": False } ]
    sent = _run( _read_all_then_answer, messages=big )
    assert _status( sent ) == 413
    assert len( sent ) == 2


async def _answers_400_after_a_failed_read( scope, receive, send ):
    """What FastAPI does: swallows the read failure and replies with its own error — two messages."""
    try:
        await receive()
    except Exception:
        pass
    await send( { "type": "http.response.start", "status": 400, "headers": [] } )
    await send( { "type": "http.response.body", "body": b"There was an error parsing the body" } )


def test_the_applications_own_error_reply_is_replaced_by_one_413():
    big  = [ { "type": "http.request", "body": b"x" * ( CAP + guard_mod.FRAMING_SLACK_BYTES + 1 ), "more_body": False } ]
    sent = _run( _answers_400_after_a_failed_read, messages=big )
    assert [ m[ "type" ] for m in sent ] == [ "http.response.start", "http.response.body" ]
    assert _status( sent ) == 413
    assert json.loads( sent[ 1 ][ "body" ] )[ "detail" ].endswith( "upload cap" )


def test_the_default_cap_is_the_handlers_own_constant( monkeypatch ):
    monkeypatch.setattr( docs_files, "UPLOAD_MAX_BYTES", 12345 )
    assert guard_mod._cap_bytes() == 12345


def test_the_real_app_mounts_the_guard_inside_cors():
    """
    Wiring, on the assembled app: the guard exists, and CORS wraps it (a lower index is
    outermost) so a browser can read the 413.
    """
    from starlette.middleware.cors import CORSMiddleware
    from lupin_app import main

    stack = [ m.cls for m in main.app.user_middleware ]
    assert UploadSizeGuard in stack, "lupin_app.main does not mount UploadSizeGuard"
    assert stack.index( CORSMiddleware ) < stack.index( UploadSizeGuard )
