"""
Unit tests for cosa.utils.atomic_json: the atomic writer and the section reader.
"""

import json
import os

import pytest

import cosa.utils.atomic_json as aj


def test_write_creates_parents_and_holds_exactly_the_data( tmp_path ):
    target = tmp_path / "a" / "b" / "ledger.json"
    aj.write_json_atomic( target, { "k": [ 1, 2 ] } )
    assert json.loads( target.read_text() ) == { "k": [ 1, 2 ] }


def test_write_replaces_whole_and_leaves_no_temp_file( tmp_path ):
    target = tmp_path / "ledger.json"
    aj.write_json_atomic( str( target ), { "old": 1, "gone": 2 } )
    aj.write_json_atomic( str( target ), { "new": 3 } )
    assert json.loads( target.read_text() ) == { "new": 3 }
    assert [ p.name for p in tmp_path.iterdir() ] == [ "ledger.json" ]


def test_write_stringifies_values_json_cannot_encode( tmp_path ):
    target = tmp_path / "ledger.json"
    aj.write_json_atomic( target, { "path": tmp_path } )
    assert json.loads( target.read_text() ) == { "path": str( tmp_path ) }


def test_write_temp_name_carries_pid_and_a_fresh_uuid( tmp_path, monkeypatch ):
    seen = []
    from pathlib import Path
    original = Path.replace
    def spy( self, target ):
        seen.append( self.name )
        return original( self, target )
    monkeypatch.setattr( Path, "replace", spy )
    aj.write_json_atomic( tmp_path / "x.json", {} )
    aj.write_json_atomic( tmp_path / "x.json", {} )
    assert len( seen ) == 2 and seen[ 0 ] != seen[ 1 ]
    assert all( name.startswith( f"x.json.{os.getpid()}-" ) and name.endswith( ".tmp" ) for name in seen )


def test_write_raises_oserror_when_the_directory_is_not_writable( tmp_path ):
    blocker = tmp_path / "file"
    blocker.write_text( "x" )
    with pytest.raises( OSError ):
        aj.write_json_atomic( blocker / "child.json", {} )


def test_load_returns_the_named_section( tmp_path ):
    target = tmp_path / "s.json"
    target.write_text( json.dumps( { "refused": { "p": [ "b" ] }, "trees": { "t": 1 } } ) )
    assert aj.load_json_section( target, "refused" ) == { "p": [ "b" ] }
    assert aj.load_json_section( target, "trees" ) == { "t": 1 }


@pytest.mark.parametrize( "content", [ None, "not json", "[1, 2]", '{"refused": [1]}', '{"other": {}}', "" ] )
def test_load_returns_empty_dict_for_anything_unusable( tmp_path, content ):
    target = tmp_path / "s.json"
    if content is not None: target.write_text( content )
    assert aj.load_json_section( target, "refused" ) == {}


def test_write_puts_the_temp_file_in_the_targets_own_directory( tmp_path, monkeypatch ):
    """A rename is atomic only inside one directory, so the temp file must sit beside the target."""
    from pathlib import Path
    moved   = []
    replace = Path.replace
    def spy( self, target ):
        moved.append( ( self.parent, Path( target ).parent ) )
        return replace( self, target )
    monkeypatch.setattr( Path, "replace", spy )
    target = tmp_path / "deep" / "ledger.json"
    aj.write_json_atomic( target, {} )
    assert moved == [ ( target.parent, target.parent ) ]
