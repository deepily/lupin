"""
Unit tests for the startup steps in `lupin_app/lifespan_steps.py`.

Each step takes its collaborators as arguments, so every branch runs here with a double and
no server. Assertions read the printed line or the argument the step passed on, because those
are what an operator and the next boot stage see.
"""

import asyncio
import io

import pytest

from lupin_app import lifespan_steps as steps


class FakeConfig:
    """A config double: get() returns the stored value, or the default when the key is absent."""

    def __init__( self, **values ):
        self.values = { k.replace( "_", " " ): v for k, v in values.items() }

    def get( self, key, default=None, return_type=None, silent=False ):
        return self.values.get( key, default )


# ── print_migration_banner ───────────────────────────────────────────────────

def test_migration_banner_names_both_revisions():
    """An applied migration prints one banner with the before and after revisions."""
    out = io.StringIO()
    assert steps.print_migration_banner( { "applied": True, "before": "abc", "after": "def" }, stream=out ) is True
    assert "MIGRATION APPLIED — the database moved abc -> def." in out.getvalue()


def test_migration_banner_says_unstamped_when_there_was_no_revision():
    """A database with no earlier revision reads as unstamped, not as an empty string."""
    out = io.StringIO()
    steps.print_migration_banner( { "applied": True, "before": None, "after": "def" }, stream=out )
    assert "moved (unstamped) -> def." in out.getvalue()


def test_migration_banner_is_silent_when_nothing_was_applied( capsys ):
    """A no-op boot prints nothing, to either stream."""
    assert steps.print_migration_banner( { "applied": False, "before": "abc", "after": "abc" } ) is False
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_migration_banner_defaults_to_stderr( capsys ):
    """With no stream given, the banner goes to stderr at call time."""
    steps.print_migration_banner( { "applied": True, "before": "a", "after": "b" } )
    captured = capsys.readouterr()
    assert "MIGRATION APPLIED" in captured.err and captured.out == ""


# ── build_snapshot_manager_config ────────────────────────────────────────────

def test_snapshot_config_reads_the_table_name():
    """The postgres manager config carries the INI table name."""
    config = FakeConfig( solution_snapshots_postgres_table="snaps_v2" )
    assert steps.build_snapshot_manager_config( "postgres", config ) == { "table_name": "snaps_v2" }


def test_snapshot_config_falls_back_to_the_default_table():
    """With no INI key the table name is solution_snapshots, and the type match ignores case."""
    assert steps.build_snapshot_manager_config( "PostgreS", FakeConfig() ) == { "table_name": "solution_snapshots" }


def test_snapshot_config_prints_only_in_debug( capsys ):
    """The manager line appears with debug on and not with debug off."""
    steps.build_snapshot_manager_config( "postgres", FakeConfig() )
    assert capsys.readouterr().out == ""
    steps.build_snapshot_manager_config( "postgres", FakeConfig(), debug=True )
    assert capsys.readouterr().out == "Using Postgres+pgvector solution snapshot manager\n"


def test_snapshot_config_refuses_any_other_type():
    """Any value but postgres raises, and the message names the value and the one supported type."""
    with pytest.raises( ValueError ) as caught:
        steps.build_snapshot_manager_config( "lancedb", FakeConfig() )
    assert str( caught.value ) == (
        "Unsupported 'solution snapshots manager type' = 'lancedb'; the only supported value is 'postgres'"
    )


# ── recover_interrupted_jobs ─────────────────────────────────────────────────

@pytest.mark.parametrize( "counts, expected", [
    ( { "running": 2, "pending_interrupted": 1 }, "3 interrupted, 0 future-scheduled preserved, 0 downtime-missed caught up" ),
    ( { "pending_preserved": 4 },                 "0 interrupted, 4 future-scheduled preserved, 0 downtime-missed caught up" ),
    ( { "pending_catchup": 5 },                   "0 interrupted, 0 future-scheduled preserved, 5 downtime-missed caught up" ),
] )
def test_recovery_summarises_each_kind_of_work( counts, expected, capsys ):
    """Any one of the three counts above zero produces the summary line with all three numbers."""
    assert steps.recover_interrupted_jobs( lambda: counts ) == counts
    assert capsys.readouterr().out == f"[CJ-PERSIST] Startup recovery: {expected}\n"


def test_recovery_reports_when_there_is_nothing( capsys ):
    """An empty result prints the nothing-found line."""
    steps.recover_interrupted_jobs( lambda: { } )
    assert capsys.readouterr().out == "[CJ-PERSIST] No interrupted or scheduled jobs found\n"


def test_recovery_failure_is_a_warning_not_a_crash( capsys ):
    """A failing recovery pass prints a warning and returns None."""
    def boom(): raise RuntimeError( "db down" )
    assert steps.recover_interrupted_jobs( boom ) is None
    assert capsys.readouterr().out == "[WARN] CJ Flow startup recovery failed: db down\n"


# ── restore_jobs_at_boot ─────────────────────────────────────────────────────

def test_restore_runs_the_restore_function():
    """A restore that returns is called once and reported as done."""
    calls = []
    assert steps.restore_jobs_at_boot( lambda: calls.append( 1 ) ) is True
    assert calls == [ 1 ]


def test_restore_failure_is_a_warning_not_a_crash( capsys ):
    """A restore that raises prints a warning and returns False."""
    def boom(): raise RuntimeError( "no jobs table" )
    assert steps.restore_jobs_at_boot( boom ) is False
    assert capsys.readouterr().out == "[WARN] Job restoration failed: no jobs table\n"


# ── print_all_clear_receipt ──────────────────────────────────────────────────

def _gate( reason, missing, roster_size, elapsed=2.25 ):
    return { "reason": reason, "elapsed": elapsed, "missing": missing, "roster_size": roster_size }


def test_receipt_for_a_deadline_fire_names_the_sessions_that_missed_it():
    """A deadline fire is labelled as such and lists who had not rejoined."""
    out = io.StringIO()
    steps.print_all_clear_receipt( _gate( "deadline", [ "s1", "s2" ], 4, 15.0 ), 7, 2, "0→1→2", stream=out )
    assert out.getvalue() == (
        "[managed-bounce] ⚠️ all-clear FIRED on DEADLINE EXPIRY (boot #7): reached 2 recipient(s) after 15.0s; "
        "reconnect curve 0→1→2. 2 session(s) had NOT rejoined and got NO all-clear (accepted loss, no re-fire): ['s1', 's2'].\n"
    )


def test_receipt_for_a_covered_roster_says_every_session_had_a_socket():
    """A roster-covered fire reports the roster size and no loss."""
    out = io.StringIO()
    steps.print_all_clear_receipt( _gate( "covered", [], 3 ), 8, 3, "0→3", stream=out )
    assert out.getvalue() == (
        "[managed-bounce] all-clear FIRED (boot #8): roster COVERED after 2.2s; reconnect curve 0→3; reached 3 recipient(s)."
        " all 3 session(s) on the roster had a live socket.\n"
    )


def test_receipt_flags_an_empty_roster_as_ambiguous():
    """An empty roster is reported as ambiguous, since the gate cannot say why it is empty."""
    out = io.StringIO()
    steps.print_all_clear_receipt( _gate( "covered", [], 0 ), 1, None, "0", stream=out )
    assert "the roster was EMPTY — either nobody was expected back, or the bridge directory could not be read." in out.getvalue()
    assert "reached None recipient(s)" in out.getvalue()


def test_receipt_defaults_to_stderr( capsys ):
    """With no stream given the receipt goes to stderr."""
    steps.print_all_clear_receipt( _gate( "covered", [], 1 ), 1, 1, "0→1" )
    captured = capsys.readouterr()
    assert "all-clear FIRED" in captured.err and captured.out == ""


# ── schedule_all_clear ───────────────────────────────────────────────────────

class _Clock:
    def isoformat( self, timespec ):
        return f"2026-10-26T14:00:00[{timespec}]"


def _schedule( config, store, tmp_path, scheduled, label_fn=lambda: ":8000", **kw ):
    def run_fn( **kwargs ): return ( "coro", kwargs )
    return steps.schedule_all_clear(
        config, store, label_fn, lambda: tmp_path, run_fn, 12.5, lambda: _Clock(),
        create_task_fn=scheduled.append, **kw
    )


def test_all_clear_is_scheduled_with_a_numbered_boot( tmp_path ):
    """The task gets the boot number and start stamps, and the counter advances per boot."""
    scheduled = []
    assert _schedule( FakeConfig(), object(), tmp_path, scheduled ) is True
    assert _schedule( FakeConfig(), object(), tmp_path, scheduled ) is True
    assert [ kw[ "boot_id" ] for _coro, kw in scheduled ] == [ 1, 2 ]
    assert scheduled[ 0 ][ 1 ] == { "boot_id": 1, "boot_started": "2026-10-26T14:00:00[seconds]", "startup_began": 12.5 }


def test_all_clear_is_skipped_when_commons_is_disabled( tmp_path ):
    """The commons switch off means nothing is scheduled and no counter file is written."""
    scheduled = []
    assert _schedule( FakeConfig( commons_enabled=False ), object(), tmp_path, scheduled ) is False
    assert scheduled == [] and list( tmp_path.iterdir() ) == []


def test_all_clear_is_skipped_when_commons_never_started( tmp_path ):
    """A None commons store means commons failed to start, so there is nobody to tell."""
    scheduled = []
    assert _schedule( FakeConfig(), None, tmp_path, scheduled ) is False
    assert scheduled == []


def test_all_clear_failure_is_a_warning_not_a_crash( tmp_path, capsys ):
    """A failure while resolving the label, even before scheduling, degrades to a stderr warning."""
    scheduled = []
    def bad_label(): raise RuntimeError( "config unreadable" )
    assert _schedule( FakeConfig(), object(), tmp_path, scheduled, label_fn=bad_label ) is False
    captured = capsys.readouterr()
    assert captured.err == "[managed-bounce] WARN: could not schedule all-clear: config unreadable\n"
    assert scheduled == []


# ── start_websocket_maintenance_tasks ────────────────────────────────────────


def _start_ws( config ):
    created = []
    async def hb(): return None
    async def cl(): return None
    def create( coro ):
        created.append( coro.__name__ )
        coro.close()
        return f"task-{coro.__name__}"
    result = steps.start_websocket_maintenance_tasks( config, hb, cl, create_task_fn=create )
    return result, created


def test_both_maintenance_tasks_start_by_default( capsys ):
    """With neither key set, both loops start and both are announced."""
    ( heartbeat, cleanup ), created = _start_ws( FakeConfig() )
    assert ( heartbeat, cleanup ) == ( "task-hb", "task-cl" ) and created == [ "hb", "cl" ]
    out = capsys.readouterr().out
    assert "[WS-HEARTBEAT] Heartbeat task started" in out and "[WS-CLEANUP] Cleanup task started" in out


def test_heartbeat_switch_off_leaves_only_cleanup():
    """Heartbeat disabled yields None for it and still starts cleanup."""
    ( heartbeat, cleanup ), created = _start_ws( FakeConfig( websocket_heartbeat_enabled=False ) )
    assert heartbeat is None and cleanup == "task-cl" and created == [ "cl" ]


def test_cleanup_switch_off_leaves_only_heartbeat():
    """Cleanup disabled yields None for it and still starts the heartbeat."""
    ( heartbeat, cleanup ), created = _start_ws( FakeConfig( websocket_cleanup_enabled=False ) )
    assert heartbeat == "task-hb" and cleanup is None and created == [ "hb" ]


def test_both_switches_off_start_nothing( capsys ):
    """Both disabled starts nothing and prints nothing."""
    config = FakeConfig( websocket_heartbeat_enabled=False, websocket_cleanup_enabled=False )
    assert _start_ws( config )[ 0 ] == ( None, None )
    assert capsys.readouterr().out == ""


# ── start_notification_sweep_task ────────────────────────────────────────────

def _start_sweep( config ):
    created = []
    async def sweep(): return None
    def create( coro ):
        created.append( 1 )
        coro.close()
        return "sweep-task"
    return steps.start_notification_sweep_task( config, sweep, create_task_fn=create ), created


def test_sweep_task_starts_when_the_switch_is_on( capsys ):
    """The switch on starts the task and announces it."""
    task, created = _start_sweep( FakeConfig( notification_expiry_sweep_enabled=True ) )
    assert task == "sweep-task" and created == [ 1 ]
    assert "[NOTIFY-SWEEP] Orphan sweep task started" in capsys.readouterr().out


def test_sweep_task_stays_off_when_the_switch_is_off():
    """The switch off starts nothing."""
    task, created = _start_sweep( FakeConfig( notification_expiry_sweep_enabled=False ) )
    assert task is None and created == []


def test_sweep_task_fails_closed_when_the_key_is_absent():
    """A missing key must not arm the sweeper, because it can refuse a human answer."""
    task, created = _start_sweep( FakeConfig() )
    assert task is None and created == []
