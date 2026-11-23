"""
Job-health rows of the job alert watcher, over a fake store and the real jobs page.

The replay feeds the poll the real record of the daily test promotion, 16 to 22 Nov 2026.
It is copied from recent[] of io/jobs/test-promotion/job-summary.json and replayed one day at a time.
It goes through the real `job_service.build_response` and `job_health.assess`.
So the rules for failing and silent are the page's own, not a copy.
"""
import datetime
import json
import pathlib
import shutil
import zoneinfo

import pytest

import cosa.rest.job_registry as jr
import cosa.rest.job_service as svc
import cosa.agents.shared.worktree_straggler_tickets as wst
import lupin_arbiter_app.job_alert_watcher as jaw
from lupin_mcp import job_summary as js

NY        = zoneinfo.ZoneInfo( "America/New_York" )
REAL_ROOT = pathlib.Path( __file__ ).resolve().parents[ 3 ]
BOOT      = datetime.datetime( 2026, 11, 1, 8, 0, tzinfo=NY )

# The real record of the daily test promotion, recent[] of its job-summary.json on 23 Nov 2026.
PROMOTION_RECORD = [
    ( "2026-11-16T18:00:02-05:00", "clean",  "promoted" ),
    ( "2026-11-17T18:00:02-05:00", "failed", "vm-unreachable" ),
    ( "2026-11-18T18:00:02-05:00", "failed", "rollback-failed" ),
    ( "2026-11-19T18:00:02-05:00", "failed", "vm-unreachable" ),
    ( "2026-11-20T18:00:02-05:00", "failed", "vm-unreachable" ),
    ( "2026-11-21T18:00:02-05:00", "failed", "rollback-failed" ),
    ( "2026-11-22T18:00:02-05:00", "clean",  "promoted" ),
]


class Deps:
    """Fake inputs for the job page: a boot time, no crontab, no unit, no lock."""

    def boot_time( self ): return BOOT

    def crontab_text( self ): return None

    def host_zone( self ): return None

    def unit_state( self, unit, health_url=None ): return None

    def lock_held( self, path ): return False

    def store_counts( self, key, now, days ): return None


class Store:
    """An in-memory store with the arbiter's four verbs; one verb can be made to fail."""

    def __init__( self ):
        self.rows, self.calls, self.fail = {}, [], set()

    def hit( self, verb ):
        self.calls.append( verb )
        if verb in self.fail: raise RuntimeError( f"{verb} refused" )

    def find_open( self, key ):
        self.hit( "find_open" )
        return next( ( i for i, r in self.rows.items() if r[ "correlation_key" ] == key and r[ "status" ] == "queued" ), None )

    def create( self, **row ):
        self.hit( "create" )
        row_id = f"row-{len( self.rows ) + 1}"
        self.rows[ row_id ] = { **row, "status": "queued", "notes": [] }
        return row_id

    def amend( self, row_id, note, reason ):
        self.hit( "amend" )
        self.rows[ row_id ][ "notes" ].append( note )

    def drop( self, row_id, reason ):
        self.hit( "drop" )
        self.rows[ row_id ].update( status="dropped", reason=reason )


class Clock:
    """A fake clock: now() is a field the test sets."""

    def __init__( self, now ): self.t = now

    def now( self ): return self.t

    def sleep( self, seconds ): self.t += datetime.timedelta( seconds=seconds )


def tree( tmp_path, jobs ):
    """Ensures: writes a registry for jobs under tmp_path and returns the root."""
    defaults = jr.load_registry( REAL_ROOT )[ "defaults" ]
    path     = tmp_path / jr.REGISTRY_FILE
    path.parent.mkdir( parents=True )
    path.write_text( json.dumps( { "schema": "job-registry/1", "defaults": defaults, "jobs": jobs } ) )
    return str( tmp_path )


def promotion_entry( **over ):
    """Ensures: returns the shipped registry's test-promotion entry, with any overrides."""
    return { **next( j for j in jr.load_registry( REAL_ROOT )[ "jobs" ] if j[ "job" ] == "test-promotion" ), **over }


def record_attempt( root, when, outcome, mode ):
    """Ensures: writes the summary the job would write after one more attempt."""
    started = datetime.datetime.fromisoformat( when )
    js.write_summary( pathlib.Path( root ) / "io" / "jobs" / "test-promotion" / "job-summary.json", "test-promotion",
                      { "started_at": when, "finished_at": ( started + datetime.timedelta( minutes=3 ) ).isoformat(), "trigger": "cron", "outcome": outcome,
                        "stage": "smoke" if outcome == "failed" else None, "failure": mode if outcome == "failed" else None, "evidence": mode, "mode": mode }, now=started )


def make_loop( root, store, alerts=None, logs=None ):
    """Ensures: returns the loop and its clock; alerts and log lines go to the lists given."""
    clock  = Clock( datetime.datetime( 2026, 11, 17, 18, 31, tzinfo=NY ) )
    data   = str( pathlib.Path( root ) / "data" )
    alerts = alerts if alerts is not None else []
    log    = lambda event, **kw: ( logs if logs is not None else [] ).append( ( event, kw ) )
    sync   = jaw.make_row_sync( store, lambda: jaw.registry_owners( root ), str( pathlib.Path( root ) / jaw.ROW_STATE_FILE ), log )
    loop   = jaw.JobAlertLoop( lambda: svc.build_response( root, data, clock.now(), Deps() )[ "jobs" ], lambda message: alerts.append( message ) or [ { "channel": "live", "outcome": "queued" } ],
                               str( pathlib.Path( root ) / jaw.STATE_FILE ), log, clock=clock, row_sync_fn=sync )
    return loop, clock


# ── the replay: the real promotion record, day by day ────────────────────────

def test_the_real_promotion_record_opens_one_row_on_17_nov_updates_it_through_21_nov_and_closes_it_on_22_nov( tmp_path ):
    root = tree( tmp_path, [ promotion_entry() ] )
    store, logs, seen = Store(), [], {}
    loop, clock = make_loop( root, store, logs=logs )
    for when, outcome, mode in PROMOTION_RECORD:
        record_attempt( root, when, outcome, mode )
        clock.t = datetime.datetime.fromisoformat( when ).replace( hour=18, minute=31, second=0 )
        loop.poll_once()
        seen[ clock.t.day ] = ( len( store.rows ), store.calls.count( "create" ), store.calls.count( "amend" ), store.calls.count( "drop" ) )
    assert seen == { 16: ( 0, 0, 0, 0 ),            # healthy and no row: only reads, nothing written
                     17: ( 1, 1, 0, 0 ),            # the row opens
                     18: ( 1, 1, 1, 0 ), 19: ( 1, 1, 2, 0 ), 20: ( 1, 1, 3, 0 ), 21: ( 1, 1, 4, 0 ),      # updated each day, never a second row
                     22: ( 1, 1, 4, 1 ) }           # healthy again: the row is closed
    row = store.rows[ "row-1" ]
    assert row[ "status" ] == "dropped" and "healthy again as of 2026-11-22T18:31" in row[ "reason" ]
    assert row[ "correlation_key" ] == "job-health:test-promotion" and row[ "priority" ] == "P5" and row[ "owner" ] == row[ "accountable" ] == "mr radio" and row[ "project" ] == "lupin"
    assert row[ "title" ] == "[LUPIN] Job health: Daily test promotion is failing" and "Owner: mr radio (confirmed)." in row[ "body" ] and "closes by itself" in row[ "body" ]
    assert [ "rollback-failed" in n for n in row[ "notes" ] ] == [ True, False, False, True ]            # 18 Nov, 19, 20 and 21 each carry their own day's reason
    assert [ e for e, _ in logs if e == "job_rows" ] == [ "job_rows" ] * 6 and json.loads( ( tmp_path / jaw.ROW_STATE_FILE ).read_text() ) == {}      # closed: its fingerprint is forgotten


def test_the_same_fault_seen_again_amends_nothing_and_a_lost_row_state_costs_one_amend_not_a_second_row( tmp_path ):
    root = tree( tmp_path, [ promotion_entry() ] )
    record_attempt( root, *PROMOTION_RECORD[ 1 ] )
    store = Store()
    loop, clock = make_loop( root, store )
    for _ in range( 3 ): loop.poll_once()
    assert store.calls.count( "create" ) == 1 and store.calls.count( "amend" ) == 0
    ( tmp_path / jaw.ROW_STATE_FILE ).unlink()
    loop.poll_once()
    assert len( store.rows ) == 1 and store.calls.count( "amend" ) == 1


def test_the_alert_still_goes_out_beside_the_row( tmp_path ):
    root = tree( tmp_path, [ promotion_entry() ] )
    record_attempt( root, *PROMOTION_RECORD[ 1 ] )
    alerts = []
    loop, _ = make_loop( root, Store(), alerts )
    assert loop.poll_once() == 1 and alerts == [ "Background job Daily test promotion is FAILING: Failed 1 time(s) in a row at smoke: vm-unreachable; last finished never reported." ]


# ── silent, never reported, behind ───────────────────────────────────────────

def test_a_job_that_missed_its_run_is_silent_and_gets_a_row_naming_the_missed_time( tmp_path ):
    root = tree( tmp_path, [ promotion_entry() ] )
    record_attempt( root, *PROMOTION_RECORD[ 0 ] )            # its last attempt is 16 Nov; nothing since
    store = Store()
    loop, clock = make_loop( root, store )
    clock.t = datetime.datetime( 2026, 11, 19, 18, 31, tzinfo=NY )
    loop.poll_once()
    row = next( iter( store.rows.values() ) )
    assert row[ "title" ].endswith( "is silent" ) and "Due 2026-11-19T18:00-05:00, nothing since." in row[ "body" ]


def test_behind_unknown_and_unlisted_states_are_left_alone_and_cost_no_store_call():
    store = Store()
    jobs  = [ { "job": "a", "state": "behind" }, { "job": "b", "state": "unknown" } ]
    out   = jaw.sync_job_rows( jobs, {}, store, { "a": "x" }, datetime.datetime( 2026, 11, 19, tzinfo=NY ) )
    assert store.calls == [] and out == { "opened": [], "updated": [], "closed": [], "errors": [], "state": { "a": "x" } }


def test_a_job_that_has_never_reported_is_unknown_and_gets_no_row( tmp_path ):
    root = tree( tmp_path, [ promotion_entry() ] )
    store = Store()
    loop, _ = make_loop( root, store )
    loop.poll_once()
    assert store.calls == [] and store.rows == {}


# ── loud failures ────────────────────────────────────────────────────────────

def red_loop( tmp_path, store ):
    root = tree( tmp_path, [ promotion_entry() ] )
    record_attempt( root, *PROMOTION_RECORD[ 1 ] )
    alerts, logs = [], []
    loop, clock = make_loop( root, store, alerts, logs )
    return loop, clock, alerts, logs


def test_a_store_that_refuses_the_row_is_logged_alerted_once_an_hour_and_tried_again_next_poll( tmp_path ):
    store = Store()
    store.fail.add( "create" )
    loop, clock, alerts, logs = red_loop( tmp_path, store )
    loop.poll_once()
    failure = [ a for a in alerts if a.startswith( "Job rows could not be kept in step" ) ]
    assert len( failure ) == 1 and "job-health:test-promotion: RuntimeError: create refused" in failure[ 0 ] and logs[ -1 ][ 0 ] == "job_row_failed" and store.rows == {}
    clock.t += datetime.timedelta( minutes=10 )
    loop.poll_once()
    assert len( [ a for a in alerts if a.startswith( "Job rows could not be kept" ) ] ) == 1, "ten minutes later it is logged again but not alerted again"
    clock.t += datetime.timedelta( hours=1 )
    loop.poll_once()
    assert len( [ a for a in alerts if a.startswith( "Job rows could not be kept" ) ] ) == 2
    store.fail.clear()
    loop.poll_once()
    assert len( store.rows ) == 1, "nothing was marked as done, so the next poll files it"


def test_a_failure_alert_that_was_not_delivered_is_sent_again_at_the_next_poll( tmp_path ):
    store = Store()
    store.fail.add( "create" )
    loop, clock, alerts, logs = red_loop( tmp_path, store )
    answers = [ [], [ { "channel": "live", "outcome": "queued" } ] ]                      # the failure alert reaches nobody once, then arrives
    ok      = [ { "channel": "live", "outcome": "queued" } ]
    loop.notify_fn = lambda message: alerts.append( message ) or ( answers.pop( 0 ) if message.startswith( "Job rows could not be kept" ) else ok )
    count = lambda: len( [ a for a in alerts if a.startswith( "Job rows could not be kept" ) ] )
    loop.poll_once()
    assert count() == 1, "the first send reached nobody"
    clock.t += datetime.timedelta( minutes=10 )
    loop.poll_once()
    assert count() == 2, "so the next poll sends it again, not an hour later"
    clock.t += datetime.timedelta( minutes=10 )
    loop.poll_once()
    assert count() == 2, "once delivered, the hour's quiet applies"


@pytest.mark.parametrize( "verb", [ "find_open", "amend", "drop" ] )
def test_every_store_verb_that_fails_is_named_in_the_failure_line( tmp_path, verb ):
    store = Store()
    loop, clock, alerts, logs = red_loop( tmp_path, store )
    loop.poll_once()                                                       # the row opens
    if verb == "amend":
        record_attempt( str( tmp_path ), *PROMOTION_RECORD[ 2 ] )
        clock.t = datetime.datetime( 2026, 11, 18, 18, 31, tzinfo=NY )
    if verb == "drop":
        record_attempt( str( tmp_path ), *PROMOTION_RECORD[ 6 ] )
        clock.t = datetime.datetime( 2026, 11, 22, 18, 31, tzinfo=NY )
    store.fail.add( verb )
    loop.poll_once()
    assert f"RuntimeError: {verb} refused" in logs[ -1 ][ 1 ][ "errors" ][ 0 ] and logs[ -1 ][ 0 ] == "job_row_failed"


def test_a_job_with_no_registry_owner_is_one_failure_line_and_the_others_go_on():
    store = Store()
    red   = lambda job: { "job": job, "title": job, "state": "failing", "reasons": [ { "state": "failing", "text": "bad" } ], "last_attempt": None }
    out   = jaw.sync_job_rows( [ red( "orphan" ), red( "kept" ) ], { "kept": ( "cheech", False ) }, store, {}, datetime.datetime( 2026, 11, 19, tzinfo=NY ) )
    assert out[ "opened" ] == [ "kept" ] and len( out[ "errors" ] ) == 1 and "job-health:orphan: KeyError" in out[ "errors" ][ 0 ] and "orphan" not in out[ "state" ]


def test_an_unreadable_registry_is_one_failure_line_and_the_summary_is_not_lost():
    def broken(): raise ValueError( "no registry" )
    sync = jaw.make_row_sync( Store(), broken, "/nonexistent/state.json", lambda *a, **k: None )
    assert sync( [], datetime.datetime( 2026, 11, 19, tzinfo=NY ) ) == [ "job registry unreadable: ValueError: no registry" ]


# ── the pieces ───────────────────────────────────────────────────────────────

def test_an_unconfirmed_owner_is_named_in_the_row_and_the_registry_slug_maps_to_the_stores_key( tmp_path ):
    root = tree( tmp_path, [ promotion_entry( owner="mr-radio", owner_confirmed=False ) ] )
    assert jaw.registry_owners( root ) == { "test-promotion": ( "mr radio", False ) }
    entry = { "job": "j", "title": "J", "state": "silent", "reasons": [ { "state": "silent", "text": "Due." }, { "state": "behind", "text": "no" } ], "last_attempt": None }
    row   = jaw.compose_job_row( entry, "mr radio", False )
    assert "Rick has not confirmed" in row[ "body" ] and row[ "owner" ] == row[ "accountable" ] == "mr radio" and "no" not in row[ "body" ].split( "Due." )[ 1 ].split( "\n" )[ 0 ]
    assert jaw.row_fingerprint( entry ) == "silent|Due.|never"
    assert jaw.row_fingerprint( { **entry, "last_attempt": { "started_at": "t" } } ) == "silent|Due.|t"


def test_the_job_page_and_the_row_function_share_one_state_file_name_under_io_jobs():
    assert jaw.ROW_STATE_FILE == "io/jobs/job-row-state.json" and jaw.ROW_PRIORITY == "P5" and jaw.ROW_STATES == ( "failing", "silent" )


class Cfg:
    """A fake arbiter config: everything default, the job alert switch on, health watch off."""
    config_block_id = "Lupin:+Stub"

    def get_required( self, key, **_kw ): return "America/New_York"

    def get( self, key, default=None, return_type="string" ):
        if key == "arbiter job alert enabled": return True
        if key == "arbiter health watch containers": return "c1"
        if key == "arbiter health flap exclude containers": return "c1"
        return default


class Gateway:
    """A gateway that answers nothing and records nothing."""

    def who( self, retention_hours=24 ): return [ ]

    def send_to( self, recipient, body, metadata=None ): pass

    def post( self, topic, body ): pass

    def read( self, topic, since=None, limit=50 ): return [ ]


# ── the app wires it ─────────────────────────────────────────────────────────

def test_the_app_wires_the_row_sync_to_the_arbiters_own_store_and_the_registry_owner( tmp_path, monkeypatch ):
    import cosa.utils.util as cu
    from lupin_arbiter_app.app import assemble_app
    root = tree( tmp_path, [] )
    shutil.copy( REAL_ROOT / jr.REGISTRY_FILE, root + "/" + jr.REGISTRY_FILE )
    store = Store()
    monkeypatch.setattr( cu, "get_project_root", lambda: root )
    monkeypatch.setattr( wst, "RepositoryStragglerStore", lambda: store )
    loop = assemble_app( Cfg(), Gateway() ).state.job_alert_loop
    red  = { "job": "test-promotion", "title": "Daily test promotion", "state": "failing", "reasons": [ { "state": "failing", "text": "bad" } ], "last_attempt": None }
    assert loop.row_sync_fn( [ red ], datetime.datetime( 2026, 11, 17, tzinfo=NY ) ) == []
    assert store.rows[ "row-1" ][ "owner" ] == "mr radio" and store.rows[ "row-1" ][ "priority" ] == "P5"
    assert json.loads( ( pathlib.Path( root ) / jaw.ROW_STATE_FILE ).read_text() ) == { "test-promotion": "failing|bad|never" }
