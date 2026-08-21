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

import inspect
import io
import tokenize
import unittest

import cosa.rest.dependencies.config as dependencies_config
import cosa.rest.routers.system as system_router


def _code_only( source ):
    """
    Strip comments from a source block, keeping the code.

    Borrowed in shape from test_registry_voice_binding.py. Needed here for the
    same reason it was needed there: the module is allowed to TALK about the
    deprecated manager in a comment — a note saying "we deliberately do not
    import this" is documentation worth keeping — while still being forbidden to
    import it. Scanning raw text would force a choice between the two.

    Requires:
        - source is a syntactically valid Python block

    Ensures:
        - returns the source with every COMMENT token removed
    """
    out    = []
    reader = io.StringIO( source ).readline
    for token in tokenize.generate_tokens( reader ):
        if token.type != tokenize.COMMENT: out.append( token.string )
    return "".join( out )


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
              SolutionSnapshotManager() with no `path`. That construction now
              raises NotImplementedError for every call shape (step 0 commit 3);
              before that it raised TypeError. Either way it could not work.
        """
        self.assertFalse(
            hasattr( system_router, "get_snapshot_manager" ),
            "routers/system.py re-imported get_snapshot_manager; nothing there calls it "
            "and the function it names cannot be called at all."
        )

    def test_the_module_source_never_names_the_deprecated_module( self ):
        """
        Ensures:
            - `solution_snapshot_mgr` appears nowhere in the router's CODE.

            The two hasattr pins above read the module NAMESPACE, so they catch
            `from ... import SolutionSnapshotManager` and miss
            `... import SolutionSnapshotManager as _mgr`, which re-opens the trap
            under a name they never look for. This reads the source instead, so
            an aliased re-import is caught by the module path it must still spell.

            RED ON REVERT: add any import of cosa.memory.solution_snapshot_mgr
            back to routers/system.py, aliased or not, and this fails.
        """
        source = _code_only( inspect.getsource( system_router ) )
        self.assertNotIn(
            "solution_snapshot_mgr", source,
            "routers/system.py names the deprecated snapshot module in its code. "
            "It has no caller there; an import — under any alias — is what makes "
            "the dead class look live to the next reader."
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


class TestDependenciesConfigHasNoSnapshotGetter( unittest.TestCase ):
    """
    Ensures:
        - the unreachable get_snapshot_manager is gone from dependencies/config,
          along with the module global that cached its result.
    """

    def test_the_unreachable_getter_is_gone( self ):
        """
        Ensures:
            - dependencies/config exposes no get_snapshot_manager. It built
              SolutionSnapshotManager() with no `path`, which raises on any call
              shape (TypeError before step 0 commit 3, NotImplementedError after).
              routers/admin.py:34 defines its own same-named dependency returning
              main's Postgres singleton, and
              that shadowing is why nobody noticed this one could not work.
        """
        self.assertFalse(
            hasattr( dependencies_config, "get_snapshot_manager" ),
            "dependencies/config.py grew back get_snapshot_manager; it cannot be called "
            "without raising, and admin.py already supplies the working one."
        )

    def test_its_cached_global_is_gone_too( self ):
        """
        Ensures:
            - the _snapshot_mgr module global is removed with its only writer.
              A surviving global is what lets the getter be restored by halves.
        """
        self.assertFalse(
            hasattr( dependencies_config, "_snapshot_mgr" ),
            "dependencies/config.py still carries the _snapshot_mgr global with no writer."
        )

    def test_the_deprecated_class_is_not_imported_here( self ):
        """
        Ensures:
            - the module no longer imports SolutionSnapshotManager at all, so a
              reader following imports out of the dependency layer is not led to
              the deprecated class.
        """
        self.assertFalse(
            hasattr( dependencies_config, "SolutionSnapshotManager" ),
            "dependencies/config.py re-imported the deprecated SolutionSnapshotManager."
        )

    def test_the_two_live_getters_survive( self ):
        """
        Ensures:
            - only the snapshot getter was removed. This fails if someone deletes
              the module's other two dependencies along with it.
        """
        self.assertTrue( hasattr( dependencies_config, "get_config_manager" ) )
        self.assertTrue( hasattr( dependencies_config, "get_id_generator" ) )


if __name__ == "__main__":
    unittest.main()
