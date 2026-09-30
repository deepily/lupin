"""
Unit tests for src/scripts/test_websocket_notification.py — the WebSocket delivery diagnostic.

WHY THIS FILE EXISTS (row d519b4fc, epic e2099400): `src/scripts` is entering the coverage
frame and this module sat at ZERO — 156 statements, 36 branches, nothing measured. Behaviour
tests, not a coverage veneer: the mutation table on the row names which test reddens for each
behaviour broken.

🔴 THE COLLECTION QUESTION THE ROW ASKED FIRST, SETTLED BY RUNNING PYTEST RATHER THAN READING
   THE CONFIG — the subject is NAMED `test_*` and lives in `src/scripts`, so it could be both
   the thing under test and a participant in the run.

   ANSWER: it is DISCOVERED but yields NOTHING, and importing it is harmless.
   · `pytest src/scripts/test_websocket_notification.py --collect-only` → "no tests collected".
   · `pytest src/scripts --collect-only` → "no tests collected".
   · WHY: pytest.ini sets `python_files = test_*.py` (the filename matches, so the module IS
     imported during discovery) but `python_functions = test_*` and `python_classes = Test*`.
     The module defines `login_user`, `check_websocket_state_via_admin_api`,
     `send_notification` and `main` — not one of them matches. So collection imports it and
     collects zero items.
   · THE IMPORT IS SIDE-EFFECT FREE: both collect runs completed with the unit tier's network
     guard armed and reported `outbound connections: 0`, and `main()` is behind
     `if __name__ == "__main__":`.
   · THE UNIT TIER NEVER REACHES IT ANYWAY: `run-unit-tests.sh` passes `src/tests/unit/`
     explicitly, and pytest.ini declares NO `testpaths` — scope comes from the runner's
     argument, not from config.

   ⇒ RESIDUAL, AND IT IS SMALL: a bare `pytest` with no path argument would import this file,
   because rootdir discovery reaches it. Harmless today for the reason above; it is a fact
   about the tree rather than a defect, and it is recorded so the next reader does not have
   to re-derive it.

   THIS TEST FILE IS DELIBERATELY NAMED `test_websocket_notification_script.py`, not
   `test_websocket_notification.py`. Two modules with the same basename in one pytest run
   collide on import in a rootless layout, and the subject already owns that name.

⚠️ HAZARDS, GUARDED AUTOUSE. Every function here talks to a live server over `requests`, and
`main` additionally reads a REAL API-key file and can query the user database. Each guard
rebinds the name ON THE MODULE (`monkeypatch.setattr( mod, ... )`) rather than patching the
shared package, so nothing leaks into another importer. Unstubbed calls raise rather than
dial out, and three tests assert the guards still bite.
"""

import json
import os
import sys
from pathlib import Path

import pytest


def _load_module():
    """Import the script under its real name (src/scripts on path) so coverage targets the file."""
    root        = os.environ[ "LUPIN_ROOT" ]
    scripts_dir = os.path.join( root, "src", "scripts" )
    if scripts_dir not in sys.path:
        sys.path.insert( 0, scripts_dir )
    import test_websocket_notification
    return test_websocket_notification


mod = _load_module()


# ── stubs ────────────────────────────────────────────────────────────────────────

class _Requests:
    """Stand-in for the `requests` module bound into the script. Unstubbed calls raise."""

    def __init__( self ):
        self.posts   = []
        self.gets    = []
        self.on_post = None
        self.on_get  = None

    def post( self, url, **kwargs ):
        self.posts.append( ( url, kwargs ) )
        if self.on_post is None:
            raise AssertionError( f"unstubbed POST reached the network: {url}" )
        result = self.on_post( url, **kwargs )
        if isinstance( result, BaseException ):
            raise result
        return result

    def get( self, url, **kwargs ):
        self.gets.append( ( url, kwargs ) )
        if self.on_get is None:
            raise AssertionError( f"unstubbed GET reached the network: {url}" )
        result = self.on_get( url, **kwargs )
        if isinstance( result, BaseException ):
            raise result
        return result


class _Response:
    def __init__( self, status_code=200, payload=None, text="" ):
        self.status_code = status_code
        self._payload    = payload if payload is not None else {}
        self.text        = text

    def json( self ):
        return self._payload


class _Clock:
    """Replaces the module's `time`, so --wait costs no wall time."""

    def __init__( self ):
        self.slept = []

    def sleep( self, seconds ):
        self.slept.append( seconds )


# ── fixtures ─────────────────────────────────────────────────────────────────────

@pytest.fixture( autouse=True )
def no_network( monkeypatch ):
    stub = _Requests()
    monkeypatch.setattr( mod, "requests", stub )
    return stub


@pytest.fixture( autouse=True )
def no_clock( monkeypatch ):
    monkeypatch.setattr( mod, "time", _Clock() )
    return mod.time


@pytest.fixture( autouse=True )
def no_real_api_key( monkeypatch ):
    """`main` reads a real key file out of the checkout; never let a test touch it."""
    def _refuse( path ):
        raise AssertionError( f"a test read the real API key file: {path}" )

    monkeypatch.setattr( mod, "load_api_key", _refuse )


@pytest.fixture( autouse=True )
def no_user_lookup( monkeypatch ):
    """The database fallback in `main` — only reachable when login returns no user_id."""
    def _refuse( email ):
        raise AssertionError( f"a test reached the user database for {email}" )

    monkeypatch.setattr( mod, "get_user_by_email", _refuse )


@pytest.fixture
def api_key( monkeypatch ):
    monkeypatch.setattr( mod, "load_api_key", lambda path: "test-api-key" )
    return "test-api-key"


SERVER = "http://localhost:7999"

# Built rather than written literally: the pre-commit secret scanner flags any literal
# adjacent to an "access_token" key, and it is right to — a synthetic token and a real one
# are indistinguishable to it. These are 60 characters of a repeated letter.
FAKE_TOKEN_NESTED = "a" * 60
FAKE_TOKEN_FLAT   = "b" * 60
FAKE_TOKEN_NO_ID  = "c" * 60
FAKE_TOKEN_PLAIN  = "d" * 60


# ── the guards themselves ────────────────────────────────────────────────────────

def test_an_unstubbed_post_fails_instead_of_reaching_the_network():
    with pytest.raises( AssertionError, match="unstubbed POST" ):
        mod.requests.post( f"{SERVER}/anything" )


def test_the_api_key_file_is_not_readable_from_a_test():
    with pytest.raises( AssertionError, match="real API key file" ):
        mod.load_api_key( "/some/path" )


def test_the_user_database_is_not_reachable_from_a_test():
    with pytest.raises( AssertionError, match="reached the user database" ):
        mod.get_user_by_email( "someone@example.invalid" )


# ── login_user ───────────────────────────────────────────────────────────────────

def test_login_reads_the_nested_token_shape( no_network, capsys ):
    no_network.on_post = lambda url, **kw: _Response( 200, {
        "tokens" : { "access_token": FAKE_TOKEN_NESTED },
        "user"   : { "id": "user-1" },
    } )

    token, user_id = mod.login_user( "e@x.invalid", "pw", SERVER )

    assert token == FAKE_TOKEN_NESTED
    assert user_id == "user-1"
    assert "Login successful" in capsys.readouterr().out


def test_login_reads_the_flat_token_shape( no_network ):
    no_network.on_post = lambda url, **kw: _Response( 200, {
        "access_token" : FAKE_TOKEN_FLAT,
        "user_id"      : "user-2",
    } )

    token, user_id = mod.login_user( "e@x.invalid", "pw", SERVER )

    assert ( token, user_id ) == ( FAKE_TOKEN_FLAT, "user-2" )


def test_login_returns_no_user_id_when_the_nested_shape_omits_the_user( no_network ):
    """The caller has a database fallback for exactly this — it must see None, not a crash."""
    no_network.on_post = lambda url, **kw: _Response( 200, { "tokens": { "access_token": FAKE_TOKEN_NO_ID } } )

    token, user_id = mod.login_user( "e@x.invalid", "pw", SERVER )

    assert token == FAKE_TOKEN_NO_ID
    assert user_id is None


def test_login_posts_the_credentials_to_the_auth_endpoint( no_network ):
    no_network.on_post = lambda url, **kw: _Response( 200, { "access_token": FAKE_TOKEN_PLAIN } )
    mod.login_user( "e@x.invalid", "pw", SERVER )

    url, kwargs = no_network.posts[ 0 ]
    assert url == f"{SERVER}/auth/login"
    assert kwargs[ "json" ] == { "email": "e@x.invalid", "password": "pw" }


def test_login_raises_and_names_the_status_on_a_rejection( no_network, capsys ):
    no_network.on_post = lambda url, **kw: _Response( 401, text="bad credentials" )

    with pytest.raises( Exception ) as info:
        mod.login_user( "e@x.invalid", "pw", SERVER )

    assert "HTTP 401" in str( info.value )
    assert "bad credentials" in str( info.value )
    assert "Login failed" in capsys.readouterr().out


def test_login_raises_when_the_body_carries_no_token_at_all( no_network ):
    no_network.on_post = lambda url, **kw: _Response( 200, { "detail": "who knows" } )

    with pytest.raises( Exception, match="missing access_token" ):
        mod.login_user( "e@x.invalid", "pw", SERVER )


def test_login_re_raises_a_transport_failure_after_reporting_it( no_network, capsys ):
    no_network.on_post = lambda url, **kw: RuntimeError( "connection refused" )

    with pytest.raises( RuntimeError, match="connection refused" ):
        mod.login_user( "e@x.invalid", "pw", SERVER )
    assert "Login failed: connection refused" in capsys.readouterr().out


# ── check_websocket_state_via_admin_api ──────────────────────────────────────────

def _admin( *user_ids ):
    return _Response( 200, { "active_connections": [ { "user_id": u } for u in user_ids ] } )


def test_the_admin_api_reports_a_connected_user( no_network ):
    no_network.on_get = lambda url, **kw: _admin( "user-1", "someone-else" )

    state = mod.check_websocket_state_via_admin_api( SERVER, "user-1" )

    assert state == {
        "is_connected"      : True,
        "connection_count"  : 1,
        "total_connections" : 2,
        "via_api"           : True,
    }


def test_the_admin_api_counts_every_session_for_the_same_user( no_network ):
    """Two tabs are two connections; a count that stopped at the first would read 1."""
    no_network.on_get = lambda url, **kw: _admin( "user-1", "user-1", "other" )

    state = mod.check_websocket_state_via_admin_api( SERVER, "user-1" )

    assert state[ "connection_count" ] == 2
    assert state[ "total_connections" ] == 3


def test_the_admin_api_reports_a_user_who_is_absent_from_the_connection_list( no_network ):
    no_network.on_get = lambda url, **kw: _admin( "someone-else" )

    state = mod.check_websocket_state_via_admin_api( SERVER, "user-1" )

    assert state[ "is_connected" ] is False
    assert state[ "connection_count" ] == 0
    assert state[ "via_api" ] is True


def test_a_non_200_from_the_admin_api_is_unknown_rather_than_disconnected( no_network ):
    """None and False are different answers: one is 'no data', the other is 'not connected'."""
    no_network.on_get = lambda url, **kw: _Response( 404 )

    state = mod.check_websocket_state_via_admin_api( SERVER, "user-1" )

    assert state[ "is_connected" ] is None
    assert state[ "via_api" ] is False
    assert "404" in state[ "error" ]


def test_an_unreachable_admin_api_is_unknown_and_never_raises( no_network ):
    no_network.on_get = lambda url, **kw: RuntimeError( "no route to host" )

    state = mod.check_websocket_state_via_admin_api( SERVER, "user-1" )

    assert state[ "is_connected" ] is None
    assert state[ "via_api" ] is False
    assert state[ "error" ] == "no route to host"


def test_the_admin_query_goes_to_the_status_endpoint( no_network ):
    no_network.on_get = lambda url, **kw: _admin()
    mod.check_websocket_state_via_admin_api( SERVER, "user-1" )
    assert no_network.gets[ 0 ][ 0 ] == f"{SERVER}/admin/websocket/status"


# ── send_notification ────────────────────────────────────────────────────────────

def test_a_notification_returns_the_server_body_verbatim( no_network ):
    no_network.on_post = lambda url, **kw: _Response( 200, { "status": "delivered", "connection_count": 2 } )

    assert mod.send_notification( "e@x.invalid", SERVER, "k" ) == {
        "status": "delivered", "connection_count": 2
    }


def test_a_notification_carries_the_api_key_in_the_header_not_the_query( no_network ):
    no_network.on_post = lambda url, **kw: _Response( 200, { "status": "queued" } )
    mod.send_notification( "e@x.invalid", SERVER, "secret-key" )

    url, kwargs = no_network.posts[ 0 ]
    assert url == f"{SERVER}/api/notify"
    assert kwargs[ "headers" ] == { "X-API-Key": "secret-key" }
    assert "secret-key" not in json.dumps( kwargs[ "params" ] )
    assert kwargs[ "params" ][ "target_user" ] == "e@x.invalid"


def test_a_non_200_notification_is_reported_as_an_http_error( no_network ):
    no_network.on_post = lambda url, **kw: _Response( 500, text="boom" )

    result = mod.send_notification( "e@x.invalid", SERVER, "k" )

    assert result == { "success": False, "status": "http_error", "code": 500, "message": "boom" }


def test_a_transport_failure_is_reported_rather_than_raised( no_network ):
    no_network.on_post = lambda url, **kw: RuntimeError( "socket closed" )

    result = mod.send_notification( "e@x.invalid", SERVER, "k" )

    assert result == { "success": False, "status": "exception", "message": "socket closed" }


# ── main ─────────────────────────────────────────────────────────────────────────

def _run_main( monkeypatch, argv ):
    monkeypatch.setattr( sys, "argv", [ "test_websocket_notification.py" ] + argv )
    return mod.main()


def _wire( monkeypatch, *, login=( "tok", "user-1" ), ws_state=None, notify=None ):
    """Wire main's three collaborators; each test overrides only what it is about."""
    if isinstance( login, BaseException ):
        def _login( *a ):
            raise login
    else:
        def _login( *a ):
            return login

    monkeypatch.setattr( mod, "login_user", _login )
    monkeypatch.setattr( mod, "check_websocket_state_via_admin_api",
                         lambda server, user_id: ws_state if ws_state is not None else
                         { "is_connected": True, "connection_count": 1,
                           "total_connections": 1, "via_api": True } )
    monkeypatch.setattr( mod, "send_notification",
                         lambda email, server, key: notify if notify is not None else
                         { "status": "delivered", "connection_count": 1 } )


def test_a_delivered_notification_exits_zero( monkeypatch, api_key, capsys ):
    _wire( monkeypatch )

    assert _run_main( monkeypatch, [ "--email", "e@x.invalid", "--password", "pw" ] ) == 0
    assert "SUCCESS: Notification delivered!" in capsys.readouterr().out


def test_a_queued_notification_also_counts_as_success( monkeypatch, api_key, capsys ):
    _wire( monkeypatch, notify={ "status": "queued" } )

    assert _run_main( monkeypatch, [ "--email", "e@x.invalid", "--password", "pw" ] ) == 0
    assert "SUCCESS" in capsys.readouterr().out


def test_the_wait_is_honoured_and_defaults_to_three_seconds( monkeypatch, api_key, no_clock ):
    _wire( monkeypatch )

    _run_main( monkeypatch, [ "--email", "e@x.invalid", "--password", "pw" ] )
    assert no_clock.slept == [ 3 ]

    _run_main( monkeypatch, [ "--email", "e@x.invalid", "--password", "pw", "--wait", "11" ] )
    assert no_clock.slept == [ 3, 11 ]


def test_the_server_defaults_to_the_dev_port( monkeypatch, api_key ):
    seen = {}
    _wire( monkeypatch )
    monkeypatch.setattr( mod, "login_user",
                         lambda email, pw, server: seen.setdefault( "server", server ) and None
                         or ( "tok", "user-1" ) )

    _run_main( monkeypatch, [ "--email", "e@x.invalid", "--password", "pw" ] )
    assert seen[ "server" ] == "http://localhost:7999"


def test_a_missing_user_id_is_recovered_from_the_database( monkeypatch, api_key, capsys ):
    _wire( monkeypatch, login=( "tok", None ) )
    monkeypatch.setattr( mod, "get_user_by_email", lambda email: { "id": "user-from-db" } )

    assert _run_main( monkeypatch, [ "--email", "e@x.invalid", "--password", "pw" ] ) == 0
    assert "Found user_id from database: user-from-db" in capsys.readouterr().out


def test_an_unrecoverable_user_id_exits_one_before_sending_anything( monkeypatch, capsys ):
    """The api-key guard is still armed here: reaching step 4 would fail loudly."""
    _wire( monkeypatch, login=( "tok", None ) )
    monkeypatch.setattr( mod, "get_user_by_email", lambda email: None )

    assert _run_main( monkeypatch, [ "--email", "e@x.invalid", "--password", "pw" ] ) == 1
    assert "Could not find user_id" in capsys.readouterr().out


def test_a_disconnected_user_gets_the_warning_block( monkeypatch, api_key, capsys ):
    _wire( monkeypatch, ws_state={ "is_connected": False, "connection_count": 0,
                                   "total_connections": 4, "via_api": True } )

    _run_main( monkeypatch, [ "--email", "e@x.invalid", "--password", "pw" ] )

    out = capsys.readouterr().out
    assert "WARNING: User is NOT connected via WebSocket!" in out
    assert "Status: ❌ Not connected" in out


def test_an_unavailable_admin_api_says_so_and_does_not_warn( monkeypatch, api_key, capsys ):
    """Unknown must not be reported as disconnected — that is the distinction under test."""
    _wire( monkeypatch, ws_state={ "is_connected": None, "connection_count": 0,
                                   "error": "refused", "via_api": False } )

    _run_main( monkeypatch, [ "--email", "e@x.invalid", "--password", "pw" ] )

    out = capsys.readouterr().out
    assert "Admin API not available: refused" in out
    assert "WARNING: User is NOT connected" not in out


def test_user_not_available_with_a_confirmed_disconnection_blames_the_websocket( monkeypatch, api_key, capsys ):
    _wire( monkeypatch,
           ws_state={ "is_connected": False, "connection_count": 0,
                      "total_connections": 0, "via_api": True },
           notify={ "status": "user_not_available" } )

    assert _run_main( monkeypatch, [ "--email", "e@x.invalid", "--password", "pw" ] ) == 0
    out = capsys.readouterr().out
    assert "Confirmed: User is NOT connected via WebSocket" in out


def test_user_not_available_while_connected_is_called_out_as_a_mismatch( monkeypatch, api_key, capsys ):
    """The interesting case: the admin API and the notify API disagree."""
    _wire( monkeypatch,
           ws_state={ "is_connected": True, "connection_count": 1,
                      "total_connections": 1, "via_api": True },
           notify={ "status": "user_not_available" } )

    _run_main( monkeypatch, [ "--email", "e@x.invalid", "--password", "pw" ] )

    out = capsys.readouterr().out
    assert "Possible user_id mismatch or logic error" in out


def test_user_not_available_with_no_admin_api_says_the_state_is_unknown( monkeypatch, api_key, capsys ):
    _wire( monkeypatch,
           ws_state={ "is_connected": None, "connection_count": 0, "error": "x", "via_api": False },
           notify={ "status": "user_not_available" } )

    _run_main( monkeypatch, [ "--email", "e@x.invalid", "--password", "pw" ] )

    assert "WebSocket state unknown" in capsys.readouterr().out


def test_an_unrecognised_status_is_named_rather_than_swallowed( monkeypatch, api_key, capsys ):
    _wire( monkeypatch, notify={ "status": "teapot" } )

    assert _run_main( monkeypatch, [ "--email", "e@x.invalid", "--password", "pw" ] ) == 0
    assert "Unexpected response status: teapot" in capsys.readouterr().out


def test_a_failure_anywhere_exits_one_with_a_traceback( monkeypatch, capsys ):
    _wire( monkeypatch, login=RuntimeError( "login exploded" ) )

    assert _run_main( monkeypatch, [ "--email", "e@x.invalid", "--password", "pw" ] ) == 1
    out = capsys.readouterr()
    assert "DIAGNOSTIC FAILED" in out.out
    assert "login exploded" in out.out
    assert "RuntimeError" in out.err, "the traceback goes to stderr, where a caller can keep it"


def test_the_api_key_is_read_from_the_notification_key_file( monkeypatch, capsys ):
    """The path is built from the module's import-time lupin_root, so it is pinned here."""
    seen = {}
    _wire( monkeypatch )
    monkeypatch.setattr( mod, "load_api_key", lambda path: seen.setdefault( "path", path ) or "k" )

    _run_main( monkeypatch, [ "--email", "e@x.invalid", "--password", "pw" ] )

    assert seen[ "path" ].endswith( "src/conf/keys/notification-api-claude-code-dev" )
    assert seen[ "path" ].startswith( mod.lupin_root )


@pytest.mark.parametrize( "argv", [
    [ "--password", "pw" ],
    [ "--email", "e@x.invalid" ],
] )
def test_both_credentials_are_required_rather_than_defaulted( monkeypatch, argv ):
    """argparse exits 2; a defaulted email would diagnose the wrong user."""
    with pytest.raises( SystemExit ) as info:
        _run_main( monkeypatch, argv )
    assert info.value.code == 2


# ── the import-time bootstrap ────────────────────────────────────────────────────
#
# The bootstrap runs once at import, before any test exists. Re-executed here from source so
# it is covered by EXECUTION rather than excused by a pragma that asserts nothing.

def _exec_bootstrap( namespace_name="test_websocket_notification_bootstrap_probe" ):
    """Compile under the module's REAL filename so coverage attributes the lines to the file."""
    source_path = Path( mod.__file__ )
    code        = compile( source_path.read_text( encoding="utf-8" ), str( source_path ), "exec" )
    namespace   = { "__name__": namespace_name, "__file__": str( source_path ) }
    exec( code, namespace )
    return namespace


def test_the_bootstrap_raises_when_lupin_root_is_not_set( monkeypatch ):
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )

    with pytest.raises( RuntimeError ) as info:
        _exec_bootstrap()

    assert "LUPIN_ROOT environment variable not set" in str( info.value )
    assert "export LUPIN_ROOT=" in str( info.value )


def test_the_bootstrap_inserts_src_at_the_front_when_it_is_absent( monkeypatch, tmp_path ):
    fake = tmp_path / "elsewhere"
    ( fake / "src" ).mkdir( parents=True )
    expected = os.path.join( str( fake ), "src" )

    original_path = list( sys.path )
    assert expected not in sys.path
    try:
        monkeypatch.setenv( "LUPIN_ROOT", str( fake ) )
        _exec_bootstrap()
        assert sys.path[ 0 ] == expected, "the bootstrap must insert at position 0, not append"
    finally:
        sys.path[ : ] = original_path


def test_the_bootstrap_does_not_insert_a_duplicate( monkeypatch ):
    root = os.environ[ "LUPIN_ROOT" ]
    src  = os.path.join( root, "src" )

    original_path = list( sys.path )
    try:
        sys.path.insert( 0, src )
        length_before = len( sys.path )
        _exec_bootstrap()
        assert len( sys.path ) == length_before
    finally:
        sys.path[ : ] = original_path
