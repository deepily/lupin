"""
Unit test for `PresentationRenderOnlySmokeTest.get_submit_payload`.

Guards the render-only submit-path regression (row 89bfcc8f): the smoke test
resolves an ABSOLUTE fixture path ({LUPIN_ROOT}/src/tests/fixtures/...), while the
receiving side treats a leading-"/" path as REPO-RELATIVE — so an absolute path used
to double-root ({root}{root}/src/...) → "Source file not found". `get_submit_payload`
must send a REPO-RELATIVE path (project-root prefix stripped, leading "/" kept).

The dedicated door this used to post to is retired; the payload is now a command plus
`args` for `/api/v2/submit`, and the path travels as `args["source"]`. The stripping is
kept rather than dropped: the job's `resolve_source_path` would now accept either
spelling, but a test that stops asserting the shape a caller sends stops guarding the
regression it was written for.

Zero external dependencies — the object is built via __new__ to skip the heavy
base __init__ (login/config); only `_yaml_path` + os.environ drive the payload.
"""

import os
import time
import unittest
from unittest.mock import patch

from tests.smoke.test_presentation_render_only_smoke import PresentationRenderOnlySmokeTest


def _obj( yaml_path ):
    """A payload-only instance: skip base __init__, set just _yaml_path."""
    o = PresentationRenderOnlySmokeTest.__new__( PresentationRenderOnlySmokeTest )
    o._yaml_path = yaml_path
    return o


class TestRenderOnlyPayload( unittest.TestCase ):
    """
    Ensures:
        - an absolute fixture path under LUPIN_ROOT → repo-relative args["source"]
        - a path NOT under LUPIN_ROOT is passed through unchanged
        - render_only=True and dry_run=False are always set inside args
    """

    def test_absolute_fixture_path_becomes_repo_relative( self ):
        """Ensures: {LUPIN_ROOT}/src/... is stripped to /src/... (no double-root)."""
        with patch.dict( os.environ, { "LUPIN_ROOT": "/var/lupin" } ):
            payload = _obj( "/var/lupin/src/tests/fixtures/presentations/render-only-example.yaml" ) \
                          .get_submit_payload( {}, "ws" )
        self.assertEqual( payload[ "command" ], "agent router go to presentation generator" )
        self.assertEqual(
            payload[ "args" ][ "source" ],
            "/src/tests/fixtures/presentations/render-only-example.yaml"
        )
        self.assertTrue( payload[ "args" ][ "render_only" ] )
        self.assertFalse( payload[ "args" ][ "dry_run" ] )

    def test_path_not_under_root_passed_through( self ):
        """Ensures: a path outside LUPIN_ROOT is left as-is (no accidental mangling)."""
        with patch.dict( os.environ, { "LUPIN_ROOT": "/var/lupin" } ):
            payload = _obj( "/io/presentations/user/deck.yaml" ).get_submit_payload( {}, "ws" )
        self.assertEqual( payload[ "args" ][ "source" ], "/io/presentations/user/deck.yaml" )

    def test_monopolize_parent_id_stamped_when_set( self ):
        """Ensures: under a monopolize sweep, parent_id_hash is stamped from
        LUPIN_TEST_MONOPOLIZE_PARENT_ID so Gate B admits the child (bug 5ed4f187).

        It stays TOP-LEVEL, outside `args`: it is a queue directive, and `args` is checked
        against the command's own argument contract, which it is not in."""
        with patch.dict( os.environ, { "LUPIN_ROOT": "/var/lupin",
                                        "LUPIN_TEST_MONOPOLIZE_PARENT_ID": "ts-abc123" } ):
            payload = _obj( "/var/lupin/src/tests/fixtures/presentations/render-only-example.yaml" ) \
                          .get_submit_payload( {}, "ws" )
        self.assertEqual( payload[ "parent_id_hash" ], "ts-abc123" )

    def test_no_parent_id_hash_when_env_absent( self ):
        """Ensures: outside a monopolize sweep (env unset), parent_id_hash is NOT
        sent (a bogus lineage tag must never be fabricated)."""
        env = { k: v for k, v in os.environ.items() if k != "LUPIN_TEST_MONOPOLIZE_PARENT_ID" }
        env[ "LUPIN_ROOT" ] = "/var/lupin"
        with patch.dict( os.environ, env, clear=True ):
            payload = _obj( "/var/lupin/src/x.yaml" ).get_submit_payload( {}, "ws" )
        self.assertNotIn( "parent_id_hash", payload )


def quick_smoke_test():
    """Run this module's unit tests with a banner + pass/fail summary."""
    print( "=" * 72 )
    print( "  Render-Only Payload Unit Test (repo-relative source_path)" )
    print( "=" * 72 )
    start  = time.time()
    suite  = unittest.TestLoader().loadTestsFromTestCase( TestRenderOnlyPayload )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    elapsed = time.time() - start
    if result.wasSuccessful():
        print( f"\n✓ All {result.testsRun} tests passed in {elapsed:.3f}s" )
    else:
        print( f"\n✗ {len( result.failures )} failures, {len( result.errors )} errors "
               f"out of {result.testsRun} tests" )
    return result.wasSuccessful()


if __name__ == "__main__":
    quick_smoke_test()
