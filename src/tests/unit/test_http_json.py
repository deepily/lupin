"""
send_json against a real local HTTP server, so status, body and headers meet real urllib.
"""

import json
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from cosa.utils.http_json import send_json


class _Echo( BaseHTTPRequestHandler ):
    """Answers 200 with what it received, or 422 for /refuse."""
    seen = []

    def do_POST( self ):
        n    = int( self.headers.get( "Content-Length", 0 ) )
        body = self.rfile.read( n )
        type( self ).seen.append( { "path": self.path, "method": self.command, "body": body, "ctype": self.headers.get( "Content-Type" ), "key": self.headers.get( "X-API-Key" ) } )
        self.send_response( 422 if self.path == "/refuse" else 200 )
        self.send_header( "X-Request-Id", "r-1" )
        self.end_headers()
        self.wfile.write( json.dumps( { "detail": "no" } if self.path == "/refuse" else { "echo": body.decode() } ).encode() )

    do_PUT = do_POST

    def log_message( self, *a ): pass


@pytest.fixture
def server():
    _Echo.seen = []
    httpd = HTTPServer( ( "127.0.0.1", 0 ), _Echo )
    t     = threading.Thread( target=httpd.serve_forever, daemon=True )
    t.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()


def test_a_dict_is_sent_as_json_with_the_default_content_type( server ):
    status, text, reply = send_json( server + "/ok", { "a": 1 } )
    assert ( status, json.loads( text ) ) == ( 200, { "echo": '{"a": 1}' } )
    assert _Echo.seen[ 0 ][ "ctype" ] == "application/json" and _Echo.seen[ 0 ][ "method" ] == "POST"
    assert reply[ "X-Request-Id" ] == "r-1"


@pytest.mark.parametrize( "payload, wire", [ ( None, b"" ), ( b"\x01raw", b"\x01raw" ), ( "text", b"text" ), ( [ 1, 2 ], b"[1, 2]" ) ] )
def test_each_payload_kind_reaches_the_wire_as_these_bytes( server, payload, wire ):
    send_json( server + "/ok", payload )
    assert _Echo.seen[ 0 ][ "body" ] == wire


def test_given_headers_are_added_and_may_replace_the_content_type( server ):
    send_json( server + "/ok", {}, headers={ "X-API-Key": "k", "Content-Type": "application/x-test" }, method="PUT" )
    assert ( _Echo.seen[ 0 ][ "key" ], _Echo.seen[ 0 ][ "ctype" ], _Echo.seen[ 0 ][ "method" ] ) == ( "k", "application/x-test", "PUT" )


def test_an_error_status_is_returned_with_its_body_not_raised( server ):
    status, text, reply = send_json( server + "/refuse", {} )
    assert ( status, json.loads( text ) ) == ( 422, { "detail": "no" } )
    assert reply[ "X-Request-Id" ] == "r-1"


def test_no_answer_at_all_raises( server ):
    with pytest.raises( urllib.error.URLError ): send_json( "http://127.0.0.1:1/x", {}, timeout=2 )


def test_the_opener_seam_replaces_urlopen():
    class Out:
        status  = 201
        headers = {}
        def read( self ): return b"\xff ok"
        def __enter__( self ): return self
        def __exit__( self, *a ): return False
    seen = []
    def opener( request, timeout ): seen.append( ( request.full_url, timeout ) ); return Out()
    assert send_json( "http://x/y", {}, timeout=7, opener=opener ) == ( 201, "� ok", {} )
    assert seen == [ ( "http://x/y", 7 ) ]
