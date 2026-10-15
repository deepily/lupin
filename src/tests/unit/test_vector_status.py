"""
Unit tests for the vector set's staleness status.

Venue: :7999-eligible. The index generation, the data folder and the store are stand-ins in a
temporary folder. Nothing touches a model, the network or the shared data folder.
"""
import datetime
import io
import json
import pathlib

import pytest

from cosa.repo.symindex import vector_refresh as vr
from cosa.repo.symindex import vector_status as vs
from cosa.repo.symindex.candidates import freshness as fr

from test_vector_refresh import ConfigFor, symbol

NOON     = datetime.datetime( 2026, 10, 15, 12, 0, 0 )
EARLY    = datetime.datetime( 2026, 10, 15, 3, 0, 0 )
HEADER   = { "manifest": { "m.py": [ 1, 2 ] }, "symbols_sha": "sha-1" }
NEW_HEAD = { "manifest": { "m.py": [ 1, 3 ] }, "symbols_sha": "sha-2" }


def utc( hours_before ):
    """The ISO UTC string for a time the given number of hours before the fixed test time."""
    return ( NOON.astimezone( datetime.timezone.utc ) - datetime.timedelta( hours=hours_before ) ).isoformat( timespec="seconds" )


class FakeLibrarian:
    def __init__( self, answer="created", error=None ):
        self.answer = answer
        self.error  = error
        self.rows   = []

    def hold_or_create( self, title, body ):
        if self.error: raise self.error
        self.rows.append( ( title, body ) )
        return self.answer


@pytest.fixture
def world( tmp_path, monkeypatch ):
    """A published index with two public pins, no live set and no job state yet."""
    symbols = [ symbol( "b", "pb" ), symbol( "a", "pa" ) ]
    head    = { "header": HEADER }
    monkeypatch.setattr( vs.sx_build, "current_generation", lambda out: "gen" )
    monkeypatch.setattr( vs.sx_build, "read_header", lambda gen: head[ "header" ] )
    monkeypatch.setattr( vs.sx_build, "read_symbols", lambda gen: symbols )
    monkeypatch.setattr( vs, "default_out_dir", lambda root: tmp_path / "idx" )
    monkeypatch.setattr( vs, "data_dir", lambda root: tmp_path / "data" )
    monkeypatch.setattr( vr, "data_dir", lambda root: tmp_path / "data" )
    return { "root": tmp_path / "repo", "data": tmp_path / "data", "live": tmp_path / "data" / "vec", "head": head, "log": [] }


def put_set( world, built_at, header=None, unwritten=() ):
    world[ "live" ].mkdir( parents=True, exist_ok=True )
    fr.write_build_info( world[ "live" ], header if header is not None else HEADER, built_at, unwritten )


def put_state( world, **fields ):
    path = pathlib.Path( vr.refresh_dir( world[ "root" ] ) ) / vr.STATE_NAME
    path.parent.mkdir( parents=True, exist_ok=True )
    path.write_text( json.dumps( fields ) )


def put_lines( world, *pins ):
    store = world[ "data" ] / "pl" / "purpose.jsonl"
    store.parent.mkdir( parents=True, exist_ok=True )
    store.write_text( "".join( json.dumps( { "pin": p, "purpose": "x", "prompt_hash": "h", "writer_version": "w" } ) + "\n" for p in pins ) )


def compute( world, now=NOON, hours=36.0 ):
    return vs.compute( world[ "root" ], now, hours, config=ConfigFor(), environ={} )


# ── the hours key ───────────────────────────────────────────────────────────


@pytest.mark.parametrize( "raw, expected", [ ( "48", 48.0 ), ( " 12.5 ", 12.5 ), ( "0", 36.0 ), ( "-3", 36.0 ), ( "soon", 36.0 ), ( None, 36.0 ), ( "", 36.0 ) ] )
def test_the_stale_hours_come_from_the_key_and_fall_back_to_36_for_anything_that_is_not_a_positive_number( raw, expected ):
    asked = []
    def reader( key ): asked.append( key ); return raw
    assert vs.read_stale_hours( reader ) == expected and asked == [ "reuse vector stale hours" ]


def test_an_unreadable_configuration_file_falls_back_to_36():
    def broken( key ): raise OSError( "ini gone" )
    assert vs.read_stale_hours( broken ) == vs.DEFAULT_STALE_HOURS == 36.0


# ── age ─────────────────────────────────────────────────────────────────────


def test_age_is_hours_since_the_utc_stamp_for_a_naive_local_now_and_an_aware_now():
    assert vs.age_hours( utc( 5 ), NOON ) == 5.0
    assert vs.age_hours( utc( 1.5 ), NOON.astimezone() ) == 1.5


@pytest.mark.parametrize( "bad", [ None, "yesterday", "2026-10-15T08:00:00", 12 ] )
def test_age_is_none_for_a_time_that_is_missing_unparseable_or_has_no_offset( bad ):
    assert vs.age_hours( bad, NOON ) is None


# ── the verdict ─────────────────────────────────────────────────────────────


def test_a_young_set_built_from_the_current_index_with_every_line_stored_is_fresh( world ):
    put_set( world, utc( 5 ) )
    put_lines( world, "pa", "pb" )
    put_state( world, last_run_date="2026-10-15", last_outcome="built", last_seconds=41.0, last_attempt_at="2026-10-15T10:47:00" )
    status = compute( world )
    assert status[ "stale" ] is False and status[ "reasons" ] == []
    assert status[ "age_hours" ] == 5.0 and status[ "built_at" ] == utc( 5 )
    assert status[ "index_differs" ] is False and status[ "missing_purpose_lines" ] == 0 and status[ "job_due" ] is False
    assert status[ "set_index_manifest" ] == status[ "current_index_manifest" ] == fr.index_manifest( HEADER )
    assert ( status[ "last_outcome" ], status[ "last_seconds" ], status[ "last_run_date" ] ) == ( "built", 41.0, "2026-10-15" )
    assert status[ "checked_at" ] == "2026-10-15T12:00:00" and status[ "stale_after_hours" ] == 36.0


def test_the_age_limit_is_strict_so_exactly_the_limit_is_fresh_and_a_little_over_is_stale( world ):
    put_set( world, utc( 36 ) )
    assert compute( world )[ "stale" ] is False
    put_set( world, utc( 36.5 ) )
    status = compute( world )
    assert status[ "stale" ] is True and status[ "reasons" ] == [ "the set is 36.5 hours old, over 36.0" ]


def test_the_limit_is_the_one_passed_in( world ):
    put_set( world, utc( 5 ) )
    assert compute( world, hours=4.0 )[ "stale" ] is True and compute( world, hours=6.0 )[ "stale" ] is False


def test_no_set_at_all_reads_as_stale_with_unknown_age( world ):
    status = compute( world )
    assert status[ "stale" ] is True and status[ "reasons" ] == [ "the set has no build info" ]
    assert status[ "built_at" ] is None and status[ "age_hours" ] is None and status[ "set_index_manifest" ] is None
    assert status[ "index_differs" ] is False


def test_a_build_time_that_cannot_be_read_is_stale_and_says_so( world ):
    put_set( world, "last tuesday" )
    status = compute( world )
    assert status[ "stale" ] is True and status[ "reasons" ] == [ "the set's build time cannot be read: last tuesday" ]


def test_a_changed_index_is_stale_only_once_the_daily_job_has_already_run_today( world ):
    put_set( world, utc( 5 ), header=HEADER )
    world[ "head" ][ "header" ] = NEW_HEAD
    put_state( world, last_run_date="2026-10-14" )
    due = compute( world )
    assert due[ "index_differs" ] is True and due[ "job_due" ] is True and due[ "stale" ] is False
    put_state( world, last_run_date="2026-10-15" )
    ran = compute( world )
    assert ran[ "job_due" ] is False and ran[ "stale" ] is True
    assert ran[ "reasons" ] == [ "the index changed since the set was built and the daily job has already run today" ]


def test_before_ten_the_job_is_not_due_so_a_changed_index_is_stale_then( world ):
    put_set( world, utc( 5 ) )
    world[ "head" ][ "header" ] = NEW_HEAD
    status = compute( world, now=EARLY )
    assert status[ "job_due" ] is False and status[ "stale" ] is True


def test_both_conditions_are_named_in_order( world ):
    put_set( world, utc( 50 ), header=HEADER )
    world[ "head" ][ "header" ] = NEW_HEAD
    put_state( world, last_run_date="2026-10-15" )
    assert len( compute( world )[ "reasons" ] ) == 2 and compute( world )[ "reasons" ][ 0 ].startswith( "the set is 50.0 hours old" )


def test_pins_without_a_purpose_line_are_counted_and_do_not_by_themselves_make_the_set_stale( world ):
    put_set( world, utc( 5 ) )
    put_lines( world, "pa" )
    status = compute( world )
    assert status[ "missing_purpose_lines" ] == 1 and status[ "stale" ] is False


def test_pins_the_build_could_not_write_a_line_for_are_settled_for_the_index_the_set_was_built_from( world ):
    put_set( world, utc( 5 ), unwritten=[ "pb" ] )
    put_lines( world, "pa" )
    assert compute( world )[ "missing_purpose_lines" ] == 0


def test_settled_pins_count_again_once_the_index_has_changed( world ):
    put_set( world, utc( 5 ), unwritten=[ "pb" ] )
    put_lines( world, "pa" )
    world[ "head" ][ "header" ] = NEW_HEAD
    assert compute( world )[ "missing_purpose_lines" ] == 1


def test_with_no_build_info_no_pin_is_settled( world ):
    put_lines( world, "pa" )
    assert compute( world )[ "missing_purpose_lines" ] == 1


def test_with_no_published_index_nothing_is_counted_against_the_set( world, monkeypatch ):
    monkeypatch.setattr( vs.sx_build, "current_generation", lambda out: None )
    put_set( world, utc( 5 ) )
    status = compute( world )
    assert status[ "current_index_manifest" ] is None and status[ "missing_purpose_lines" ] is None
    assert status[ "index_differs" ] is False and status[ "stale" ] is False


def test_an_absent_job_state_gives_none_for_every_last_field_and_a_due_job( world ):
    status = compute( world )
    assert [ status[ k ] for k in ( "last_outcome", "last_seconds", "last_error", "last_attempt_at", "last_run_date" ) ] == [ None ] * 5
    assert status[ "job_due" ] is True


def test_a_job_that_failed_shows_its_error_and_outcome( world ):
    put_set( world, utc( 5 ) )
    put_state( world, last_outcome="failed", last_error="TimeoutError: slow", last_run_date="2026-10-14" )
    status = compute( world )
    assert status[ "last_outcome" ] == "failed" and status[ "last_error" ] == "TimeoutError: slow"


# ── the row ─────────────────────────────────────────────────────────────────


def test_the_stale_row_has_a_fixed_title_and_a_body_that_names_every_reason_and_the_rebuild_command( world ):
    put_set( world, utc( 50 ) )
    put_state( world, last_outcome="failed", last_error="boom", last_attempt_at="2026-10-15T10:47:00" )
    title, body = vs.stale_row( compute( world ) )
    assert title == vs.STALE_TITLE == "[LUPIN] reuse vector set is stale"
    assert "- the set is 50.0 hours old, over 36.0" in body
    assert "last_error: boom" in body and "pins_without_purpose_line: 2" in body and f"built_at: {utc( 50 )}" in body
    assert "python -m cosa.repo.symindex.vector_refresh --force" in body


# ── check ───────────────────────────────────────────────────────────────────


def run_check( world, librarian=None, hours=36.0 ):
    return vs.check( world[ "root" ], NOON, librarian=librarian, stale_hours=hours, config=ConfigFor(), environ={}, log=world[ "log" ].append )


def written( world ):
    return json.loads( ( pathlib.Path( vr.refresh_dir( world[ "root" ] ) ) / vs.STATUS_NAME ).read_text() )


def test_a_fresh_set_files_no_row_and_writes_the_status_file( world ):
    put_set( world, utc( 5 ) )
    lib    = FakeLibrarian()
    status = run_check( world, lib )
    assert status[ "stale" ] is False and "row" not in status and lib.rows == []
    assert written( world ) == status


def test_a_stale_set_files_one_row_and_the_status_file_records_the_answer( world ):
    lib    = FakeLibrarian( "created" )
    status = run_check( world, lib )
    assert status[ "stale" ] is True and status[ "row" ] == "created"
    assert [ t for t, _ in lib.rows ] == [ vs.STALE_TITLE ] and written( world ) == status


@pytest.mark.parametrize( "answer", [ "exists", "pending" ] )
def test_the_librarians_answer_for_an_open_or_held_row_is_recorded( world, answer ):
    assert run_check( world, FakeLibrarian( answer ) )[ "row" ] == answer


def test_an_unreadable_store_is_logged_and_the_check_still_answers( world ):
    status = run_check( world, FakeLibrarian( error=RuntimeError( "task store query failed: status 500" ) ) )
    assert status[ "stale" ] is True and status[ "row" ] == "unreadable"
    assert "no stale row was filed" in world[ "log" ][ 0 ] and "status 500" in world[ "log" ][ 0 ]
    assert written( world )[ "row" ] == "unreadable"


def test_with_no_librarian_a_stale_set_files_nothing_and_still_writes_the_file( world ):
    status = run_check( world, None )
    assert status[ "stale" ] is True and "row" not in status and written( world ) == status


def test_the_limit_defaults_to_the_configuration_value_when_not_passed( world, monkeypatch ):
    monkeypatch.setattr( vs, "read_stale_hours", lambda reader=None: 4.0 )
    put_set( world, utc( 5 ) )
    status = vs.check( world[ "root" ], NOON, config=ConfigFor(), environ={} )
    assert status[ "stale_after_hours" ] == 4.0 and status[ "stale" ] is True


# ── command line ────────────────────────────────────────────────────────────


def run_main( world, **kw ):
    out = io.StringIO()
    code = vs.main( [ "--root", str( world[ "root" ] ) ], environ={}, now=NOON, out=out, **kw )
    return code, json.loads( out.getvalue() )


def test_the_command_exits_one_with_the_status_for_a_stale_set_and_files_no_row( world, monkeypatch ):
    monkeypatch.setattr( vs.sp, "build_config", lambda: ConfigFor() )
    monkeypatch.setattr( vs, "read_stale_hours", lambda reader=None: 36.0 )
    code, status = run_main( world )
    assert code == vs.EXIT_STALE == 1 and status[ "stale" ] is True and "row" not in status


def test_the_command_exits_zero_for_a_fresh_set( world, monkeypatch ):
    monkeypatch.setattr( vs.sp, "build_config", lambda: ConfigFor() )
    monkeypatch.setattr( vs, "read_stale_hours", lambda reader=None: 36.0 )
    put_set( world, utc( 5 ) )
    code, status = run_main( world )
    assert code == vs.EXIT_FRESH == 0 and status[ "stale" ] is False


def test_the_command_takes_its_root_from_the_environment_then_the_working_folder( world, monkeypatch, tmp_path ):
    monkeypatch.setattr( vs.sp, "build_config", lambda: ConfigFor() )
    monkeypatch.setattr( vs, "read_stale_hours", lambda reader=None: 36.0 )
    seen = []
    monkeypatch.setattr( vs, "check", lambda root, now, **kw: seen.append( root ) or { "stale": False } )
    vs.main( [], environ={ "LUPIN_ROOT": "/from/env" }, now=NOON, out=io.StringIO() )
    monkeypatch.chdir( tmp_path )
    vs.main( [], environ={}, now=NOON, out=io.StringIO() )
    monkeypatch.setenv( "LUPIN_ROOT", "/from/process" )
    vs.main( [], now=NOON, out=io.StringIO() )
    assert seen == [ "/from/env", str( tmp_path ), "/from/process" ]
