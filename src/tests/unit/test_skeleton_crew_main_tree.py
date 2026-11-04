#!/usr/bin/env python3
"""
Tests that the switch is read from the main checkout's configuration file.

A seat can run in a git worktree, and a worktree carries its own copy of the tracked
configuration file. A switch read from that copy would be a private setting that no one
flips. The reader, the writer and the launcher resolve the file through the main checkout.
One flip therefore reaches every seat.

The tests build a real repository and a real worktree in tmp_path. They point the project
root at the worktree and ask where the switch file is.
"""
import os
import subprocess
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_mcp import skeleton_crew as sc


def _git( where, *args ):
    subprocess.run( [ "git", "-C", str( where ), *args ], check=True, capture_output=True, text=True )


@pytest.fixture
def repo( tmp_path, monkeypatch ):
    main = tmp_path / "main"
    ( main / "src" / "conf" ).mkdir( parents=True )
    ( main / "src" / "conf" / "lupin-app.ini" ).write_text( "[Lupin: Baseline]\n", encoding="utf-8" )
    _git( main, "init", "-q", "-b", "main" )
    _git( main, "-c", "user.email=t@example.com", "-c", "user.name=t", "add", "." )
    _git( main, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "x" )
    monkeypatch.delenv( sc.INI_OVERRIDE_ENV, raising=False )
    return main


def test_a_seat_in_a_worktree_reads_the_main_checkouts_file( repo, tmp_path, monkeypatch ):
    tree = tmp_path / "seat-tree"
    _git( repo, "worktree", "add", "-q", "--detach", str( tree ) )
    monkeypatch.setenv( "LUPIN_ROOT", str( tree ) )
    assert sc.ini_path() == str( repo.resolve() / "src" / "conf" / "lupin-app.ini" )


def test_a_plain_checkout_reads_its_own_file( repo, monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( repo ) )
    assert sc.ini_path() == str( repo.resolve() / "src" / "conf" / "lupin-app.ini" )


def test_a_root_that_is_not_a_repository_falls_back_to_that_root( tmp_path, monkeypatch ):
    plain = tmp_path / "not-a-repo"
    ( plain / "src" / "conf" ).mkdir( parents=True )
    monkeypatch.delenv( sc.INI_OVERRIDE_ENV, raising=False )
    monkeypatch.setenv( "LUPIN_ROOT", str( plain ) )
    assert sc.ini_path() == str( plain.resolve() / "src" / "conf" / "lupin-app.ini" )


def test_the_override_wins_over_the_main_checkout( repo, tmp_path, monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( repo ) )
    monkeypatch.setenv( sc.INI_OVERRIDE_ENV, str( tmp_path / "other.ini" ) )
    assert sc.ini_path() == str( tmp_path / "other.ini" )


def test_the_route_writes_the_same_file_the_reader_reads( repo, tmp_path, monkeypatch ):
    tree = tmp_path / "seat-tree"
    _git( repo, "worktree", "add", "-q", "--detach", str( tree ) )
    monkeypatch.setenv( "LUPIN_ROOT", str( tree ) )
    ini = repo / "src" / "conf" / "lupin-app.ini"
    ini.write_text( "[Lupin: Baseline]\ncc session fleet size cap maximum = 18\n"
                    f"{sc.SKELETON_CREW_KEY} = false\n", encoding="utf-8" )
    from lupin_mcp import fleet_cap_ini_io
    fleet_cap_ini_io.write_bool_to_disk( sc.ini_path(), sc.SKELETON_CREW_KEY, True )
    assert sc.read_state_from_disk() is True
    assert "= true" in ini.read_text( encoding="utf-8" )
