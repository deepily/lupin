"""
tests.helpers.app_login tells a refused login from no server.

A local stub answers the login with a chosen status and body, so no real server, account or database
is touched. A closed local port stands for "no server".
"""

import http.server
import json
import socket
import threading

import pytest

from tests.helpers import app_login


def _stub( status, body ):
    """Serve every POST with `status` and `body`; return ( base_url, server )."""
    class Handler( http.server.BaseHTTPRequestHandler ):
        def do_POST( self ):
            self.rfile.read( int( self.headers.get( "Content-Length", 0 ) ) )
            self.send_response( status )
            self.send_header( "Content-Type", "application/json" )
            self.end_headers()
            self.wfile.write( body )

        def log_message( self, *args ): pass

    server = http.server.HTTPServer( ( "127.0.0.1", 0 ), Handler )
    threading.Thread( target=server.serve_forever, daemon=True ).start()
    return f"http://127.0.0.1:{server.server_address[ 1 ]}", server


@pytest.fixture
def stub():
    servers = [ ]

    def make( status, body ):
        base_url, server = _stub( status, body )
        servers.append( server )
        return base_url

    yield make
    for server in servers:
        server.shutdown()
        server.server_close()


def _closed_port_url():
    probe = socket.socket()
    probe.bind( ( "127.0.0.1", 0 ) )
    port = probe.getsockname()[ 1 ]
    probe.close()
    return f"http://127.0.0.1:{port}"


def _outcome( call ):
    """
    Run `call` and say how it ended: returned, failed or skipped, with the text.

    A skip raised inside pytest.raises(fail) would turn the test itself into a skip, which reads green.
    Reading the outcome by name makes a skip where a failure is owed a red test.
    """
    try:
        return "returned", call()
    except pytest.fail.Exception as error:
        return "failed", str( error )
    except pytest.skip.Exception as error:
        return "skipped", str( error )


GOOD = json.dumps( { "tokens": { "access_token": "abc" }, "user": { "id": 1 } } ).encode()


def test_a_good_login_returns_the_whole_body( stub ):
    how, payload = _outcome( lambda: app_login.login( stub( 200, GOOD ), "probe@example.invalid", "x" ) )
    assert how == "returned"
    assert payload[ "tokens" ][ "access_token" ] == "abc" and payload[ "user" ] == { "id": 1 }


@pytest.mark.parametrize( "status", [ 401, 403, 500 ] )
def test_a_refused_login_fails_and_names_the_account_and_the_host( stub, status ):
    base_url = stub( status, b'{"detail":"no"}' )
    how, message = _outcome( lambda: app_login.login( base_url, "probe@example.invalid", "x" ) )
    assert how == "failed"
    assert "probe@example.invalid" in message and base_url in message and f"HTTP {status}" in message


def test_a_closed_port_still_skips():
    how, message = _outcome( lambda: app_login.login( _closed_port_url(), "probe@example.invalid", "x" ) )
    assert how == "skipped" and "no server answered" in message


def test_a_timeout_still_skips( monkeypatch ):
    def slow( *args, **kwargs ): raise TimeoutError( "timed out" )
    monkeypatch.setattr( app_login.urllib.request, "urlopen", slow )
    how, _ = _outcome( lambda: app_login.login( "http://127.0.0.1:1", "probe@example.invalid", "x" ) )
    assert how == "skipped"


@pytest.mark.parametrize( "body", [ b'{"user":{}}', b'{"tokens":{}}', b'{"tokens":{"access_token":""}}', b'[1,2]' ] )
def test_an_answer_without_a_token_fails( stub, body ):
    how, message = _outcome( lambda: app_login.login( stub( 200, body ), "probe@example.invalid", "x" ) )
    assert how == "failed" and "without an access token" in message


def test_an_answer_that_is_not_json_raises_rather_than_skipping( stub ):
    with pytest.raises( ValueError ):
        app_login.login( stub( 200, b"<html>" ), "probe@example.invalid", "x" )
