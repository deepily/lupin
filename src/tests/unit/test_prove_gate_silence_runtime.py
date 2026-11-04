"""
The runtime of the gate-silence proof, with network, socket and clock stood in.

The proof needs a live :8000 server and about 15 minutes of real build.
These cases run every other line of it: the answers it posts, the socket loop,
the queue polling, the verdict arithmetic and the `main()` report.
The verdict is the product, so each check gets a case that turns only that check red.
"""

import asyncio
import importlib.util
import json
import os
import sys
import types

import pytest


def _load_proof():
    path = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "scripts",
                         "presentation-gate-silence-proof", "prove_gate_silence.py" )
    spec = importlib.util.spec_from_file_location( "prove_gate_silence_runtime", path )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )
    return mod


@pytest.fixture
def pg():
    return _load_proof()


class _R:
    """A response double: status, JSON body and raw text."""
    def __init__( self, status=200, body=None, text="" ):
        self.status_code, self._body, self.text = status, body, text
    def json( self ): return self._body
    def raise_for_status( self ):
        if self.status_code >= 400: raise RuntimeError( f"HTTP {self.status_code}" )


# ── response_options ──────────────────────────────────────────────────────────

@pytest.mark.parametrize( "options, expected", [
    ( None, [ ] ),
    ( "not json", [ ] ),
    ( "[1, 2]", [ ] ),
    ( { "questions": [ { "header": "A" }, { "header": None }, { } ] }, [ "A" ] ),
    ( json.dumps( { "questions": [ { "header": "B" } ] } ), [ "B" ] ),
    ( { "other": 1 }, [ ] ),
] )
def test_headers_come_from_a_dict_or_a_json_string_and_never_raise( pg, options, expected ):
    assert pg._headers_from_options( options ) == expected


def test_the_password_is_strong_and_fresh_each_time( pg ):
    first, second = pg._strong_password(), pg._strong_password()
    assert first != second and first.startswith( "Arnold!Gate9proof-" ) and len( first ) == 28


# ── auth ──────────────────────────────────────────────────────────────────────

def test_register_returns_the_new_users_token_and_id( pg, monkeypatch ):
    monkeypatch.setattr( pg.requests, "post", lambda url, **k: _R( 201, { "tokens": { "access_token": "T" }, "user": { "id": 7 } } ) )
    assert pg.register_and_login( "http://b", "e@x", "pw" ) == ( "T", "e@x", 7 )


def test_an_existing_user_falls_back_to_login( pg, monkeypatch ):
    urls = [ ]
    def post( url, **k ):
        urls.append( url )
        return _R( 400, text="exists" ) if url.endswith( "/register" ) else \
               _R( 200, { "tokens": { "access_token": "T2" }, "user": { "id": 8 } } )
    monkeypatch.setattr( pg.requests, "post", post )
    assert pg.register_and_login( "http://b", "e@x", "pw" ) == ( "T2", "e@x", 8 )
    assert urls == [ "http://b/auth/register", "http://b/auth/login" ]


def test_when_neither_door_opens_the_error_carries_both_answers( pg, monkeypatch ):
    monkeypatch.setattr( pg.requests, "post", lambda url, **k: _R( 400 if "register" in url else 401, text="why-" + url[ -5: ] ) )
    with pytest.raises( RuntimeError ) as caught:
        pg.register_and_login( "http://b", "e@x", "pw" )
    msg = str( caught.value )
    assert "register 400" in msg and "login 401" in msg


# ── frames and answers ────────────────────────────────────────────────────────

def _user( pg, answer_mode=False ):
    return pg.SilentConnectedUser( "https://host:1", "sess-1", "jwt", answer_mode=answer_mode )


def test_the_socket_url_swaps_the_scheme_and_quotes_the_session( pg ):
    assert _user( pg ).ws_url == "wss://host:1/ws/queue/sess-1"
    assert pg.SilentConnectedUser( "http://h", "a b", "j" ).ws_url == "ws://h/ws/queue/a%20b"


def _gate( **over ):
    note = { "id": "n1", "response_requested": True, "job_id": "pr-1", "title": "Gate",
             "response_type": "multiple_choice", "timeout_seconds": 600,
             "response_options": { "questions": [ { "header": "Continue?" } ] } }
    note.update( over )
    return json.dumps( { "type": "notification_queue_update", "notification": note } )


def test_a_gate_frame_is_recorded_as_a_delivery( pg ):
    user = _user( pg )
    user._record_frame( _gate() )
    assert len( user.deliveries ) == 1
    got = user.deliveries[ 0 ]
    assert ( got[ "notification_id" ], got[ "job_id" ], got[ "headers" ], got[ "timeout_seconds" ] ) == \
           ( "n1", "pr-1", [ "Continue?" ], 600 )


@pytest.mark.parametrize( "raw", [
    "{not json",
    json.dumps( { "type": "something_else" } ),
    json.dumps( { "type": "notification_queue_update", "notification": { "response_requested": False } } ),
    json.dumps( { "type": "notification_queue_update", "notification": None } ),
] )
def test_frames_that_are_not_gate_asks_record_nothing( pg, raw ):
    user = _user( pg )
    user._record_frame( raw )
    assert user.deliveries == [ ]


def test_the_notification_id_may_arrive_under_its_other_name( pg ):
    user = _user( pg )
    user._record_frame( _gate( id=None, notification_id="n9" ) )
    assert user.deliveries[ 0 ][ "notification_id" ] == "n9"


class _InlineThread:
    """Runs its target when started, so the answer is posted before the test looks."""
    def __init__( self, target, args=( ), daemon=None ): self.target, self.args = target, args
    def start( self ): self.target( *self.args )


def test_answer_mode_answers_a_gate_that_has_headers( pg, monkeypatch ):
    monkeypatch.setattr( pg.threading, "Thread", _InlineThread )
    posted = [ ]
    monkeypatch.setattr( pg.requests, "post", lambda url, **k: posted.append( k[ "json" ] ) or _R( 200 ) )
    user = _user( pg, answer_mode=True )
    user._record_frame( _gate() )
    assert posted == [ { "notification_id": "n1", "response_value": { "answers": { "Continue?": "Approve" } } } ]


@pytest.mark.parametrize( "over", [ { "id": None }, { "response_options": None } ] )
def test_answer_mode_does_not_answer_without_an_id_or_headers( pg, monkeypatch, over ):
    monkeypatch.setattr( pg.threading, "Thread", _InlineThread )
    monkeypatch.setattr( pg.requests, "post", lambda *a, **k: pytest.fail( "must not answer" ) )
    user = _user( pg, answer_mode=True )
    user._record_frame( _gate( **over ) )
    assert len( user.deliveries ) == 1


def test_silent_mode_never_answers( pg, monkeypatch ):
    monkeypatch.setattr( pg.requests, "post", lambda *a, **k: pytest.fail( "silent mode must not answer" ) )
    _user( pg, answer_mode=False )._record_frame( _gate() )


# ── liveness ──────────────────────────────────────────────────────────────────

def test_liveness_report_measures_the_widest_gap_between_samples( pg ):
    user = _user( pg )
    user.liveness = [ { "ts": "2026-01-01T00:00:00+00:00", "kind": "auth" },
                      { "ts": "2026-01-01T00:00:10+00:00", "kind": "ping" },
                      { "ts": "2026-01-01T00:00:50+00:00", "kind": "ping" } ]
    rep = user.liveness_report()
    assert rep[ "samples" ] == 3 and rep[ "max_gap_seconds" ] == 40.0
    assert rep[ "first_ts" ].endswith( ":00+00:00" ) and rep[ "last_ts" ].endswith( ":50+00:00" ) and rep[ "dropped_at" ] is None


def test_liveness_report_of_nothing_is_empty_not_an_error( pg ):
    rep = _user( pg ).liveness_report()
    assert rep[ "samples" ] == 0 and rep[ "first_ts" ] is None and rep[ "last_ts" ] is None


# ── the socket loop ───────────────────────────────────────────────────────────

class _FakeWS:
    """Scripted socket: `incoming` items are returned, or raised when they are exceptions."""
    def __init__( self, user, incoming, ping_fails=False ):
        self.user, self.incoming, self.ping_fails, self.sent = user, list( incoming ), ping_fails, [ ]
    async def send( self, text ): self.sent.append( json.loads( text ) )
    async def recv( self ):
        if not self.incoming:
            self.user._stop.set()
            raise asyncio.TimeoutError()
        item = self.incoming.pop( 0 )
        if isinstance( item, BaseException ): raise item
        return item if isinstance( item, str ) else json.dumps( item )
    async def ping( self ):
        if self.ping_fails: raise ConnectionError( "gone" )
        fut = asyncio.get_running_loop().create_future()
        fut.set_result( None )
        return fut


def _fake_websockets( monkeypatch, ws ):
    seen = { }
    class _Ctx:
        async def __aenter__( self ): return ws
        async def __aexit__( self, *a ): return False
    def connect( url, **kw ):
        seen.update( url=url, kw=kw )
        return _Ctx()
    monkeypatch.setitem( sys.modules, "websockets", types.SimpleNamespace( connect=connect ) )
    return seen


def test_the_loop_authenticates_then_records_frames_and_keeps_going_past_timeouts( pg, monkeypatch ):
    user = _user( pg )
    ws   = _FakeWS( user, [ { "type": "auth_success" }, asyncio.TimeoutError(), _gate() ] )
    seen = _fake_websockets( monkeypatch, ws )
    asyncio.run( user._aio() )
    assert seen[ "url" ] == user.ws_url
    assert ws.sent[ 0 ] == { "type": "auth_request", "token": "jwt", "subscribed_events": [ "*" ] }
    assert user._ready.is_set() and user._err is None and user.dropped_at is None
    assert [ s[ "kind" ] for s in user.liveness ] == [ "auth", "recv" ]
    assert len( user.deliveries ) == 1


def test_an_auth_reply_that_is_not_success_stops_the_loop_with_an_error( pg, monkeypatch ):
    user = _user( pg )
    _fake_websockets( monkeypatch, _FakeWS( user, [ { "type": "auth_error", "why": "bad" } ] ) )
    asyncio.run( user._aio() )
    assert user._ready.is_set() and "auth not successful" in user._err and user.liveness == [ ]


def test_a_failed_receive_is_a_drop( pg, monkeypatch ):
    user = _user( pg )
    _fake_websockets( monkeypatch, _FakeWS( user, [ { "type": "auth_success" }, ConnectionError( "reset" ) ] ) )
    asyncio.run( user._aio() )
    assert user.dropped_at is not None


def test_a_ping_is_sampled_when_due_and_a_failed_ping_is_a_drop( pg, monkeypatch ):
    monkeypatch.setattr( pg, "LIVENESS_PING_SEC", 0 )
    ok = _user( pg )
    _fake_websockets( monkeypatch, _FakeWS( ok, [ { "type": "auth_success" } ] ) )
    asyncio.run( ok._aio() )
    assert "ping" in [ s[ "kind" ] for s in ok.liveness ] and ok.dropped_at is None
    bad = _user( pg )
    _fake_websockets( monkeypatch, _FakeWS( bad, [ { "type": "auth_success" } ], ping_fails=True ) )
    asyncio.run( bad._aio() )
    assert bad.dropped_at is not None and "ping" not in [ s[ "kind" ] for s in bad.liveness ]


def test_a_crash_in_the_loop_marks_the_drop_and_releases_the_waiter( pg, monkeypatch ):
    user = _user( pg )
    async def boom(): raise OSError( "refused" )
    monkeypatch.setattr( user, "_aio", boom )
    user._run()
    assert user.dropped_at is not None and "refused" in user._err and user._ready.is_set()


def test_a_crash_keeps_an_earlier_drop_time( pg, monkeypatch ):
    user = _user( pg )
    user.dropped_at = "EARLIER"
    async def boom(): raise OSError( "late" )
    monkeypatch.setattr( user, "_aio", boom )
    user._run()
    assert user.dropped_at == "EARLIER"


def test_start_returns_once_the_socket_is_authenticated_and_stop_joins_the_thread( pg, monkeypatch ):
    user = _user( pg )
    monkeypatch.setattr( user, "_run", lambda: user._ready.set() )
    user.start( ready_timeout=2 )
    user.stop()
    assert user._stop.is_set() and not user._thread.is_alive()


def test_start_fails_when_the_socket_never_authenticates( pg, monkeypatch ):
    user = _user( pg )
    monkeypatch.setattr( user, "_run", lambda: None )
    with pytest.raises( RuntimeError, match = "did not authenticate" ):
        user.start( ready_timeout=0.05 )


def test_start_fails_with_the_loops_own_error( pg, monkeypatch ):
    user = _user( pg )
    def run():
        user._err = "auth not successful"
        user._ready.set()
    monkeypatch.setattr( user, "_run", run )
    with pytest.raises( RuntimeError, match = "WS online failed: auth not successful" ):
        user.start( ready_timeout=2 )


def test_stop_without_a_started_thread_is_harmless( pg ):
    user = _user( pg )
    user.stop()
    assert user._stop.is_set()


# ── the build and the queues ──────────────────────────────────────────────────

def test_submit_posts_the_build_through_the_one_door_and_returns_the_job( pg, monkeypatch ):
    seen = { }
    def post( url, headers, json, timeout ):
        seen.update( url=url, headers=headers, body=json )
        return _R( 200, { "job_id": "pr-123" } )
    monkeypatch.setattr( pg.requests, "post", post )
    assert pg.submit_build( "http://b", "jwt", "/doc.md", duration=9, audience="execs" ) == "pr-123"
    assert seen[ "url" ] == "http://b/api/v2/submit" and seen[ "headers" ] == { "Authorization": "Bearer jwt" }
    assert seen[ "body" ][ "command" ] == "agent router go to presentation generator"
    assert seen[ "body" ][ "args" ] == { "source": "/doc.md", "target_duration_minutes": 9, "audience": "execs", "dry_run": False }


@pytest.mark.parametrize( "resp, says", [
    ( _R( 503, text="down" ), "submit failed: 503" ),
    ( _R( 200, { "job_id": "ts-5" } ), "unexpected submit response" ),
    ( _R( 201, { } ), "unexpected submit response" ),
] )
def test_a_refused_or_misrouted_submit_raises( pg, monkeypatch, resp, says ):
    monkeypatch.setattr( pg.requests, "post", lambda *a, **k: resp )
    with pytest.raises( RuntimeError, match = says ):
        pg.submit_build( "http://b", "jwt", "/doc.md" )


@pytest.mark.parametrize( "resp, expected", [
    ( _R( 500 ), [ ] ),
    ( _R( 200, { "done_jobs_metadata": [ { "job_id": "a" } ] } ), [ { "job_id": "a" } ] ),
    ( _R( 200, { "done_jobs_metadata": None } ), [ ] ),
    ( _R( 200, { } ), [ ] ),
    ( _R( 200, [ { "job_id": "b" } ] ), [ { "job_id": "b" } ] ),
    ( _R( 200, None ), [ ] ),
] )
def test_a_queue_read_returns_the_job_list_in_any_shape( pg, monkeypatch, resp, expected ):
    monkeypatch.setattr( pg.requests, "get", lambda *a, **k: resp )
    assert pg._queue( "http://b", "jwt", "done" ) == expected


def test_find_matches_a_job_by_any_of_its_three_ids( pg ):
    jobs = [ { "job_id": "a" }, { "id_hash": "b" }, { "id": "c" } ]
    assert [ pg._find( jobs, x ) for x in ( "a", "b", "c" ) ] == jobs
    assert pg._find( jobs, "zzz" ) is None


def test_a_gate_state_read_returns_the_body_or_names_the_failure( pg, monkeypatch ):
    monkeypatch.setattr( pg.requests, "get", lambda *a, **k: _R( 200, { "state": "responded", "response_value": 1 } ) )
    assert pg.read_notification_state( "http://b", "jwt", "n" )[ "state" ] == "responded"
    monkeypatch.setattr( pg.requests, "get", lambda *a, **k: _R( 404 ) )
    assert pg.read_notification_state( "http://b", "jwt", "n" ) == { "state": "HTTP 404", "response_value": None }
    def boom( *a, **k ): raise ConnectionError( "gone" )
    monkeypatch.setattr( pg.requests, "get", boom )
    got = pg.read_notification_state( "http://b", "jwt", "n" )
    assert got[ "state" ].startswith( "ERR " ) and "gone" in got[ "state" ] and got[ "response_value" ] is None


def test_pool_status_returns_the_body_and_raises_on_an_error_status( pg, monkeypatch ):
    monkeypatch.setattr( pg.requests, "get", lambda *a, **k: _R( 200, { "monopolize_id": None } ) )
    assert pg.pool_status( "http://b", "jwt" ) == { "monopolize_id": None }
    monkeypatch.setattr( pg.requests, "get", lambda *a, **k: _R( 500 ) )
    with pytest.raises( RuntimeError ):
        pg.pool_status( "http://b", "jwt" )


@pytest.mark.parametrize( "status", [ { "monopolize_id": "ts-1" }, { "monopolize_inflight": True }, { "monopolize_id": "x", "monopolize_inflight": 1 } ] )
def test_a_held_monopolize_slot_refuses_the_submit( pg, monkeypatch, status ):
    monkeypatch.setattr( pg, "pool_status", lambda base, jwt: status )
    with pytest.raises( RuntimeError, match = "REFUSING to submit" ):
        pg.require_lock_clear( "http://b", "jwt" )


def test_a_clear_slot_returns_the_status( pg, monkeypatch ):
    status = { "monopolize_id": None, "monopolize_inflight": 0 }
    monkeypatch.setattr( pg, "pool_status", lambda base, jwt: status )
    assert pg.require_lock_clear( "http://b", "jwt" ) is status


# ── polling ───────────────────────────────────────────────────────────────────

class _Clock:
    def __init__( self ): self.now = 0.0
    def monotonic( self ): return self.now
    def sleep( self, secs ): self.now += secs


@pytest.fixture
def clock( pg, monkeypatch ):
    clk = _Clock()
    monkeypatch.setattr( pg, "time", clk )
    return clk


def _queues( monkeypatch, pg, per_call ):
    """per_call(name, n) -> the list the nth read of that queue returns."""
    counts = { }
    def fake( base, jwt, name ):
        counts[ name ] = counts.get( name, 0 ) + 1
        return per_call( name, counts[ name ] )
    monkeypatch.setattr( pg, "_queue", fake )
    return counts


def test_polling_returns_done_as_soon_as_the_job_is_in_the_done_queue( pg, monkeypatch, clock ):
    _queues( monkeypatch, pg, lambda name, n: [ { "job_id": "j" } ] if name == "done" else [ ] )
    assert pg.poll_until_terminal( "b", "j", "j", 100 )[ 0 ] == "done"
    assert clock.now == 0.0


def test_polling_returns_dead_when_the_job_dies( pg, monkeypatch, clock ):
    _queues( monkeypatch, pg, lambda name, n: [ { "job_id": "j", "why": "x" } ] if name == "dead" else [ ] )
    assert pg.poll_until_terminal( "b", "j", "j", 100 ) == ( "dead", { "job_id": "j", "why": "x" } )


def test_polling_reports_each_tick_with_whether_the_job_was_seen_running_then_times_out( pg, monkeypatch, clock ):
    _queues( monkeypatch, pg, lambda name, n: [ { "job_id": "j" } ] if name == "run" and n >= 2 else [ ] )
    ticks = [ ]
    assert pg.poll_until_terminal( "b", "j", "j", 20, on_tick=ticks.append ) == ( "timeout", None )
    assert ticks == [ False, True, True, True ]
    assert clock.now == 20.0


def test_polling_without_a_tick_callback_still_times_out( pg, monkeypatch, clock ):
    _queues( monkeypatch, pg, lambda name, n: [ ] )
    assert pg.poll_until_terminal( "b", "j", "j", 5 ) == ( "timeout", None )


# ── verdict ───────────────────────────────────────────────────────────────────

def _silent( pg, deliveries=( "n1", ), answers=( ( "n1", 200 ), ), dropped=None, gap=5.0 ):
    s = types.SimpleNamespace()
    s.deliveries     = [ { "notification_id": n, "title": f"G-{n}", "ts": "t" } for n in deliveries ]
    s.answers_posted = [ { "notification_id": n, "status": st } for n, st in answers ]
    s.liveness_report = lambda: { "dropped_at": dropped, "max_gap_seconds": gap }
    return s


_RESPONDED = { "n1": { "state": "responded", "response_value": { "answers": { "q": "Approve" } } } }


def test_all_five_checks_holding_is_a_pass( pg ):
    v = pg.build_verdict_direction_a( _silent( pg ), "done", { "completed_at": "c" }, _RESPONDED )
    assert v[ "PASS" ] is True and all( v[ "checks" ].values() ) and len( v[ "checks" ] ) == 5
    assert v[ "gates_delivered" ] == 1 and v[ "gates_answered" ] == 1 and v[ "job_completed_at" ] == "c"
    assert v[ "per_gate" ][ 0 ] == { "notification_id": "n1", "title": "G-n1", "delivered_ts": "t",
                                     "answered": True, "state": "responded",
                                     "response_value": { "answers": { "q": "Approve" } } }


@pytest.mark.parametrize( "case, silent_kw, job_state, states, red", [
    ( "no gate arrived",  dict( deliveries=( ), answers=( ) ),           "done",    { },                                       [ "delivered", "every_gate_answered", "every_gate_human_resolved" ] ),
    ( "socket dropped",   dict( dropped="2026" ),                        "done",    _RESPONDED,                                [ "connected_through_wait" ] ),
    ( "gap too wide",     dict( gap=61.0 ),                              "done",    _RESPONDED,                                [ "connected_through_wait" ] ),
    ( "answer refused",   dict( answers=( ( "n1", 401 ), ) ),            "done",    _RESPONDED,                                [ "every_gate_answered" ] ),
    ( "gate expired",     dict( ),                                       "done",    { "n1": { "state": "expired" } },          [ "every_gate_human_resolved" ] ),
    ( "state unreadable", dict( ),                                       "done",    { },                                       [ "every_gate_human_resolved" ] ),
    ( "job died",         dict( ),                                       "dead",    _RESPONDED,                                [ "job_reached_done" ] ),
] )
def test_each_check_turns_red_on_its_own_failure_and_the_verdict_with_it( pg, case, silent_kw, job_state, states, red ):
    v = pg.build_verdict_direction_a( _silent( pg, **silent_kw ), job_state, None, states )
    assert v[ "PASS" ] is False, case
    assert sorted( k for k, ok in v[ "checks" ].items() if not ok ) == sorted( red ), case
    assert v[ "job_completed_at" ] is None


def test_one_unanswered_gate_among_answered_ones_fails_the_answered_check( pg ):
    states = { "n1": { "state": "responded" }, "n2": { "state": "responded" } }
    s = _silent( pg, deliveries=( "n1", "n2" ), answers=( ( "n1", 200 ), ) )
    v = pg.build_verdict_direction_a( s, "done", None, states )
    assert v[ "checks" ][ "every_gate_answered" ] is False and v[ "PASS" ] is False
    assert v[ "checks" ][ "every_gate_human_resolved" ] is True


def test_a_gap_exactly_at_the_limit_still_counts_as_connected( pg ):
    v = pg.build_verdict_direction_a( _silent( pg, gap=float( pg.MAX_LIVENESS_GAP ) ), "done", None, _RESPONDED )
    assert v[ "checks" ][ "connected_through_wait" ] is True


def test_a_delivery_with_no_id_is_listed_but_cannot_be_counted_answered( pg ):
    s = _silent( pg, deliveries=( None, ), answers=( ) )
    v = pg.build_verdict_direction_a( s, "done", None, { } )
    assert v[ "checks" ][ "every_gate_answered" ] is False and v[ "per_gate" ][ 0 ][ "answered" ] is False


# ── main ──────────────────────────────────────────────────────────────────────

class _FakeSilent:
    instances = [ ]
    def __init__( self, base, session_id, jwt, answer_mode=False ):
        self.session_id, self.answer_mode, self.stopped = session_id, answer_mode, False
        self.deliveries     = [ { "notification_id": "n1", "title": "Gate", "ts": "t" },
                                { "notification_id": None,  "title": "Idle", "ts": "t" } ]
        self.answers_posted = [ { "notification_id": "n1", "status": 200 } ]
        _FakeSilent.instances.append( self )
    def start( self ): pass
    def stop( self ): self.stopped = True
    def liveness_report( self ): return { "dropped_at": None, "max_gap_seconds": 1.0, "samples": 3 }


@pytest.fixture
def run_main( pg, monkeypatch, tmp_path ):
    """Wire every outside call; returns a function that runs main() with the given argv."""
    _FakeSilent.instances = [ ]
    calls = { "locks": 0, "reads": [ ], "polled": None }
    def lock( base, jwt ):
        calls[ "locks" ] += 1
        return { "monopolize_id": None }
    def poll( base, jwt, job_id, timeout, on_tick=None ):
        calls[ "polled" ] = ( job_id, timeout )
        on_tick( True )
        return calls.get( "terminal", ( "done", { "completed_at": "c" } ) )
    def read( base, jwt, nid ):
        calls[ "reads" ].append( nid )
        return { "state": calls.get( "gate_state", "responded" ), "response_value": { } }
    monkeypatch.setattr( pg, "register_and_login", lambda base, email, pw: ( "jwt", email, 42 ) )
    monkeypatch.setattr( pg, "require_lock_clear", lock )
    monkeypatch.setattr( pg, "SilentConnectedUser", _FakeSilent )
    monkeypatch.setattr( pg, "submit_build", lambda base, jwt, source: "pr-77" )
    monkeypatch.setattr( pg, "poll_until_terminal", poll )
    monkeypatch.setattr( pg, "read_notification_state", read )
    monkeypatch.setattr( pg, "__file__", str( tmp_path / "prove_gate_silence.py" ) )
    def run( *argv ):
        monkeypatch.setattr( sys, "argv", [ "prove_gate_silence.py", *argv ] )
        return pg.main()
    run.calls, run.tmp = calls, tmp_path
    return run


def test_a_passing_run_writes_its_evidence_and_exits_zero( run_main, capsys ):
    out = run_main.tmp / "ev.json"
    assert run_main( "--evidence", str( out ), "--email", "a@b", "--base", "http://b:1", "--source", "/d.md" ) == 0
    ev = json.loads( out.read_text() )
    assert ev[ "verdict" ][ "PASS" ] is True and ev[ "job_id" ] == "pr-77" and ev[ "user_id" ] == 42
    assert ev[ "base" ] == "http://b:1" and ev[ "submitter" ] == "a@b" and ev[ "source_path" ] == "/d.md"
    assert set( ev[ "thresholds" ] ) == { "gate_timeout", "min_silence_secs", "max_liveness_gap" }
    assert run_main.calls[ "locks" ] == 1 and run_main.calls[ "polled" ] == ( "pr-77", 1500 )
    assert run_main.calls[ "reads" ] == [ "n1" ]                        # the delivery with no id is never read
    silent = _FakeSilent.instances[ 0 ]
    assert silent.stopped and silent.answer_mode is True and silent.session_id.startswith( "arnold-gate-" )
    text = capsys.readouterr().out
    assert "VERDICT: ✅ PASS" in text and "no monopolizer holds" in text and "running=True gates_delivered=2" in text


def test_a_failing_run_exits_one_and_says_not_proven( run_main, capsys ):
    run_main.calls[ "gate_state" ] = "expired"
    assert run_main( "--evidence", str( run_main.tmp / "ev.json" ) ) == 1
    out = capsys.readouterr().out
    assert "NOT PROVEN" in out and "❌  every_gate_human_resolved" in out


def test_force_skips_the_lock_check_and_the_build_timeout_is_passed_on( run_main, capsys ):
    assert run_main( "--force", "--build-timeout", "30", "--evidence", str( run_main.tmp / "ev.json" ) ) == 0
    assert run_main.calls[ "locks" ] == 0 and run_main.calls[ "polled" ][ 1 ] == 30
    assert "skipping lock-clear precondition" in capsys.readouterr().out


def test_without_an_evidence_path_the_file_lands_beside_the_script( run_main ):
    run_main( "--force" )
    written = [ p for p in run_main.tmp.iterdir() if p.name.startswith( "evidence-" ) ]
    assert len( written ) == 1 and written[ 0 ].name.endswith( "Z.json" )
