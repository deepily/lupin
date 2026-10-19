"""
Unit tests for the guarded poll loop and the docker inspect helper of the arbiter service.

The poll loop is shared by the health watcher and the context-pressure writer. The inspect helper is
driven here by replacing subprocess.run, so no docker process starts.
"""
import subprocess
import threading
from types import SimpleNamespace

import pytest

from lupin_arbiter_app import health_watcher as hw
from lupin_arbiter_app.poll_loop import run_poll_loop


class StopAfter:
    """A clock that records each sleep and sets the stop event after a set number."""

    def __init__( self, stop, after ):
        self.stop, self.after, self.slept = stop, after, []

    def sleep( self, seconds ):
        self.slept.append( seconds )
        if len( self.slept ) >= self.after: self.stop.set()


def test_the_loop_polls_then_sleeps_the_interval_until_stop_is_set():
    stop, polls, logs = threading.Event(), [], []
    clock = StopAfter( stop, 3 )
    run_poll_loop( stop, lambda: polls.append( 1 ), lambda event, **f: logs.append( ( event, f ) ), clock, 7.5 )
    assert len( polls ) == 3 and clock.slept == [ 7.5, 7.5, 7.5 ] and logs == []


def test_a_poll_that_raises_is_logged_and_the_loop_goes_on():
    stop, logs, calls = threading.Event(), [], []
    def poll():
        calls.append( 1 )
        if len( calls ) == 1: raise RuntimeError( "first-poll-bad" )
    clock = StopAfter( stop, 2 )
    run_poll_loop( stop, poll, lambda event, **f: logs.append( ( event, f ) ), clock, 1 )
    assert logs == [ ( "poll_error", { "error": "first-poll-bad" } ) ]
    assert len( calls ) == 2 and len( clock.slept ) == 2            # slept after the bad poll too


def test_a_loop_whose_stop_is_already_set_polls_nothing():
    stop = threading.Event()
    stop.set()
    run_poll_loop( stop, lambda: pytest.fail( "polled" ), lambda *a, **k: pytest.fail( "logged" ), SimpleNamespace( sleep=lambda s: pytest.fail( "slept" ) ), 1 )


def fake_run( result=None, error=None ):
    """Ensures: returns a stand-in for subprocess.run that records calls and returns or raises."""
    seen = []
    def run( cmd, **kwargs ):
        seen.append( ( cmd, kwargs ) )
        if error is not None: raise error
        return result
    run.seen = seen
    return run


def test_the_inspect_helper_builds_the_docker_command_and_hands_the_result_to_the_parser( monkeypatch ):
    run = fake_run( SimpleNamespace( returncode=0, stdout="STDOUT" ) )
    monkeypatch.setattr( hw.subprocess, "run", run )
    got = hw._docker_inspect( "box", "{{x}}", 4.0, lambda rc, out: ( rc, out ) )
    assert got == ( 0, "STDOUT" )
    cmd, kwargs = run.seen[ 0 ]
    assert cmd == [ "docker", "inspect", "box", "--format", "{{x}}" ] and kwargs == { "capture_output": True, "text": True, "timeout": 4.0 }


@pytest.mark.parametrize( "error", [ subprocess.TimeoutExpired( "docker", 1 ), subprocess.SubprocessError( "x" ), FileNotFoundError( "no docker" ) ] )
def test_every_way_the_command_can_fail_to_run_gives_none( monkeypatch, error ):
    monkeypatch.setattr( hw.subprocess, "run", fake_run( error=error ) )
    assert hw._docker_inspect( "box", "{{x}}", 1.0, lambda rc, out: pytest.fail( "parsed" ) ) is None


def test_the_health_reader_asks_for_the_state_health_json_and_parses_it( monkeypatch ):
    run = fake_run( SimpleNamespace( returncode=0, stdout='{"Status": "healthy"}' ) )
    monkeypatch.setattr( hw.subprocess, "run", run )
    assert hw.docker_inspect_health( "box", 2.0 ) == { "Status": "healthy" }
    assert run.seen[ 0 ][ 0 ] == [ "docker", "inspect", "box", "--format", "{{json .State.Health}}" ]


def test_the_restart_count_reader_asks_for_the_restart_count_and_parses_it( monkeypatch ):
    run = fake_run( SimpleNamespace( returncode=0, stdout="3\n" ) )
    monkeypatch.setattr( hw.subprocess, "run", run )
    assert hw.docker_inspect_restart_count( "box", 2.0 ) == 3
    assert run.seen[ 0 ][ 0 ] == [ "docker", "inspect", "box", "--format", "{{.RestartCount}}" ]


def test_both_readers_give_none_when_docker_exits_nonzero( monkeypatch ):
    monkeypatch.setattr( hw.subprocess, "run", fake_run( SimpleNamespace( returncode=1, stdout="" ) ) )
    assert hw.docker_inspect_health( "box", 2.0 ) is None and hw.docker_inspect_restart_count( "box", 2.0 ) is None


@pytest.mark.parametrize( "stdout, expected", [
    ( '["LUPIN_ENV=dev", "LUPIN_RELOAD=1"]', [ "LUPIN_ENV=dev", "LUPIN_RELOAD=1" ] ),
    ( "  []\n", [] ),
    ( "null", None ),
    ( "", None ),
    ( None, None ),
    ( "not json", None ),
] )
def test_the_env_reader_parses_the_inspect_output_it_is_given( monkeypatch, stdout, expected ):
    monkeypatch.setattr( hw.subprocess, "run", fake_run( SimpleNamespace( returncode=0, stdout=stdout ) ) )
    assert hw.docker_inspect_env( "box", 2.0 ) == expected


def test_the_env_reader_asks_for_the_config_env_json_and_gives_none_on_a_failed_inspect( monkeypatch ):
    run = fake_run( SimpleNamespace( returncode=1, stdout='["A=1"]' ) )
    monkeypatch.setattr( hw.subprocess, "run", run )
    assert hw.docker_inspect_env( "box", 2.0 ) is None
    assert run.seen[ 0 ][ 0 ] == [ "docker", "inspect", "box", "--format", "{{json .Config.Env}}" ]


def test_the_env_reader_gives_none_when_the_command_cannot_run( monkeypatch ):
    monkeypatch.setattr( hw.subprocess, "run", fake_run( error=subprocess.TimeoutExpired( "docker", 1 ) ) )
    assert hw.docker_inspect_env( "box", 2.0 ) is None
