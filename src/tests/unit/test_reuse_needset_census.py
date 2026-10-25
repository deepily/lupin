"""
The committed need set: pending until the status flips, then verified in full.
"""
import pathlib

import pytest

from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import finalize
from tests.unit.test_reuse_needset_final import FROZEN, build_set

DATA = pathlib.Path( __file__ ).resolve().parents[ 1 ] / "data" / "reuse_needset"


def set_status( folder, status ):
    """Write the status file."""
    ( folder / finalize.STATUS_FILE ).write_text( '{ "status": "%s" }' % status, encoding="utf-8" )


def code_of( folder ):
    """Return the detail of the mismatch that check_committed_set raises."""
    with pytest.raises( er.NeedsetError ) as e: finalize.check_committed_set( folder )
    assert e.value.code == er.MANIFEST_MISMATCH
    return e.value.detail


def test_the_committed_set_matches_its_status():
    assert ( DATA / finalize.STATUS_FILE ).is_file(), "the committed status file is gone: restore it with the status pending"
    finalize.check_committed_set( DATA )


def test_a_pending_set_may_hold_no_set_file( tmp_path ):
    set_status( tmp_path, "pending" )
    finalize.check_committed_set( tmp_path )
    for name in ( finalize.FINAL_FILE, finalize.MANIFEST_FILE ):
        ( tmp_path / name ).write_text( "x", encoding="utf-8" )
        assert code_of( tmp_path ).startswith( "STATUS" ) and name in code_of( tmp_path )
        ( tmp_path / name ).unlink()


def test_a_final_set_is_verified_and_a_missing_file_is_red( tmp_path ):
    needs, labels = build_set()
    finalize.finalize( needs, labels, 0.62, 7, "0123456789abcdef0123456789abcdef01234567", FROZEN, tmp_path )
    set_status( tmp_path, "final" )
    finalize.check_committed_set( tmp_path )
    ( tmp_path / finalize.FINAL_FILE ).unlink()
    assert code_of( tmp_path ).startswith( "FILES" )


def test_a_final_status_with_no_set_is_red( tmp_path ):
    set_status( tmp_path, "final" )
    assert code_of( tmp_path ).startswith( "FILES" )


def test_no_status_file_an_unreadable_one_and_an_unknown_status_are_red( tmp_path ):
    assert code_of( tmp_path ).startswith( "STATUS" )
    ( tmp_path / finalize.STATUS_FILE ).write_text( "not json", encoding="utf-8" )
    assert code_of( tmp_path ).startswith( "STATUS" )
    set_status( tmp_path, "done" )
    assert "done" in code_of( tmp_path )
