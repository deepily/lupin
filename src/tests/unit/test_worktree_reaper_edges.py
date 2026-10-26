#!/usr/bin/env python3
"""
Unit tests for the small refusals inside cosa.agents.shared.worktree_reaper.

Each case is a place where the reaper must fail closed. A tree it cannot list, a directory
it cannot judge, or a file it cannot read is never treated as safe to delete.
Git is a stub runner and the filesystem is a temp directory, so nothing leaves the process.
"""

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cosa.agents.shared import worktree_reaper as wr


def _proc( returncode=0, stdout="", stderr="" ):
    return SimpleNamespace( returncode=returncode, stdout=stdout, stderr=stderr )


class TestIsArtifact:

    def test_a_symlink_is_an_artifact_even_with_a_plain_name( self, tmp_path ):
        target = tmp_path / "target.txt"
        target.write_text( "x" )
        link = tmp_path / "plain-name"
        link.symlink_to( target )
        assert wr._is_artifact( "plain-name", str( link ) ) is True

    @pytest.mark.parametrize( "rel", [ "", "/", "//" ] )
    def test_an_empty_relative_path_is_not_an_artifact( self, rel, tmp_path ):
        assert wr._is_artifact( rel, str( tmp_path / "absent" ) ) is False


class TestExpandIgnoredDirectory:

    def test_a_directory_with_too_many_files_cannot_be_judged( self, tmp_path, monkeypatch ):
        ( tmp_path / "big" ).mkdir()
        for name in ( "a", "b" ): ( tmp_path / "big" / name ).write_text( "x" )
        monkeypatch.setattr( wr, "MAX_EXPANDED_FILES", 1 )
        assert wr._expand_ignored_directory( str( tmp_path ), "big" ) is None

    def test_a_small_directory_lists_its_files_relative_to_the_tree( self, tmp_path ):
        ( tmp_path / "small" ).mkdir()
        ( tmp_path / "small" / "a" ).write_text( "x" )
        assert wr._expand_ignored_directory( str( tmp_path ), "small" ) == [ os.path.join( "small", "a" ) ]

    def test_a_walk_that_raises_cannot_be_judged( self, tmp_path ):
        with patch( "os.walk", side_effect=RuntimeError( "boom" ) ):
            assert wr._expand_ignored_directory( str( tmp_path ), "x" ) is None


class TestFilesIdentical:

    def test_a_missing_file_is_not_identical( self, tmp_path ):
        ( tmp_path / "a" ).write_text( "x" )
        assert wr._files_identical( str( tmp_path / "a" ), str( tmp_path / "missing" ) ) is False

    def test_same_bytes_are_identical_and_different_bytes_are_not( self, tmp_path ):
        ( tmp_path / "a" ).write_text( "xy" )
        ( tmp_path / "b" ).write_text( "xy" )
        ( tmp_path / "c" ).write_text( "xz" )
        assert wr._files_identical( str( tmp_path / "a" ), str( tmp_path / "b" ) ) is True
        assert wr._files_identical( str( tmp_path / "a" ), str( tmp_path / "c" ) ) is False

    def test_an_unreadable_file_is_not_identical( self, tmp_path ):
        ( tmp_path / "a" ).write_text( "x" )
        ( tmp_path / "b" ).write_text( "x" )
        with patch( "os.path.getsize", side_effect=OSError( "gone" ) ):
            assert wr._files_identical( str( tmp_path / "a" ), str( tmp_path / "b" ) ) is False


def test_a_pointer_that_cannot_be_opened_names_nothing( tmp_path ):
    assert wr._pointer_names( str( tmp_path / "missing.md" ) ) is None


class TestFindIgnoredBlockers:

    def test_a_listing_failure_is_reported_and_blocks_nothing_by_itself( self, tmp_path ):
        run = lambda argv, cwd=None, timeout=60: _proc( 128, stderr="not a repo" )
        found = wr.find_ignored_blockers( str( tmp_path ), str( tmp_path ), run )
        assert found[ "ok" ] is False
        assert found[ "blockers" ] == []
        assert "git ls-files --ignored failed: not a repo" in found[ "error" ]

    def test_a_directory_that_cannot_be_judged_blocks_as_a_whole( self, tmp_path, monkeypatch ):
        ( tmp_path / "data" ).mkdir()
        ( tmp_path / "data" / "f" ).write_text( "x" )
        monkeypatch.setattr( wr, "MAX_EXPANDED_FILES", 0 )
        run = lambda argv, cwd=None, timeout=60: _proc( 0, stdout="data/\n" )
        found = wr.find_ignored_blockers( str( tmp_path ), str( tmp_path ), run )
        assert found == { "ok": True, "blockers": [ "data/" ], "error": None }


def test_a_reap_whose_ignored_files_cannot_be_listed_is_refused_and_leaves_the_tree( tmp_path ):
    def run( argv, cwd=None, timeout=60 ):
        if "ls-files" in argv: return _proc( 128, stderr="index locked" )
        return _proc( 0, stdout="main" )
    result = wr.drain_then_remove( str( tmp_path ), project_root=str( tmp_path ), run=run )
    assert result[ "removed" ] is False
    assert result[ "skipped_reason" ] == "ignored_check_failed"
    assert any( "index locked" in e for e in result[ "errors" ] )
    assert tmp_path.exists()


class TestTmuxSessionAbsent:

    def test_an_existing_session_is_not_absent( self ):
        with patch( "subprocess.run", return_value=_proc( 0 ) ):
            assert wr._tmux_session_absent( "seat-x" ) is False

    def test_a_missing_session_is_absent( self ):
        with patch( "subprocess.run", return_value=_proc( 1, stderr="can't find session: seat-x" ) ):
            assert wr._tmux_session_absent( "seat-x" ) is True

    def test_an_unrecognised_failure_is_not_proof_of_absence( self ):
        with patch( "subprocess.run", return_value=_proc( 1, stderr="permission denied" ) ):
            assert wr._tmux_session_absent( "seat-x" ) is False

    def test_tmux_not_installed_is_not_proof_of_absence( self ):
        with patch( "subprocess.run", side_effect=FileNotFoundError( "tmux" ) ):
            assert wr._tmux_session_absent( "seat-x" ) is False
