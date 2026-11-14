"""
The fence around the main configuration file refuses a write and sees a changed byte.

Each test builds its own decoy file in tmp_path, so nothing here can reach the real one.

Venue: :7999 (unit, no server, tmp_path only).
"""
import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_mcp import fleet_cap_ini_io as io
from tests.helpers import main_ini_fence as fence

KEY = "demo setting"


@pytest.fixture
def decoy( tmp_path ):
    path = tmp_path / "lupin-app.ini"
    path.write_text( f"[Lupin: Baseline]\n{KEY} = true\n", encoding="utf-8" )
    return str( path.resolve() )


def test_the_main_path_comes_from_git_and_names_a_real_file():
    path = fence.main_ini_path()
    assert path.endswith( os.path.join( "src", "conf", "lupin-app.ini" ) )
    assert os.path.isfile( path )
    assert ".claude/worktrees" not in path, "a worktree must resolve to the main checkout, never to itself"


@pytest.mark.parametrize( "writer, args", [
    ( "write_bool_to_disk",  ( KEY, False ) ),
    ( "write_int_to_disk",   ( KEY, 3 ) ),
    ( "_replace_value_line", ( KEY, "false" ) ),
] )
def test_every_writer_refuses_the_fenced_file_before_writing( monkeypatch, decoy, writer, args ):
    before, refused = fence.raise_fence( monkeypatch, decoy )
    with pytest.raises( AssertionError, match="fence:" ):
        getattr( io, writer )( decoy, *args )
    assert refused and refused[ 0 ][ 1 ] == decoy
    assert fence._sha256( decoy ) == before, "the refusal must come before any byte is written"
    with pytest.raises( AssertionError, match="tried to write" ):
        fence.check_fence( decoy, before, refused )


def test_a_swallowed_refusal_still_fails_at_the_check( monkeypatch, decoy ):
    before, refused = fence.raise_fence( monkeypatch, decoy )
    try:
        io.write_bool_to_disk( decoy, KEY, False )
    except AssertionError:
        pass                                   # the code under test swallowed it
    with pytest.raises( AssertionError, match="tried to write" ):
        fence.check_fence( decoy, before, refused )


def test_another_file_is_written_normally( monkeypatch, decoy, tmp_path ):
    other = tmp_path / "other.ini"
    other.write_text( f"[Lupin: Baseline]\n{KEY} = true\n", encoding="utf-8" )
    before, refused = fence.raise_fence( monkeypatch, decoy )
    io.write_bool_to_disk( str( other ), KEY, False )
    assert io.read_value_from_disk( str( other ), KEY ).strip() == "false"
    fence.check_fence( decoy, before, refused )


def test_a_changed_byte_is_noticed_even_with_no_refusal( monkeypatch, decoy ):
    before, refused = fence.raise_fence( monkeypatch, decoy )
    with open( decoy, "a", encoding="utf-8" ) as handle: handle.write( "; hand edit\n" )
    with pytest.raises( AssertionError, match="changed during the test" ):
        fence.check_fence( decoy, before, refused )


def test_an_untouched_file_passes_the_check( monkeypatch, decoy ):
    before, refused = fence.raise_fence( monkeypatch, decoy )
    fence.check_fence( decoy, before, refused )
