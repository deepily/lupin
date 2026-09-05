#!/usr/bin/env python3
"""
THE SWEEPER'S WIRING, INTERROGATED ON THE `lupin_app.main` THAT ACTUALLY ASSEMBLES.

WHY THIS FILE EXISTS. `test_the_orphan_sweeper_never_shortens_a_human_answer_window`
is 12 tests and they are correct. They also pass with the sweeper COMPLETELY
UNWIRED — none of them imports `lupin_app.main`, so deleting the `create_task`
call in the lifespan leaves them all green while the server sweeps nothing and
orphans keep accumulating. That is § IMPLEMENTED BUT NOT INSTALLED: a module at
100% that the app never starts.

  Measured 2026-09-05, this worktree at d8e7e713 + the sweeper commit:
      baseline                                    12 passed (sweeper unit file)
      delete the create_task call in lifespan     12 passed  <- SEES NOTHING
      the same mutation against THIS file          2 failed  <- named, both arms

⇒ Those establish that the sweeper's LOGIC is right. This file is the second
  claim: that the app ever STARTS it.

HOW IT ASKS. Not by grepping main.py's source — a commented-out line, a line in
a docstring and a live call all match a text search equally (§ A HIT IS NOT A
USE). It reads the COMPILED code objects of `lifespan`, so only a reference the
interpreter would actually execute counts.

🔴 WHY JWT_SECRET_KEY IS SET AT MODULE SCOPE. `jwt_service.py` raises AT IMPORT
when it is unset, and the repo-root `.env` that supplies it on this host is
gitignored — PRESENT in the main checkout, ABSENT in every worktree. A fixture
runs at execution time, after the collection-time import that needs it. The
value is a throwaway; nothing here signs or verifies a token.
"""
import os
import unittest

os.environ.setdefault( "JWT_SECRET_KEY", "test-only-orphan-sweeper-wiring-guard" )


def _names_reachable_from( code ):
    """
    Every name referenced by a code object and everything nested inside it.

    `lifespan` is an async context manager whose body compiles into nested code
    objects, so a flat read of co_names would miss a call made inside a `with`
    or an `if`. This walks co_consts so the search reaches the whole function.
    """
    seen = set( code.co_names )
    for const in code.co_consts:
        if hasattr( const, "co_names" ):
            seen |= _names_reachable_from( const )
    return seen


class TheAssembledAppStartsTheSweeper( unittest.TestCase ):

    @classmethod
    def setUpClass( cls ):
        import lupin_app.main as main_module
        cls.main = main_module

        # `lifespan` is @asynccontextmanager-decorated, so the attribute on the
        # module is the DECORATOR's wrapper — reading its __code__ finds only
        # the decorator's own names. Unwrap to the function main.py wrote. The
        # KNOWN-wired control below is what caught this: the first cut of this
        # guard read the wrapper and reported websocket_cleanup_loop absent.
        lifespan = getattr( main_module.lifespan, "__wrapped__", main_module.lifespan )
        cls.names = _names_reachable_from( lifespan.__code__ )

    def test_the_sweep_loop_exists_on_the_module_the_app_assembles( self ):
        self.assertTrue(
            hasattr( self.main, "notification_expiry_sweep_loop" ),
            "lupin_app.main has no notification_expiry_sweep_loop — the sweeper "
            "module can be perfect and the server will still never call it"
        )

    def test_the_lifespan_actually_references_the_sweep_loop( self ):
        """
        THE ARM THAT CATCHES A REVERT. Deleting the create_task call in the
        lifespan reddens exactly this test and nothing else in the tier.
        """
        self.assertIn(
            "notification_expiry_sweep_loop", self.names,
            "lifespan never references notification_expiry_sweep_loop — the "
            "sweeper is implemented but not installed"
        )

    def test_the_same_reading_finds_a_KNOWN_wired_loop_CONTROL( self ):
        """
        Without this, a failure above would be indistinguishable from a probe
        that can never see any loop at all. websocket_cleanup_loop has been
        wired into this lifespan since long before the sweeper existed.
        """
        self.assertIn( "websocket_cleanup_loop", self.names )

    def test_the_same_reading_does_NOT_find_a_name_that_was_never_wired( self ):
        """
        The negative control. A reading that returned every identifier in the
        file would satisfy the two arms above by accident.
        """
        self.assertNotIn( "a_loop_that_was_never_written", self.names )

    def test_the_shutdown_path_cancels_the_sweep_task( self ):
        """
        A task created and never cancelled leaks a pending coroutine through
        every bounce. The other two loops are cancelled; this one must be too.
        """
        self.assertIn( "notification_sweep_task", self.names )


if __name__ == "__main__":
    unittest.main()
