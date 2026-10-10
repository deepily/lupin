"""
The fleet cap is read from the main checkout's configuration file.

The function `config_file_path()` joined `LUPIN_ROOT` and the source path, with no step for a worktree.
A process pinned to a seat tree therefore read that tree's tracked copy, which holds the committed cap.
The panel writes the main checkout's file. On the host the two files held 15 and 17.
The switch's `ini_path()` already asked git for the main checkout. These tests pin that the cap does the same.

Venue: :7999 (unit, a throwaway git repository with a real worktree, no server).
"""

import os
import subprocess

import pytest

from lupin_mcp import fleet_size_cap, skeleton_crew

BODY = "[Lupin: Development]\ncc session fleet size cap                        = {cap}\ncc session fleet size cap maximum                = 18\n"


def _git( root, *args ):
    return subprocess.run( [ "git", "-C", str( root ), *args ], capture_output=True, text=True, check=True ).stdout


@pytest.fixture
def trees( tmp_path, monkeypatch ):
    """A main checkout holding cap 17 on disk and a worktree whose tracked copy holds 15."""
    main = tmp_path / "main"
    ( main / "src" / "conf" ).mkdir( parents=True )
    ini = main / "src" / "conf" / "lupin-app.ini"
    ini.write_text( BODY.format( cap=15 ) )
    _git( main, "init", "-q" )
    _git( main, "config", "user.email", "t@example.com" )
    _git( main, "config", "user.name", "t" )
    _git( main, "add", "src/conf/lupin-app.ini" )
    _git( main, "commit", "-q", "-m", "committed cap 15" )
    seat = tmp_path / "seat"
    _git( main, "worktree", "add", "-q", "--detach", str( seat ) )
    ini.write_text( BODY.format( cap=17 ) )
    monkeypatch.delenv( skeleton_crew.INI_OVERRIDE_ENV, raising=False )
    return main, seat


def test_in_a_worktree_the_cap_file_is_the_main_checkouts_file( trees, monkeypatch ):
    main, seat = trees
    monkeypatch.setenv( "LUPIN_ROOT", str( seat ) )
    assert os.path.realpath( fleet_size_cap.config_file_path() ) == os.path.realpath( main / "src" / "conf" / "lupin-app.ini" )


def test_the_cap_file_and_the_switch_file_are_one_file_in_a_worktree( trees, monkeypatch ):
    _, seat = trees
    monkeypatch.setenv( "LUPIN_ROOT", str( seat ) )
    assert fleet_size_cap.config_file_path() == skeleton_crew.ini_path()


def test_the_fresh_cap_read_in_a_worktree_sees_the_value_the_panel_wrote( trees, monkeypatch ):
    _, seat = trees
    monkeypatch.setenv( "LUPIN_ROOT", str( seat ) )
    assert ( seat / "src" / "conf" / "lupin-app.ini" ).read_text() == BODY.format( cap=15 )
    assert fleet_size_cap.default_disk_cap_reader() == 17


def test_in_the_main_checkout_nothing_moves( trees, monkeypatch ):
    main, _ = trees
    monkeypatch.setenv( "LUPIN_ROOT", str( main ) )
    assert os.path.realpath( fleet_size_cap.config_file_path() ) == os.path.realpath( main / "src" / "conf" / "lupin-app.ini" )
    assert fleet_size_cap.default_disk_cap_reader() == 17


def test_outside_a_repository_the_path_is_the_root_plus_the_source_path( tmp_path, monkeypatch ):
    ( tmp_path / "src" / "conf" ).mkdir( parents=True )
    ( tmp_path / "src" / "conf" / "lupin-app.ini" ).write_text( BODY.format( cap=9 ) )
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
    monkeypatch.delenv( skeleton_crew.INI_OVERRIDE_ENV, raising=False )
    assert fleet_size_cap.config_file_path() == str( tmp_path / "src" / "conf" / "lupin-app.ini" )
    assert fleet_size_cap.default_disk_cap_reader() == 9


def test_the_switch_override_still_wins_for_the_switch_and_does_not_move_the_cap( trees, monkeypatch, tmp_path ):
    main, seat = trees
    override = tmp_path / "switch-only.ini"
    override.write_text( "[Lupin: Baseline]\ncc session skeleton crew enabled = false\n" )
    monkeypatch.setenv( "LUPIN_ROOT", str( seat ) )
    monkeypatch.setenv( skeleton_crew.INI_OVERRIDE_ENV, str( override ) )
    assert skeleton_crew.ini_path() == str( override )
    assert os.path.realpath( fleet_size_cap.config_file_path() ) == os.path.realpath( main / "src" / "conf" / "lupin-app.ini" )


def test_one_function_names_the_main_checkouts_file_for_both_readers( trees, monkeypatch ):
    main, seat = trees
    monkeypatch.setenv( "LUPIN_ROOT", str( seat ) )
    named = fleet_size_cap.main_checkout_ini_path()
    assert os.path.realpath( named ) == os.path.realpath( main / "src" / "conf" / "lupin-app.ini" )
    assert fleet_size_cap.config_file_path() == named == skeleton_crew.ini_path()
