#!/usr/bin/env python3
"""
Row a9f87d29 — the worktree false-green guard, tested in BOTH directions.

EXECUTOR: AI — pure path logic over temp dirs with fake `.git` markers; no git, no
server, no worktree needed. :7999-class.

The guard must FIRE on the trap (a test file in a different git tree than LUPIN_ROOT)
and stay SILENT on every correct setup AND on any uncertainty (fail-safe). Each fire
assertion is paired with the silent case that proves the fire meant "mismatch", not
"this predicate always fires".

Run: PYTHONPATH=src python -m pytest src/tests/unit/test_worktree_tree_guard.py -v
"""

import os
import shutil
import tempfile
import unittest

from tests.worktree_tree_guard import git_tree_root, tree_mismatch, check_paths


def _make_tree( base, marker="dir" ):
    """Create a fake git tree at `base` with a `.git` dir (normal) or file (worktree)."""
    os.makedirs( base, exist_ok=True )
    dot_git = os.path.join( base, ".git" )
    if marker == "dir":
        os.makedirs( dot_git, exist_ok=True )
    else:                                   # linked worktree: .git is a FILE
        with open( dot_git, "w" ) as handle:
            handle.write( "gitdir: /somewhere/.git/worktrees/wt\n" )
    return base


class TestGitTreeRoot( unittest.TestCase ):
    def setUp( self ):
        self._tmp = tempfile.mkdtemp()

    def tearDown( self ):
        shutil.rmtree( self._tmp, ignore_errors=True )

    def test_finds_dot_git_directory_ancestor( self ):
        root = _make_tree( os.path.join( self._tmp, "main" ), "dir" )
        deep = os.path.join( root, "src", "tests", "unit" )
        os.makedirs( deep )
        self.assertEqual( git_tree_root( os.path.join( deep, "t.py" ) ), os.path.realpath( root ) )

    def test_finds_dot_git_FILE_ancestor_worktree( self ):
        root = _make_tree( os.path.join( self._tmp, "wt" ), "file" )   # linked worktree marker
        deep = os.path.join( root, "src", "tests" )
        os.makedirs( deep )
        self.assertEqual( git_tree_root( os.path.join( deep, "t.py" ) ), os.path.realpath( root ) )

    def test_returns_none_when_no_git_ancestor( self ):
        lonely = os.path.join( self._tmp, "no_git", "a", "b" )
        os.makedirs( lonely )
        self.assertIsNone( git_tree_root( os.path.join( lonely, "t.py" ) ) )


class TestTreeMismatch( unittest.TestCase ):
    def setUp( self ):
        self._tmp = tempfile.mkdtemp()
        self.main = _make_tree( os.path.join( self._tmp, "main" ), "dir" )
        self.wt   = _make_tree( os.path.join( self._tmp, "wt" ), "file" )
        for tree in ( self.main, self.wt ):
            os.makedirs( os.path.join( tree, "src", "tests" ), exist_ok=True )
        self.main_file = os.path.join( self.main, "src", "tests", "t.py" )
        self.wt_file   = os.path.join( self.wt, "src", "tests", "t.py" )

    def tearDown( self ):
        shutil.rmtree( self._tmp, ignore_errors=True )

    # -- SILENT (correct setups + uncertainty) --------------------------------
    def test_silent_same_tree_main( self ):
        self.assertIsNone( tree_mismatch( self.main_file, self.main ) )

    def test_silent_same_tree_worktree( self ):
        self.assertIsNone( tree_mismatch( self.wt_file, self.wt ) )

    def test_silent_when_lupin_root_falsy( self ):
        self.assertIsNone( tree_mismatch( self.wt_file, None ) )
        self.assertIsNone( tree_mismatch( self.wt_file, "" ) )

    def test_silent_when_file_tree_unresolvable( self ):
        outside = os.path.join( self._tmp, "no_git", "t.py" )
        os.makedirs( os.path.dirname( outside ) )
        self.assertIsNone( tree_mismatch( outside, self.main ) )

    def test_silent_when_lupin_root_unresolvable( self ):
        no_git_root = os.path.join( self._tmp, "no_git_root" )
        os.makedirs( no_git_root )
        self.assertIsNone( tree_mismatch( self.wt_file, no_git_root ) )

    # -- FIRES (the trap) -----------------------------------------------------
    def test_fires_worktree_file_against_main_lupin_root( self ):
        hit = tree_mismatch( self.wt_file, self.main )
        self.assertIsNotNone( hit )
        self.assertEqual( hit[ "file_tree" ],  os.path.realpath( self.wt ) )
        self.assertEqual( hit[ "lupin_tree" ], os.path.realpath( self.main ) )


class TestCheckPaths( unittest.TestCase ):
    def setUp( self ):
        self._tmp = tempfile.mkdtemp()
        self.main = _make_tree( os.path.join( self._tmp, "main" ), "dir" )
        self.wt   = _make_tree( os.path.join( self._tmp, "wt" ), "file" )
        for tree in ( self.main, self.wt ):
            os.makedirs( os.path.join( tree, "src", "tests" ), exist_ok=True )

    def tearDown( self ):
        shutil.rmtree( self._tmp, ignore_errors=True )

    def test_silent_all_main_tree( self ):
        paths = [ os.path.join( self.main, "src", "tests", f"t{i}.py" ) for i in range( 5 ) ]
        self.assertIsNone( check_paths( paths, self.main ) )

    def test_silent_empty( self ):
        self.assertIsNone( check_paths( [], self.main ) )

    def test_fires_on_a_worktree_path_against_main_root( self ):
        paths = [
            os.path.join( self.main, "src", "tests", "ok.py" ),
            os.path.join( self.wt,   "src", "tests", "trap.py" ),   # the offender
        ]
        msg = check_paths( paths, self.main )
        self.assertIsNotNone( msg )
        self.assertIn( "WORKTREE FALSE-GREEN GUARD", msg )
        self.assertIn( os.path.realpath( self.wt ), msg )
        self.assertIn( os.path.realpath( self.main ), msg )


if __name__ == "__main__":
    unittest.main()
