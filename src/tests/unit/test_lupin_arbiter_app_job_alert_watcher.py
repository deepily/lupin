"""
Unit tests for the job alert watcher of the :8001 arbiter.

Every decision runs on a fake clock and fake summaries, so no server and no real time is involved.
The wiring tests build the real app with the real watcher class and check the enable switch.
"""
import datetime
import json
import types

import pytest

import lupin_arbiter_app.job_alert_watcher as jaw
from cosa.utils.atomic_json import load_json_dict, write_json_atomic
from lupin_arbiter_app.app import assemble_app, create_app

T0 = datetime.datetime( 2026, 11, 9, 12, 0, tzinfo=datetime.timezone.utc )


def entry( job="dup", state="failing", target=None, interval=1800, title=None, reasons=None, targets=None ):
    """One summary entry with the fields the watcher reads."""
    return { "job": job, "title": title or job.title(), "target": target, "state": state, "notify_interval_seconds": interval,
             "reasons": [ { "text": "ran late" } ] if reasons is None else reasons, "targets": targets or [ ] }


class Clock:
    """A fake clock: now() and sleep() move one number."""
    def __init__( self, now=T0 ): self.t = now; self.slept = [ ]
    def now( self ): return self.t
    def sleep( self, seconds ): self.slept.append( seconds ); self.t += datetime.timedelta( seconds=seconds )
    def advance( self, seconds ): self.t += datetime.timedelta( seconds=seconds )


def test_a_bad_job_alerts_once_then_waits_for_its_own_interval():
    jobs  = [ entry( interval=600 ) ]
    first, state = jaw.decide( jobs, { }, T0 )
    assert first == [ "Background job Dup is FAILING: ran late" ] and state == { "dup": T0.isoformat() }
    again, state2 = jaw.decide( jobs, state, T0 + datetime.timedelta( seconds=599 ) )
    assert again == [ ] and state2 == state, "inside the interval: no message, stored time kept"
    due, state3 = jaw.decide( jobs, state, T0 + datetime.timedelta( seconds=600 ) )
    assert len( due ) == 1 and state3 == { "dup": ( T0 + datetime.timedelta( seconds=600 ) ).isoformat() }, "exactly at the interval counts as due"


def test_each_job_uses_its_own_interval():
    jobs = [ entry( job="fast", interval=60 ), entry( job="slow", interval=86400 ) ]
    _, state = jaw.decide( jobs, { }, T0 )
    msgs, _ = jaw.decide( jobs, state, T0 + datetime.timedelta( seconds=120 ) )
    assert msgs == [ "Background job Fast is FAILING: ran late" ]


@pytest.mark.parametrize( "state, alerted", [ ( "failing", True ), ( "silent", True ), ( "behind", True ), ( "unknown", False ), ( "healthy", False ) ] )
def test_only_failing_silent_and_behind_are_alerted( state, alerted ):
    msgs, new = jaw.decide( [ entry( state=state ) ], { }, T0 )
    assert bool( msgs ) is alerted and bool( new ) is alerted


def test_a_job_that_recovers_is_forgotten_so_its_next_bad_spell_alerts_at_once():
    _, state = jaw.decide( [ entry( interval=86400 ) ], { }, T0 )
    _, state = jaw.decide( [ entry( state="healthy" ) ], state, T0 + datetime.timedelta( seconds=60 ) )
    assert state == { }
    msgs, _ = jaw.decide( [ entry( interval=86400 ) ], state, T0 + datetime.timedelta( seconds=120 ) )
    assert len( msgs ) == 1


def test_a_job_with_targets_alerts_per_target_and_not_for_the_job_itself():
    bad  = entry( job="census", target="lupin", title="Census", state="silent", reasons=[ { "text": "lupin: nothing since 03:00" } ] )
    good = entry( job="census", target="cosa", title="Census", state="healthy" )
    top  = entry( job="census", title="Census", state="silent", targets=[ bad, good ] )
    msgs, state = jaw.decide( [ top ], { }, T0 )
    assert msgs == [ "Background job Census (lupin) is SILENT: lupin: nothing since 03:00" ]
    assert list( state ) == [ "census/lupin" ]


def test_an_unreadable_stored_time_alerts_again_and_a_future_one_does_not():
    assert len( jaw.decide( [ entry() ], { "dup": "garbage" }, T0 )[ 0 ] ) == 1
    future = ( T0 + datetime.timedelta( hours=1 ) ).isoformat()
    assert jaw.decide( [ entry() ], { "dup": future }, T0 )[ 0 ] == [ ]


def test_the_message_names_the_state_and_handles_no_reason_and_long_reasons():
    assert jaw.alert_message( entry( reasons=[ ] ) ) == "Background job Dup is FAILING: no reason recorded"
    long = jaw.alert_message( entry( reasons=[ { "text": "x" * 500 } ] ) )
    assert len( long ) == jaw.MAX_MESSAGE and long.endswith( "…" )


OK = [ { "channel": "durable", "outcome": "posted" } ]


def sender( sent, outcomes=None ):
    """A notify_fn that records the message and answers like the escalation sink."""
    def send( message ): sent.append( message ); return OK if outcomes is None else outcomes
    return send


def test_the_loop_sends_each_due_alert_then_saves_the_state_and_alerts_again_only_after_the_interval(tmp_path):
    clock, sent, logged = Clock(), [ ], [ ]
    jobs = [ entry( interval=600 ), entry( job="b", state="healthy" ) ]
    loop = jaw.JobAlertLoop( lambda: jobs, sender( sent ), str( tmp_path / "sub" / "state.json" ), lambda event, **kw: logged.append( ( event, kw ) ), clock=clock )
    assert loop.poll_once() == 1 and len( sent ) == 1
    assert json.loads( ( tmp_path / "sub" / "state.json" ).read_text() ) == { "dup": T0.isoformat() }
    clock.advance( 300 ); assert loop.poll_once() == 0
    clock.advance( 300 ); assert loop.poll_once() == 1 and len( sent ) == 2
    assert [ e for e, _ in logged ] == [ "job_alert", "job_alert" ]


def test_a_new_loop_reads_the_saved_state_so_a_restart_does_not_repeat_an_alert(tmp_path):
    path, sent = str( tmp_path / "state.json" ), [ ]
    jobs = [ entry( interval=86400 ) ]
    jaw.JobAlertLoop( lambda: jobs, sender( sent ), path, lambda e, **k: None, clock=Clock() ).poll_once()
    jaw.JobAlertLoop( lambda: jobs, sender( sent ), path, lambda e, **k: None, clock=Clock( T0 + datetime.timedelta( seconds=60 ) ) ).poll_once()
    assert len( sent ) == 1


def test_an_alert_that_reached_no_channel_is_not_saved_and_is_tried_again_at_the_next_poll(tmp_path):
    path, sent, logged, clock = str( tmp_path / "state.json" ), [ ], [ ], Clock()
    failed = [ { "channel": "durable", "outcome": "post_error" }, { "channel": "live", "outcome": "user_not_available" } ]
    jobs   = [ entry( interval=86400 ) ]
    loop   = jaw.JobAlertLoop( lambda: jobs, sender( sent, failed ), path, lambda e, **k: logged.append( e ), clock=clock )
    assert loop.poll_once() == 0 and load_json_dict( path ) == { }, "nothing delivered: nothing remembered"
    assert "job_alert_undelivered" in logged
    clock.advance( 60 )
    loop.notify_fn = sender( sent, OK )
    assert loop.poll_once() == 1 and len( sent ) == 2, "the very next poll tries again, long before the 86400 second interval"
    assert list( load_json_dict( path ) ) == [ "dup" ]


def test_a_failed_repeat_keeps_the_old_time_so_the_interval_still_counts_from_the_last_delivery(tmp_path):
    path, clock = str( tmp_path / "state.json" ), Clock()
    jobs = [ entry( interval=600 ) ]
    loop = jaw.JobAlertLoop( lambda: jobs, sender( [ ] ), path, lambda e, **k: None, clock=clock )
    loop.poll_once()
    first = load_json_dict( path )
    clock.advance( 600 )
    loop.notify_fn = sender( [ ], [ { "channel": "live", "outcome": "http_error" } ] )
    assert loop.poll_once() == 0 and load_json_dict( path ) == first


def test_one_delivered_channel_is_enough_and_a_live_delivery_counts():
    assert jaw.delivered( [ { "channel": "durable", "outcome": "post_error" }, { "channel": "live", "outcome": "queued" } ] )
    assert jaw.delivered( [ { "channel": "live", "outcome": "delivered_via_listener" } ] )
    assert not jaw.delivered( [ ] ) and not jaw.delivered( None ) and not jaw.delivered( [ "posted" ] )
    assert not jaw.delivered( [ { "channel": "live", "outcome": "deduped" }, { "channel": "live", "outcome": "disabled" } ] )


def test_a_send_that_raises_leaves_the_state_file_untouched(tmp_path):
    path = str( tmp_path / "state.json" )
    write_json_atomic( path, { "old": T0.isoformat() } )
    before = ( tmp_path / "state.json" ).read_text()
    def boom( message ): raise RuntimeError( "sink down" )
    loop = jaw.JobAlertLoop( lambda: [ entry() ], boom, path, lambda e, **k: None, clock=Clock() )
    with pytest.raises( RuntimeError ): loop.poll_once()
    assert ( tmp_path / "state.json" ).read_text() == before, "the state is written only after the sends"


def test_a_poll_that_changes_nothing_writes_nothing():
    writes = [ ]
    loop = jaw.JobAlertLoop( lambda: [ entry( state="healthy" ) ], print, "/x/state.json", print, clock=Clock(),
                             read_state_fn=lambda p: { }, write_state_fn=lambda p, s: writes.append( s ) )
    assert loop.poll_once() == 0 and writes == [ ]


def test_the_default_clock_is_the_real_one_and_a_failing_summary_raises_for_the_poll_loop_to_log():
    def boom(): raise ValueError( "registry unusable" )
    loop = jaw.JobAlertLoop( boom, print, "/x/state.json", print )
    assert loop.clock.now().tzinfo is not None
    with pytest.raises( ValueError ): loop.poll_once()


def test_state_files_round_trip_and_bad_files_read_as_empty(tmp_path):
    path = str( tmp_path / "a" / "state.json" )
    assert load_json_dict( path ) == { }
    write_json_atomic( path, { "k": "v" } )
    assert load_json_dict( path ) == { "k": "v" } and not ( tmp_path / "a" / "state.json.tmp" ).exists()
    ( tmp_path / "a" / "state.json" ).write_text( "{not json" ); assert load_json_dict( path ) == { }
    ( tmp_path / "a" / "state.json" ).write_text( "[1, 2]" );    assert load_json_dict( path ) == { }


def test_the_live_summary_builds_the_job_list_from_the_job_service(monkeypatch, tmp_path):
    import cosa.rest.job_service as svc
    seen = { }
    class Deps:
        def __init__( self, root, data ): seen[ "deps" ] = ( root, data )
    def build( root, data, now, deps ):
        seen[ "build" ] = ( root, data, now.tzinfo is not None, type( deps ).__name__ )
        return { "jobs": [ entry() ] }
    monkeypatch.setattr( svc, "build_response", build ); monkeypatch.setattr( svc, "LiveDeps", Deps )
    monkeypatch.setenv( "LUPIN_REUSE_REVIEW_DATA_ROOT", str( tmp_path / "d" ) )
    assert jaw.make_live_summary_fn( str( tmp_path ) )() == [ entry() ]
    assert seen[ "build" ] == ( str( tmp_path ), str( tmp_path / "d" ), True, "Deps" ) and seen[ "deps" ] == ( str( tmp_path ), str( tmp_path / "d" ) )
    monkeypatch.delenv( "LUPIN_REUSE_REVIEW_DATA_ROOT" )
    import cosa.repo.symindex.paths as paths
    monkeypatch.setattr( paths, "data_dir", lambda root: "/derived" )
    jaw.make_live_summary_fn( str( tmp_path ) )()
    assert seen[ "build" ][ 1 ] == "/derived"


# ── wiring ───────────────────────────────────────────────────────────────────

class Cfg:
    """A fake config: everything default, except the job alert switch."""
    config_block_id = "Lupin:+Stub"
    def __init__( self, job_alert ): self.job_alert = job_alert
    def get_required( self, key, **_kw ): return "America/New_York"
    def get( self, key, default=None, return_type="string" ):
        if key == "arbiter job alert enabled": return self.job_alert
        if key == "arbiter health watch containers": return "c1"
        if key == "arbiter health flap exclude containers": return "c1"
        if key == "arbiter job alert interval seconds": return 123
        return default


class Gateway:
    """Records the durable posts the escalation sink makes."""
    def __init__( self ): self.posts = [ ]
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, recipient, body, metadata=None ): pass
    def post( self, topic, body ): self.posts.append( ( topic, body ) )
    def read( self, topic, since=None, limit=50 ): return [ ]


@pytest.mark.parametrize( "health_enabled", [ True, False ] )
def test_the_app_wires_the_watcher_in_both_paths_and_alerts_reach_the_durable_channel_and_the_live_push( health_enabled ):
    class C( Cfg ):
        def get( self, key, default=None, return_type="string" ):
            return health_enabled if key == "arbiter health watch enabled" else super().get( key, default, return_type )
    gateway, live = Gateway(), [ ]
    app  = assemble_app( C( True ), gateway, live_notify_fn=lambda m: live.append( m ) or { "channel": "live", "outcome": "delivered" } )
    loop = app.state.job_alert_loop
    assert isinstance( loop, jaw.JobAlertLoop ) and loop.interval_seconds == 123
    assert loop.state_path.endswith( "/io/jobs/alert-state.json" )
    loop.notify_fn( "Background job Dup is FAILING: ran late" )
    assert gateway.posts and gateway.posts[ 0 ][ 1 ] == "Background job Dup is FAILING: ran late" and live == [ "Background job Dup is FAILING: ran late" ]


def test_the_switch_off_wires_nothing_and_says_so(capsys):
    app = assemble_app( Cfg( False ), Gateway() )
    assert app.state.job_alert_loop is None
    assert "job_alert_watcher_disabled" in capsys.readouterr().out


def test_the_injected_logger_receives_the_disabled_line_too():
    lines = [ ]
    assemble_app( Cfg( False ), Gateway(), log_fn=lambda event, **kw: lines.append( event ) )
    assert "job_alert_watcher_disabled" in lines


def test_the_lifespan_starts_and_stops_the_job_alert_loop_and_health_reports_it():
    from fastapi.testclient import TestClient
    class Loop:
        started = stopped = False
        _thread = types.SimpleNamespace( is_alive=lambda: True )
        def start( self ): self.started = True
        def stop( self ): self.stopped = True
    loop = Loop()
    with TestClient( create_app( job_alert_loop=loop ) ) as client:
        assert loop.started and client.app.state.job_alert_loop is loop
        assert client.get( "/health" ).json()[ "loops" ] == { "job_alert_watcher": "alive" }
    assert loop.stopped
