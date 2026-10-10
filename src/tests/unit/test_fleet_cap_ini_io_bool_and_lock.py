#!/usr/bin/env python3
"""
Tests for the boolean write and the write lock in the configuration file writer.

The skeleton crew switch is a boolean on one line of the main configuration file. It uses the
same one-line writer as the fleet cap, so these tests pin two things the cap writer lacked.

The boolean write keeps the column alignment and every other byte, refuses a missing or
duplicated key, and returns what it re-read from the file.

Both writers take one lock before they read the file, so two near-simultaneous writes cannot
lose one of them. The lock is held in the test from outside, and the writer must wait for it.

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

from lupin_mcp import fleet_cap_ini_io as io
from lupin_mcp import config_backup as cb


CAP_KEY    = "cc session fleet size cap"
SWITCH_KEY = "cc session skeleton crew enabled"

WELL_FORMED = """\
[Lupin: Baseline]
# The switch is `cc session skeleton crew enabled`, set here and not in code.
cc session fleet size cap                        = 8
cc session fleet size cap maximum                = 18
cc session skeleton crew enabled                 = false
cc session spawn write memento default           = true
"""


def _ini( tmp_path, body=WELL_FORMED ):
    path = tmp_path / "lupin-app.ini"
    path.write_text( body, encoding="utf-8" )
    return str( path )


def test_a_boolean_write_changes_only_the_value( tmp_path ):
    path = _ini( tmp_path )
    assert io.write_bool_to_disk( path, SWITCH_KEY, True ) is True
    expected = WELL_FORMED.replace(
        "cc session skeleton crew enabled                 = false",
        "cc session skeleton crew enabled                 = true" )
    assert open( path, encoding="utf-8" ).read() == expected


def test_a_boolean_write_back_to_false_round_trips( tmp_path ):
    path = _ini( tmp_path )
    io.write_bool_to_disk( path, SWITCH_KEY, True )
    assert io.write_bool_to_disk( path, SWITCH_KEY, False ) is False
    assert open( path, encoding="utf-8" ).read() == WELL_FORMED


def test_a_boolean_write_refuses_a_missing_key( tmp_path ):
    path = _ini( tmp_path, "[Lupin: Baseline]\nother = 1\n" )
    with pytest.raises( io.KeyNotFound ):
        io.write_bool_to_disk( path, SWITCH_KEY, True )
    assert open( path, encoding="utf-8" ).read() == "[Lupin: Baseline]\nother = 1\n"


def test_a_boolean_write_refuses_a_duplicated_key( tmp_path ):
    body = WELL_FORMED + "[Lupin: Testing]\ncc session skeleton crew enabled = false\n"
    path = _ini( tmp_path, body )
    with pytest.raises( io.KeyDefinedTwice ):
        io.write_bool_to_disk( path, SWITCH_KEY, True )
    assert open( path, encoding="utf-8" ).read() == body


def test_a_boolean_write_that_cannot_be_read_back_raises( tmp_path, monkeypatch ):
    path = _ini( tmp_path )
    monkeypatch.setattr( io, "read_value_from_disk", lambda p, k: None )
    with pytest.raises( io.KeyNotFound ):
        io.write_bool_to_disk( path, SWITCH_KEY, True )


def test_an_integer_write_still_returns_the_re_read_integer( tmp_path ):
    path = _ini( tmp_path )
    assert io.write_int_to_disk( path, CAP_KEY, 12 ) == 12


def test_an_integer_write_that_cannot_be_read_back_raises( tmp_path, monkeypatch ):
    path = _ini( tmp_path )
    monkeypatch.setattr( io, "read_int_from_disk", lambda p, k: None )
    with pytest.raises( io.KeyNotFound ):
        io.write_int_to_disk( path, CAP_KEY, 12 )


def test_a_failed_replace_leaves_no_temp_file_and_the_file_unchanged( tmp_path, monkeypatch ):
    path = _ini( tmp_path )
    def boom( src, dst ):
        raise OSError( "disk full" )
    monkeypatch.setattr( io.os, "replace", boom )
    with pytest.raises( OSError ):
        io.write_bool_to_disk( path, SWITCH_KEY, True )
    assert open( path, encoding="utf-8" ).read() == WELL_FORMED
    assert [ p.name for p in tmp_path.iterdir() ] == [ "lupin-app.ini" ]


def test_the_writer_waits_for_the_lock_and_then_writes( tmp_path ):
    path = _ini( tmp_path )
    os.makedirs( cb.backup_dir(), exist_ok=True )
    holder = open( cb.lock_path(), "w" )
    fcntl.flock( holder.fileno(), fcntl.LOCK_EX )
    finished = []

    def write():
        io.write_bool_to_disk( path, SWITCH_KEY, True )
        finished.append( True )

    worker = threading.Thread( target=write )
    worker.start()
    time.sleep( 0.3 )
    waited = not finished
    unchanged = open( path, encoding="utf-8" ).read() == WELL_FORMED
    fcntl.flock( holder.fileno(), fcntl.LOCK_UN )
    holder.close()
    worker.join( timeout=5 )
    assert waited, "the writer did not wait for the lock"
    assert unchanged
    assert finished == [ True ]
    assert io.read_value_from_disk( path, SWITCH_KEY ) == "true"


def test_a_lock_that_cannot_be_created_refuses_the_write( tmp_path, monkeypatch ):
    path = _ini( tmp_path )
    blocker = tmp_path / "not-a-folder"
    blocker.write_text( "x", encoding="utf-8" )
    monkeypatch.setenv( cb.BACKUP_DIR_ENV, str( blocker / "inside" ) )
    with pytest.raises( OSError ):
        io.write_bool_to_disk( path, SWITCH_KEY, True )
    assert open( path, encoding="utf-8" ).read() == WELL_FORMED


def test_the_lock_lives_in_the_backup_folder_not_beside_the_configuration_file( tmp_path ):
    assert os.path.dirname( cb.lock_path() ) == cb.backup_dir()
    assert os.path.basename( cb.lock_path() ) == cb.LOCK_FILENAME


def test_the_backup_folder_follows_the_env_override( tmp_path, monkeypatch ):
    monkeypatch.setenv( cb.BACKUP_DIR_ENV, str( tmp_path / "x" ) )
    assert cb.backup_dir() == str( tmp_path / "x" )


def test_the_backup_folder_in_a_container_is_inside_the_flow_ratio_mount( tmp_path, monkeypatch ):
    monkeypatch.delenv( cb.BACKUP_DIR_ENV, raising=False )
    monkeypatch.setenv( "LUPIN_FLOW_RATIO_DIR", str( tmp_path / "flow" ) )
    assert cb.backup_dir() == str( tmp_path / "flow" / "config-backups" )


def test_the_backup_folder_on_the_host_is_under_the_fleet_data_root( monkeypatch ):
    monkeypatch.delenv( cb.BACKUP_DIR_ENV, raising=False )
    monkeypatch.delenv( "LUPIN_FLOW_RATIO_DIR", raising=False )
    from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root
    assert cb.backup_dir() == os.path.join( str( fleet_data_root() ), "flow-ratio", "config-backups" )
