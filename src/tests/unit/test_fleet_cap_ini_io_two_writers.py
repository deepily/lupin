#!/usr/bin/env python3
"""
Tests for two writers of one configuration file, and for what the writers return.

The fleet cap writer and the skeleton crew switch writer each read the whole file, change
one line and replace it. They are safe together only if three things hold, and each is
pinned here against a break of exactly that thing.

Both writers wait on the same lock, so neither can run while the other holds it.

The file is read after the lock is held. A writer that read first would write back a stale
copy and undo whatever the other writer changed while it waited.

Each writer returns what it re-read from the file and never its argument, so a write that
did not land cannot report success.

Every test writes to tmp_path. The live configuration file is never touched.
"""
import fcntl
import os
import sys
import threading
import time

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_mcp import config_write_lock as lock
from lupin_mcp import fleet_cap_ini_io as io


CAP_KEY    = "cc session fleet size cap"
SWITCH_KEY = "cc session skeleton crew enabled"

BODY = """\
[Lupin: Baseline]
cc session fleet size cap                        = 8
cc session fleet size cap maximum                = 18
cc session skeleton crew enabled                 = false
"""

WRITERS = {
    "cap"    : lambda path: io.write_int_to_disk( path, CAP_KEY, 12 ),
    "switch" : lambda path: io.write_bool_to_disk( path, SWITCH_KEY, True ),
}


def _ini( tmp_path, body=BODY ):
    path = tmp_path / "lupin-app.ini"
    path.write_text( body, encoding="utf-8" )
    return str( path )


class _HeldLock:
    """Hold the real write lock from outside, the way a second writer would."""
    def __enter__( self ):
        os.makedirs( lock.lock_dir(), exist_ok=True )
        self.handle = open( lock.lock_path(), "w" )
        fcntl.flock( self.handle.fileno(), fcntl.LOCK_EX )
        return self

    def __exit__( self, *exc ):
        fcntl.flock( self.handle.fileno(), fcntl.LOCK_UN )
        self.handle.close()


def _start( writer, path ):
    done   = []
    worker = threading.Thread( target=lambda: ( writer( path ), done.append( True ) ) )
    worker.start()
    return worker, done


@pytest.mark.parametrize( "name", sorted( WRITERS ) )
def test_each_writer_waits_for_the_one_shared_lock( tmp_path, name ):
    path = _ini( tmp_path )
    with _HeldLock():
        worker, done = _start( WRITERS[ name ], path )
        time.sleep( 0.3 )
        assert done == [], f"the {name} writer did not wait for the shared lock"
        assert open( path, encoding="utf-8" ).read() == BODY
    worker.join( timeout=5 )
    assert done == [ True ]


@pytest.mark.parametrize( "name", sorted( WRITERS ) )
def test_a_writer_reads_the_file_after_it_holds_the_lock( tmp_path, name ):
    path = _ini( tmp_path )
    with _HeldLock():
        worker, done = _start( WRITERS[ name ], path )
        time.sleep( 0.3 )
        # While the writer waits, the other writer's change lands on a different line.
        changed = BODY.replace( "fleet size cap maximum                = 18",
                                "fleet size cap maximum                = 20" )
        open( path, "w", encoding="utf-8" ).write( changed )
    worker.join( timeout=5 )
    final = open( path, encoding="utf-8" ).read()
    assert "fleet size cap maximum                = 20" in final, "a stale copy was written back"


def test_alternating_writers_never_lose_each_others_last_value( tmp_path ):
    path   = _ini( tmp_path )
    errors = []

    def cap_writer():
        try:
            for n in range( 9, 29 ):
                io.write_int_to_disk( path, CAP_KEY, n )
        except Exception as error:
            errors.append( error )

    def switch_writer():
        try:
            for n in range( 20 ):
                io.write_bool_to_disk( path, SWITCH_KEY, n % 2 == 0 )
            io.write_bool_to_disk( path, SWITCH_KEY, True )
        except Exception as error:
            errors.append( error )

    workers = [ threading.Thread( target=cap_writer ), threading.Thread( target=switch_writer ) ]
    for worker in workers: worker.start()
    for worker in workers: worker.join( timeout=30 )
    assert errors == []
    assert io.read_int_from_disk( path, CAP_KEY ) == 28
    assert io.read_value_from_disk( path, SWITCH_KEY ) == "true"


def test_the_boolean_writer_returns_the_re_read_value_not_its_argument( tmp_path, monkeypatch ):
    path = _ini( tmp_path )
    monkeypatch.setattr( io, "_replace_value_line", lambda *a, **k: None )   # a write that never lands
    assert io.write_bool_to_disk( path, SWITCH_KEY, True ) is False


def test_the_integer_writer_returns_the_re_read_value_not_its_argument( tmp_path, monkeypatch ):
    path = _ini( tmp_path )
    monkeypatch.setattr( io, "_replace_value_line", lambda *a, **k: None )
    assert io.write_int_to_disk( path, CAP_KEY, 12 ) == 8


def test_a_key_before_any_section_header_reports_an_empty_section( tmp_path ):
    path = tmp_path / "bare.ini"
    path.write_text( f"{SWITCH_KEY} = false\n", encoding="utf-8" )
    found = io.find_definitions( path.read_text( encoding="utf-8" ).split( "\n" ), SWITCH_KEY )
    assert [ d.section for d in found ] == [ "" ]


def test_a_failed_replace_whose_cleanup_also_fails_still_raises_the_original_error( tmp_path, monkeypatch ):
    path = _ini( tmp_path )
    def refuse_replace( src, dst ):
        raise OSError( "replace failed" )
    def refuse_unlink( target ):
        raise OSError( "unlink failed" )
    monkeypatch.setattr( io.os, "replace", refuse_replace )
    monkeypatch.setattr( io.os, "unlink", refuse_unlink )
    with pytest.raises( OSError, match="replace failed" ):
        io.write_bool_to_disk( path, SWITCH_KEY, True )
    assert open( path, encoding="utf-8" ).read() == BODY
