"""
Unit tests for the orphaned-DM-buffer reporter (row 298af249).

The loss this makes visible: a message the server accepted, persisted, pushed and
the listener buffered — for a session that ended before any hook drained it.
Nobody is told. The sender already has `dispatched: true`; the recipient never
existed long enough to notice an absence. Measured 2026-08-30: 45 buffer files
holding 67 such messages, oldest last written 2026-07-02.

🔴 THE TEST THAT MATTERS MOST HERE IS THE LIVE-SESSION CONTROL. The first cut of
`is_session_live` tested for the PRESENCE of a spawn-lock, which is an empty file
that outlives the session that wrote it — 44 of 45 dead sessions still had one, so
the check could only ever answer "live" and the reporter announced 1 orphan against
a true 67. A clean report from an instrument that cannot fail is worth nothing, so
these tests hold the check to answering BOTH ways.
"""

import importlib.util
import json
import os
from pathlib import Path

import pytest

import cosa.utils.util as cu


def _load_module():
    """Load the script by path — src/scripts is not an importable package."""
    path = Path( cu.get_project_root() ) / "src" / "scripts" / "report-orphaned-dm-buffers.py"
    spec = importlib.util.spec_from_file_location( "report_orphaned_dm_buffers", path )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )
    return mod


rob = _load_module()


NOW = 1_000_000.0


def _write_buffer( d, session_hash, bodies, age_hours=48.0, persona="Tiberius" ):
    p = d / f"cc-buffer-{session_hash}.jsonl"
    p.write_text( "\n".join(
        json.dumps( { "message": b, "sender_persona": persona } ) for b in bodies
    ) + "\n" )
    stamp = NOW - age_hours * 3600.0
    os.utime( p, ( stamp, stamp ) )
    return p


def _mark_live( d, session_hash, age_seconds=10.0 ):
    """Touch the listener log the way a running seat does."""
    p = d / f"cc-listener-{session_hash}.log"
    p.write_text( "running\n" )
    stamp = NOW - age_seconds
    os.utime( p, ( stamp, stamp ) )
    return p


# ── the liveness check, both directions ──────────────────────────────────────

def test_a_session_whose_listener_log_is_fresh_is_live( tmp_path ):
    _mark_live( tmp_path, "aaaaaaaa", age_seconds=5.0 )
    assert rob.is_session_live( "aaaaaaaa", tmp_path, now=NOW ) is True


def test_a_session_whose_spawn_bridge_is_fresh_is_live( tmp_path ):
    """Two file shapes because neither alone covers every seat."""
    p = tmp_path / "spawned-bbbbbbbb-full-id.json"
    p.write_text( "{}" )
    os.utime( p, ( NOW - 5.0, NOW - 5.0 ) )
    assert rob.is_session_live( "bbbbbbbb", tmp_path, now=NOW ) is True


def test_a_session_with_only_STALE_files_is_not_live( tmp_path ):
    """Freshness, not presence — this is the exact distinction the first cut missed."""
    _mark_live( tmp_path, "cccccccc", age_seconds=rob.LIVE_THRESHOLD_SECONDS + 60 )
    assert rob.is_session_live( "cccccccc", tmp_path, now=NOW ) is False


def test_a_spawn_lock_alone_does_NOT_make_a_session_live( tmp_path ):
    """
    The regression control for the defect that shipped. A spawn-lock is empty,
    carries no pid, and survives its session; 44 of 45 dead sessions had one.
    Presence of that file must never count as liveness again.
    """
    ( tmp_path / "cc-listener-dddddddd.spawn-lock" ).write_text( "" )
    assert rob.is_session_live( "dddddddd", tmp_path, now=NOW ) is False


def test_a_session_with_no_files_at_all_is_not_live( tmp_path ):
    assert rob.is_session_live( "eeeeeeee", tmp_path, now=NOW ) is False


def test_the_clock_is_read_when_no_now_is_supplied( tmp_path ):
    """Covers the `now is None` branch against the real clock."""
    _mark_live( tmp_path, "ffffffff", age_seconds=0.0 )
    os.utime( tmp_path / "cc-listener-ffffffff.log", None )
    assert rob.is_session_live( "ffffffff", tmp_path ) is True


# ── collect_orphans ──────────────────────────────────────────────────────────

def test_a_dead_sessions_buffer_is_reported( tmp_path ):
    _write_buffer( tmp_path, "11111111", [ "approval one", "approval two" ] )
    orphans = rob.collect_orphans( session_dir=tmp_path, now_fn=lambda: NOW )
    assert len( orphans ) == 1
    assert orphans[ 0 ][ "messages" ] == 2
    assert orphans[ 0 ][ "session" ]  == "11111111"


def test_a_LIVE_sessions_buffer_is_excluded( tmp_path ):
    """
    The control. Mail waiting for a running seat's next turn is the mechanism
    working, not a loss — counting it would make the report cry wolf every time
    anyone was mid-task.
    """
    _write_buffer( tmp_path, "22222222", [ "in flight" ] )
    _mark_live( tmp_path, "22222222" )
    assert rob.collect_orphans( session_dir=tmp_path, now_fn=lambda: NOW ) == []


def test_an_empty_buffer_file_is_not_an_orphan( tmp_path ):
    """Nothing is stranded in it; counting it would inflate the loss."""
    p = tmp_path / "cc-buffer-33333333.jsonl"
    p.write_text( "" )
    os.utime( p, ( NOW - 99999, NOW - 99999 ) )
    assert rob.collect_orphans( session_dir=tmp_path, now_fn=lambda: NOW ) == []


def test_min_age_hours_filters_recent_buffers( tmp_path ):
    _write_buffer( tmp_path, "44444444", [ "recent" ], age_hours=1.0 )
    assert rob.collect_orphans( session_dir=tmp_path, min_age_hours=24.0, now_fn=lambda: NOW ) == []
    assert len( rob.collect_orphans( session_dir=tmp_path, min_age_hours=0.5, now_fn=lambda: NOW ) ) == 1


def test_a_missing_directory_yields_nothing_rather_than_raising( tmp_path ):
    assert rob.collect_orphans( session_dir=tmp_path / "nope", now_fn=lambda: NOW ) == []


def test_distinct_senders_are_reported_so_an_owner_is_findable( tmp_path ):
    p = tmp_path / "cc-buffer-55555555.jsonl"
    p.write_text(
        json.dumps( { "message": "a", "sender_persona": "Krishna" } ) + "\n"
        + json.dumps( { "message": "b", "sender_persona": "maya" } ) + "\n"
        + json.dumps( { "message": "c" } ) + "\n"
    )
    os.utime( p, ( NOW - 7200, NOW - 7200 ) )
    orphans = rob.collect_orphans( session_dir=tmp_path, now_fn=lambda: NOW )
    assert orphans[ 0 ][ "senders" ] == [ "Krishna", "maya", "unknown" ]


def test_orphans_are_ordered_youngest_first( tmp_path ):
    _write_buffer( tmp_path, "66666666", [ "old" ],   age_hours=100.0 )
    _write_buffer( tmp_path, "77777777", [ "young" ], age_hours=2.0 )
    ages = [ o[ "age_hours" ] for o in rob.collect_orphans( session_dir=tmp_path, now_fn=lambda: NOW ) ]
    assert ages == sorted( ages )


# ── read_buffer ──────────────────────────────────────────────────────────────

def test_a_malformed_line_is_skipped_not_fatal( tmp_path ):
    """One bad line must not hide the readable messages beside it."""
    p = tmp_path / "cc-buffer-88888888.jsonl"
    p.write_text( '{"message": "good"}\nNOT JSON\n\n{"message": "also good"}\n' )
    assert [ e[ "message" ] for e in rob.read_buffer( p ) ] == [ "good", "also good" ]


def test_an_unreadable_file_reads_as_empty( tmp_path ):
    assert rob.read_buffer( tmp_path / "does-not-exist.jsonl" ) == []


# ── format_report ────────────────────────────────────────────────────────────

def test_the_all_clear_is_explicit_never_blank():
    """Silence and success must not look alike."""
    out = rob.format_report( [] )
    assert out.strip() != ""
    assert "No orphaned DM buffers" in out


def test_the_report_leads_with_the_MESSAGE_count_not_the_file_count():
    """
    The file count understates the loss. The number that decides anything is how
    many messages nobody will read.
    """
    orphans = [
        { "session": "aaaa1111", "path": "p", "messages": 40, "age_hours": 3.0, "senders": [ "x" ] },
        { "session": "bbbb2222", "path": "p", "messages": 27, "age_hours": 9.0, "senders": [ "y" ] },
    ]
    first = rob.format_report( orphans ).splitlines()[ 0 ]
    assert "67" in first
    assert "2 dead session" in first


def test_the_report_says_the_sender_was_told_it_succeeded():
    """The whole point of the row: the failure is invisible at both ends."""
    orphans = [ { "session": "a", "path": "p", "messages": 1, "age_hours": 1.0, "senders": [ "x" ] } ]
    assert "told the send succeeded" in rob.format_report( orphans )


# ── main ─────────────────────────────────────────────────────────────────────

def test_exit_0_when_nothing_is_orphaned( tmp_path, capsys ):
    assert rob.main( [ "--session-dir", str( tmp_path ) ] ) == 0
    assert "No orphaned DM buffers" in capsys.readouterr().out


def test_exit_1_when_something_is_orphaned( tmp_path, capsys ):
    """A non-zero exit so a scheduled run can page somebody."""
    _write_buffer( tmp_path, "99999999", [ "stranded" ] )
    assert rob.main( [ "--session-dir", str( tmp_path ) ] ) == 1
    assert "never delivered" in capsys.readouterr().out


def test_json_mode_emits_parseable_records( tmp_path, capsys ):
    _write_buffer( tmp_path, "aaaa0000", [ "one", "two" ] )
    assert rob.main( [ "--session-dir", str( tmp_path ), "--json" ] ) == 1
    records = json.loads( capsys.readouterr().out )
    assert records[ 0 ][ "messages" ] == 2


def test_min_age_hours_reaches_main( tmp_path, capsys ):
    """
    `main` reads the REAL clock — it takes no now_fn — so this fixture must use a
    real mtime rather than the frozen NOW the other tests inject. Writing the file
    and leaving its timestamp alone makes it seconds old, which 999 hours excludes.
    """
    p = tmp_path / "cc-buffer-bbbb0000.jsonl"
    p.write_text( json.dumps( { "message": "recent", "sender_persona": "Tiberius" } ) + "\n" )
    assert rob.main( [ "--session-dir", str( tmp_path ), "--min-age-hours", "999" ] ) == 0
    assert "No orphaned DM buffers" in capsys.readouterr().out


# ── the defensive arms, exercised rather than pragma'd ───────────────────────

def test_a_directory_that_raises_on_glob_reads_as_not_live():
    """
    `is_session_live` must never take the caller down. A session directory that
    errors mid-scan is unknowable, and unknowable is NOT live — reporting it as
    live would hide a real orphan behind an I/O fault.
    """
    class _Exploding:
        def glob( self, pattern ):
            raise OSError( "scan failed" )

    assert rob.is_session_live( "aaaa9999", _Exploding(), now=NOW ) is False


def test_a_buffer_whose_mtime_cannot_be_read_is_skipped_not_fatal( tmp_path, monkeypatch ):
    """
    A file that vanishes between the glob and the stat must not abort the sweep —
    the remaining buffers still need reporting, and a crash here would leave every
    orphan unreported because one file raced.
    """
    _write_buffer( tmp_path, "cccc9999", [ "stranded" ] )

    def _boom( _path ):
        raise OSError( "vanished" )

    monkeypatch.setattr( rob.os.path, "getmtime", _boom )
    assert rob.collect_orphans( session_dir=tmp_path, now_fn=lambda: NOW ) == []
