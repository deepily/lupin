"""
The deprecated SolutionSnapshotManager refuses to be constructed.

This file replaces test_solution_snapshot_mgr.py (746 lines, ~10 constructions),
which tested a class the application forbids. Step 0 of the brain-integration
plan made __init__ raise, so every one of those tests exercised a path that can
no longer be entered; there is nothing to rewrite them into.

What is left to assert is the refusal itself, and that its message points at the
construction that works. Plan:
src/rnd/v0.2.0/2026.08.20-brain-integration-cascade-review-plan.md, step 0.
"""

import unittest

from cosa.memory.solution_snapshot_mgr import SolutionSnapshotManager


class TestDeprecatedManagerRefusesConstruction( unittest.TestCase ):
    """
    Ensures:
        - the class cannot be instantiated, by any argument shape.
        - the refusal names the supported alternative rather than just failing.
    """

    def test_construction_raises( self ):
        """
        Ensures:
            - a well-formed call with a path still raises NotImplementedError.
              This is the shape the old tests used, so it is the shape that has
              to be shut.
        """
        with self.assertRaises( NotImplementedError ):
            SolutionSnapshotManager( "/some/path", debug=False, verbose=False )

    def test_construction_with_no_path_raises_too( self ):
        """
        Ensures:
            - the no-argument call raises NotImplementedError, not TypeError.
              dependencies/config.py's deleted getter called it exactly this way,
              and a TypeError would say "you called it wrong" when the truth is
              "there is no right way to call it."
        """
        with self.assertRaises( NotImplementedError ):
            SolutionSnapshotManager()

    def test_the_refusal_names_the_working_construction( self ):
        """
        Ensures:
            - the message names the factory and "postgres". A refusal that does
              not say what to do instead just moves the reader's dead end.
        """
        with self.assertRaises( NotImplementedError ) as ctx:
            SolutionSnapshotManager( "/some/path" )
        message = str( ctx.exception )
        self.assertIn( "SolutionSnapshotManagerFactory.create_manager", message )
        self.assertIn( "postgres", message )

    def test_the_refusal_disowns_the_file_backend( self ):
        """
        Ensures:
            - the message says the file backend is FileBasedSolutionManager, a
              different class. This is the specific misreading step 0 exists to
              close: the factory advertises a "file_based" branch, and it does
              not build this class.
        """
        with self.assertRaises( NotImplementedError ) as ctx:
            SolutionSnapshotManager( "/some/path" )
        self.assertIn( "FileBasedSolutionManager", str( ctx.exception ) )


if __name__ == "__main__":
    unittest.main()
