#!/usr/bin/env python3
"""
Tests for the copies the configuration writers make on both sides of every write.

The operator's rule is that the configuration file must always be backed up with no prompt.
A copy made only before a write holds the value that was just replaced, so the newest value
would exist nowhere else. Each write therefore copies the file before the replace and again
after it. A copy that cannot be made refuses the write.

Retention keeps the newest 50 copies plus the newest copy of each day for 14 days. The folder
is on the same disk as the file, so these copies are history and not protection against
losing the disk. The last test pins that the repo backup's exclude list does not drop the file.

Every test writes to tmp_path or the run's own backup folder. The live file is never touched.
"""
import datetime
import fnmatch
import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_mcp import config_backup as cb
from lupin_mcp import fleet_cap_ini_io as io


SWITCH_KEY = "cc session skeleton crew enabled"
CAP_KEY    = "cc session fleet size cap"

BODY = """\
[Lupin: Baseline]
cc session fleet size cap                        = 8
cc session fleet size cap maximum                = 18
cc session skeleton crew enabled                 = false
"""


@pytest.fixture
def folder( tmp_path, monkeypatch ):
    target = tmp_path / "backups"
    monkeypatch.setenv( cb.BACKUP_DIR_ENV, str( target ) )
    return target


def _ini( tmp_path ):
    path = tmp_path / "lupin-app.ini"
    path.write_text( BODY, encoding="utf-8" )
    return str( path )


def _copies( folder, tag ):
    return sorted( p for p in os.listdir( folder ) if p.endswith( f".{tag}" ) )


def test_a_write_leaves_a_before_copy_with_the_old_bytes( tmp_path, folder ):
    path = _ini( tmp_path )
    io.write_bool_to_disk( path, SWITCH_KEY, True )
    before = _copies( folder, "before" )
    assert len( before ) == 1
    assert ( folder / before[ 0 ] ).read_text( encoding="utf-8" ) == BODY


def test_a_write_leaves_an_after_copy_with_the_new_bytes( tmp_path, folder ):
    path = _ini( tmp_path )
    io.write_bool_to_disk( path, SWITCH_KEY, True )
    after = _copies( folder, "after" )
    assert len( after ) == 1
    assert ( folder / after[ 0 ] ).read_text( encoding="utf-8" ) == open( path, encoding="utf-8" ).read()
    assert "skeleton crew enabled                 = true" in ( folder / after[ 0 ] ).read_text( encoding="utf-8" )


def test_the_cap_writer_is_backed_up_too( tmp_path, folder ):
    path = _ini( tmp_path )
    io.write_int_to_disk( path, CAP_KEY, 12 )
    assert len( _copies( folder, "before" ) ) == 1
    assert len( _copies( folder, "after" ) ) == 1


def test_a_refused_write_makes_no_copy( tmp_path, folder ):
    path = tmp_path / "lupin-app.ini"
    path.write_text( "[Lupin: Baseline]\nother = 1\n", encoding="utf-8" )
    with pytest.raises( io.KeyNotFound ):
        io.write_bool_to_disk( str( path ), SWITCH_KEY, True )
    assert not folder.exists() or _copies( folder, "before" ) == []


def test_a_failed_before_copy_refuses_the_write( tmp_path, folder, monkeypatch ):
    path = _ini( tmp_path )
    def refuse( source, tag, now=None ):
        raise OSError( "backup folder not writable" )
    monkeypatch.setattr( cb, "copy_config", refuse )
    with pytest.raises( OSError ):
        io.write_bool_to_disk( path, SWITCH_KEY, True )
    assert open( path, encoding="utf-8" ).read() == BODY


def test_a_failed_after_copy_raises_after_the_value_landed( tmp_path, folder, monkeypatch ):
    path  = _ini( tmp_path )
    real  = cb.copy_config
    def only_before( source, tag, now=None ):
        if tag == "after":
            raise OSError( "disk full" )
        return real( source, tag, now=now )
    monkeypatch.setattr( cb, "copy_config", only_before )
    with pytest.raises( OSError ):
        io.write_bool_to_disk( path, SWITCH_KEY, True )
    assert io.read_value_from_disk( path, SWITCH_KEY ) == "true"


def test_copy_names_sort_by_time_and_carry_the_tag( tmp_path, folder ):
    path   = _ini( tmp_path )
    first  = cb.copy_config( path, "before", now=datetime.datetime( 2026, 10, 10, 12, 0, 0, tzinfo=datetime.timezone.utc ) )
    second = cb.copy_config( path, "after",  now=datetime.datetime( 2026, 10, 10, 12, 0, 1, tzinfo=datetime.timezone.utc ) )
    assert os.path.basename( first ).endswith( ".before" )
    assert os.path.basename( second ).endswith( ".after" )
    assert os.path.basename( first ) < os.path.basename( second )
    assert os.path.basename( first ).startswith( "lupin-app.ini.20261010T120000" )


def test_an_unknown_tag_is_refused( tmp_path, folder ):
    with pytest.raises( ValueError ):
        cb.copy_config( _ini( tmp_path ), "during" )


def _fake( folder, when ):
    folder.mkdir( parents=True, exist_ok=True )
    name = f"lupin-app.ini.{when.strftime( '%Y%m%dT%H%M%S' )}000000Z.after"
    ( folder / name ).write_text( "x", encoding="utf-8" )
    return name


def test_retention_keeps_the_newest_fifty_and_one_per_day_for_fourteen_days( folder ):
    now   = datetime.datetime( 2026, 10, 20, 12, 0, 0, tzinfo=datetime.timezone.utc )
    names = []
    for minute in range( 60 ):                        # 60 copies in the last hour
        names.append( _fake( folder, now - datetime.timedelta( minutes=minute ) ) )
    for days in range( 1, 21 ):                       # two copies a day for 20 earlier days
        for hour in ( 9, 15 ):
            when = ( now - datetime.timedelta( days=days ) ).replace( hour=hour, minute=0, second=0 )
            names.append( _fake( folder, when ) )
    cb.prune( now=now )
    kept = set( os.listdir( folder ) )
    newest50 = sorted( names, reverse=True )[ :50 ]
    assert set( newest50 ) <= kept
    day_keepers = set()
    for days in range( 1, 15 ):
        day = ( now - datetime.timedelta( days=days ) ).strftime( "%Y%m%d" )
        same_day = sorted( n for n in names if n.split( "." )[ 2 ].startswith( day ) )
        day_keepers.add( same_day[ -1 ] )
    assert day_keepers <= kept
    too_old = [ n for n in names if n.split( "." )[ 2 ][ :8 ] < ( now - datetime.timedelta( days=14 ) ).strftime( "%Y%m%d" ) ]
    assert too_old and not ( set( too_old ) & kept )
    assert len( kept ) == len( newest50 ) + len( day_keepers - set( newest50 ) )


def test_prune_ignores_files_that_are_not_copies( folder ):
    folder.mkdir( parents=True )
    ( folder / cb.LOCK_FILENAME ).write_text( "", encoding="utf-8" )
    ( folder / "notes.txt" ).write_text( "keep", encoding="utf-8" )
    cb.prune()
    assert sorted( os.listdir( folder ) ) == sorted( [ cb.LOCK_FILENAME, "notes.txt" ] )


def test_prune_survives_a_missing_folder( folder ):
    cb.prune()


# ── the repo backup does not drop the file ───────────────────────────────────

def _excluded( patterns, path ):
    segments = [ s for s in path.strip( "/" ).split( "/" ) ]
    for pattern in patterns:
        anchored  = pattern.startswith( "/" )
        wanted    = [ s for s in pattern.strip( "/" ).split( "/" ) if s ]
        if not wanted:
            continue
        starts = [ 0 ] if anchored else range( len( segments ) )
        for start in starts:
            window = segments[ start : start + len( wanted ) ]
            if len( window ) < len( wanted ):
                continue
            if all( fnmatch.fnmatch( s, w ) for s, w in zip( window, wanted ) ):
                return True
    return False


def test_the_matcher_finds_a_pattern_that_would_exclude_the_file():
    assert _excluded( [ "*.ini" ], "/src/conf/lupin-app.ini" )
    assert _excluded( [ "/src/conf/" ], "/src/conf/lupin-app.ini" )
    assert _excluded( [ "lupin-app.ini" ], "/src/conf/lupin-app.ini" )
    assert not _excluded( [ "/src/conf/long-term-memory/lupin.lancedb/" ], "/src/conf/lupin-app.ini" )


def test_the_repo_backup_exclude_list_does_not_drop_the_configuration_file():
    root = os.environ.get( "LUPIN_ROOT", os.getcwd() )
    with open( os.path.join( root, "src", "scripts", "conf", "rsync-exclude.txt" ), encoding="utf-8" ) as handle:
        patterns = [ l.strip() for l in handle if l.strip() and not l.lstrip().startswith( "#" ) ]
    assert patterns, "the exclude list read as empty"
    assert not _excluded( patterns, "/src/conf/lupin-app.ini" )
