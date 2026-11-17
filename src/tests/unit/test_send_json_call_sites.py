"""
What each send_json caller hands to the wire: headers, timeout, cut and error mapping.

urlopen is replaced, and the request it receives is read back, so each wire is checked at the socket door.
"""

import types

import pytest

from cosa.agents import model_window
from cosa.repo.doc_lint import jev_transport
from cosa.utils import hook_link_tick
from lupin_arbiter_app import arbiter_live_notify
from lupin_mcp.reuse_candidates import CandidateStage


class _Reply:
    headers = {}
    def __init__( self, status, text ): self.status, self._text = status, text
    def read( self ): return self._text.encode()
    def __enter__( self ): return self
    def __exit__( self, *a ): return False


@pytest.fixture
def wire( monkeypatch ):
    """Replace urlopen; answers is the reply to give, seen collects ( request, timeout )."""
    state = { "seen": [], "reply": _Reply( 200, "{}" ) }
    def fake( request, timeout ):
        state[ "seen" ].append( ( request, timeout ) )
        return state[ "reply" ]
    monkeypatch.setattr( "urllib.request.urlopen", fake )
    return state


def test_model_window_passes_its_timeout_and_turns_an_error_status_into_a_runtime_error( wire ):
    model_window._post_json( "http://x/tokenize", { "a": 1 }, 7 )
    assert wire[ "seen" ][ 0 ][ 1 ] == 7
    wire[ "reply" ] = _Reply( 500, '{"detail": "down"}' )
    with pytest.raises( RuntimeError, match="HTTP Error 500: .*down" ): model_window._post_json( "http://x/tokenize", {}, 7 )


def test_jev_transport_passes_its_headers_and_timeout( wire ):
    jev_transport._post( "http://x/y", { "X-Probe": "h1" }, b"{}", 11 )
    request, timeout = wire[ "seen" ][ 0 ]
    assert ( request.get_header( "X-probe" ), timeout ) == ( "h1", 11 )


def test_hook_link_tick_sends_the_key_the_timeout_and_cuts_the_reply_to_400( wire ):
    wire[ "reply" ] = _Reply( 200, "z" * 1000 )
    status, text = hook_link_tick.post_json( "http://x", "key-1", "/p", { "a": 1 } )
    request, timeout = wire[ "seen" ][ 0 ]
    assert ( status, len( text ) ) == ( 200, 400 )
    assert ( request.get_header( "X-api-key" ), timeout ) == ( "key-1", hook_link_tick.HTTP_TIMEOUT_SECONDS )


def test_arbiter_live_notify_passes_its_headers_and_timeout( wire ):
    arbiter_live_notify._http_post_json( "http://x/y", { "X-Probe": "h2" }, {}, timeout_seconds=13 )
    request, timeout = wire[ "seen" ][ 0 ]
    assert ( request.get_header( "X-probe" ), timeout ) == ( "h2", 13 )


def test_reuse_candidates_passes_the_client_timeout_and_key( wire ):
    client = types.SimpleNamespace( base_url="http://x", api_key="k3", timeout=17, _urlopen=lambda request, timeout: wire[ "seen" ].append( ( request, timeout ) ) or wire[ "reply" ] )
    CandidateStage._call( client, "POST", "/q", {} )
    request, timeout = wire[ "seen" ][ 0 ]
    assert ( request.get_header( "X-api-key" ), timeout ) == ( "k3", 17 )
