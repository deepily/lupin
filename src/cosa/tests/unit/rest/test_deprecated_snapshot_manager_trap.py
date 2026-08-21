"""
Step 0 of the brain-integration plan — the deprecated-manager trap, closed.

`grep "def save_snapshot"` finds the DEPRECATED `SolutionSnapshotManager` first,
whose docstring says it saves to files. That reading is wrong in production:
`main.py:706` raises for any manager type but postgres, so the file backend can
never be built. A reader who trusts the grep concludes that the queue writes
snapshots to disk while the brain reads Postgres — two stores that do not exist.

These pins keep the trap closed. They assert RUNTIME module state, not source
text, so they stay meaningful if the imports move or are re-worded.

Plan: src/rnd/v0.2.0/2026.08.20-brain-integration-cascade-review-plan.md, step 0.
"""

import unittest

import cosa.rest.routers.system as system_router


class TestSystemRouterDoesNotCarryTheTrap( unittest.TestCase ):
    """
    Ensures:
        - routers/system.py imports neither the deprecated class nor the
          unreachable dependency getter it never called.
    """

    def test_system_router_does_not_import_the_deprecated_manager( self ):
        """
        Ensures:
            - `SolutionSnapshotManager` is not bound in the system router's
              namespace. It was imported and never used; the import alone is
              what makes the deprecated class look live to a reader.
        """
        self.assertFalse(
            hasattr( system_router, "SolutionSnapshotManager" ),
            "routers/system.py re-imported the deprecated SolutionSnapshotManager; "
            "it has no caller there and its presence is the trap step 0 closes."
        )

    def test_system_router_does_not_import_the_unreachable_getter( self ):
        """
        Ensures:
            - `get_snapshot_manager` is not bound in the system router's
              namespace. The dependencies/config getter it named constructs
              SolutionSnapshotManager() with no `path`, which its __init__
              requires, so calling it would raise TypeError.
        """
        self.assertFalse(
            hasattr( system_router, "get_snapshot_manager" ),
            "routers/system.py re-imported get_snapshot_manager; nothing there calls it "
            "and the function it names cannot be called without raising TypeError."
        )

    def test_the_getters_system_actually_uses_are_still_bound( self ):
        """
        Ensures:
            - trimming line 22 removed only the unused name. Both getters the
              router really depends on survive, so this pin fails if someone
              deletes the whole import line instead of narrowing it.
        """
        self.assertTrue( hasattr( system_router, "get_config_manager" ) )
        self.assertTrue( hasattr( system_router, "get_id_generator" ) )


if __name__ == "__main__":
    unittest.main()
