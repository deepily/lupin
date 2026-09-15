#!/usr/bin/env python3
"""
The Sword of Damocles switch — Rick's runtime on/off for "a promote request must name a
ticket of yours to delete" (row ab8c5728, ruling 2026-09-14 ~22:32 EDT: "you will make it
runtime configurable so I can turn it on or off as I see fit").

Plan: src/rnd/2026.09.14-sword-of-damocles-enforcement-plan.md §3.1. The switch rides the
existing approval-settings door, so these arms prove the reader, the writer and the
settings read-out each know the new key.
"""
import json
import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import cosa.rest.task_approval_settings as approval

KEY = "sword_of_damocles_active"


@pytest.fixture
def override( tmp_path, monkeypatch ):
    """The override file inside tmp_path, never the live fleet file."""
    target = tmp_path / "task-approval-settings.json"
    monkeypatch.setattr( approval, "override_path", lambda: str( target ) )
    monkeypatch.setattr( approval, "_cache_mtime", None )
    return target


def _no_overrides():
    """Every override key present and None, the shape `_read_overrides` promises."""
    return { key: None for key in approval.WRITABLE_KEYS }


# ── the reader ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize( "raw,expected", [ ( True, True ), ( False, False ),
                                            ( "false", False ), ( " ON ", True ) ] )
def test_the_OVERRIDE_decides_when_it_parses( monkeypatch, raw, expected ):
    monkeypatch.setattr( approval, "_read_overrides", lambda: { **_no_overrides(), KEY: raw } )
    monkeypatch.setattr( approval, "_ini_value", lambda *a, **k: "true" if not expected else "false" )
    assert approval.get_sword_of_damocles_active() is expected


def test_an_UNPARSEABLE_override_falls_through_to_the_INI( monkeypatch ):
    """"banana" is not a decision, so it must not make one."""
    monkeypatch.setattr( approval, "_read_overrides", lambda: { **_no_overrides(), KEY: "banana" } )
    monkeypatch.setattr( approval, "_ini_value", lambda *a, **k: "true" )
    assert approval.get_sword_of_damocles_active() is True


def test_the_INI_decides_when_there_is_no_override( monkeypatch ):
    monkeypatch.setattr( approval, "_read_overrides", _no_overrides )
    monkeypatch.setattr( approval, "_ini_value", lambda *a, **k: "false" )
    assert approval.get_sword_of_damocles_active() is False


def test_NO_override_and_NO_INI_falls_back_to_the_constant( monkeypatch ):
    monkeypatch.setattr( approval, "_read_overrides", _no_overrides )
    monkeypatch.setattr( approval, "_ini_value", lambda *a, **k: None )
    assert approval.get_sword_of_damocles_active() is approval.FALLBACK_SWORD_OF_DAMOCLES_ACTIVE
    assert approval.FALLBACK_SWORD_OF_DAMOCLES_ACTIVE is False


def test_the_reader_reads_the_file_the_writer_writes( override ):
    """Round trip through the real file — the key is in `_read_overrides`' projection."""
    override.write_text( json.dumps( { KEY: True } ) )
    assert approval._read_overrides()[ KEY ] is True


def test_a_MISSING_or_CORRUPT_file_projects_the_key_as_None( override ):
    assert approval._read_overrides()[ KEY ] is None
    override.write_text( "{ not json" )
    approval._cache_mtime = None
    assert approval._read_overrides()[ KEY ] is None


# ── the writer and the read-out ──────────────────────────────────────────────

def test_the_key_is_WRITABLE_and_BOOLEAN():
    assert KEY in approval.WRITABLE_KEYS
    assert KEY in approval._BOOLEAN_KEYS


@pytest.mark.parametrize( "good", [ True, False ] )
def test_a_REAL_boolean_is_written_and_read_back( override, monkeypatch, good ):
    live = approval.set_overrides( **{ KEY: good } )
    assert json.loads( override.read_text() )[ KEY ] is good
    assert live[ KEY ][ "value" ]  is good
    assert live[ KEY ][ "source" ] == "override"


@pytest.mark.parametrize( "bad", [ "false", "true", 0, 1, None ] )
def test_a_NON_boolean_is_REFUSED_and_nothing_is_written( override, bad ):
    with pytest.raises( ValueError ) as raised:
        approval.set_overrides( **{ KEY: bad } )
    assert KEY in str( raised.value )
    assert not override.exists()


def test_the_read_out_names_the_CONFIG_layer_when_nothing_is_overridden( override, monkeypatch ):
    monkeypatch.setattr( approval, "_ini_value", lambda *a, **k: None )
    settings = approval.current_settings()
    assert settings[ KEY ] == { "value": False, "source": "config" }
