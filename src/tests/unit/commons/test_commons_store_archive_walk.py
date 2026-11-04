"""
Unit tests for the CommonsStore archive walk and its early stop.

Archive days are written in the store's own on-disk format, so the real parser reads them.
"""

import shutil
from pathlib import Path

import pytest

from lupin_mcp.commons_store import (
    ENTRY_SEPARATOR, CommonsStore, _format_entry, _frontmatter_block,
)


@pytest.fixture
def store( tmp_path ):
    """A fresh store rooted in a temp directory."""
    return CommonsStore( tmp_path )


def _seed_day( store, topic, day, entries ):
    """Write archive/<day>/<topic>.md holding (ts, body) pairs; return its path."""
    day_dir = store.archive_dir / day
    day_dir.mkdir( parents=True, exist_ok=True )
    blocks = [ _format_entry( ts, "sess1234", "Clayton", "😎", "#000", body, {} ) for ts, body in entries ]
    path = day_dir / f"{topic}.md"
    path.write_text( _frontmatter_block( topic, False, "2026-07-01T00:00:00+00:00" ) + ENTRY_SEPARATOR.join( blocks ),
                     encoding="utf-8" )
    return path


def test_a_missing_archive_directory_yields_no_paths_and_read_still_answers( store ):
    """With archive/ removed, the path list is empty and read returns the active entries."""
    store.post( "notes", "live entry", "sess0001" )
    shutil.rmtree( store.archive_dir )
    assert store._archive_topic_paths( "notes", None ) == []
    assert [ e[ "body" ] for e in store.read( "notes" ) ] == [ "live entry" ]


def test_stray_files_and_days_without_the_topic_are_skipped( store ):
    """A stray file and a day lacking <topic>.md add nothing; a real day is found."""
    ( store.archive_dir / "README.txt" ).write_text( "not a day" )
    ( store.archive_dir / "2026-07-02" ).mkdir()
    wanted = _seed_day( store, "notes", "2026-07-01", [ ( "2026-07-01T10:00:00+00:00", "old" ) ] )
    assert store._archive_topic_paths( "notes", None ) == [ wanted ]


def test_a_since_after_a_day_drops_that_day_but_keeps_an_oddly_named_one( store ):
    """Ten-character day names before `since` are dropped; a malformed name is kept."""
    _seed_day( store, "notes", "2026-07-01", [ ( "2026-07-01T10:00:00+00:00", "old" ) ] )
    kept = _seed_day( store, "notes", "2026-07-05", [ ( "2026-07-05T10:00:00+00:00", "new" ) ] )
    odd  = _seed_day( store, "notes", "0000-old", [ ( "2026-07-03T10:00:00+00:00", "odd" ) ] )
    paths = store._archive_topic_paths( "notes", "2026-07-04T00:00:00+00:00" )
    assert kept in paths and odd in paths and len( paths ) == 2


def test_without_since_the_walk_stops_once_limit_entries_are_held( store, monkeypatch ):
    """limit=1, two days: the newest answers and the older file is never parsed."""
    newest = _seed_day( store, "notes", "2026-07-05", [ ( "2026-07-05T10:00:00+00:00", "newest" ) ] )
    oldest = _seed_day( store, "notes", "2026-07-01", [ ( "2026-07-01T10:00:00+00:00", "oldest" ) ] )
    parsed = []
    real   = CommonsStore._parse_topic_file
    def spy( self, path ):
        parsed.append( Path( path ) )
        return real( self, path )
    monkeypatch.setattr( CommonsStore, "_parse_topic_file", spy )
    got = store.read( "notes", limit=1 )
    assert [ e[ "body" ] for e in got ] == [ "newest" ]
    assert newest in parsed and oldest not in parsed


def test_with_since_every_kept_day_is_read_even_past_limit( store ):
    """The control for early stop: with `since` the walk reads all days the date filter kept."""
    _seed_day( store, "notes", "2026-07-05", [ ( "2026-07-05T10:00:00+00:00", "b" ) ] )
    _seed_day( store, "notes", "2026-07-04", [ ( "2026-07-04T10:00:00+00:00", "a" ) ] )
    got = store.read( "notes", since="2026-07-03T00:00:00+00:00", limit=50 )
    assert [ e[ "body" ] for e in got ] == [ "a", "b" ]
