"""
Unit tests for commons_archival.

Per AC10 minimum scope: 5+ tests covering 24h-cutoff split, archive-dir
creation, reserved-topic retention, rotation idempotence, daemon crash+restart.

Plus AC9 verification: test_write_failure_no_data_loss must show that on a
mid-rewrite failure, no entries are removed from the active file.

Coverage target: 100% lines/branches/functions (AC10 commons-only mandate).
"""

import os
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from lupin_mcp.commons_archival import (
    CommonsArchiver,
    _cutoff_iso,
    _entries_to_text,
    _now_iso,
    _now_utc,
    _today_str_utc,
)
from lupin_mcp.commons_store import (
    ENTRY_SEPARATOR,
    RESERVED_TOPICS,
    _format_entry,
    _frontmatter_block,
    _split_frontmatter,
)


# ---------- Test helpers ----------


def _iso( dt: datetime ) -> str:
    """Format a datetime as the same microsecond-ISO shape the store uses."""
    return dt.astimezone( timezone.utc ).isoformat( timespec="microseconds" )


def _entry( ts_iso: str, body: str = "hi", session_id: str = "sess0", persona_name: str = "Tester", persona_icon: str = "🎵", persona_color: str = "#123456" ) -> dict:
    """Build a parsed-entry dict (mirrors CommonsStore.read() output shape)."""
    return {
        "ts"                : ts_iso,
        "sender_session_id" : session_id,
        "persona_name"      : persona_name,
        "persona_icon"      : persona_icon,
        "persona_color"     : persona_color,
        "body"              : body,
        "metadata"          : { },
    }


def _seed_topic_file( commons_dir: Path, topic: str, entries: list, reserved: bool = False, created_iso: str = None ) -> Path:
    """Write a topic file with specifically-timestamped entries. Bypasses CommonsStore."""
    if created_iso is None:
        created_iso = _now_iso()
    content = _frontmatter_block( topic, reserved, created_iso )
    for e in entries:
        content += ENTRY_SEPARATOR
        content += _format_entry(
            ts            = e[ "ts" ],
            session_id    = e[ "sender_session_id" ],
            persona_name  = e[ "persona_name" ],
            persona_icon  = e[ "persona_icon" ],
            persona_color = e[ "persona_color" ],
            body          = e[ "body" ],
            metadata      = e[ "metadata" ],
        )
    path = commons_dir / f"{topic}.md"
    path.write_text( content, encoding="utf-8" )
    return path


@pytest.fixture
def archiver_root():
    """Tempdir with io/commons/ + io/commons/archive/ pre-created; archiver bound to it."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path( tmp )
        ( root / "io" / "commons" / "archive" ).mkdir( parents=True )
        yield root


@pytest.fixture
def archiver( archiver_root ):
    """A fresh CommonsArchiver bound to archiver_root."""
    return CommonsArchiver( archiver_root, interval_seconds=3600, retention_hours=24 )


# ---------- Module-level helpers ----------


def test_now_iso_format():
    """_now_iso returns ISO-8601 microsecond UTC string."""
    ts = _now_iso()
    assert "T" in ts
    assert ts.endswith( "+00:00" )


def test_now_utc_returns_aware_utc():
    """_now_utc returns timezone-aware UTC datetime."""
    now = _now_utc()
    assert now.tzinfo is not None
    assert now.utcoffset().total_seconds() == 0


def test_today_str_utc_format():
    """_today_str_utc returns yyyy-mm-dd."""
    s = _today_str_utc()
    assert len( s ) == 10
    assert s.count( "-" ) == 2
    datetime.strptime( s, "%Y-%m-%d" )   # parses cleanly


def test_cutoff_iso_offset():
    """_cutoff_iso returns ISO timestamp `hours` ago."""
    cutoff = _cutoff_iso( 24 )
    parsed = datetime.fromisoformat( cutoff )
    now    = _now_utc()
    delta  = now - parsed
    assert 23 * 3600 < delta.total_seconds() < 25 * 3600


def test_entries_to_text_round_trip():
    """_entries_to_text produces format the store's parser accepts."""
    entries = [
        _entry( _iso( _now_utc() ), body="entry-a" ),
        _entry( _iso( _now_utc() ), body="entry-b", session_id="sessB" ),
    ]
    text = _entries_to_text( "alpha", entries, reserved=False, created_iso=_now_iso() )
    fm, body = _split_frontmatter( text )
    assert fm[ "topic" ] == "alpha"
    assert fm[ "reserved" ] is False
    assert "entry-a" in body
    assert "entry-b" in body


def test_entries_to_text_empty_list():
    """Empty entries list yields frontmatter-only output (no separators)."""
    text = _entries_to_text( "alpha", [ ], reserved=False, created_iso=_now_iso() )
    assert ENTRY_SEPARATOR not in text.split( "---\n", 2 )[ -1 ]   # body section has no separators


# ---------- __init__ + lifecycle ----------


def test_archiver_init_paths( archiver_root, archiver ):
    """__init__ wires commons_dir + archive_dir + thread state."""
    assert archiver.commons_dir   == archiver_root / "io" / "commons"
    assert archiver.archive_dir   == archiver_root / "io" / "commons" / "archive"
    assert archiver.interval_seconds == 3600
    assert archiver.retention_hours  == 24
    assert archiver._thread is None
    assert not archiver._stop_event.is_set()


def test_daemon_start_stop_lifecycle( archiver_root ):
    """start() spawns daemon thread; stop() joins it cleanly."""
    a = CommonsArchiver( archiver_root, interval_seconds=10 )
    a.start()
    assert a._thread is not None
    assert a._thread.is_alive()
    a.stop( join_timeout=2.0 )
    assert not a._thread.is_alive()


def test_daemon_start_idempotent( archiver_root ):
    """Second start() on a live archiver is a no-op (same thread object)."""
    a = CommonsArchiver( archiver_root, interval_seconds=10 )
    a.start()
    first_thread = a._thread
    a.start()
    assert a._thread is first_thread
    a.stop( join_timeout=2.0 )


def test_daemon_stop_before_start_safe( archiver_root ):
    """stop() on a never-started archiver doesn't raise (covers _thread-is-None branch)."""
    a = CommonsArchiver( archiver_root )
    a.stop()   # must not raise


def test_daemon_can_be_restarted( archiver_root ):
    """start() → stop() → start() works (covers _thread-not-None-but-not-alive branch)."""
    a = CommonsArchiver( archiver_root, interval_seconds=10 )
    a.start()
    a.stop( join_timeout=2.0 )
    a.start()
    assert a._thread.is_alive()
    a.stop( join_timeout=2.0 )


# ---------- rotate_once: missing dir + empty cases ----------


def test_rotate_once_missing_commons_dir():
    """If commons_dir does not exist, rotate_once returns {} without error."""
    with tempfile.TemporaryDirectory() as tmp:
        a = CommonsArchiver( tmp )   # commons_dir intentionally not created
        # archiver's commons_dir was set at __init__; remove it to simulate absence
        if a.commons_dir.exists():
            for p in a.commons_dir.rglob( "*" ):
                if p.is_file(): p.unlink()
            a.commons_dir.rmdir()
        assert not a.commons_dir.exists()
        assert a.rotate_once() == { }


def test_rotate_once_no_aged_entries_noop( archiver_root, archiver ):
    """All entries fresh → no archive file created, active file untouched."""
    young_ts = _iso( _now_utc() - timedelta( hours=1 ) )
    _seed_topic_file( archiver.commons_dir, "alpha", [ _entry( young_ts, body="fresh" ) ] )
    original = ( archiver.commons_dir / "alpha.md" ).read_text()
    result = archiver.rotate_once()
    assert result[ "alpha" ] == ( 1, 0 )
    # No archive subdir created (only the pre-existing `archive/` dir, no yyyy-mm-dd children)
    assert not any( ( archiver.archive_dir / _today_str_utc() / "alpha.md" ).exists() for _ in [ 0 ] )
    # Active file unchanged
    assert ( archiver.commons_dir / "alpha.md" ).read_text() == original


# ---------- AC9 + AC10 minimum-scope tests ----------


def test_24h_split_cutoff( archiver_root, archiver ):
    """AC9: seed 25h/23h/1h entries → 25h goes to archive, 23h + 1h stay active."""
    now = _now_utc()
    aged_25h  = _entry( _iso( now - timedelta( hours=25 ) ), body="25h-old",   session_id="s25" )
    young_23h = _entry( _iso( now - timedelta( hours=23 ) ), body="23h-young", session_id="s23" )
    young_1h  = _entry( _iso( now - timedelta( hours=1  ) ), body="1h-young",  session_id="s1"  )
    _seed_topic_file( archiver.commons_dir, "alpha", [ aged_25h, young_23h, young_1h ] )

    result = archiver.rotate_once()
    assert result[ "alpha" ] == ( 2, 1 )   # 2 kept, 1 archived

    archive_path = archiver.archive_dir / _today_str_utc() / "alpha.md"
    assert archive_path.exists()
    arc_text = archive_path.read_text()
    assert "25h-old" in arc_text
    assert "23h-young" not in arc_text
    assert "1h-young"  not in arc_text

    active_text = ( archiver.commons_dir / "alpha.md" ).read_text()
    assert "25h-old"   not in active_text
    assert "23h-young" in active_text
    assert "1h-young"  in active_text


def test_archive_dir_yyyy_mm_dd_creation( archiver_root, archiver ):
    """AC10 test #2: archive subdir is `archive/yyyy-mm-dd/`."""
    aged = _entry( _iso( _now_utc() - timedelta( hours=30 ) ), body="aged" )
    _seed_topic_file( archiver.commons_dir, "alpha", [ aged ] )
    archiver.rotate_once()
    day_dir = archiver.archive_dir / _today_str_utc()
    assert day_dir.is_dir()
    assert ( day_dir / "alpha.md" ).is_file()


def test_reserved_topic_retention( archiver_root, archiver ):
    """AC10 test #3: reserved topics retain `reserved: true` frontmatter through rotation."""
    aged  = _entry( _iso( _now_utc() - timedelta( hours=30 ) ), body="aged",  session_id="sA" )
    young = _entry( _iso( _now_utc() - timedelta( hours=1  ) ), body="young", session_id="sB" )
    _seed_topic_file( archiver.commons_dir, "broadcast-acks", [ aged, young ], reserved=True )
    archiver.rotate_once()
    active_text = ( archiver.commons_dir / "broadcast-acks.md" ).read_text()
    fm, _ = _split_frontmatter( active_text )
    assert fm[ "reserved" ] is True
    assert fm[ "topic" ] == "broadcast-acks"

    archive_text = ( archiver.archive_dir / _today_str_utc() / "broadcast-acks.md" ).read_text()
    arc_fm, _ = _split_frontmatter( archive_text )
    assert arc_fm[ "reserved" ] is True


def test_rotation_idempotence( archiver_root, archiver ):
    """AC10 test #4: running rotation twice is no-op on the second pass."""
    aged  = _entry( _iso( _now_utc() - timedelta( hours=30 ) ), body="aged" )
    young = _entry( _iso( _now_utc() - timedelta( hours=1  ) ), body="young" )
    _seed_topic_file( archiver.commons_dir, "alpha", [ aged, young ] )

    first = archiver.rotate_once()
    after_first = ( archiver.commons_dir / "alpha.md" ).read_text()
    archive_after_first = ( archiver.archive_dir / _today_str_utc() / "alpha.md" ).read_text()

    second = archiver.rotate_once()
    after_second = ( archiver.commons_dir / "alpha.md" ).read_text()
    archive_after_second = ( archiver.archive_dir / _today_str_utc() / "alpha.md" ).read_text()

    assert first[ "alpha" ]  == ( 1, 1 )
    assert second[ "alpha" ] == ( 1, 0 )   # nothing left to archive
    assert after_first       == after_second
    assert archive_after_first == archive_after_second


def test_write_failure_no_data_loss( archiver_root, archiver ):
    """AC9 + AC10 test #5: mid-rewrite OSError leaves the active file intact."""
    aged  = _entry( _iso( _now_utc() - timedelta( hours=30 ) ), body="aged",  session_id="sA" )
    young = _entry( _iso( _now_utc() - timedelta( hours=1  ) ), body="young", session_id="sB" )
    _seed_topic_file( archiver.commons_dir, "alpha", [ aged, young ] )
    original_active = ( archiver.commons_dir / "alpha.md" ).read_text()

    # os.replace is the atomic-commit step inside _atomic_rewrite.
    with patch( "lupin_mcp.commons_archival.os.replace", side_effect=OSError( "disk full" ) ):
        with pytest.raises( OSError, match="disk full" ):
            archiver.rotate_once()

    # Active file must be untouched (still contains both entries).
    assert ( archiver.commons_dir / "alpha.md" ).read_text() == original_active
    assert "aged"  in original_active
    assert "young" in original_active
    # No tempfiles left lying around in commons_dir
    leftover_tmps = list( archiver.commons_dir.glob( ".*alpha.md.*.tmp" ) )
    assert leftover_tmps == [ ]


# ---------- Edge-case branches for 100% coverage ----------


def test_multiple_rotations_same_day_append( archiver_root, archiver ):
    """Two rotations on the same day → both batches accumulate in same archive file."""
    now = _now_utc()
    _seed_topic_file( archiver.commons_dir, "alpha", [ _entry( _iso( now - timedelta( hours=30 ) ), body="aged-A" ) ] )
    archiver.rotate_once()
    # Append a second aged entry to active and rotate again
    aged_b = _entry( _iso( now - timedelta( hours=31 ) ), body="aged-B" )
    active_path = archiver.commons_dir / "alpha.md"
    # Re-seed with fresh frontmatter + new aged entry
    _seed_topic_file( archiver.commons_dir, "alpha", [ aged_b ] )
    archiver.rotate_once()

    archive_text = ( archiver.archive_dir / _today_str_utc() / "alpha.md" ).read_text()
    assert "aged-A" in archive_text
    assert "aged-B" in archive_text


def test_skips_malformed_entry_blocks( archiver_root, archiver ):
    """Malformed entry blocks are skipped (covers `if entry is None: continue`)."""
    now = _now_utc()
    aged = _entry( _iso( now - timedelta( hours=30 ) ), body="aged" )
    path = _seed_topic_file( archiver.commons_dir, "alpha", [ aged ] )
    # Append a malformed block at the end (no header line)
    with path.open( "a", encoding="utf-8" ) as f:
        f.write( ENTRY_SEPARATOR )
        f.write( "this is not a valid entry header\n" )
    result = archiver.rotate_once()
    assert result[ "alpha" ] == ( 0, 1 )   # malformed block silently skipped


def test_missing_frontmatter_created_falls_back_to_now( archiver_root, archiver ):
    """Topic file with no `created` in frontmatter → archiver substitutes _now_iso()."""
    now  = _now_utc()
    aged = _entry( _iso( now - timedelta( hours=30 ) ), body="aged"  )
    yng  = _entry( _iso( now - timedelta( hours=1 )  ), body="young" )
    path = archiver.commons_dir / "alpha.md"
    # Hand-build content WITHOUT a frontmatter block at all
    content = ENTRY_SEPARATOR + _format_entry(
        ts=aged[ "ts" ], session_id=aged[ "sender_session_id" ],
        persona_name=aged[ "persona_name" ], persona_icon=aged[ "persona_icon" ],
        persona_color=aged[ "persona_color" ], body=aged[ "body" ], metadata=aged[ "metadata" ],
    ) + ENTRY_SEPARATOR + _format_entry(
        ts=yng[ "ts" ], session_id=yng[ "sender_session_id" ],
        persona_name=yng[ "persona_name" ], persona_icon=yng[ "persona_icon" ],
        persona_color=yng[ "persona_color" ], body=yng[ "body" ], metadata=yng[ "metadata" ],
    )
    path.write_text( content, encoding="utf-8" )
    result = archiver.rotate_once()
    assert result[ "alpha" ] == ( 1, 1 )
    new_text = path.read_text()
    fm, _ = _split_frontmatter( new_text )
    assert "created" in fm   # archiver synthesized a new `created` value


def test_atomic_rewrite_cleanup_on_failure( archiver_root, archiver ):
    """_atomic_rewrite removes the sibling tempfile when os.replace fails."""
    topic_path = archiver.commons_dir / "alpha.md"
    topic_path.write_text( "original\n", encoding="utf-8" )

    with patch( "lupin_mcp.commons_archival.os.replace", side_effect=OSError( "boom" ) ):
        with pytest.raises( OSError, match="boom" ):
            archiver._atomic_rewrite( topic_path, "new content" )

    leftover_tmps = list( archiver.commons_dir.glob( ".*alpha.md.*.tmp" ) )
    assert leftover_tmps == [ ]
    assert topic_path.read_text() == "original\n"


def test_atomic_rewrite_cleanup_tolerates_unlink_failure( archiver_root, archiver ):
    """When os.unlink ALSO fails inside the cleanup block, the original exception still propagates."""
    topic_path = archiver.commons_dir / "alpha.md"
    topic_path.write_text( "original\n", encoding="utf-8" )

    with patch( "lupin_mcp.commons_archival.os.replace", side_effect=OSError( "replace-boom" ) ):
        with patch( "lupin_mcp.commons_archival.os.unlink", side_effect=OSError( "unlink-boom" ) ):
            with pytest.raises( OSError, match="replace-boom" ):
                archiver._atomic_rewrite( topic_path, "new content" )


# ---------- Daemon loop coverage ----------


def test_run_loop_swallows_exceptions_and_continues( archiver_root ):
    """If rotate_once raises, the daemon loop catches + retries on the next tick."""
    a = CommonsArchiver( archiver_root, interval_seconds=1, debug=True )
    call_count = { "n": 0 }
    real_stop  = a._stop_event

    def flaky_rotate():
        call_count[ "n" ] += 1
        if call_count[ "n" ] == 1:
            raise RuntimeError( "transient" )
        # After surviving the first exception, signal the loop to stop
        real_stop.set()

    a.interval_seconds = 0.05   # speed up loop ticks
    with patch.object( a, "rotate_once", side_effect=flaky_rotate ):
        a.start()
        a._thread.join( timeout=3.0 )
    assert call_count[ "n" ] >= 2   # loop survived the exception


def test_run_loop_normal_iteration_increments( archiver_root ):
    """Daemon loop calls rotate_once at least once before stop."""
    a = CommonsArchiver( archiver_root, interval_seconds=1, verbose=True )
    a.interval_seconds = 0.05
    call_count = { "n": 0 }

    def count_and_stop():
        call_count[ "n" ] += 1
        a._stop_event.set()
        return { }

    with patch.object( a, "rotate_once", side_effect=count_and_stop ):
        a.start()
        a._thread.join( timeout=3.0 )
    assert call_count[ "n" ] >= 1


def test_rotate_once_verbose_prints( archiver_root, capsys ):
    """verbose=True path prints per-topic kept/archived counts."""
    a = CommonsArchiver( archiver_root, verbose=True )
    aged = _entry( _iso( _now_utc() - timedelta( hours=30 ) ), body="aged" )
    _seed_topic_file( a.commons_dir, "alpha", [ aged ] )
    a.rotate_once()
    captured = capsys.readouterr()
    assert "alpha" in captured.out
    assert "kept=" in captured.out
