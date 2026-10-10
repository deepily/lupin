#!/usr/bin/env python3
"""
Tests for the skeleton crew switch: how its state is read and what the refusal says.

The state is one boolean in the main configuration file. Four things are pinned, each against
the real producer.

The reader obeys true and false. A value that is present but not a clean boolean reads as on,
so the gate refuses and says why. An absent key, or a file that cannot be read, reads as off
and prints a line that starts with the gate's tag.

The refusal text names the state and tells no one how to change it.

An injected configuration manager is the caller saying what the configuration is, so the live
file must not outvote it.

The shipped file defines the key once, in the baseline block, and ships it off.

Every test reads a file in tmp_path. The live file is read in one test, only to pin what ships.
Nothing here writes to it.
"""
import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_mcp import skeleton_crew as sc
from lupin_mcp import fleet_cap_ini_io as io


COACHING = [ "raise the cap", "lupin-app.ini", "fleet size cap maximum", "ask the operator", "flip", "toggle" ]


def _ini( tmp_path, value_line ):
    path = tmp_path / "lupin-app.ini"
    path.write_text( "[Lupin: Baseline]\n" + value_line + "\n", encoding="utf-8" )
    return str( path )


class _Cfg:
    """A configuration manager that answers every get with one value and records the asks."""
    def __init__( self, value ):
        self.value = value
        self.asked = []

    def get( self, key, default=None, silent=False, return_type="string" ):
        self.asked.append( ( key, return_type ) )
        return self.value


class _RaisingCfg:
    def get( self, *args, **kwargs ):
        raise RuntimeError( "config unreadable" )


# ── 1. the reader ────────────────────────────────────────────────────────────

@pytest.mark.parametrize( "written, expected", [
    ( "true",  True ),
    ( "TRUE",  True ),
    ( "false", False ),
    ( "False", False ),
] )
def test_a_clean_boolean_is_obeyed( tmp_path, written, expected ):
    path = _ini( tmp_path, f"{sc.SKELETON_CREW_KEY}                 = {written}" )
    assert sc.read_state_from_disk( path ) is expected


@pytest.mark.parametrize( "garbled", [ "maybe", "", "2", "yes please" ] )
def test_a_present_but_garbled_value_reads_as_on( tmp_path, garbled, capsys ):
    path = _ini( tmp_path, f"{sc.SKELETON_CREW_KEY} = {garbled}" )
    assert sc.read_state_from_disk( path ) is True
    assert "[SKELETON-CREW-GATE]" in capsys.readouterr().err


def test_an_absent_key_reads_as_off_and_says_so( tmp_path, capsys ):
    path = _ini( tmp_path, "some other key = 1" )
    assert sc.read_state_from_disk( path ) is None
    err = capsys.readouterr().err
    assert "[SKELETON-CREW-GATE]" in err and "reads as OFF" in err


def test_an_unreadable_file_reads_as_off_and_says_so( tmp_path, capsys ):
    assert sc.read_state_from_disk( str( tmp_path / "missing.ini" ) ) is None
    assert "reads as OFF" in capsys.readouterr().err


def test_a_key_defined_twice_reads_as_off_and_says_so( tmp_path, capsys ):
    path = tmp_path / "lupin-app.ini"
    path.write_text( f"[a]\n{sc.SKELETON_CREW_KEY} = true\n[b]\n{sc.SKELETON_CREW_KEY} = true\n" )
    assert sc.read_state_from_disk( str( path ) ) is None
    assert "reads as OFF" in capsys.readouterr().err


def test_a_clean_read_prints_nothing( tmp_path, capsys ):
    sc.read_state_from_disk( _ini( tmp_path, f"{sc.SKELETON_CREW_KEY} = true" ) )
    assert capsys.readouterr().err == ""


def test_the_default_reader_follows_the_env_override( tmp_path, monkeypatch ):
    path = _ini( tmp_path, f"{sc.SKELETON_CREW_KEY} = true" )
    monkeypatch.setenv( sc.INI_OVERRIDE_ENV, path )
    assert sc.default_disk_skeleton_reader() is True


def test_the_default_reader_uses_the_project_file_without_the_override( monkeypatch ):
    monkeypatch.delenv( sc.INI_OVERRIDE_ENV, raising=False )
    from lupin_mcp import fleet_size_cap
    assert sc.ini_path() == fleet_size_cap.config_file_path()


# ── 2. the refusal text ──────────────────────────────────────────────────────

def test_the_refusal_is_the_approved_words_and_coaches_nothing():
    text = sc.refusal_text( "spawn" )
    assert text.startswith( "SKELETON CREW IS ON — no spawning." )
    assert "Each manager plans and implements its own work." in text
    assert "Nothing was started and nothing was terminated." in text
    lowered = text.lower()
    assert [ p for p in COACHING if p in lowered ] == []


def test_the_launcher_variant_says_launch_and_still_coaches_nothing():
    text = sc.refusal_text( "launch" )
    assert text.startswith( "SKELETON CREW IS ON — no launching." )
    assert [ p for p in COACHING if p in text.lower() ] == []


def test_an_unknown_door_is_refused_loudly():
    with pytest.raises( ValueError ):
        sc.refusal_text( "teleport" )


# ── 3. the injected-configuration boundary ───────────────────────────────────

def test_the_disk_value_wins_when_a_disk_reader_is_supplied():
    assert sc.skeleton_crew_refusal( _Cfg( False ), disk_fn=lambda: True ) == sc.refusal_text( "spawn" )
    assert sc.skeleton_crew_refusal( _Cfg( True ),  disk_fn=lambda: False ) is None


def test_a_disk_reader_that_cannot_tell_falls_back_to_the_manager():
    assert sc.skeleton_crew_refusal( _Cfg( True ),  disk_fn=lambda: None ) == sc.refusal_text( "spawn" )
    assert sc.skeleton_crew_refusal( _Cfg( False ), disk_fn=lambda: None ) is None


def test_a_disk_reader_that_raises_falls_back_to_the_manager():
    def boom():
        raise OSError( "disk" )
    assert sc.skeleton_crew_refusal( _Cfg( True ), disk_fn=boom ) == sc.refusal_text( "spawn" )


def test_the_manager_is_asked_for_a_boolean_under_the_right_key():
    cfg = _Cfg( True )
    sc.skeleton_crew_refusal( cfg )
    assert cfg.asked == [ ( sc.SKELETON_CREW_KEY, "boolean" ) ]


def test_no_manager_and_no_reader_means_off():
    assert sc.skeleton_crew_refusal( None ) is None


def test_a_manager_that_raises_means_off():
    assert sc.skeleton_crew_refusal( _RaisingCfg() ) is None


def test_the_door_argument_reaches_the_text():
    assert sc.skeleton_crew_refusal( _Cfg( True ), door="launch" ) == sc.refusal_text( "launch" )


# ── 4. the shipped file ──────────────────────────────────────────────────────

def test_the_shipped_ini_defines_the_key_once_in_baseline_and_ships_off():
    root = os.environ.get( "LUPIN_ROOT", os.getcwd() )
    path = os.path.join( root, "src", "conf", "lupin-app.ini" )
    with open( path, encoding="utf-8" ) as handle:
        lines = handle.read().split( "\n" )
    found = io.find_definitions( lines, sc.SKELETON_CREW_KEY )
    assert len( found ) == 1
    assert found[ 0 ].section == "Lupin: Baseline"
    assert io.read_value_from_disk( path, sc.SKELETON_CREW_KEY ) == "false"


def test_the_splainer_explains_the_key():
    root = os.environ.get( "LUPIN_ROOT", os.getcwd() )
    path = os.path.join( root, "src", "conf", "lupin-app-splainer.ini" )
    assert io.read_value_from_disk( path, sc.SKELETON_CREW_KEY ) is not None
