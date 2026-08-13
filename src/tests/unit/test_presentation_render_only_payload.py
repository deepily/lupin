"""
Unit test for `PresentationRenderOnlySmokeTest.get_submit_payload`.

Guards the render-only submit-path regression (row 89bfcc8f): the smoke test
resolves an ABSOLUTE fixture path ({LUPIN_ROOT}/src/tests/fixtures/...), but the
`/api/presentation-generator/submit` handler treats a leading-"/" source_path as
REPO-RELATIVE and prepends project_root — so an absolute path double-roots
({root}{root}/src/...) → 404 "Source file not found". `get_submit_payload` must
send a REPO-RELATIVE path (project-root prefix stripped, leading "/" kept).

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
        - an absolute fixture path under LUPIN_ROOT → repo-relative source_path
        - a path NOT under LUPIN_ROOT is passed through unchanged
        - render_only=True and dry_run=False are always set
    """

    def test_absolute_fixture_path_becomes_repo_relative( self ):
        """Ensures: {LUPIN_ROOT}/src/... is stripped to /src/... (no double-root)."""
        with patch.dict( os.environ, { "LUPIN_ROOT": "/var/lupin" } ):
            payload = _obj( "/var/lupin/src/tests/fixtures/presentations/render-only-example.yaml" ) \
                          .get_submit_payload( {}, "ws" )
        self.assertEqual(
            payload[ "source_path" ],
            "/src/tests/fixtures/presentations/render-only-example.yaml"
        )
        self.assertTrue( payload[ "render_only" ] )
        self.assertFalse( payload[ "dry_run" ] )

    def test_path_not_under_root_passed_through( self ):
        """Ensures: a path outside LUPIN_ROOT is left as-is (no accidental mangling)."""
        with patch.dict( os.environ, { "LUPIN_ROOT": "/var/lupin" } ):
            payload = _obj( "/io/presentations/user/deck.yaml" ).get_submit_payload( {}, "ws" )
        self.assertEqual( payload[ "source_path" ], "/io/presentations/user/deck.yaml" )

    def test_monopolize_parent_id_stamped_when_set( self ):
        """Ensures: under a monopolize sweep, parent_id_hash is stamped from
        LUPIN_TEST_MONOPOLIZE_PARENT_ID so Gate B admits the child (bug 5ed4f187)."""
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
