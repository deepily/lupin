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
import subprocess
import sys
import tempfile
import unittest

from tests.worktree_tree_guard import (
    git_tree_root, tree_mismatch, check_paths, is_test_file, paths_to_scan
)


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



class TestIsTestFile( unittest.TestCase ):
    """
    Row 08f6be8e — the filter that decides WHICH walked files the fallback may name.

    `pytest_collect_file` is offered conftest.py as well as the test modules, and naming a
    conftest as "the test file being collected" would send a reader to the wrong file. The
    patterns come from pytest's own `python_files` ini so there is no second copy to drift.
    """

    PATTERNS = [ "test_*.py" ]

    def test_a_test_module_matches( self ):
        self.assertTrue( is_test_file( "/tree/src/tests/unit/test_thing.py", self.PATTERNS ) )

    def test_a_conftest_does_not( self ):
        self.assertFalse( is_test_file( "/tree/src/tests/unit/conftest.py", self.PATTERNS ) )

    def test_only_the_basename_is_read( self ):
        """A directory called `test_stuff` must not make every file inside it a test file."""
        self.assertFalse( is_test_file( "/tree/test_stuff/helpers.py", self.PATTERNS ) )

    def test_a_second_pattern_can_match( self ):
        """The loop must consider every configured pattern, not just the first."""
        self.assertTrue( is_test_file( "/tree/thing_test.py", [ "test_*.py", "*_test.py" ] ) )

    def test_no_patterns_matches_nothing( self ):
        """The empty-iterable path through the loop — falls out returning False."""
        self.assertFalse( is_test_file( "/tree/test_thing.py", [] ) )


class TestPathsToScan( unittest.TestCase ):
    """
    Row 08f6be8e — the ZERO-ITEM BLIND SPOT, in both directions.

    ⚠️ THE SECOND TEST IS THE ONE THAT MATTERS. Preferring items whenever there are items
    is what keeps every live run byte-for-byte unchanged; without it the fallback could
    alter an existing verdict instead of only adding the missing one.
    """

    def test_falls_back_to_walked_files_when_no_item_survived( self ):
        walked = [ "/wt/src/tests/unit/test_skipped_at_module_level.py" ]
        self.assertEqual( paths_to_scan( [], walked ), walked )

    def test_prefers_the_surviving_items_whenever_there_are_any( self ):
        items  = [ "/wt/src/tests/unit/test_ran.py" ]
        walked = [ "/wt/src/tests/unit/test_ran.py", "/wt/src/tests/unit/test_other.py" ]
        self.assertEqual( paths_to_scan( items, walked ), items )

    def test_both_empty_stays_empty_so_the_guard_stays_silent( self ):
        """Nothing walked and nothing collected is not a mismatch — check_paths sees []."""
        self.assertEqual( paths_to_scan( [], [] ), [] )
        self.assertIsNone( check_paths( paths_to_scan( [], [] ), "/anywhere" ) )




class TestZeroItemWiringEndToEnd( unittest.TestCase ):
    """
    Row 08f6be8e — the WIRING, proved by running real pytest, not by trusting the predicate.

    The pure tests above prove `paths_to_scan` returns the right list. They cannot prove
    `src/conftest.py` actually hands it the walked files, and that is the half that was
    broken: the predicate was always correct and was simply never given anything to read.

    HOW THE MISMATCH IS BUILT WITHOUT A REAL WORKTREE. `git_tree_root` walks up to the
    nearest ancestor holding a `.git` entry — a FILE in a linked worktree. Writing such a
    file into a throwaway directory INSIDE this repo makes that directory its own tree
    root, so it disagrees with LUPIN_ROOT exactly as a worktree does, while staying under
    the repo's pytest.ini so the root conftest still loads. No `git worktree add`, no
    network, no second checkout.
    """

    def setUp( self ):
        self.repo = os.environ.get( "LUPIN_ROOT" ) or git_tree_root( __file__ )
        self.dir  = tempfile.mkdtemp( dir=os.path.join( self.repo, "src", "tests", "unit" ),
                                      prefix="_zero_item_probe_" )
        with open( os.path.join( self.dir, ".git" ), "w" ) as handle:
            handle.write( "gitdir: /nowhere/.git/worktrees/probe\n" )

    def tearDown( self ):
        shutil.rmtree( self.dir, ignore_errors=True )

    def _run_pytest( self ):
        env = dict( os.environ )
        env[ "LUPIN_ROOT" ] = self.repo
        env[ "PYTHONPATH" ] = os.path.join( self.repo, "src" )
        proc = subprocess.run(
            [ sys.executable, "-m", "pytest", self.dir, "-q", "-p", "no:cacheprovider" ],
            cwd=self.repo, capture_output=True, text=True, timeout=180, env=env,
        )
        return proc.returncode, proc.stdout + proc.stderr

    def test_a_module_level_skip_still_reports_the_tree_mismatch( self ):
        """
        THE DEFECT ITSELF. Every item is gone before `pytest_collection_modifyitems` sees
        the list, so the guard used to be handed [] and said nothing while LUPIN_ROOT
        pointed at another tree.
        """
        with open( os.path.join( self.dir, "test_module_skip.py" ), "w" ) as handle:
            handle.write( "import pytest\n"
                          "pytest.skip( 'skipped at module level', allow_module_level=True )\n"
                          "def test_never(): assert True\n" )

        code, output = self._run_pytest()

        self.assertEqual( code, 4, "a tree mismatch is a usage error, not a quiet skip" )
        self.assertIn( "WORKTREE FALSE-GREEN GUARD", output )
        self.assertIn( "export LUPIN_ROOT=", output, "the message must carry the remedy" )

    def test_a_file_holding_no_tests_still_reports_the_tree_mismatch( self ):
        """The other zero-item shape: the module imports fine and simply defines no tests."""
        with open( os.path.join( self.dir, "test_no_tests_here.py" ), "w" ) as handle:
            handle.write( "# a module pytest walks and finds nothing in\n" )

        code, output = self._run_pytest()

        self.assertEqual( code, 4 )
        self.assertIn( "WORKTREE FALSE-GREEN GUARD", output )

    def test_a_correctly_configured_empty_selection_is_left_alone( self ):
        """
        ⚠️ THE CONTROL THAT KEEPS THIS FROM BECOMING DECORATION. An empty selection in a
        tree that AGREES with LUPIN_ROOT must stay pytest's own exit 5 and print no guard
        text. A guard that failed every deliberately-empty run would earn an escape hatch
        within a week; the condition being reported is a MISMATCH, never emptiness.
        """
        os.remove( os.path.join( self.dir, ".git" ) )   # same tree as LUPIN_ROOT now
        with open( os.path.join( self.dir, "test_no_tests_here.py" ), "w" ) as handle:
            handle.write( "# a module pytest walks and finds nothing in\n" )

        code, output = self._run_pytest()

        self.assertEqual( code, 5, "no tests collected is pytest's own verdict, unchanged" )
        self.assertNotIn( "WORKTREE FALSE-GREEN GUARD", output )



if __name__ == "__main__":
    unittest.main()
