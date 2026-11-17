"""
The four :8001 arbiter jobs skip their work on a tick whose switch reads false.

The jobs are fleet-arbiter, context-pressure-writer, health-watcher and worktree-janitor. Each test
uses a real TickSwitch over a configuration file in a temporary folder. It runs ticks with the key
false, then true, and counts the calls to the work the tick would do.
"""
import asyncio
import datetime
import json
import os
import sys
import types

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob
from lupin_arbiter_app import app as arbiter_app
from lupin_arbiter_app.context_pressure_writer import ContextPressureWriterLoop
from lupin_arbiter_app.fleet_arbiter_loop import make_worktree_janitor_fn
from lupin_arbiter_app.health_watcher import HealthWatcherLoop
from lupin_arbiter_app.local_snapshot_store import LocalSnapshotStore
from lupin_mcp import cron_switch_read as csr

NOW = datetime.datetime( 2026, 11, 14, 16, 0, 0, tzinfo=datetime.timezone.utc )


class _Ini:
    """A configuration file holding one job's switch, which a test can flip."""

    def __init__( self, tmp_path, job ):
        self.path, self.job = tmp_path / "lupin-app.ini", job

    def set( self, value ):
        self.path.write_text( f"[Lupin]\ncron job {self.job} enabled = {value}\n" )

    def switch( self, logged=None ):
        return csr.TickSwitch( self.job, lambda: str( self.path ), None, ( logged if logged is not None else [] ).append )


class _StopAfter:
    """A clock that stops the loop after a set number of sleeps."""

    def __init__( self, after ):
        self.after, self.slept, self.loop = after, 0, None

    def sleep( self, seconds ):
        self.slept += 1
        if self.slept >= self.after: self.loop.stop()

    def now( self ):
        return NOW


def _run( loop, clock ):
    clock.loop = loop
    loop._stop.clear()
    clock.slept = 0
    loop.run()


def test_the_context_pressure_writer_does_no_work_while_its_switch_is_false( tmp_path ):
    ini, calls = _Ini( tmp_path, "context-pressure-writer" ), []
    ini.set( "false" )
    clock  = _StopAfter( 2 )
    loop   = ContextPressureWriterLoop( lambda **kw: calls.append( 1 ) or [], LocalSnapshotStore(), budget_fractions={ "default": 0.5 },
                                        clock=clock, log_fn=lambda event, **f: None, switch=ini.switch() )
    _run( loop, clock )
    assert calls == [] and clock.slept == 2
    ini.set( "true" )
    _run( loop, clock )
    assert len( calls ) == 2


def test_the_health_watcher_inspects_nothing_while_its_switch_is_false( tmp_path ):
    ini, inspected = _Ini( tmp_path, "health-watcher" ), []
    ini.set( "false" )
    clock = _StopAfter( 3 )
    loop  = HealthWatcherLoop( containers=[ "c1" ], inspect_fn=lambda name: inspected.append( name ) or { "Status": "healthy" },
                               notify_fn=lambda *a, **k: None, clock=clock, log_fn=lambda event, **f: None, switch=ini.switch() )
    _run( loop, clock )
    assert inspected == [] and clock.slept == 3
    ini.set( "true" )
    _run( loop, clock )
    assert inspected == [ "c1", "c1", "c1" ]


def test_the_worktree_janitor_sweeps_nothing_while_its_switch_is_false( tmp_path ):
    ini, reconciled = _Ini( tmp_path, "worktree-janitor" ), []
    ini.set( "false" )
    janitor = make_worktree_janitor_fn( sandbox_root=str( tmp_path ), age_hours=1, ledger_path=str( tmp_path / "refused.json" ),
                                        notify_fn=lambda *a: [], log_fn=lambda event, **f: None,
                                        reconcile_fn=lambda **kw: reconciled.append( kw ) or {}, report_fn=lambda *a: {}, switch=ini.switch() )
    assert janitor() == {} and reconciled == []
    ini.set( "true" )
    assert janitor()[ "repos" ] == [ { "root": None, "swept": 0 } ] and len( reconciled ) == 1


def test_the_fleet_arbiter_skips_its_poll_while_its_switch_is_false_and_keeps_its_error_streak( tmp_path ):
    ini, polls = _Ini( tmp_path, "fleet-arbiter" ), []
    ini.set( "false" )
    ticks = iter( range( 100 ) )

    async def sleep( seconds ):
        return None

    stub = types.SimpleNamespace( _cancel_requested=False, max_duration_seconds=3, poll_seconds=60, _switch=ini.switch(),
                                  _poll_error_streak=2, _poll_error_escalated=True, _poll_once=lambda: polls.append( 1 ),
                                  _clock=types.SimpleNamespace( monotonic=lambda: next( ticks ), sleep=sleep ),
                                  _exit_summary=lambda why: why )
    assert asyncio.run( ArbiterConsumerJob._execute( stub ) ) == "hard-cap"
    assert polls == [] and ( stub._poll_error_streak, stub._poll_error_escalated ) == ( 2, True )
    ini.set( "true" )
    ticks = iter( range( 100 ) )
    stub._clock.monotonic = lambda: next( ticks )
    assert asyncio.run( ArbiterConsumerJob._execute( stub ) ) == "hard-cap"
    assert len( polls ) == 2 and ( stub._poll_error_streak, stub._poll_error_escalated ) == ( 0, False )


def test_the_context_pressure_builder_gives_its_loop_the_switch_for_its_own_job():
    cfg  = types.SimpleNamespace( get=lambda key, default=None, return_type=None: default )
    loop = arbiter_app._build_context_pressure_loop( cfg, LocalSnapshotStore(), log_fn=lambda event, **f: None )
    assert isinstance( loop._switch, csr.TickSwitch ) and loop._switch.job == "context-pressure-writer"


def test_for_job_reads_the_main_checkout_file_and_writes_a_failure_into_its_summary( tmp_path, monkeypatch ):
    from lupin_mcp import fleet_size_cap
    from lupin_cli.claude_code.hooks.lib import heartbeat_hold
    ( tmp_path / "src/conf" ).mkdir( parents=True )
    ( tmp_path / "src/conf/lupin-app.ini" ).write_text( "[Lupin]\n" )
    monkeypatch.setattr( fleet_size_cap, "main_checkout_ini_path", lambda: str( tmp_path / "src/conf/lupin-app.ini" ) )
    monkeypatch.setattr( heartbeat_hold, "_main_repo_path", lambda root: tmp_path )
    logged = []
    switch = csr.for_job( "health-watcher", logged.append )
    assert switch.allowed( NOW ) is False
    attempt = json.loads( ( tmp_path / "io/jobs/health-watcher/job-summary.json" ).read_text() )[ "last_attempt" ]
    assert attempt[ "outcome" ] == "failed" and attempt[ "evidence" ] == "INI key 'cron job health-watcher enabled' is missing or holds neither true nor false"
    assert logged[ 0 ].startswith( "health-watcher: ERROR:" )
