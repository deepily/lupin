"""
Row b9604f8c — a run must refuse at second one when a model-server port is not answering.

PROVED BY CONSTRUCTION. The live arms run REAL HTTP servers on real localhost ports and
the dead arms point at a port with nothing listening on it. A test that only exercises the
happy path proves the probe EXISTS, not that it FIRES — and "it fires" is the whole row:
the last outage was invisible because :3001 answered while :3000 did not, and half-alive
read as alive.
"""

import contextlib
import http.server
import json
import socket
import threading

import pytest

from cosa.utils.model_server_liveness import (
    ModelServerUnavailable,
    discover_vllm_endpoints,
    parse_vllm_endpoint,
    probe_endpoint,
    render_refusal,
    require_live,
)


# ── Real servers and real dead ports ────────────────────────────────────────
def _make_handler( status, body ):
    class _Handler( http.server.BaseHTTPRequestHandler ):
        def do_GET( self ):
            payload = body.encode()
            self.send_response( status )
            self.send_header( "Content-Type", "application/json" )
            self.send_header( "Content-Length", str( len( payload ) ) )
            self.end_headers()
            self.wfile.write( payload )

        def log_message( self, *a ):    # keep the test output readable
            pass
    return _Handler


@contextlib.contextmanager
def _serving( model_id="test/model", status=200, body=None ):
    """A real HTTP server on a real ephemeral port, answering /v1/models."""
    payload = body if body is not None else json.dumps( { "data": [ { "id": model_id } ] } )
    server  = http.server.HTTPServer( ( "127.0.0.1", 0 ), _make_handler( status, payload ) )
    thread  = threading.Thread( target=server.serve_forever, daemon=True )
    thread.start()
    try:
        yield f"127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def _dead_endpoint():
    """A port that is genuinely not listening — bound to learn the number, then released."""
    s = socket.socket()
    s.bind( ( "127.0.0.1", 0 ) )
    port = s.getsockname()[ 1 ]
    s.close()
    return f"127.0.0.1:{port}"


@contextlib.contextmanager
def _accepting_but_silent():
    """A socket that accepts the connection and then says nothing — the timeout shape."""
    s = socket.socket()
    s.bind( ( "127.0.0.1", 0 ) )
    s.listen( 1 )
    try:
        yield f"127.0.0.1:{s.getsockname()[ 1 ]}"
    finally:
        s.close()


# ── 1. THE FIRING ARM — a port genuinely not listening ──────────────────────
def test_a_dead_port_refuses_the_run_and_names_it():
    dead = _dead_endpoint()
    with pytest.raises( ModelServerUnavailable ) as exc:
        require_live( endpoints=[ dead ], timeout_s=2 )
    message = str( exc.value )
    assert dead in message
    assert "DID NOT ANSWER" in message


def test_half_alive_is_refused_and_only_the_dead_port_is_blamed():
    """THE INCIDENT. :3001 up, :3000 down — the box looked alive to any one-port check."""
    dead = _dead_endpoint()
    with _serving( model_id="kaitchup/Phi-4" ) as live:
        with pytest.raises( ModelServerUnavailable ) as exc:
            require_live( endpoints=[ dead, live ], timeout_s=2 )
    message = str( exc.value )
    assert message.index( dead ) < message.index( live ), "the dead port leads — it is the action"
    assert "answered" in message and "kaitchup/Phi-4" in message
    assert "half-alive" in message


# ── 2. THE CONTROL — a live pair proceeds ───────────────────────────────────
def test_a_live_pair_proceeds_and_reports_what_it_found():
    with _serving( model_id="ministral-8b" ) as one, _serving( model_id="phi-4" ) as two:
        results = require_live( endpoints=[ one, two ], timeout_s=5 )
    assert [ r[ "alive" ] for r in results ] == [ True, True ]
    assert "ministral-8b" in results[ 0 ][ "detail" ] and "phi-4" in results[ 1 ][ "detail" ]


# ── 3. THE FAILURE SHAPES, each named differently ───────────────────────────
def test_a_socket_that_accepts_and_says_nothing_is_reported_as_a_timeout():
    with _accepting_but_silent() as hung:
        result = probe_endpoint( hung, timeout_s=1 )
    assert result[ "alive" ] is False
    assert "did not answer" in result[ "detail" ]


def test_an_http_error_names_the_status():
    with _serving( status=503, body="upstream down" ) as endpoint:
        result = probe_endpoint( endpoint, timeout_s=5 )
    assert result[ "alive" ] is False
    assert "503" in result[ "detail" ]


def test_something_that_is_not_vllm_answering_is_not_counted_as_alive():
    """A live socket in front of the wrong service is the half-alive reading one layer in."""
    with _serving( body="<html>hello from nginx</html>" ) as endpoint:
        result = probe_endpoint( endpoint, timeout_s=5 )
    assert result[ "alive" ] is False
    assert "not with a model list" in result[ "detail" ]


def test_every_endpoint_is_probed_even_after_the_first_one_fails():
    """Stopping at the first dead port would hide the second — half-alive, again."""
    dead_one, dead_two = _dead_endpoint(), _dead_endpoint()
    with pytest.raises( ModelServerUnavailable ) as exc:
        require_live( endpoints=[ dead_one, dead_two ], timeout_s=2 )
    assert dead_one in str( exc.value ) and dead_two in str( exc.value )


# ── 4. DISCOVERY — probe what the run will actually dial ────────────────────
class _StubConfig:
    def __init__( self, pairs ): self._pairs = pairs
    def get_keys( self ):        return list( self._pairs.keys() )
    def get( self, key, default=None, silent=False ): return self._pairs.get( key, default )


def test_discovery_returns_each_endpoint_once():
    config = _StubConfig( {
        "router/ministral" : "vllm://192.168.1.21:3000@some/model",
        "router/qwen"      : "vllm://192.168.1.21:3000@other/model",
        "judge/phi4"       : "vllm://192.168.1.21:3001@kaitchup/Phi-4",
        "some flag"        : "true",
        "openai/gpt"       : "openai://gpt-4",
        "a number"         : 7,
    } )
    assert discover_vllm_endpoints( config ) == [ "192.168.1.21:3000", "192.168.1.21:3001" ]


def test_parse_ignores_everything_that_is_not_a_vllm_spec():
    assert parse_vllm_endpoint( "vllm://host:3000@model" ) == "host:3000"
    assert parse_vllm_endpoint( "openai://gpt-4" ) is None
    assert parse_vllm_endpoint( None ) is None
    assert parse_vllm_endpoint( 42 ) is None
    assert parse_vllm_endpoint( "vllm://@model" ) is None


def test_nothing_to_probe_is_a_refusal_not_a_pass():
    """An empty endpoint list cannot prove a live dependency, so it must not read as one."""
    with pytest.raises( ModelServerUnavailable ):
        require_live( endpoints=[] )


def test_require_live_needs_something_to_work_from():
    with pytest.raises( ValueError ):
        require_live()


def test_refusal_text_stands_alone_when_nothing_answered():
    results = [ { "endpoint": "h:3000", "alive": False, "detail": "did not answer", "models": [] } ]
    text = render_refusal( results, context="the paired run" )
    assert "the paired run" in text
    assert "half-alive" not in text, "with nothing alive, the half-alive note would be wrong"


def test_a_non_error_status_that_is_not_200_is_not_counted_as_alive():
    """
    urllib raises for 4xx/5xx, so this is the OTHER way a server answers without serving:
    a 204/3xx that arrives as an ordinary response. It answered, it is not serving models,
    and calling that alive is the half-alive reading in miniature.
    """
    with _serving( status=204, body="" ) as endpoint:
        result = probe_endpoint( endpoint, timeout_s=5 )
    assert result[ "alive" ] is False
    assert "204" in result[ "detail" ]


def test_require_live_discovers_endpoints_from_the_configuration():
    """
    The caller passes the config the RUN reads, not a hand-kept list — so an endpoint added
    to lupin-app.ini is probed without anyone remembering to update the probe.
    """
    with _serving( model_id="ministral-8b" ) as endpoint:
        config  = _StubConfig( { "router/ministral": f"vllm://{endpoint}@some/model" } )
        results = require_live( config_mgr=config, timeout_s=5 )
    assert [ r[ "endpoint" ] for r in results ] == [ endpoint ]
