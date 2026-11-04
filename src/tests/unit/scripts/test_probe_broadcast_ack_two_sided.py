"""
The two-sided broadcast-ack probe, run against a stood-in `requests`.

The real probe broadcasts to every live seat, so no test here may reach the network.
Each case scripts the four endpoints and checks the verdict the probe reaches.
A pass needs recipients and at least one attributed saved ack.
It also needs agreeing doors, or an honest note that only one door was measured.
"""

import importlib.util
import json
import os
import types

import pytest

_PROBE = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "scripts", "probe_broadcast_ack_two_sided.py" )


def _load():
    spec = importlib.util.spec_from_file_location( "probe_broadcast_ack_two_sided_t", _PROBE )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )
    return mod


class _Resp:
    def __init__( self, status=200, body=None, text=None ):
        self.status_code = status
        self._body       = body
        self.text        = text if text is not None else json.dumps( body )
    def json( self ):
        if self._body is None: raise ValueError( "no json" )
        return self._body


class _Clock:
    """A clock that only moves when the probe sleeps, so the wait loop ends deterministically."""
    def __init__( self ): self.now = 1000.0
    def time( self ): return self.now
    def sleep( self, secs ): self.now += secs
    def strftime( self, fmt ): return "T"


@pytest.fixture
def probe( monkeypatch ):
    mod = _load()
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL", "e@x" )
    monkeypatch.setenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD", "pw" )
    monkeypatch.setattr( mod, "time", _Clock() )
    monkeypatch.setattr( mod, "ACK_WAIT_SECS", 6.0 )
    world = {
        "login"      : _Resp( 200, { "tokens": { "access_token": "tok" } } ),
        "broadcast"  : _Resp( 200, { "recipients": 2 } ),
        "saved"      : None,
        "undelivered": _Resp( 200, { "notifications": [ ] } ),
        "posts"      : [ ], "gets": [ ],
    }
    def post( url, json=None, headers=None, timeout=None ):
        world[ "posts" ].append( ( url, json, headers ) )
        return world[ "login" ] if url.endswith( "/auth/login" ) else world[ "broadcast" ]
    def get( url, headers=None, timeout=None ):
        world[ "gets" ].append( url )
        if "/broadcast-acks/" in url:
            bid = url.rsplit( "/", 1 )[ 1 ]
            return world[ "saved" ]( bid ) if callable( world[ "saved" ] ) else world[ "saved" ]
        return world[ "undelivered" ]
    monkeypatch.setattr( mod.requests, "post", post )
    monkeypatch.setattr( mod.requests, "get", get )
    mod.world = world
    return mod


def _ack( bid, session="sess-aaaa1111", **extra ):
    return { "broadcast_id": bid, "session_id": session, "persona_name": "Cheech",
             "persona_icon": "x", "ack_status": "ok", "state": "saved", **extra }


def _pushed( bid, session ):
    return { "type": "commons_broadcast_ack", "payload": { "broadcast_id": bid, "session_id": session } }


def test_missing_credentials_exit_two_without_any_request( probe, monkeypatch, capsys ):
    monkeypatch.delenv( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    with pytest.raises( SystemExit ) as stop:
        probe._login()
    assert stop.value.code == 2 and probe.world[ "posts" ] == [ ]
    assert "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" in capsys.readouterr().out


def test_a_rejected_login_fails_with_the_raw_body( probe, capsys ):
    probe.world[ "login" ] = _Resp( 401, text="nope-raw" )
    with pytest.raises( SystemExit ) as stop:
        probe._login()
    out = capsys.readouterr().out
    assert stop.value.code == 1 and "returned 401" in out and "nope-raw" in out


def test_a_login_body_without_a_token_fails( probe, capsys ):
    probe.world[ "login" ] = _Resp( 200, { "tokens": { } } )
    with pytest.raises( SystemExit ) as stop:
        probe._login()
    assert stop.value.code == 1 and "no access_token" in capsys.readouterr().out
    probe.world[ "login" ] = _Resp( 200, text="not json" )
    with pytest.raises( SystemExit ):
        probe._login()


def test_login_returns_the_token( probe ):
    assert probe._login() == "tok"
    assert probe.world[ "posts" ][ 0 ][ 1 ] == { "email": "e@x", "password": "pw" }


def test_a_refused_broadcast_fails( probe, capsys ):
    probe.world[ "broadcast" ] = _Resp( 500, text="server broke" )
    with pytest.raises( SystemExit ):
        probe._broadcast( { }, "b1" )
    assert "broadcast returned 500" in capsys.readouterr().out


def test_the_broadcast_asks_for_acks_from_everyone_including_the_sender( probe ):
    probe._broadcast( { "h": 1 }, "b1" )
    url, body, headers = probe.world[ "posts" ][ 0 ]
    assert url.endswith( "/api/commons/broadcast-to-cc-sessions" ) and headers == { "h": 1 }
    assert body[ "broadcast_id" ] == "b1" and body[ "require_ack" ] is True and body[ "include_originator" ] is True


def test_a_failed_saved_read_and_a_failed_undelivered_read_both_fail( probe, capsys ):
    probe.world[ "saved" ] = _Resp( 503, text="saved-raw" )
    with pytest.raises( SystemExit ):
        probe._saved_acks( { }, "b1" )
    assert "saved-ack read returned 503" in capsys.readouterr().out
    probe.world[ "undelivered" ] = _Resp( 502, text="undel-raw" )
    with pytest.raises( SystemExit ):
        probe._pushed_acks( { }, "b1" )
    assert "undelivered read returned 502" in capsys.readouterr().out


def test_the_pushed_read_keeps_only_acks_for_this_broadcast( probe ):
    probe.world[ "undelivered" ] = _Resp( 200, { "notifications": [
        _pushed( "b1", "s1" ),
        _pushed( "other", "s2" ),
        { "type": "something_else", "payload": { "broadcast_id": "b1" } },
        { "type": "commons_broadcast_ack", "payload": None },
    ] } )
    matched, raw = probe._pushed_acks( { }, "b1" )
    assert [ n[ "payload" ][ "session_id" ] for n in matched ] == [ "s1" ]
    assert "notifications" in raw


def test_a_broadcast_to_nobody_fails_instead_of_comparing_two_empties( probe, capsys ):
    probe.world[ "broadcast" ] = _Resp( 200, { "recipients": 0 } )
    with pytest.raises( SystemExit ) as stop:
        probe.main()
    assert stop.value.code == 1 and "reached NOBODY" in capsys.readouterr().out
    assert not any( "/broadcast-acks/" in u for u in probe.world[ "gets" ] )


def test_nothing_saved_after_the_wait_fails_and_the_wait_is_bounded( probe, capsys ):
    probe.world[ "saved" ] = _Resp( 200, { "ack_count": 0, "acks": [ ] } )
    with pytest.raises( SystemExit ) as stop:
        probe.main()
    assert stop.value.code == 1 and "NOTHING WAS SAVED" in capsys.readouterr().out
    assert sum( "/broadcast-acks/" in u for u in probe.world[ "gets" ] ) == 3     # 6s wait, 2s poll


def test_an_ack_for_the_wrong_broadcast_or_without_a_session_fails( probe, capsys ):
    probe.world[ "saved" ] = lambda bid: _Resp( 200, { "ack_count": 1, "acks": [ _ack( "wrong-id" ) ] } )
    with pytest.raises( SystemExit ):
        probe.main()
    assert "no usable attribution" in capsys.readouterr().out
    probe.world[ "saved" ] = lambda bid: _Resp( 200, { "ack_count": 1, "acks": [ _ack( bid, session=None ) ] } )
    with pytest.raises( SystemExit ):
        probe.main()


def test_agreeing_doors_pass_and_stop_waiting_at_the_first_ack( probe, capsys ):
    probe.world[ "saved" ] = lambda bid: _Resp( 200, { "ack_count": 1, "acks": [ _ack( bid, "s1" ) ] } )
    probe.world[ "undelivered" ] = _Resp( 200, { "notifications": [] } )
    sent = probe.world
    # the pushed door names the same session, whatever broadcast id the probe generated
    def undelivered_for_any_id( ):
        bid = sent[ "posts" ][ 1 ][ 1 ][ "broadcast_id" ]
        return _Resp( 200, { "notifications": [ _pushed( bid, "s1" ) ] } )
    class _Lazy:
        status_code = 200
        @property
        def text( self ): return undelivered_for_any_id().text
        def json( self ): return undelivered_for_any_id().json()
    sent[ "undelivered" ] = _Lazy()
    assert probe.main() == 0
    out = capsys.readouterr().out
    assert "AGREEMENT: both doors name the same session set" in out
    assert "1 attributed ack(s)" in out
    assert sum( "/broadcast-acks/" in u for u in sent[ "gets" ] ) == 1


def test_doors_naming_different_sessions_are_a_disagreement_with_raw_bodies( probe, capsys ):
    probe.world[ "saved" ] = lambda bid: _Resp( 200, { "ack_count": 1, "acks": [ _ack( bid, "s-saved" ) ] } )
    class _Other:
        status_code = 200
        text        = "RAW-UNDELIVERED"
        def json( self ):
            bid = probe.world[ "posts" ][ 1 ][ 1 ][ "broadcast_id" ]
            return { "notifications": [ _pushed( bid, "s-pushed" ) ] }
    probe.world[ "undelivered" ] = _Other()
    assert probe.main() == 0
    out = capsys.readouterr().out
    assert "DISAGREEMENT TO CHASE" in out
    assert "saved only : ['s-saved']" in out and "pushed only: ['s-pushed']" in out
    assert "RAW-UNDELIVERED" in out


def test_an_empty_left_door_is_reported_as_one_side_measured( probe, capsys ):
    probe.world[ "saved" ] = lambda bid: _Resp( 200, { "ack_count": 1, "acks": [ _ack( bid ) ] } )
    assert probe.main() == 0
    out = capsys.readouterr().out
    assert "LEFT was empty" in out and "Only RIGHT was measured" in out
    assert "AGREEMENT" not in out and "DISAGREEMENT" not in out
